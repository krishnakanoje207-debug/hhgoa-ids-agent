"""Embed closed-case narratives and the knowledge chunks for TigerGraph vector search (GraphRAG).

Writes data_prep/docs.csv, data_prep/emb_closed.txt and data_prep/emb_doc.txt ("id|v1:v2:...").
"""
import json
import re

import pandas as pd

from hhg import config, llm


def case_text(c):
    """Notes are templated; with IDs and numbers masked, 5,565 cases collapse to ~400 distinct texts,
    which keeps embedding fast."""
    note = re.sub(r"\b(CC-\d+|C\d{5}(-K\d)?|\d[\d,.:-]*)\b", "#", c.analyst_notes)
    return f"{c.outcome}; pattern {c.pattern}; actions {c.actions_taken}; report {c.report_filed}. {note}"


def write(path, ids, vecs):
    with open(path, "w") as fh:
        for i, v in zip(ids, vecs):
            fh.write(f"{i}|{':'.join(f'{x:.6f}' for x in v)}\n")


def main():
    docs = pd.DataFrame([json.loads(l) for l in open(config.ROOT / "knowledge" / "chunks.jsonl", encoding="utf-8")])
    docs[["id", "source", "section", "title", "text"]].to_csv(config.PREP / "docs.csv", index=False)
    write(config.PREP / "emb_doc.txt", docs.id, llm.embed((docs.title + ". " + docs.text).tolist()))
    print("docs", len(docs))

    cc = pd.read_csv(config.DATASET / "closed_cases_history.csv", dtype=str).fillna("")
    texts = [case_text(c) for c in cc.itertuples()]
    uniq = sorted(set(texts))
    vec = dict(zip(uniq, llm.embed(uniq)))
    write(config.PREP / "emb_closed.txt", cc.case_id, [vec[t] for t in texts])
    print("closed cases", len(cc))


if __name__ == "__main__":
    main()
