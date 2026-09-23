"""The agent's only path to the graph: the official TigerGraph MCP server (pip `tigergraph-mcp`).

One server process is spawned over stdio for the life of the Python process and driven from a
background asyncio loop, so callers stay synchronous: `call("run_installed_query", ...)`.

Permissions / controls
----------------------
* Tool allowlist (`ALLOWED_TOOLS`, passed to the server as TG_ALLOWED_TOOLS). The server withholds
  every other tool at dispatch, not just in the listing, so the agent cannot reach them even by name:
    read : get_graph_schema, run_installed_query (only the 8 reviewed queries in gsql/queries.gsql),
           get_node, get_neighbors
    write: add_node, add_edges, upsert_vectors  (case memory only - see below)
  Not served: run_query / gsql (ad-hoc GSQL), install/drop query, every delete_*, clear_graph_data,
  schema changes, loading jobs, data sources. The agent can neither rewrite the graph nor run
  arbitrary GSQL.
* Write scope. The MCP allowlist cannot scope writes by vertex type, so the agent writes only via
  `upsert_case` / `upsert_case_embedding` (AgentCase vertex, its emb vector, the six AgentCase edge
  types; other edge types raise before reaching the server). Hard per-type enforcement would need a
  TigerGraph RBAC role behind the secret.
* Audit. Every call is appended to `LOG` ({tool, args (truncated), ms, ok}) and counted in `calls`;
  this feeds per-case `tool_calls` telemetry and the UI timeline.
* Credentials never reach the agent/LLM: the server gets TG_SECRET from .env via its environment.

Auth: TG_SECRET is enough on Savanna. pyTigerGraph (inside the server) sends it as basic auth and,
on the first 401 from RESTPP, mints a JWT from the secret and retries.
Savanna auto-resume: the first calls after idle can fail with 502/503/504; `call` retries with backoff.
"""
import asyncio
import atexit
import json
import os
import re
import sys
import threading
import time

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hhg import config

ALLOWED_TOOLS = ("get_graph_schema", "run_installed_query", "get_node", "get_neighbors",
                 "add_node", "add_edges", "upsert_vectors")
CASE_EDGES = {"INVOLVES": "Txn", "ON_CARD": "Card", "CONNECTED_TO": "Card",
              "LINKS_DEVICE": "DeviceProfile", "SIMILAR_TO": "ClosedCase", "CITES": "Doc"}

LOG: list[dict] = []
calls = 0

_RETRYABLE = re.compile(r"\b50[234]\b|bad gateway|service unavailable|gateway time|timed? ?out|cannot connect|connection reset", re.I)
_state: dict = {}
_lock = threading.Lock()


class MCPError(RuntimeError):
    pass


def _start() -> None:
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    stop = asyncio.Event()
    errlog = open(config.ROOT / ".cache" / "mcp_server.log", "a", encoding="utf-8")
    env = {"TG_HOST": config.TG_HOST, "TG_GRAPHNAME": config.TG_GRAPH, "TG_SECRET": config.TG_SECRET,
           "TG_TGCLOUD": os.environ.get("TG_TGCLOUD", "true"), "TG_ALLOWED_TOOLS": ",".join(ALLOWED_TOOLS)}

    async def main():
        params = StdioServerParameters(command=sys.executable, args=["-m", "tigergraph_mcp.main"],
                                       env=env, cwd=str(config.ROOT))
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    _state["session"] = session
                    ready.set()
                    await stop.wait()
        except BaseException as e:  # surface startup failures to the caller
            _state["error"] = e
            ready.set()

    thread = threading.Thread(target=loop.run_until_complete, args=(main(),), daemon=True, name="tg-mcp")
    thread.start()
    ready.wait(120)
    if "session" not in _state:
        raise MCPError(f"tigergraph-mcp failed to start: {_state.get('error')!r} (see .cache/mcp_server.log)")
    _state.update(loop=loop, thread=thread)

    def _close():
        loop.call_soon_threadsafe(stop.set)
        thread.join(10)
        errlog.close()
    atexit.register(_close)


def _run(coro_fn, timeout=600):
    with _lock:
        if "session" not in _state:
            _start()
    fut = asyncio.run_coroutine_threadsafe(coro_fn(_state["session"]), _state["loop"])
    return fut.result(timeout)


def list_tools() -> list[str]:
    return [t.name for t in _run(lambda s: s.list_tools()).tools]


def _short(v, n=120):
    s = json.dumps(v, default=str)
    return v if len(s) <= n else s[:n] + "..."


def _parse(result) -> dict:
    text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    m = re.match(r"```json\n(.*?)\n```", text, re.S)
    if not m:
        return {"success": not result.isError, "error": text[:500]}
    return json.loads(m.group(1))


def call(tool: str, retries: int = 6, **args):
    """Call one MCP tool; returns the tool's `data` payload (dict/list, None if the tool returned none)."""
    global calls
    name = tool if tool.startswith("tigergraph__") else f"tigergraph__{tool}"
    t0 = time.perf_counter()
    ok, err = False, None
    calls += 1
    try:
        for i in range(retries):
            resp = _parse(_run(lambda s: s.call_tool(name, args)))
            if resp.get("success"):
                ok = True
                return resp.get("data")
            err = resp.get("error") or resp.get("summary")
            if not _RETRYABLE.search(str(err)):
                break
            time.sleep(10 * (i + 1))
        raise MCPError(f"{name} failed: {str(err)[:500]}")
    finally:
        LOG.append({"tool": name, "args": {k: _short(v) for k, v in args.items()},
                    "ms": round((time.perf_counter() - t0) * 1000), "ok": ok})


def reset_log() -> None:
    global calls
    LOG.clear()
    calls = 0


def run_query(name: str, params: dict | None = None) -> dict:
    """Run an installed query. RESTPP returns one dict per PRINT; they are merged into one dict."""
    data = call("run_installed_query", query_name=name, params=params or {})
    return {k: v for part in data["result"] for k, v in part.items()}


def upsert_case(case_vertex: dict, edges: list[tuple]) -> None:
    """Upsert an AgentCase ({"id": ..., <attributes>}) and its edges [(edge_type, target_id), ...].

    Edge target types come from CASE_EDGES. Note: RESTPP upserts create a missing target vertex
    (with default attributes), so only link to IDs read from the graph.
    """
    cid = case_vertex["id"]
    call("add_node", vertex_type="AgentCase", vertex_id=cid,
         attributes={k: v for k, v in case_vertex.items() if k != "id"})
    groups: dict[str, list] = {}
    for etype, target in edges:
        if etype not in CASE_EDGES:
            raise ValueError(f"not an AgentCase edge: {etype}")
        groups.setdefault(etype, []).append(target)
    for etype, targets in groups.items():
        call("add_edges", edge_type=etype,
             edges=[{"source_type": "AgentCase", "source_id": cid, "target_type": CASE_EDGES[etype], "target_id": t}
                    for t in targets])


def upsert_case_embedding(case_id: str, vector: list[float]) -> None:
    data = call("upsert_vectors", vertex_type="AgentCase", vector_attribute="emb",
                vectors=[{"vertex_id": case_id, "vector": vector}])
    if data.get("failed_count"):
        raise MCPError(f"upsert_vectors failed: {data.get('failed')}")
