"""New cases outside the case pack: from a transaction ID, read its card, customer, amount and bank risk
score from the graph (MCP), build a case-pack style trigger, run the agent, and keep the answer and trace
in cases_new/ (git-ignored, same layout as cases/)."""
import json
from datetime import datetime, timedelta

from hhg import config, mcp_tools
from hhg.agent import FMT, investigate
from hhg.validate import validate_answer

DIR = config.ROOT / "cases_new"
TRIGGERS = ("risk_score", "customer_report", "analyst_request")
# the benchmark period (the dataset's last two months): the window the cardholder portal lists
PERIOD = ("2016-11-01 00:00:00", "2017-01-01 00:00:00")


def lookup(txn_id):
    """{"txn": attributes, "card_id", "customer_id"} for a transaction; LookupError if it is not in the graph."""
    try:
        node = mcp_tools.call("get_node", vertex_type="Txn", vertex_id=txn_id)
    except mcp_tools.MCPError as e:
        raise LookupError(f"transaction {txn_id} is not in the graph") from e
    card = mcp_tools.call("get_neighbors", vertex_type="Txn", vertex_id=txn_id, edge_type="MADE",
                          target_vertex_type="Card")["neighbors"][0]["v_id"]
    cust = mcp_tools.call("get_neighbors", vertex_type="Card", vertex_id=card, edge_type="OWNS",
                          target_vertex_type="Customer")["neighbors"][0]["v_id"]
    return {"txn": node["attributes"], "card_id": card, "customer_id": cust}


def trigger_text(trigger_type, txn, customer_id, message=""):
    """Case-pack wording for each trigger type; an analyst request needs the analyst's own message."""
    amount, where = f"${txn['amount']:,.2f}", ("online" if txn["channel"] == "online"
                                              else f"in billing region {txn['addr1']}")
    if trigger_type == "risk_score":
        return f"Real-time model scored transaction {txn['id']} ({amount}, {where}) at {txn['risk']:.2f}. Review and decide."
    if trigger_type == "customer_report":
        said = message or f"I never made this {amount} purchase. Please check my card."
        return f"Customer {customer_id} message: '{said}' Refers to {txn['id']}."
    if not message:
        raise ValueError("an analyst request needs a message")
    return f"Analyst request: {message} Refers to {txn['id']}."


def make_row(case_id, info, trigger_type, message="", opened_at=None):
    """A case-pack row. Opens one hour after the flagged transaction unless opened_at is given."""
    if trigger_type not in TRIGGERS:
        raise ValueError(f"trigger_type must be one of {TRIGGERS}")
    txn = info["txn"]
    opened = opened_at or (datetime.strptime(txn["ts"][:19], FMT) + timedelta(hours=1)).strftime(FMT)
    if opened < txn["ts"][:19]:
        raise ValueError("the case cannot open before the flagged transaction")
    return {"case_id": case_id, "opened_at": opened, "trigger_type": trigger_type,
            "trigger_text": trigger_text(trigger_type, txn, info["customer_id"], message),
            "flagged_txn_id": txn["id"], "card_id": info["card_id"], "customer_id": info["customer_id"],
            "risk_score": txn["risk"]}


def next_case_id(directory=DIR):
    taken = [int(p.stem[4:]) for p in directory.glob("NEW-*.json") if p.stem[4:].isdigit()]
    return f"NEW-{max(taken, default=0) + 1:03d}"


def open_case(txn_id, trigger_type, message="", opened_at=None, write_graph=False, on_step=None):
    """Investigate a new case end to end. Returns (answer, trace, validation errors)."""
    row = make_row(next_case_id(), lookup(txn_id), trigger_type, message, opened_at)
    answer, trace = investigate(row, write_graph=write_graph, on_step=on_step)
    (DIR / "traces").mkdir(parents=True, exist_ok=True)
    (DIR / f"{row['case_id']}.json").write_text(json.dumps(answer, indent=2, ensure_ascii=False), encoding="utf-8")
    (DIR / "traces" / f"{row['case_id']}.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False),
                                                           encoding="utf-8")
    errors, _ = validate_answer(answer, None)
    return answer, trace, errors


def customer_txns(customer_id, t_from=PERIOD[0], t_to=PERIOD[1]):
    """The customer's transactions on all their cards in the window, newest first."""
    cards = [v["v_id"] for v in mcp_tools.run_query("customer_cases", {"customer_id": customer_id}).get("cards") or []]
    out = []
    for card in cards:
        res = mcp_tools.run_query("card_history", {"card_id": card, "t_from": t_from, "t_to": t_to})
        for v in res.get("txns") or []:
            a = v.get("attributes") or {}
            out.append({"id": v["v_id"], "ts": a.get("ts", ""), "amount": a.get("amount", 0.0),
                        "channel": a.get("channel", ""), "product": a.get("product", ""), "card": card})
    return sorted(out, key=lambda r: r["ts"], reverse=True)
