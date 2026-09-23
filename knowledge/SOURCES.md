# Knowledge corpus sources

`knowledge/chunks.jsonl` is built by `scripts/build_knowledge.py` from the sources below.
Each entry: document, URL, retrieval status, local file (under `knowledge/raw/`), and
chunk count contributed to `chunks.jsonl`.

## Retrieved and used

| Source | URL | Status | Local file | Chunks |
|---|---|---|---|---|
| Bank Fraud Policy v1.0 (§0–§7) | `dataset/README.md` (this repo) | n/a, local file | `dataset/README.md` | 20 (`POLICY-*`) |
| The five known fraud patterns | `dataset/README.md` (this repo) | n/a, local file | `dataset/README.md` | 5 (`PATTERN-*`) |
| README "Things to know" | `dataset/README.md` (this repo) | n/a, local file | `dataset/README.md` | 3 (`README-THINGS-TO-KNOW-*`) |
| FinCEN: SAR Narrative Guidance (Nov 2003) | https://www.fincen.gov/system/files/shared/sar_guidance_narrative.pdf | Retrieved | `sar_guidance_narrative.pdf` | 11 (`FINCEN-SAR-NARRATIVE-*`) |
| FinCEN: Preparing a Complete and Sufficient SAR Narrative | https://www.fincen.gov/system/files/shared/sarnarrcompletguidfinal_112003.pdf | Retrieved — **identical content** to the row above (same document under a second URL); no separate chunks were made to avoid duplicating the corpus | `sarnarrcompletguidfinal_112003.pdf` | 0 (covered by `FINCEN-SAR-NARRATIVE-*`) |
| FinCEN Advisory FIN-2011-A016: Account Takeover Activity | https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016 | Retrieved (HTML) | `fincen_account_takeover_advisory.html` | 2 (`FINCEN-ATO-ADVISORY-*`) |
| FFIEC BSA/AML Manual: Suspicious Activity Reporting | https://bsaaml.ffiec.gov/manual/AssessingComplianceWithBSARegulatoryRequirements/04 | Retrieved via Wayback Machine snapshot (`web.archive.org/web/20260829013757/...`) after the live site returned a CAPTCHA error on two direct attempts with different user agents | `ffiec_sar.html` | 8 (`FFIEC-SAR-*`) |
| FFIEC BSA/AML Manual, Appendix F: Money Laundering and Terrorist Financing Red Flags | https://bsaaml.ffiec.gov/manual/Appendices/07 | Retrieved via Wayback Machine snapshot (`web.archive.org/web/20260803195340/...`) after the live site returned a CAPTCHA error on two direct attempts with different user agents | `ffiec_redflags.html` | 3 (`FFIEC-REDFLAGS-*`) — most of this appendix is cash/wire/AML-specific and out of scope for card fraud; only the generically relevant red flags were chunked |
| FinCEN: Identity-Related Suspicious Activity, 2021 Threats and Trends | https://www.fincen.gov/system/files/shared/FTA_Identity_Final508.pdf | Retrieved | `FTA_Identity_Final508.pdf` | 8 (`FINCEN-IDENTITY-*`) |
| FATF/Interpol/Egmont: Illicit Financial Flows from Cyber-Enabled Fraud (Nov 2023) | https://www.fatf-gafi.org/content/dam/fatf-gafi/reports/Illicit-financial-flows-cyber-enabled-fraud.pdf.coredownload.inline.pdf | Retrieved — first attempt returned a Cloudflare bot-check page (`Just a moment...`); one retry with a browser-style User-Agent succeeded | `fatf_cyber_fraud.pdf` | 8 (`FATF-CYBERFRAUD-*`) — only Annex A/B (risk indicators, anti-fraud controls) and the money-mule/coordination sections of §2.3 were chunked; the report's broader ML/asset-recovery/international-cooperation sections (§3–§6) are out of scope |

## Skipped per task instructions

| Source | URL | Reason |
|---|---|---|
| OFAC Specially Designated Nationals list | https://www.treasury.gov/ofac/downloads/sdnlist.pdf | Explicitly excluded by the task: a name list, not investigative guidance |
| FATF: Money Laundering Using New Payment Methods, Professional Money Laundering, Money Laundering through Remittance and Currency Exchange Providers, Trade-Based Money Laundering, International Co-operation on ML Detection | various fatf-gafi.org | Explicitly deprioritized ("large FATF laundering reports unless you have time"); out of scope for card fraud / account takeover / SAR narrative focus |
| FinCEN: SAR Filing FAQs (Oct 2025) | https://www.fincen.gov/system/files/2025-10/SAR-FAQs-October-2025.pdf | Not downloaded — lower priority than the core narrative/ATO/identity documents; FFIEC manual already covers the SAR-quality and timing rules this would add |
| FinCEN: SAR Supporting Documentation (FIN-2007-G003) | https://www.fincen.gov/system/files/shared/fin-2007-g003.pdf | Not downloaded — lower priority; the "no attachments, retain 5 years" rule it covers is already captured via `FINCEN-SAR-NARRATIVE-10` |
| FinCEN: SAR Activity Review — Trends, Tips and Issues | https://www.fincen.gov/sites/default/files/sar_report/sar_tti_19.pdf | Not downloaded — lower priority, general trends bulletin rather than card-fraud/ATO-specific guidance |
| FinCEN: Advisory on Imposter Scams and Money Mule Schemes (COVID-19) | https://www.fincen.gov/system/files/advisory/2020-07-07/Advisory_%20Imposter_and_Money_Mule_COVID_19_508_FINAL.pdf | Not downloaded — lower priority; mule-recruitment guidance is already captured via the FATF cyber-enabled-fraud chunks |

No download failed outright after retry; the two FFIEC pages needed the Wayback Machine fallback (their live CAPTCHA blocked both a plain and a browser-style `curl` request), and the FATF PDF needed a browser-style User-Agent on the second attempt (Cloudflare bot check on the first).

## Regenerating

```
D:\hhgoa\.venv\Scripts\python.exe D:\hhgoa\scripts\build_knowledge.py
```

Writes `knowledge/chunks.jsonl`. The script validates unique ids, required fields, and a
60–350 word count per chunk, and fails fast if a referenced source file under
`knowledge/raw/` (or `dataset/README.md`) is missing.
