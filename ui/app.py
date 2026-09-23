"""HHGOA analyst console: Streamlit UI over case answer files and agent trace files.

Reads cases/*.json (answer files, README "Answer Format") and cases/traces/*.json
(trace files, SPEC.md "Trace file"). The "Evidence & approval" tab replays evidence replies through the
policy engine (hhg.policy) and records L1/L2 sign-offs (hhg.approvals); neither touches TigerGraph.

Run:  D:\\hhgoa\\.venv\\Scripts\\streamlit.exe run ui/app.py   (from D:\\hhgoa)
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hhg import approvals, policy  # noqa: E402

st.set_page_config(page_title="HHGOA Fraud Console", layout="wide")

APP_DIR = Path(__file__).resolve().parent
REAL_CASES_DIR = Path("cases")
MOCK_CASES_DIR = APP_DIR / "mock" / "cases"
PENDING = "awaiting reply"

VERDICT_COLOR = {"fraud": "#e5484d", "legitimate": "#30a46c", "uncertain": "#e2a336"}
STATUS_COLOR = {
    "open": "#8b8d98",
    "closed_fraud": "#e5484d",
    "closed_legitimate": "#30a46c",
    "escalated": "#8e4ec6",
}
ROUTE_COLOR = {"auto": "#30a46c", "L1": "#e2a336", "L2": "#e5484d"}
FLAG_COLOR = {"subject": "#e5484d", "suspicious": "#e2a336", "cleared": "#30a46c", "normal": "#8b8d98"}
NODE_SHAPE = {
    "Customer": "ellipse",
    "Card": "box",
    "Transaction": "note",
    "DeviceProfile": "hexagon",
    "EmailDomain": "component",
    "BillingRegion": "diamond",
    "ClosedCase": "folder",
    "AgentCase": "tab",
}

CSS = """
<style>
.badge {display:inline-block; padding:2px 10px; border-radius:11px; font-size:0.78rem;
        font-weight:600; color:#fff; margin-right:6px; white-space:nowrap;}
.chip {display:inline-block; padding:2px 9px; border-radius:8px; font-size:0.75rem;
       background:rgba(127,127,127,0.18); margin:2px 4px 2px 0;}
.mono {font-family:"SFMono-Regular",Consolas,monospace; font-size:0.85rem;}
.sar-box {border:1px solid rgba(127,127,127,0.4); border-radius:8px; padding:16px 18px;
          background:rgba(127,127,127,0.06); line-height:1.55;}
.diff-add {color:#30a46c; font-weight:600;}
.diff-rem {color:#e5484d; font-weight:600; text-decoration:line-through;}
.step-row {padding:4px 0; border-bottom:1px solid rgba(127,127,127,0.15);}
.small-muted {color:#8b8d98; font-size:0.8rem;}
</style>
"""


def badge(text, color):
    return f'<span class="badge" style="background:{color}">{text}</span>'


def chip(text):
    return f'<span class="chip">{text}</span>'


def money(x):
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "—"


def md(text):
    """Escape "$" so dollar amounts in agent text don't render as LaTeX in st.markdown."""
    return str(text).replace("$", "\\$")


# ---------------------------------------------------------------- data ----

def _load_json_files(directory: Path):
    out = {}
    if directory.exists():
        for f in sorted(directory.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out[data.get("case_id", f.stem)] = data
            except (json.JSONDecodeError, OSError):
                continue
    return out


@st.cache_data
def load_cases(base_dir_str: str):
    base_dir = Path(base_dir_str)
    cases = _load_json_files(base_dir)
    traces = _load_json_files(base_dir / "traces")
    return cases, traces


def real_has_cases():
    return REAL_CASES_DIR.exists() and any(REAL_CASES_DIR.glob("*.json"))


# ------------------------------------------------------------- sections ----

def render_header(case_id, case, trace):
    trig = (trace or {}).get("trigger", {})
    c = case["case"]
    left, right = st.columns([3, 2])
    with left:
        st.subheader(case_id)
        if trig:
            st.markdown(
                f'**Trigger:** `{trig.get("trigger_type", "—")}` — {md(trig.get("trigger_text", "—"))}'
            )
            st.markdown(
                f'Flagged txn `{trig.get("flagged_txn_id", "—")}` · '
                f'card `{trig.get("card_id", "—")}` · '
                f'customer `{trig.get("customer_id", "—")}` · '
                f'bank risk score **{trig.get("risk_score") if trig.get("risk_score") is not None else "—"}**'
            )
        else:
            st.caption("No trace file for this case — trigger detail unavailable.")
        st.caption(
            "The bank risk score is an input that flags a transaction for review — "
            "it is never the agent's verdict."
        )
    with right:
        st.markdown(
            badge(c["status"], STATUS_COLOR.get(c["status"], "#8b8d98"))
            + badge(c["verdict"], VERDICT_COLOR.get(c["verdict"], "#8b8d98"))
            + badge(c["pattern"], "#5b5bd6")
            + badge(f'p = {c["fraud_probability"]:.2f}', "#3e63dd"),
            unsafe_allow_html=True,
        )
        if c.get("pattern") == "undocumented" and c.get("pattern_description"):
            st.caption(md(c["pattern_description"]))
        st.metric("Exposure", money(c["exposure_usd"]))


def render_timeline(case, trace):
    st.markdown("#### Investigation timeline")
    tc, tok, lat = case.get("tool_calls"), case.get("tokens"), case.get("latency_s")
    m1, m2, m3 = st.columns(3)
    m1.metric("Tool calls", tc if tc is not None else "—")
    m2.metric("Tokens", tok if tok is not None else "—")
    m3.metric("Latency (s)", lat if lat is not None else "—")
    if not trace or not trace.get("steps"):
        st.info("No trace file — timeline unavailable.")
        return
    for s in trace["steps"]:
        tool = f'<span class="mono">{s["tool"]}</span>' if s.get("tool") else '<span class="small-muted">—</span>'
        st.markdown(
            f'<div class="step-row">'
            f'<b>{s["step"]}. {s["name"]}</b> &nbsp; {tool} &nbsp; '
            f'<span class="small-muted">{s.get("ms", "—")} ms</span><br>'
            f'<span class="small-muted">{s.get("summary", "")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def render_courtroom(trace):
    st.markdown("#### Courtroom")
    if not trace or not trace.get("hypotheses"):
        st.info("No trace file — hypotheses unavailable.")
        return
    hyp = trace["hypotheses"]
    left, right = st.columns(2)

    def render_side(col, title, items, color):
        with col:
            st.markdown(f"**{title}**")
            if not items:
                st.caption("No evidence on this side.")
            for it in items:
                st.progress(min(max(it.get("score", 0), 0.0), 1.0), text=f'{it.get("score", 0):.2f}')
                st.markdown(md(it.get("claim", "")))
                ids = ", ".join(it.get("entity_ids", [])) or "—"
                st.caption(f'{it.get("ref", "—")} · entities: {ids}')

    render_side(left, "Prosecution — evidence for fraud", hyp.get("prosecution", []), "#e5484d")
    render_side(right, "Defence — evidence for legitimacy", hyp.get("defence", []), "#30a46c")

    st.markdown("**Calibrated probability**")
    prob = trace.get("probability", {})
    initial, final = prob.get("initial"), prob.get("final")
    if initial is not None and final is not None:
        thresholds = [(0.15, "§6"), (0.30, "§3a"), (0.70, "R1"), (0.85, "§6")]
        marks = "".join(
            f'<div style="position:absolute; left:{t*100:.1f}%; top:0; bottom:0; '
            f'border-left:1px dashed rgba(127,127,127,0.7);">'
            f'<span style="position:absolute; top:-18px; left:-10px; font-size:0.7rem; color:#8b8d98;">{lbl}</span>'
            f'</div>'
            for t, lbl in thresholds
        )
        bar = (
            f'<div style="position:relative; height:14px; margin:28px 4px 6px 4px; '
            f'background:linear-gradient(90deg,#30a46c,#e2a336,#e5484d); border-radius:7px;">'
            f'{marks}'
            f'<div title="initial {initial:.2f}" style="position:absolute; left:{initial*100:.1f}%; '
            f'top:-6px; width:2px; height:26px; background:#111;"></div>'
            f'<div title="final {final:.2f}" style="position:absolute; left:{final*100:.1f}%; '
            f'top:-6px; width:3px; height:26px; background:#fff; border:1px solid #111;"></div>'
            f'</div>'
        )
        st.markdown(bar, unsafe_allow_html=True)
        st.caption(f"initial {initial:.2f} (dark marker) → final {final:.2f} (light marker)")
    else:
        st.caption("No probability trace recorded.")


def render_evidence(case):
    st.markdown("#### Evidence")
    ev = case["case"].get("evidence", [])
    if ev:
        rows = [
            {
                "claim": e.get("claim", ""),
                "source": e.get("source", ""),
                "ref": e.get("ref", ""),
                "entity_ids": ", ".join(e.get("entity_ids", [])),
            }
            for e in ev
        ]
        st.dataframe(rows, width='stretch', hide_index=True)
    else:
        st.caption("No evidence recorded.")
    prior = case["case"].get("similar_prior_cases", [])
    if prior:
        st.markdown("Similar prior cases: " + "".join(chip(p) for p in prior), unsafe_allow_html=True)


def render_graph(trace):
    st.markdown("#### Graph neighbourhood")
    if not trace or not trace.get("graph"):
        st.info("No trace file — graph unavailable.")
        return
    g = trace["graph"]
    lines = ["digraph G {", 'rankdir=LR; bgcolor="transparent"; node [fontsize=10]; edge [fontsize=8, color="#888888"];']
    for n in g.get("nodes", []):
        color = FLAG_COLOR.get(n.get("flag", "normal"), "#8b8d98")
        shape = NODE_SHAPE.get(n.get("type", ""), "ellipse")
        label = n.get("label", n["id"]).replace('"', "'")
        lines.append(
            f'"{n["id"]}" [label="{label}", shape={shape}, style=filled, '
            f'fillcolor="{color}", fontcolor="white", color="{color}"];'
        )
    for e in g.get("edges", []):
        lines.append(f'"{e["src"]}" -> "{e["dst"]}" [label="{e["type"]}"];')
    lines.append("}")
    st.graphviz_chart("\n".join(lines))
    st.caption(
        "Colour = flag (subject red · suspicious amber · cleared green · normal grey). "
        "Shape = entity type (ellipse Customer · box Card · note Transaction · hexagon DeviceProfile · "
        "diamond BillingRegion · component EmailDomain · folder ClosedCase · tab AgentCase)."
    )


def render_nba(case, trace):
    st.markdown("#### Next best action")
    gate = (trace or {}).get("evidence_gate")
    if gate:
        st.markdown(f'**Evidence gate:** `{gate["type"]}` — {md(gate.get("why", ""))}')
        rows = [{"response": resp, "resulting actions": ", ".join(acts)} for resp, acts in gate.get("outcomes", {}).items()]
        st.dataframe(rows, width='stretch', hide_index=True)
    else:
        st.caption("No evidence gate recorded (stop: no response would change the decision, or no trace file).")

    reqs = case.get("evidence_requests", [])
    if reqs:
        st.markdown("**Evidence requested**")
        st.dataframe(
            [
                {
                    "type": r.get("type", ""),
                    "asked after step": r.get("asked_after_step", ""),
                    "assumed response": r.get("assumed_response", ""),
                }
                for r in reqs
            ],
            width='stretch',
            hide_index=True,
        )
    else:
        st.caption("No evidence requested.")

    nba = case["next_best_actions"]
    initial, final = nba.get("initial", []), nba.get("final", [])
    init_names = {a["action"] for a in initial}
    final_names = {a["action"] for a in final}
    added = final_names - init_names
    removed = init_names - final_names

    def action_list(actions, other_missing):
        html = ""
        for a in actions:
            cls = "diff-add" if a["action"] in other_missing else ""
            html += (
                f'<div style="margin-bottom:8px;"><span class="{cls}">{a["action"]}</span> '
                + badge(a["route"], ROUTE_COLOR.get(a["route"], "#8b8d98"))
                + f'<br><span class="small-muted">{a["reason"]}</span></div>'
            )
        return html or '<span class="small-muted">none</span>'

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Initial**")
        st.markdown(action_list(initial, added), unsafe_allow_html=True)
        if removed:
            st.markdown(
                "Dropped in final: " + ", ".join(f'<span class="diff-rem">{a}</span>' for a in removed),
                unsafe_allow_html=True,
            )
    with c2:
        st.markdown("**Final**")
        st.markdown(action_list(final, set()), unsafe_allow_html=True)
        if added:
            st.caption(f'Added: {", ".join(added)}')

    st.markdown(f'**What changed:** {md(nba.get("what_changed", "—"))}')


def recorded_replies(trace):
    """The replies the agent assumed, in order (None where it left the request pending)."""
    return [(s["args"]["type"], s["args"].get("assumed_response"))
            for s in trace.get("steps", []) if s["name"] == "Request more evidence"]


def render_evidence_replies(case_id, case, trace):
    """Replay evidence replies from the agent's pre-evidence findings. Returns (actions, replies)."""
    st.markdown("#### Evidence replies")
    f0 = (trace or {}).get("findings")
    if not f0:
        st.info("This trace has no findings recorded; rerun the agent on the case to enable replies.")
        return None, []
    st.caption("Starts from the agent's findings before it asked for anything. Choose the reply that came back "
               "and the policy engine re-decides. Preset to the replies the agent assumed.")
    recorded = recorded_replies(trace)
    cur, replies = f0, []
    for i in range(len(policy.EVIDENCE)):
        gate = policy.evidence_gate(cur)
        if gate is None:
            st.caption("No reply to any warranted request would change the actions: the agent stops (§6).")
            break
        options = [PENDING] + policy.RESPONSES[gate["type"]]
        default = recorded[i][1] if i < len(recorded) and recorded[i][0] == gate["type"] else None
        resp = st.radio(f'{i + 1}. `{gate["type"]}` reply', options, horizontal=True,
                        index=options.index(default) if default in options else 0,
                        key=f"reply-{case_id}-{i}-{gate['type']}")
        st.caption(md(gate["why"]))
        if resp == PENDING:
            st.caption("Waiting for this reply: the case stays open with the actions below.")
            break
        cur = policy.apply_response(cur, gate["type"], resp)
        replies.append((gate["type"], resp))

    actions = policy.decide(cur)
    status = policy.status_for(cur, actions)
    file_sar, sar_reason = policy.needs_sar(cur, actions)
    st.markdown(
        badge(status, STATUS_COLOR.get(status, "#8b8d98"))
        + badge(cur["verdict"], VERDICT_COLOR.get(cur["verdict"], "#8b8d98"))
        + badge(f'p {f0["fraud_probability"]:.2f} → {cur["fraud_probability"]:.2f}', "#3e63dd")
        + badge("SAR" if file_sar else "no SAR", "#e5484d" if file_sar else "#8b8d98"),
        unsafe_allow_html=True,
    )
    st.caption(md(sar_reason))
    recorded_final = case["next_best_actions"]["final"]
    if [(a["action"], a["route"]) for a in actions] == [(a["action"], a["route"]) for a in recorded_final]:
        st.caption("Same actions as the recorded answer.")
    else:
        st.caption("Differs from the recorded answer ("
                   + (", ".join(a["action"] for a in recorded_final) or "none") + ").")
    return actions, replies


def render_approvals(case_id, actions, replies, role, analyst):
    st.markdown("#### Approvals")
    st.caption(f"Signed in as {approvals.ROLES[role]} ({role}). Auto actions are executed by the agent; "
               "L1 and L2 actions wait for a human (§2). Every decision is appended to the audit log.")
    log = approvals.history(case_id)
    basis = [list(r) for r in replies]
    note = st.text_input("Note for the audit log", key=f"note-{case_id}")
    for i, a in enumerate(actions):
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f'**{a["action"]}** ' + badge(a["route"], ROUTE_COLOR.get(a["route"], "#8b8d98")),
                        unsafe_allow_html=True)
            st.caption(md(a["reason"]))
        with right:
            if a["route"] == "auto":
                st.caption("executed by the agent")
                continue
            last = next((e for e in reversed(log) if e["action"] == a["action"] and e["responses"] == basis), None)
            if last:
                st.markdown(badge(last["decision"], "#30a46c" if last["decision"] == "approved" else "#e5484d")
                            + f'<span class="small-muted">{last["analyst"]} ({last["role"]}), {last["at"]}</span>',
                            unsafe_allow_html=True)
            if not approvals.can_sign(role, a["route"]):
                st.caption(f'needs a {approvals.ROLES[a["route"]]}')
                continue
            b1, b2 = st.columns(2)
            for col, decision, label in ((b1, "approved", "Approve"), (b2, "rejected", "Reject")):
                if col.button(label, key=f"{decision}-{case_id}-{i}-{a['action']}"):
                    approvals.record(case_id, a["action"], a["route"], decision, role, analyst, note, replies)
                    st.rerun()
    if log:
        st.markdown("**Audit log**")
        st.dataframe([{**e, "responses": "; ".join(f"{t}={r}" for t, r in e["responses"]) or "none"} for e in log],
                     width='stretch', hide_index=True)


def render_decision_desk(case_id, case, trace, role, analyst):
    actions, replies = render_evidence_replies(case_id, case, trace)
    st.divider()
    render_approvals(case_id, actions if actions is not None else case["next_best_actions"]["final"],
                     replies, role, analyst)


def render_sar(case):
    st.markdown("#### Suspicious Activity Report")
    sar = case.get("sar", {})
    if sar.get("file"):
        dates = sar.get("activity_dates", [])
        date_str = " – ".join(dates) if dates else "—"
        st.markdown(
            f'<div class="sar-box">{sar.get("narrative", "")}<br><br>'
            f'<b>Subjects:</b> {", ".join(sar.get("subjects", [])) or "—"}<br>'
            f'<b>Total:</b> {money(sar.get("total_amount_usd", 0))} &nbsp; '
            f'<b>Activity dates:</b> {date_str}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info(f'Not filed. {md(sar.get("reason", ""))}')


def render_summary(case_id, case, trace):
    st.markdown("#### Case summary")
    st.write(md(case["case"].get("summary", "")))
    st.caption(f'Stop reason: {md(case.get("stop_reason", "—"))}')
    st.download_button(
        "Download raw answer JSON",
        data=json.dumps(case, indent=2),
        file_name=f"{case_id}.json",
        mime="application/json",
    )
    if trace and trace.get("rag_context"):
        with st.expander("What the LLM saw — GraphRAG context"):
            st.text(trace["rag_context"])


def render_case_view(case_id, case, trace, role, analyst):
    render_header(case_id, case, trace)
    st.divider()
    tabs = st.tabs(
        ["Timeline", "Courtroom", "Evidence", "Graph", "Next best action", "Evidence & approval", "SAR",
         "Summary"]
    )
    with tabs[0]:
        render_timeline(case, trace)
    with tabs[1]:
        render_courtroom(trace)
    with tabs[2]:
        render_evidence(case)
    with tabs[3]:
        render_graph(trace)
    with tabs[4]:
        render_nba(case, trace)
    with tabs[5]:
        render_decision_desk(case_id, case, trace, role, analyst)
    with tabs[6]:
        render_sar(case)
    with tabs[7]:
        render_summary(case_id, case, trace)


def render_overview(cases, traces):
    st.subheader("Overview — all cases")
    rows = []
    counts = {"fraud": 0, "legitimate": 0, "uncertain": 0}
    for case_id, case in sorted(cases.items()):
        c = case["case"]
        trig = traces.get(case_id, {}).get("trigger", {})
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
        rows.append(
            {
                "case": case_id,
                "trigger": trig.get("trigger_type", "—"),
                "verdict": c["verdict"],
                "pattern": c["pattern"],
                "p": c["fraud_probability"],
                "exposure": c["exposure_usd"],
                "SAR": "yes" if case.get("sar", {}).get("file") else "no",
                "#final actions": len(case.get("next_best_actions", {}).get("final", [])),
                "status": c["status"],
            }
        )
    st.dataframe(rows, width='stretch', hide_index=True)
    cols = st.columns(len(counts))
    for col, (verdict, n) in zip(cols, counts.items()):
        col.metric(verdict, n)


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    st.sidebar.title("HHGOA Fraud Console")

    default_mock = not real_has_cases()
    use_mock = st.sidebar.checkbox("Use mock data", value=default_mock)
    base_dir = MOCK_CASES_DIR if use_mock else REAL_CASES_DIR
    cases, traces = load_cases(str(base_dir))
    role = st.sidebar.selectbox("Signed in as", list(approvals.ROLES),
                                format_func=lambda r: f"{approvals.ROLES[r]} ({r})")
    analyst = st.sidebar.text_input("Analyst name", value="analyst")

    if not cases:
        st.warning(f"No case files found in `{base_dir}`.")
        return

    def case_label(cid):
        c = cases[cid]["case"]
        return f'{cid} · {c["verdict"]} · p={c["fraud_probability"]:.2f} · {c["status"]}'

    options = ["Overview"] + sorted(cases.keys())
    choice = st.sidebar.radio(
        "Case",
        options,
        format_func=lambda o: o if o == "Overview" else case_label(o),
    )

    if choice == "Overview":
        render_overview(cases, traces)
    else:
        render_case_view(choice, cases[choice], traces.get(choice), role, analyst)


main()
