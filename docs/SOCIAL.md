# Social posts

## X (≤280 chars)

```
Built a fraud agent on @TigerGraphDB for HHGOA @247pmstudio: 99.3% verdict accuracy on 1,376 held-out cases,
just 2 of 1,258 frauds cleared by mistake. It argues both sides and writes every case back to the
graph. Blog: [blog link] Demo: https://drive.google.com/file/d/16rMjGdsbA4KBOAKjSAZYw7p_FWWT6k_b/view
```
(272 characters as X counts them, with each link at 23)

## LinkedIn (~300 words)

We spent the hackathon building an agentic fraud investigator on TigerGraph — not a classifier,
an investigator. Given a trigger (a risk-score alert, a customer report, or an analyst request),
the agent pulls a card's history, its device and region neighbourhood, and prior cases straight
out of a TigerGraph knowledge graph via TigerGraph MCP, then argues both sides before deciding
anything: prosecution evidence (shared device rings, shared regions, testing sequences) against
defence evidence (a trip, a new phone, a recurring charge, the customer's own stated intent).

The numbers, on 1,376 of the bank's own closed cases that we never trained on:
• 99.3% verdict accuracy when the agent decides
• Only 2 of 1,258 frauds called legitimate (down from 121 after two fixes)
• 99.6% of its fraud calls were fraud; the pattern named right 92.8% of the time
• All 20 exam cases answered, validated and written back to the graph

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

Built for HHGOA by @247pmstudio, with @TigerGraphDB Savanna, TigerGraph MCP, and GraphRAG over policy, regulatory, and
case-history text.

Blog: [blog link]
Demo: https://drive.google.com/file/d/16rMjGdsbA4KBOAKjSAZYw7p_FWWT6k_b/view
