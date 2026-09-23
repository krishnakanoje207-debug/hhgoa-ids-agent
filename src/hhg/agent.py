"""Investigation loop: the brief's 8 steps for one case-pack row.

    answer, trace = investigate(case_row, write_graph=True)

Graph access only through mcp_tools (installed queries + case-memory writes). Card analytics come from
analytics.assess, actions from policy.decide, retrieval from rag.build_context. The LLM plans optional
extra queries (step 2) and writes text (step 7); it never sets verdict, probability, actions or IDs.
Queries never look past `opened_at`.
"""
import csv
import json
import re
import time
from datetime import datetime, timedelta

from hhg import analytics, config, llm, mcp_tools, policy, rag
from hhg.validate import _sentences

FMT = "%Y-%m-%d %H:%M:%S"
QTOOL = "tigergraph__run_installed_query"
# IDs the text checks look for: txns, cards, customers, closed/agent cases
ID_RE = re.compile(r"\b(?:CASE-HHG-\d{3}|HHG-\d{3}|CC-\d{4}|C\d{5}(?:-K\d+)?|\d{7})\b")
TXN_KEYS = ("ts", "amount", "product", "channel", "risk", "addr1", "addr2", "dist1", "p_email", "r_email",
            "m_flags", "c1", "c13", "d1", "d15", "model_score")
# pattern names the LLM must not use for a case of another pattern (it relabels structuring as takeover)
WRONG_PATTERN_WORDS = {"account_takeover": "takeover", "card_testing": "card testing",
                       "out_of_region_use": "out-of-region"}
# probability band in which a simulated reply would only echo the agent's own guess (§3a case threshold 0.30,
# R1 block threshold 0.70): the request is recorded but no answer is assumed
AMBIGUOUS = (0.30, 0.70)
MAX_CASE_READS = 15  # closed cases read per alert for the account-history signal (one get_neighbors call each)
# evidence type -> (response when evidence leans fraud, response when it leans legitimate)
ASSUME = {"customer_validation": ("deny", "confirm"), "step_up_auth": ("fail", "pass"),
          "analyst_info": ("fraud", "legitimate")}
PLANNER_SYSTEM = (
    "You plan optional graph queries for a card-fraud investigation. The mandatory queries already ran. "
    "Pick at most 2 options from OPTIONS that could change the assessment (a second device profile that may "
    "link this card to other cards, or a second billing region). Pick none if nothing is worth checking. "
    'Return JSON {"calls": [{"option": "<option key>", "why": "<short reason>"}], "reasoning": "<1-2 sentences>"}.')
EXPLAIN_SYSTEM = (
    "You write the explanation for a bank fraud investigation. Verdict, probability, pattern, actions, routes "
    "and IDs are final (graph analysis + policy engine): explain them, never change them. Use only facts and "
    "IDs from the context and DECISION; never invent an ID, amount or date. Cite rule numbers (R1-R10, §). "
    "Return one JSON object with keys: summary (2-6 sentences an analyst can read); what_changed (1-2 "
    "sentences on why the final actions differ from the initial ones, or exactly \"nothing\" when no "
    "evidence was requested); pattern_description (2-3 sentences: what the pattern is, who it affects, how "
    "it was found; only when needs_pattern_description is true, else \"\"); sar_narrative (exactly 8 sentences "
    "for a regulator that stand on their own, one each for: who (customer, card), what (txns, total), when "
    "(dates), where (channels, regions), how (device profiles, proxy), why it is suspicious, connected cards, "
    "actions; name every id in sar_subjects; only when needs_sar_narrative is true, else \"\"). Actions routed "
    "L1/L2 await approval: call them recommended, not done. evidence_rewrites (clearer wording of each evidence claim, "
    "same order and count, keeping every ID and number).")


def _fmt(dt):
    return dt.strftime(FMT)


def _dt(s):
    return datetime.strptime(s[:19], FMT)


def _later_case_ids(opened):
    """AgentCase ids of this case and every case (case pack, sentinel or new) opened at/after it: hidden from
    memory (no look-ahead)."""
    with open(config.DATASET / "case_pack.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rows += [json.loads(p.read_text(encoding="utf-8"))["trigger"]
             for d in ("sentinel_cases", "cases_new") for p in (config.ROOT / d / "traces").glob("*.json")]
    return {"CASE-" + r["case_id"] for r in rows if _dt(r["opened_at"]) >= opened}


def _query(name, params):
    """Installed query result, or None when the seed vertex does not exist."""
    try:
        return mcp_tools.run_query(name, params)
    except mcp_tools.MCPError as e:
        if "is not valid" in str(e):
            return None
        raise


def _txn(v):
    a = v.get("attributes") or {}
    r = {"id": v["v_id"], **{k: a.get(k) for k in TXN_KEYS}}
    for k in ("amount", "risk", "model_score"):
        r[k] = float(r[k] or 0)
    for k in ("ts", "product", "channel", "addr1", "addr2", "p_email", "r_email", "m_flags"):
        r[k] = str(r[k] or "")
    for k in ("device", "dev_status", "proxy"):
        vals = sorted(x for x in a.get("@" + k) or [] if x)
        r[k] = vals[0] if vals else ""
    return r


def _device_ctx(device_id, res, hide):
    cards = []
    for v in (res or {}).get("cards") or []:
        a = v.get("attributes") or {}
        c = {"id": v["v_id"], **{k: a.get("@" + k, 0) for k in ("n", "n_new", "amt")},
             **{k: a.get("@" + k, "") for k in ("first", "last")},
             **{k: list(a.get("@" + k) or []) for k in ("txns", "proxy")}}
        c["cases"] = [k for k in a.get("@cases") or [] if k not in hide]
        cards.append(c)
    return {"device_id": device_id, "ever_txns": (res or {}).get("ever_txns", 0),
            "ever_cards": (res or {}).get("ever_cards", 0), "cards": cards}


def _region_ctx(region, res, hide):
    cards = []
    for v in (res or {}).get("new_cards") or []:
        a = v.get("attributes") or {}
        cards.append({"id": v["v_id"], "first": a.get("@first", ""), "n_win": a.get("@n_win", 0),
                      "amt_win": a.get("@amt_win", 0), "channels": list(a.get("@channels") or []),
                      "cases": [k for k in a.get("@cases") or [] if k not in hide]})
    return {"region": region, "region_txns": (res or {}).get("region_txns", 0),
            "region_cards": (res or {}).get("region_cards", 0), "new_cards": cards}


def _customer_ctx(row, res, hide):
    cases = []
    for v in (res or {}).get("cases") or []:
        if v["v_id"] in hide:
            continue
        a = v.get("attributes") or {}
        outcome = a.get("outcome", "") if v["v_type"] == "ClosedCase" else f"agent_{a.get('verdict', '')}"
        cases.append({"id": v["v_id"], "type": v["v_type"], "outcome": outcome, "pattern": a.get("pattern", ""),
                      "opened_at": a.get("opened_at", ""), "cards": list(a.get("@cards") or [])})
    return {"customer_id": row["customer_id"], "card_id": row["card_id"],
            "cards": [v["v_id"] for v in (res or {}).get("cards") or []], "cases": cases}


def _device_claim(ctx, own_txns):
    others = [c for c in ctx["cards"] if not own_txns & set(c["txns"])]
    new = [c for c in others if c["n_new"]]
    cases = sorted({k for c in others for k in c["cases"]})
    return {"claim": f"Device profile {ctx['device_id']} was used by {len(others)} other card(s) in the 30 days "
                     f"before the alert ({len(new)} as a New device; {ctx['ever_cards']} cards ever)"
                     + (f"; their cases: {', '.join(cases[:6])}" if cases else ""),
            "source": "graph", "ref": f"query:device_neighbors(device_id={ctx['device_id']}, window=30d)",
            "entity_ids": [c["id"] for c in others[:10]] + [k for k in cases if k.startswith("CC-")][:6]}


def _region_claim(ctx):
    cards = ctx["new_cards"]
    with_cases = [c for c in cards if c["cases"]]
    return {"claim": f"{len(cards)} card(s) made their first purchase in billing region {ctx['region']} in the 7 days "
                     f"before the alert ({len(with_cases)} linked to cases; {ctx['region_cards']} cards ever billed there)",
            "source": "graph", "ref": f"query:region_cluster(region={ctx['region']}, window=7d)",
            "entity_ids": [c["id"] for c in cards[:10]]}


def _options(txns, flag, opened, devs, regions):
    """Optional-query catalogue: devices / regions seen on this card in the 7 days before opening, nearest to
    the flag first, excluding those already queried."""
    recent = sorted((r for r in txns if _dt(r["ts"]) >= opened - timedelta(days=7)),
                    key=lambda r: abs((_dt(r["ts"]) - _dt(flag["ts"])).total_seconds()))
    dev = list(dict.fromkeys(r["device"] for r in recent if r["device"] and r["device"] not in devs))[:6]
    reg = list(dict.fromkeys(r["addr1"] for r in recent if r["addr1"] and r["addr1"] not in regions))[:6]
    opts = {f"D{i + 1}": ("device_neighbors", d) for i, d in enumerate(dev)}
    opts.update({f"R{i + 1}": ("region_cluster", g) for i, g in enumerate(reg)})
    return opts, recent


def _plan_rules(opts, recent, flag):
    """Deterministic fallback: a device marked New and an in-person region, both within 48 h of the flag."""
    near = [r for r in recent if abs((_dt(r["ts"]) - _dt(flag["ts"])).total_seconds()) <= 48 * 3600]
    new_devs = {r["device"] for r in near if r["dev_status"] == "New"}
    in_person = {r["addr1"] for r in near if r["channel"] == "in_person"}
    picks = []
    for key, (tool, arg) in opts.items():
        want = new_devs if tool == "device_neighbors" else in_person
        if arg in want and not any(opts[p["option"]][0] == tool for p in picks):
            picks.append({"option": key, "why": "rule: " + ("device marked New within 48 h of the flag"
                                                            if tool == "device_neighbors" else
                                                            "in-person region within 48 h of the flag")})
    return picks


def _plan(opts, recent, flag, known_facts):
    """LLM planner over the catalogue; returns (picks, reasoning, source). Rules when the LLM fails."""
    if not opts:
        return [], "no optional query left in the catalogue", "none"
    if llm.available():
        catalogue = {k: {"tool": t, "arg": a, "what": ("other cards on this device profile in 30 days, their "
                                                       "activity and cases" if t == "device_neighbors" else
                                                       "cards new to this billing region in 7 days and their cases")}
                     for k, (t, a) in opts.items()}
        try:
            out = llm.chat_json(PLANNER_SYSTEM, json.dumps({"known": known_facts, "OPTIONS": catalogue}, default=str))
            calls = out.get("calls")
            if not isinstance(calls, list):
                raise ValueError("planner reply has no calls list")
            picks = []
            for c in calls:
                if isinstance(c, dict) and c.get("option") in opts and all(p["option"] != c["option"] for p in picks):
                    picks.append({"option": c["option"], "why": str(c.get("why", ""))[:200]})
            return picks[:2], str(out.get("reasoning", ""))[:400], "llm"
        except Exception as e:  # quota, network or malformed reply
            why = f"LLM planner failed ({type(e).__name__}); deterministic rules used"
    else:
        why = "no LLM configured; deterministic rules used"
    return _plan_rules(opts, recent, flag)[:2], why, "rules"


def _assumption(etype, resp, p, row, flag_id, top_claim):
    lean = (f"the evidence leans towards fraud (probability {p:.2f} >= 0.50; strongest point: {top_claim})"
            if resp in ASSUME[etype][:1] else
            f"the evidence leans legitimate (probability {p:.2f} < 0.50; strongest point: {top_claim})")
    what = {
        "deny": f"Assumed the customer denies making transaction {flag_id} and the related activity and still holds the card",
        "confirm": f"Assumed the customer confirms transaction {flag_id} as their own"
                   + (" and withdraws the dispute" if row["trigger_type"] == "customer_report" else ""),
        "fail": "Assumed the step-up authentication fails (the one-time passcode is not confirmed by the cardholder)",
        "pass": "Assumed the cardholder passes step-up authentication",
        "fraud": "Assumed the analyst resolves the conflicting evidence as fraud",
        "legitimate": "Assumed the analyst resolves the conflicting evidence as legitimate",
    }[resp]
    return f"{what}, because {lean.rstrip('.')}."


def _doc_token(doc_id):
    m = re.fullmatch(r"POLICY-R(\d+)", doc_id)
    if m:
        return re.compile(rf"\bR{m.group(1)}\b")
    m = re.fullmatch(r"POLICY-S(\d+[A-Z]?)(-.*)?", doc_id)
    return re.compile("§" + m.group(1).lower() + r"(?![0-9a-z])") if m else None


def _policy_docs_from_corpus(final):
    """Fallback when retrieval returned no policy passage: the cited rules' Doc ids from the corpus
    that the graph's Doc vertices were loaded from."""
    cited = {f"POLICY-R{n}" for a in final for n in re.findall(r"\bR(\d+)\b", a["reason"])}
    docs = []
    with open(config.ROOT / "knowledge" / "chunks.jsonl", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d["id"] in cited:
                docs.append({"id": d["id"], "title": d.get("title", "")})
    return docs


# ---------------------------------------------------------------- templates (LLM fallback)

def _t_summary(row, f, pattern_reason, affected, first, final, requests):
    s = [f"{row['trigger_type'].replace('_', ' ').capitalize()} alert on card {row['card_id']} "
         f"(customer {row['customer_id']}), flagged transaction {row['flagged_txn_id']}.",
         f"Graph analysis gives verdict {f['verdict']} at fraud probability {f['fraud_probability']:.2f}"
         + (f", pattern {f['pattern']} ({pattern_reason})." if f["pattern"] != "none" else ".")]
    if affected:
        s.append(f"The episode covers {len(affected)} transaction(s) starting at {first}, exposure ${f['exposure_usd']:,.2f}.")
    if requests:
        s.append("Evidence requested: " + "; ".join(r["type"] for r in requests) + ", with the assumed responses in the case file.")
    s.append("Final actions: " + ", ".join(f"{a['action']} ({a['route']})" for a in final) + ".")
    return " ".join(s)


def _t_what_changed(requests, gates, p0, p1, initial, final):
    if not requests:
        return "nothing"
    if not gates:
        return (f"The {requests[0]['type']} response is still pending, so the recommended actions stay as they are "
                f"until it arrives.")
    a0, a1 = [a["action"] for a in initial], [a["action"] for a in final]
    s = (f"The assumed {', '.join(g['type'] + ' response (' + g['assumed'] + ')' for g in gates)} moved the fraud "
         f"probability from {p0:.2f} to {p1:.2f}.")
    return s + (f" Actions changed from {', '.join(a0)} to {', '.join(a1)}." if a0 != a1
                else " The recommended actions stayed the same.")


def _t_pattern(row, pattern_reason, conn_cards, conn_devs, queries):
    who = f"It affects card {row['card_id']} of customer {row['customer_id']}"
    if conn_cards:
        who += f" and {len(conn_cards)} other card(s) ({', '.join(conn_cards[:6])})"
        if conn_devs:
            who += f" that share device profile {conn_devs[0]}"
    return (f"The activity fits none of the five documented patterns: {pattern_reason}. {who}. "
            f"It was found by the agent's graph queries ({', '.join(queries)}) over the card's 60-day history "
            f"and its device and region neighbourhood.")


def _t_sar(row, f, txns, affected, conn_cards, conn_devs, pattern_reason, pros, requests, final, dates):
    rows = [txns[t] for t in affected]
    chans = sorted({r["channel"].replace("_", " ") for r in rows}) or ["unknown"]
    regs = sorted({r["addr1"] for r in rows if r["addr1"]})
    devs = sorted({r["device"] for r in rows if r["device"]})
    why = "; ".join(e["claim"].rstrip(".") for e in pros[:2]) or "the graph analysis scored the episode as fraud"
    when = f"On {dates[0]}" if dates[0] == dates[1] else f"Between {dates[0]} and {dates[1]}"
    s = [f"{when}, card {row['card_id']} held by customer {row['customer_id']} was used "
         f"for {len(rows)} transaction(s) totalling ${f['exposure_usd']:,.2f} that investigation {row['case_id']} "
         f"identified as suspicious.",
         f"The activity began with transaction {affected[0]} at {txns[affected[0]]['ts']} and includes "
         f"{', '.join(affected[:10])}{' and others' if len(affected) > 10 else ''}.",
         f"The transactions were made {' and '.join(chans)}"
         + (f", billed in region(s) {', '.join(regs)}" if regs else "")
         + (f", from device profile(s) {'; '.join(devs[:3])}" if devs else "") + ".",
         f"The activity matches the pattern {f['pattern'].replace('_', ' ')}: {pattern_reason}.",
         f"It is suspicious because {why}."]
    if conn_cards:
        s.append(f"The same device profile {conn_devs[0] if conn_devs else ''} links this activity to card(s) "
                 f"{', '.join(conn_cards)}, which points to a common actor across cardholders.")
    else:
        s.append("No other cardholder's card was linked to this activity by the graph queries run.")
    for r in requests:
        s.append(f"Verification ({r['type'].replace('_', ' ')}): {r['assumed_response']}")
    s.append("Recommended actions: " + ", ".join(a["action"] for a in final) + f"; total suspicious amount "
             f"${f['exposure_usd']:,.2f}.")
    return " ".join(s)


def _mentions(text, entity_id):
    """Whole-ID mention (C12382 does not count as mentioned inside C12382-K1)."""
    return entity_id in ID_RE.findall(text) if ID_RE.fullmatch(entity_id) else entity_id in text


def _ok_text(s, lo, hi, known):
    return (isinstance(s, str) and bool(s.strip()) and lo <= _sentences(s) <= hi
            and set(ID_RE.findall(s)) <= known)


# ---------------------------------------------------------------- UI graph

def _ui_graph(row, txns, affected, cctx, devs, regions, conn_cards, conn_devs, similar, case_node):
    nodes, edges = {}, []

    def node(i, typ, flag, label=None):
        nodes.setdefault(i, {"id": i, "type": typ, "label": label or i, "flag": flag})

    def edge(s, d, t):
        if {"src": s, "dst": d, "type": t} not in edges:
            edges.append({"src": s, "dst": d, "type": t})

    cust, card = row["customer_id"], row["card_id"]
    node(cust, "Customer", "subject")
    node(card, "Card", "subject")
    edge(cust, card, "OWNS")
    for c in cctx["cards"]:
        node(c, "Card", "normal")
        edge(cust, c, "OWNS")
    for t in dict.fromkeys([str(row["flagged_txn_id"]), *affected]):
        r = txns[t]
        node(t, "Transaction", "suspicious" if t in affected else "cleared", f"{t} ${abs(r['amount']):,.2f}")
        edge(card, t, "MADE")
        if r["device"]:
            node(r["device"], "DeviceProfile", "suspicious" if r["device"] in conn_devs else "normal")
            edge(t, r["device"], "FROM_DEVICE")
        if r["addr1"] in regions:
            node("region " + r["addr1"], "BillingRegion", "normal")
            edge(t, "region " + r["addr1"], "BILLED_IN")
    for d, ctx in devs.items():
        node(d, "DeviceProfile", "suspicious" if d in conn_devs else "normal")
        for c in ctx["cards"][:15]:
            node(c["id"], "Card", "suspicious" if c["id"] in conn_cards else "normal")
            edge(c["id"], d, "FROM_DEVICE")
    for g, ctx in regions.items():
        node("region " + g, "BillingRegion", "normal")
        for c in ctx["new_cards"][:10]:
            node(c["id"], "Card", "normal")
            edge(c["id"], "region " + g, "BILLED_IN")
    for k in cctx["cases"]:
        fraud, legit = k["outcome"] in ("confirmed_fraud", "agent_fraud"), k["outcome"] in ("cleared", "agent_legitimate")
        node(k["id"], k["type"], "suspicious" if fraud else "cleared" if legit else "normal")
        for c in k["cards"]:
            if c in nodes:
                edge(k["id"], c, "ON_CARD")
    if case_node:
        node(case_node, "AgentCase", "subject")
        edge(case_node, card, "ON_CARD")
        for s in similar:
            node(s["id"], s["type"], "suspicious" if s["outcome_or_verdict"] in ("confirmed_fraud", "fraud")
                 else "cleared" if s["outcome_or_verdict"] in ("cleared", "legitimate") else "normal")
            edge(case_node, s["id"], "SIMILAR_TO")
    return {"nodes": list(nodes.values()), "edges": edges}


# ---------------------------------------------------------------- the loop

def investigate(case_row, write_graph=True, on_step=None):
    """Investigate one case-pack row. Returns (answer, trace): README Answer Format / SPEC trace file.
    on_step(step_dict) is called as each step completes (the console streams them)."""
    wall0, calls0, tok0 = time.perf_counter(), mcp_tools.calls, llm.tokens_used
    row = dict(case_row)
    row["flagged_txn_id"] = flag_id = str(row["flagged_txn_id"])
    row["risk_score"] = float(row["risk_score"]) if row.get("risk_score") not in (None, "") else None
    cid, card, cust = row["case_id"], row["card_id"], row["customer_id"]
    opened, graph_case_id = _dt(row["opened_at"]), "CASE-" + row["case_id"]
    hide = _later_case_ids(opened)
    steps, raw = [], []  # raw: every query result, for the ID whitelist of LLM text

    def step(n, name, tool, args, summary, t0):
        steps.append({"step": n, "name": name, "tool": tool, "args": args, "summary": summary,
                      "ms": round((time.perf_counter() - t0) * 1000)})
        if on_step:
            on_step(steps[-1])

    def run(name, params, label, summarize):
        t0 = time.perf_counter()
        res = _query(name, params)
        raw.append(res)
        shown = {k: (f"<{len(v)}-d vector>" if isinstance(v, list) else v) for k, v in params.items()}
        step(2, label, QTOOL, {"query": name, **shown}, "not found in graph" if res is None else summarize(res), t0)
        return res

    def win(days):
        return {"t_from": _fmt(opened - timedelta(days=days)), "t_to": _fmt(opened)}

    # 1. Trigger
    t0 = time.perf_counter()
    step(1, "Trigger received", None, {"trigger_type": row["trigger_type"]},
         f"{row['trigger_type']} alert on card {card}, flagged txn {flag_id}"
         + (f", bank risk score {row['risk_score']:.2f} (a reason to look, not a verdict)" if row["risk_score"] is not None else ""), t0)

    # 2. Investigate: mandatory queries, then planner-chosen optional ones
    res = run("card_history", {"card_id": card, **win(60)}, "Card history (60 days to opening)",
              lambda r: f"{len(r.get('txns') or [])} txns on {card}")
    txn_list = sorted((_txn(v) for v in (res or {}).get("txns") or []), key=lambda r: r["ts"])
    txns = {r["id"]: r for r in txn_list}
    if flag_id not in txns:
        raise LookupError(f"{cid}: flagged txn {flag_id} not returned by card_history({card}); is the graph loaded?")
    flag = txns[flag_id]
    cres = run("customer_cases", {"customer_id": cust}, "Customer cards and prior cases",
               lambda r: f"{len(r.get('cards') or [])} card(s), {len(r.get('cases') or [])} case(s)")
    cctx = _customer_ctx(row, cres, hide)
    # account history (analytics._account): which of this card's txns are in its closed cases. Only cases on this
    # card opened inside the history window and before opening can hold them; most recent first, at most MAX_CASE_READS
    if flag["addr1"] and (flag["d1"] or 0) > 0:
        rel = sorted((k for k in cctx["cases"] if k["type"] == "ClosedCase" and card in k["cards"] and k["opened_at"]
                      and opened - timedelta(days=60) <= _dt(k["opened_at"]) < opened), key=lambda k: k["opened_at"], reverse=True)
        cctx["case_txns"], cctx["case_txns_partial"] = {}, len(rel) > MAX_CASE_READS
        for k in rel[:MAX_CASE_READS]:
            t0 = time.perf_counter()
            nb = mcp_tools.call("get_neighbors", vertex_type="ClosedCase", vertex_id=k["id"], edge_type="INVOLVES",
                                target_vertex_type="Txn")
            raw.append(nb)
            got = [n["v_id"] for n in (nb or {}).get("neighbors") or []]
            for t in got:
                if t in txns:
                    cctx["case_txns"].setdefault(t, (k["id"], k["outcome"], k["opened_at"]))
            step(2, "Closed case txns (account history)", "tigergraph__get_neighbors",
                 {"vertex_id": k["id"], "edge_type": "INVOLVES"}, f"{len(got)} txn(s) in {k['id']} ({k['outcome']})", t0)

    devs, regions = {}, {}
    near = sorted((r for r in txn_list if r["device"] and abs((_dt(r["ts"]) - _dt(flag["ts"])).total_seconds()) <= 48 * 3600),
                  key=lambda r: abs((_dt(r["ts"]) - _dt(flag["ts"])).total_seconds()))
    device = flag["device"] or (near[0]["device"] if near else "")

    def ask_device(d):
        r = run("device_neighbors", {"device_id": d, **win(30)}, "Device neighbourhood (30 days)",
                lambda r: f"{len(r.get('cards') or [])} card(s) used it in the window, {r.get('ever_cards', 0)} ever")
        devs[d] = _device_ctx(d, r, hide)

    def ask_region(g):
        r = run("region_cluster", {"region": g, **win(7)}, "Region cluster (7 days)",
                lambda r: f"{len(r.get('new_cards') or [])} card(s) new to region {g} in the window")
        regions[g] = _region_ctx(g, r, hide)

    if device:
        ask_device(device)
    if flag["channel"] == "in_person" and flag["addr1"]:
        ask_region(flag["addr1"])

    t0 = time.perf_counter()
    opts, recent = _options(txn_list, flag, opened, devs, regions)
    known_facts = {
        "trigger": row["trigger_text"], "flagged": {k: flag[k] for k in ("ts", "amount", "channel", "product", "addr1",
                                                                        "device", "dev_status", "proxy", "model_score")},
        "card_txns_60d": len(txn_list),
        "recent_7d": [{k: r[k] for k in ("ts", "amount", "channel", "addr1", "device", "dev_status")} for r in recent[:15]],
        "device_neighbors_done": {d: {"cards": len(c["cards"]), "new_on": sum(1 for x in c["cards"] if x["n_new"])}
                                  for d, c in devs.items()},
        "region_cluster_done": {g: len(c["new_cards"]) for g, c in regions.items()},
        "customer_cases": [(k["id"], k["outcome"], k["pattern"]) for k in cctx["cases"]]}
    picks, reasoning, source = _plan(opts, recent, flag, known_facts)
    step(2, "Plan optional queries", None if source != "llm" else "llm",
         {"source": source, "choices": [{"tool": opts[p["option"]][0], "arg": opts[p["option"]][1], "why": p["why"]}
                                        for p in picks], "catalogue": len(opts)},
         reasoning or "planner chose no extra query", t0)
    for p in picks:
        tool, arg = opts[p["option"]]
        (ask_device if tool == "device_neighbors" else ask_region)(arg)

    # 3. Gather evidence: card-level analytics -> Findings
    t0 = time.perf_counter()
    dctx = devs.get(device) or next(iter(devs.values()), None)
    own = set(cctx["cards"]) | {card}
    # R6 shared origin (analytics._shared_origin): on a rare device, read the txns (emails, times) of the other
    # cards active on it from 7 days before the flag up to opening
    lo = _dt(flag["ts"]) - timedelta(days=7)
    if (dctx and dctx["device_id"] == flag["device"] and flag["p_email"] and flag["r_email"]
            and 0 < dctx["ever_cards"] <= analytics.SHARED_MAX_CARDS):
        cands = [c["id"] for c in dctx["cards"] if c["id"] not in own and c["last"] and _dt(c["last"]) >= lo]
        if len(cands) >= 2:
            dctx["recent_txns"] = []
            for c in cands:
                r = run("card_history", {"card_id": c, "t_from": _fmt(lo), "t_to": _fmt(opened)},
                        "Card history of a card sharing the device (7 days before the flag to opening)",
                        lambda r, c=c: f"{len(r.get('txns') or [])} txns on {c}")
                dctx["recent_txns"] += [dict(_txn(v), card_id=c) for v in (r or {}).get("txns") or []]
    a = analytics.assess(txn_list, flag_id, row["opened_at"], row["trigger_type"], device_ctx=dctx, customer_ctx=cctx)
    ep = a["episode"]
    confirmed_cards = {c for k in cctx["cases"] if k["outcome"] == "confirmed_fraud" for c in k["cards"] if c in own}
    f = {"trigger_type": row["trigger_type"], "fraud_probability": a["fraud_probability"], "verdict": a["verdict"],
         "pattern": a["pattern"], "independent_evidence": a["independent_evidence"],
         "single_signal": a["single_signal"], "evidence_conflicts": a["evidence_conflicts"],
         "exposure_usd": ep["exposure_usd"], "card_testing": a["card_testing"],
         "cleared_purchase_over_100": a["cleared_purchase_over_100"], "shared_origin": a.get("shared_origin"),
         "connects_to_other_fraud": bool(a.get("connects_to_other_fraud")),
         "recurring_match": bool(a.get("recurring_match")),
         "customer_cards_confirmed_fraud": len(confirmed_cards),
         "credentials_compromised": False,  # no credential-compromise signal exists in the graph
         "customer_response": None, "step_up_result": None}
    own_txns = set(txns)
    extra_claims = ([_device_claim(c, own_txns) for d, c in devs.items() if not (a.get("shared_origin") and d == dctx["device_id"])]
                    + [_region_claim(c) for c in regions.values()])
    step(3, "Gather evidence (card analytics)", None, {"device_ctx": dctx["device_id"] if dctx else None},
         f"pattern {a['pattern']} ({a['pattern_reason']}); {len(ep['affected_txn_ids'])} episode txn(s), "
         f"exposure ${ep['exposure_usd']:,.2f}; {len(a['prosecution'])} prosecution / {len(a['defence'])} defence items", t0)

    # 4. Assess uncertainty
    t0 = time.perf_counter()
    initial = policy.decide(f)
    step(4, "Assess uncertainty", None, {"fraud_probability": f["fraud_probability"], "verdict": f["verdict"]},
         f"probability {f['fraud_probability']:.2f}, verdict {f['verdict']}, {f['independent_evidence']} independent "
         f"evidence, single_signal={f['single_signal']}, conflicts={f['evidence_conflicts']}; initial: "
         + ", ".join(x["action"] for x in initial), t0)

    # 5. Gather more evidence if needed (decision-flip gate; responses simulated from the evidence balance)
    gate0 = gate = policy.evidence_gate(f)
    cur, requests, gates = f, [], []
    while gate and len(requests) < len(ASSUME):
        t0 = time.perf_counter()
        p = cur["fraud_probability"]
        if AMBIGUOUS[0] < p < AMBIGUOUS[1]:  # balanced evidence: don't presume the answer, keep the case open
            requests.append({"type": gate["type"], "asked_after_step": 4 if not requests else 5,
                             "assumed_response": f"No response assumed yet: the evidence is balanced (probability "
                                                 f"{p:.2f}), so the agent does not presume the {gate['type']} outcome; "
                                                 f"the case stays open until it arrives."})
            step(5, "Request more evidence", None, {"type": gate["type"], "assumed_response": None},
                 f"{gate['why']} Evidence balanced (p {p:.2f}): request left pending, case stays open", t0)
            break
        resp = ASSUME[gate["type"]][0 if p >= 0.5 else 1]
        side = a["prosecution"] if p >= 0.5 else a["defence"]
        top = max(side, key=lambda e: e["score"])["claim"] if side else "no other signal beyond the alert"
        requests.append({"type": gate["type"], "asked_after_step": 4 if not requests else 5,
                         "assumed_response": _assumption(gate["type"], resp, p, row, flag_id, top)})
        gates.append({**gate, "assumed": resp})
        cur = policy.apply_response(cur, gate["type"], resp)
        step(5, "Request more evidence", None, {"type": gate["type"], "assumed_response": resp},
             f"{gate['why']} Assumed '{resp}': probability {p:.2f} -> {cur['fraud_probability']:.2f}", t0)
        gate = policy.evidence_gate(cur)
    if not requests:
        step(5, "Evidence gate", None, {}, "no response to any warranted request changes the actions: stop", time.perf_counter())
    final = policy.decide(cur) if requests else initial
    _, stop_reason = policy.should_stop(cur)

    # final episode
    legit = cur["verdict"] == "legitimate"
    affected = [] if legit else list(ep["affected_txn_ids"] or a.get("candidate_txn_ids") or [])
    if affected != ep["affected_txn_ids"]:
        cur = {**cur, "exposure_usd": round(sum(abs(txns[t]["amount"]) for t in affected), 2)}
    first = affected[0] if affected else ""
    conn_cards = [] if legit else list(a.get("connected_card_ids") or [])
    conn_devs = [] if legit else list(a.get("connected_device_profiles") or [])

    # 6. Actions
    t0 = time.perf_counter()
    auto = [x["action"] for x in final if x["route"] == "auto"]
    held = [f"{x['action']} ({x['route']})" for x in final if x["route"] != "auto"]
    step(6, "Next best actions", None, {"final": [x["action"] for x in final]},
         f"executed (auto): {', '.join(auto) or 'none'}; awaiting approval: {', '.join(held) or 'none'}", t0)
    status = policy.status_for(cur, final)
    file_sar, sar_reason = policy.needs_sar(cur, final)

    # 7. Explain: GraphRAG context + one LLM call for text
    t0 = time.perf_counter()
    graph_facts = [e["claim"] + f" ({e['ref']})" for e in extra_claims]
    graph_facts += [f"Customer {cust} cards: {', '.join(cctx['cards']) or card}; prior cases on them: "
                    + (", ".join(f"{k['id']} ({k['outcome']}, {k['pattern']})" for k in cctx["cases"]) or "none")
                    + " (query:customer_cases)"]
    rfind = {**a, **cur, "episode": {"affected_txn_ids": affected, "first_suspicious_txn_id": first,
                                     "exposure_usd": cur["exposure_usd"]},
             "rule_ids": [x["reason"] for x in final]}
    try:
        rctx = rag.build_context(row, rfind, graph_facts)
        rag_err = ""
    except Exception as e:  # retrieval down: explain from the graph evidence alone
        rctx, rag_err = {"context": "", "similar_cases": [], "docs": [], "calls": 0}, f"{type(e).__name__}: {e}"
    raw.append(rctx["similar_cases"])
    step(7, "GraphRAG retrieval", QTOOL, {"queries": ["similar_cases", "search_docs"], "calls": rctx["calls"]},
         f"{len(rctx['similar_cases'])} similar case(s), {len(rctx['docs'])} passage(s)" + (f"; failed: {rag_err[:200]}" if rag_err else ""), t0)
    similar_cc = [s for s in rctx["similar_cases"] if s["type"] == "ClosedCase" and re.fullmatch(r"CC-\d{4}", s["id"])]
    similar_ac = [s for s in rctx["similar_cases"] if s["type"] == "AgentCase"]

    evidence = [{"claim": e["claim"], "source": "graph", "ref": e["ref"], "entity_ids": list(e["entity_ids"])}
                for e in a["prosecution"] + a["defence"]] + extra_claims
    if row["trigger_type"] == "customer_report":
        evidence.append({"claim": f"Customer {cust} disputed transaction {flag_id}: \"{row['trigger_text']}\"",
                         "source": "customer", "ref": "case_pack:trigger_text", "entity_ids": [flag_id, cust]})
    for i, r in enumerate(requests):
        evidence.append({"claim": r["assumed_response"], "source": "external" if r["type"] == "analyst_info" else "customer",
                         "ref": f"evidence_request:{i + 1}", "entity_ids": []})
    if similar_cc or similar_ac:
        evidence.append({"claim": "Nearest cases in case memory: " + "; ".join(
            f"{s['id']} ({s['outcome_or_verdict']}, {s['pattern']})" for s in similar_cc + similar_ac),
            "source": "graph", "ref": "query:similar_cases", "entity_ids": [s["id"] for s in similar_cc]})
    pol = [d for d in rctx["docs"] if d["id"].startswith("POLICY-")] or _policy_docs_from_corpus(final)
    for d in pol:
        tok = _doc_token(d["id"])
        using = [x["action"] for x in final if tok and tok.search(x["reason"])]
        evidence.append({"claim": f"Fraud Policy {d['title'] or d['id']}"
                                  + (f": basis for {', '.join(using)}" if using else ": retrieved as context"),
                         "source": "document", "ref": d["id"], "entity_ids": []})
    other_docs = [d for d in rctx["docs"] if not d["id"].startswith("POLICY-")]
    if other_docs:
        evidence.append({"claim": "Typology and regulatory guidance retrieved: " + "; ".join(d["title"] or d["id"] for d in other_docs),
                         "source": "document", "ref": ", ".join(d["id"] for d in other_docs), "entity_ids": []})

    dates = sorted(txns[t]["ts"][:10] for t in affected) or [flag["ts"][:10]]
    dates = [dates[0], dates[-1]]
    subj_all = list(dict.fromkeys([cust, card] + conn_cards + conn_devs))
    queries_run = list(dict.fromkeys(s["args"]["query"] for s in steps if s["tool"] == QTOOL and "query" in s["args"]))
    tmpl = {
        "summary": _t_summary(row, cur, a["pattern_reason"], affected, first, final, requests),
        "what_changed": _t_what_changed(requests, gates, f["fraud_probability"], cur["fraud_probability"], initial, final),
        "pattern_description": _t_pattern(row, a["pattern_reason"], conn_cards, conn_devs, queries_run)
        if cur["pattern"] == "undocumented" else "",
        "sar_narrative": _t_sar(row, cur, txns, affected, conn_cards, conn_devs, a["pattern_reason"], a["prosecution"],
                                requests, final, dates) if file_sar and affected else "",
    }
    known = set(ID_RE.findall(json.dumps([raw, row], default=str))) | {graph_case_id}
    text, fell_back = dict(tmpl), []
    t0 = time.perf_counter()
    out = None
    if llm.available():
        decision = {"case_id": cid, "customer_id": cust, "card_id": card, "flagged_txn": flag, "verdict": cur["verdict"],
                    "fraud_probability": cur["fraud_probability"], "pattern": cur["pattern"],
                    "pattern_reason": a["pattern_reason"], "affected_txn_ids": affected, "first_suspicious_txn_id": first,
                    "exposure_usd": cur["exposure_usd"], "connected_card_ids": conn_cards,
                    "connected_device_profiles": conn_devs, "evidence_requests": requests,
                    "initial_actions": initial, "final_actions": final, "status": status, "stop_reason": stop_reason,
                    "needs_pattern_description": cur["pattern"] == "undocumented",
                    "needs_sar_narrative": bool(tmpl["sar_narrative"]), "sar_subjects": subj_all,
                    "activity_dates": dates, "evidence_claims": [e["claim"] for e in evidence]}
        try:
            out = llm.chat_json(EXPLAIN_SYSTEM, (rctx["context"] or "(retrieval unavailable)")
                                + "\n\nDECISION\n" + json.dumps(decision, default=str))
        except Exception as e:
            fell_back.append(f"llm call failed: {type(e).__name__}")
    else:
        fell_back.append("no LLM configured")
    if isinstance(out, dict):
        checks = {"summary": (2, 6), "what_changed": (1, 2), "pattern_description": (2, 3), "sar_narrative": (6, 12)}
        for k, (lo, hi) in checks.items():
            if not tmpl[k] or (k == "what_changed" and not requests):
                continue  # field not required: keep "" / "nothing"
            ok = _ok_text(out.get(k), lo, hi, known) and not any(
                p != cur["pattern"] and w in out[k].lower() for p, w in WRONG_PATTERN_WORDS.items())
            if k == "sar_narrative" and ok:
                ok = _mentions(out[k], cust) and _mentions(out[k], card)
            if ok:
                text[k] = out[k].strip()
            else:
                fell_back.append(k)
        rw = out.get("evidence_rewrites")
        if isinstance(rw, list) and len(rw) == len(evidence):
            for e, new in zip(evidence, rw):
                if isinstance(new, str) and new.strip() and set(ID_RE.findall(new)) <= set(ID_RE.findall(e["claim"])) | set(e["entity_ids"]):
                    e["claim"] = new.strip()
    elif out is not None:
        fell_back.append("llm reply not an object")
    step(7, "Explain decision", "llm" if isinstance(out, dict) else None, {"fallback": fell_back},
         ("LLM text validated" if isinstance(out, dict) else "deterministic templates")
         + (f"; template used for: {', '.join(fell_back)}" if fell_back else ""), t0)

    sar = {"file": file_sar, "reason": sar_reason, "narrative": "", "subjects": [], "total_amount_usd": 0,
           "activity_dates": []}
    if file_sar:
        sar.update(narrative=text["sar_narrative"], subjects=[s for s in subj_all if _mentions(text["sar_narrative"], s)],
                   total_amount_usd=cur["exposure_usd"], activity_dates=dates)

    answer = {
        "case_id": cid,
        "case": {"status": status, "verdict": cur["verdict"], "fraud_probability": cur["fraud_probability"],
                 "pattern": cur["pattern"], "pattern_description": text["pattern_description"],
                 "affected_txn_ids": affected, "first_suspicious_txn_id": first, "connected_card_ids": conn_cards,
                 "connected_device_profiles": conn_devs, "exposure_usd": cur["exposure_usd"], "evidence": evidence,
                 "similar_prior_cases": [s["id"] for s in similar_cc], "summary": text["summary"],
                 "written_to_graph": bool(write_graph), "graph_case_id": graph_case_id if write_graph else ""},
        "evidence_requests": requests,
        "next_best_actions": {"initial": initial, "final": final, "what_changed": text["what_changed"]},
        "sar": sar,
        "stop_reason": stop_reason,
        "tool_calls": 0, "tokens": 0, "latency_s": 0.0,
    }

    # 8. Update case memory
    if write_graph:
        t0 = time.perf_counter()
        edges = ([("INVOLVES", t) for t in affected] + [("ON_CARD", card)]
                 + [("CONNECTED_TO", c) for c in conn_cards] + [("LINKS_DEVICE", d) for d in conn_devs]
                 + [("SIMILAR_TO", s["id"]) for s in similar_cc] + [("CITES", d["id"]) for d in rctx["docs"]])
        vertex = {"id": graph_case_id, "case_id": cid, "created_at": row["opened_at"], "status": status,
                  "verdict": cur["verdict"], "pattern": cur["pattern"], "probability": cur["fraud_probability"],
                  "exposure": cur["exposure_usd"], "summary": text["summary"],
                  "answer_json": json.dumps(answer, ensure_ascii=False)}
        note = ""
        try:
            mcp_tools.upsert_case(vertex, edges)
            try:
                mcp_tools.upsert_case_embedding(graph_case_id, llm.embed([rag.case_embedding_text(answer)])[0])
            except Exception as e:
                note = f"; embedding failed: {type(e).__name__}: {str(e)[:150]}"
        except Exception as e:
            answer["case"].update(written_to_graph=False, graph_case_id="")
            note = f"; write failed: {type(e).__name__}: {str(e)[:200]}"
        step(8, "Update case memory", "tigergraph__add_node", {"vertex": "AgentCase", "id": graph_case_id,
                                                               "edges": len(edges)},
             ("wrote " if answer["case"]["written_to_graph"] else "did not write ") + graph_case_id + note, t0)
    else:
        step(8, "Update case memory", None, {}, "graph write disabled (dry run)", time.perf_counter())

    answer["tool_calls"] = mcp_tools.calls - calls0
    answer["tokens"] = llm.tokens_used - tok0
    answer["latency_s"] = round(time.perf_counter() - wall0, 1)

    trace = {
        "case_id": cid,
        "trigger": {k: row.get(k) for k in ("case_id", "opened_at", "trigger_type", "trigger_text", "flagged_txn_id",
                                            "card_id", "customer_id", "risk_score")},
        "steps": steps,
        "findings": f,  # before any evidence request: the UI what-if replays replies from here
        "hypotheses": {"prosecution": a["prosecution"], "defence": a["defence"]},
        "probability": {"initial": f["fraud_probability"], "final": cur["fraud_probability"],
                        "features": a.get("features") or {}},
        "evidence_gate": ({**gate0, "assumed_response": gates[0]["assumed"] if gates else None} if gate0 else None),
        "graph": _ui_graph(row, txns, affected, cctx, devs, regions, conn_cards, conn_devs, rctx["similar_cases"],
                           answer["case"]["graph_case_id"]),
        "rag_context": rctx["context"],
    }
    return answer, trace
