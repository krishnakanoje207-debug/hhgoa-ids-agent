# Social posts

## X (≤280 chars)

```
Built a fraud agent on @TigerGraphDB for HHGOA: it argues prosecution vs. defence on every case,
only asks for evidence when the answer could flip the decision, and writes every closed case
back to the graph as memory. Blog: [link] Demo: [link]
```
(244 characters)

## LinkedIn (~230 words)

We spent the hackathon building an agentic fraud investigator on TigerGraph — not a classifier,
an investigator. Given a trigger (a risk-score alert, a customer report, or an analyst request),
the agent pulls a card's history, its device and region neighbourhood, and prior cases straight
out of a TigerGraph knowledge graph via TigerGraph MCP, then argues both sides before deciding
anything: prosecution evidence (shared device rings, shared regions, testing sequences) against
defence evidence (a trip, a new phone, a recurring charge, the customer's own stated intent).

A deterministic policy engine — never the LLM — turns that evidence into a recommendation and
an approval route, and only asks for one more piece of evidence if some possible answer would
actually change the outcome. Every closed case gets written back into the graph, so the next
investigation inherits it.

One finding along the way: on this bank's own confirmed-vs-cleared cases, its live risk score
scored worse than random. Worth knowing before you trust a fraud score.

What we'd build next with more time: real customer channels in place of simulated replies,
proper sign-in and a tamper-proof audit trail for approvals, community detection on the graph,
and an agent that learns from how cases actually end, so every analyst decision sharpens the
next investigation.

Built with @TigerGraphDB Savanna, TigerGraph MCP, and GraphRAG over policy, regulatory, and
case-history text.

Blog: [link]
Demo: [link]
