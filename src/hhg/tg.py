"""Thin TigerGraph REST client (bulk loading + admin). The agent itself talks to the graph through TigerGraph MCP."""
import json
import time
from pathlib import Path

import requests

from hhg import config

_TOKEN_FILE = config.ROOT / ".cache" / "tg_token.json"
calls = 0  # REST calls made through this module


def token() -> str:
    if _TOKEN_FILE.exists():
        t = json.loads(_TOKEN_FILE.read_text())
        if t["expires"] > time.time() + 3600:
            return t["token"]
    r = _send("POST", "/gsql/v1/tokens", auth=False,
              json={"secret": config.TG_SECRET, "lifetime": "2592000"})
    tok = r.json()["token"]
    _TOKEN_FILE.parent.mkdir(exist_ok=True)
    _TOKEN_FILE.write_text(json.dumps({"token": tok, "expires": time.time() + 2592000}))
    return tok


def _send(method, path, auth=True, retries=6, **kw):
    """Retries cover Savanna auto-resume: the first requests after idle return 502/503."""
    global calls
    headers = kw.pop("headers", {})
    if auth:
        headers["Authorization"] = f"Bearer {token()}"
    for i in range(retries):
        calls += 1
        r = requests.request(method, config.TG_HOST + path, headers=headers, timeout=600, **kw)
        if r.status_code not in (502, 503, 504):
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r
        time.sleep(10 * (i + 1))
    raise RuntimeError(f"{method} {path} still {r.status_code} after {retries} tries (workspace waking up?)")


def gsql(text: str) -> str:
    r = _send("POST", "/gsql/v1/statements", data=text.encode(), headers={"Content-Type": "text/plain"})
    return r.text


def run_query(name: str, **params) -> list:
    r = _send("POST", f"/restpp/query/{config.TG_GRAPH}/{name}", json=params)
    return r.json()["results"]


def upsert(vertices: dict | None = None, edges: dict | None = None) -> dict:
    body = {"vertices": vertices or {}, "edges": edges or {}}
    return _send("POST", f"/restpp/graph/{config.TG_GRAPH}", json=body).json()


def load_file(job: str, file_var: str, path: Path, chunk_bytes: int = 1_000_000) -> list:
    """Post a file to a loading job (RESTPP /ddl) in ~1 MB pieces: larger bodies get dropped on this
    network. CSV pieces repeat the header line because the jobs skip it."""
    lines = path.read_bytes().splitlines(keepends=True)
    header, body = (lines[0], lines[1:]) if path.suffix == ".csv" else (b"", lines)
    results, piece, size = [], [], 0
    for i, line in enumerate(body):
        piece.append(line)
        size += len(line)
        if size >= chunk_bytes or i == len(body) - 1:
            for attempt in range(5):
                try:
                    r = _send("POST", f"/restpp/ddl/{config.TG_GRAPH}", data=header + b"".join(piece),
                              params={"tag": job, "filename": file_var, "eol": "\n",
                                      "sep": "," if path.suffix == ".csv" else "|"},
                              headers={"Content-Type": "text/csv"})
                    break
                except requests.ConnectionError:
                    if attempt == 4:
                        raise
                    time.sleep(5 * (attempt + 1))
            results.append(r.json())
            piece, size = [], 0
    return results
