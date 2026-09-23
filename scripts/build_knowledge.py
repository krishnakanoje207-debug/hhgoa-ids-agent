"""Build knowledge/chunks.jsonl for the GraphRAG fraud-investigation corpus.

Each chunk is {"id", "source", "section", "title", "text"}. Text is curated
(quoted or closely paraphrased, never invented) from:
  - dataset/README.md: the Fraud Policy (verbatim, source "bank_fraud_policy_v1.0"),
    the five known fraud patterns, and the "Things to know" notes.
  - knowledge/raw/*.pdf|*.html: regulatory guidance downloaded per the README's
    "Regulatory references" list.

The excerpts below were extracted by hand from the files in knowledge/raw and
dataset/README.md and checked against them; this script's job is to assemble,
validate (word count 60-350, unique ids, required fields) and write them out
deterministically, and to fail fast if the underlying source files are gone.
Run: D:\\hhgoa\\.venv\\Scripts\\python.exe D:\\hhgoa\\scripts\\build_knowledge.py
"""
import json
from pathlib import Path

ROOT = Path(r"D:\hhgoa")
README = ROOT / "dataset" / "README.md"
RAW = ROOT / "knowledge" / "raw"
OUT = ROOT / "knowledge" / "chunks.jsonl"

# source slug -> raw file(s) it was extracted from, for the existence check.
# "dataset_readme" sources come from dataset/README.md itself.
SOURCE_FILES = {
    "bank_fraud_policy_v1.0": [README],
    "dataset_readme": [README],
    "fincen_sar_narrative_guidance": [RAW / "sar_guidance_narrative.pdf", RAW / "sarnarrcompletguidfinal_112003.pdf"],
    "fincen_account_takeover_advisory": [RAW / "fincen_account_takeover_advisory.html"],
    "ffiec_bsaaml_manual_sar": [RAW / "ffiec_sar.html"],
    "ffiec_bsaaml_manual_redflags": [RAW / "ffiec_redflags.html"],
    "fincen_identity_related_sar_2021": [RAW / "FTA_Identity_Final508.pdf"],
    "fatf_cyber_enabled_fraud_2023": [RAW / "fatf_cyber_fraud.pdf"],
}

CHUNKS = []


def add(id_, source, section, title, text):
    CHUNKS.append({"id": id_, "source": source, "section": section, "title": title, "text": " ".join(text.split())})


# ---------------------------------------------------------------------------
# POLICY (bank_fraud_policy_v1.0) -- verbatim text from dataset/README.md
# ---------------------------------------------------------------------------

add("POLICY-S0-SCORE", "bank_fraud_policy_v1.0", "§0 What the agent starts with",
    "What the agent starts with: the risk score", '''
Every transaction carries a risk_score between 0 and 1 from the bank's detection model.
The model is useful and imperfect: many high scores are legitimate, and some fraud scores
low. A score is a reason to look, never a verdict. The only confirmed outcomes are in the
closed cases. As the README glossary puts it: Risk score -- a number from 0 to 1 the bank's
model attached to every transaction. High means "look at this." It is often wrong in both
directions. Never treat it as the answer.
''')

add("POLICY-S1-ACTIONS", "bank_fraud_policy_v1.0", "§1 Actions",
    "Actions the agent may recommend", '''
The Fraud Policy defines a fixed set of action identifiers the agent must use exactly as
named. ALLOW_TRANSACTION lets the flagged transaction stand (no customer impact).
DECLINE_TRANSACTION declines the flagged authorization only; the card stays active (low
impact). MONITOR_CARD keeps the card active and raises monitoring sensitivity for 72 hours
(no impact). MONITOR_CONNECTED_CARDS puts other cards linked to the same device profile,
region cluster, or ring under monitoring (no impact). WARN_CUSTOMER sends an informational
message, such as a recurring-charge reminder or a security tip (no impact).
VERIFY_WITH_CUSTOMER asks the cardholder whether they made the transaction; the card stays
active pending reply (low impact). STEP_UP_AUTH requires a one-time passcode or app
confirmation before further activity (low impact). BLOCK_CARD blocks this card and reissues
it (high impact). BLOCK_ALL_CARDS blocks every card the customer holds (very high impact).
GENERATE_REPORT writes up the investigation for the internal record without opening a case.
CREATE_CASE opens an internal fraud case with the evidence attached and writes it to the
graph. FILE_REPORT files a suspicious activity report with the regulator. ESCALATE_TO_ANALYST
hands the case to a human analyst with the evidence. CLOSE_NO_FRAUD closes the alert as
legitimate. An agent may recommend several actions for one case, ordered by what happens
first.
''')

add("POLICY-S2-ROUTING", "bank_fraud_policy_v1.0", "§2 Approval routing",
    "Approval routing: auto, L1, L2", '''
auto applies to ALLOW_TRANSACTION, MONITOR_CARD, MONITOR_CONNECTED_CARDS, WARN_CUSTOMER,
VERIFY_WITH_CUSTOMER, STEP_UP_AUTH, GENERATE_REPORT, CREATE_CASE, ESCALATE_TO_ANALYST, and
CLOSE_NO_FRAUD. L1 (team lead) applies to DECLINE_TRANSACTION, and to BLOCK_CARD when exposure
is $2,500 or less. L2 (fraud manager) applies to BLOCK_CARD when exposure exceeds $2,500, to
BLOCK_ALL_CARDS always, and to FILE_REPORT always. The agent recommends; only auto actions may
be executed by the agent. L1 and L2 actions are recommended with the route stated and wait for
a human. As the glossary states: Approval route -- auto the agent may act alone; L1 a team
lead must approve; L2 a fraud manager must approve.
''')

add("POLICY-R1", "bank_fraud_policy_v1.0", "§3 Rules — R1",
    "R1. Verify before you block on a weak signal", '''
R1. Verify before you block on a weak signal. If the case rests on a single signal (including
a risk score alone) and your assessed fraud probability is below 0.70, recommend
VERIFY_WITH_CUSTOMER or STEP_UP_AUTH before any block. Blocking a legitimate customer on one
signal is a policy breach. Related actions (§1): VERIFY_WITH_CUSTOMER -- ask the cardholder
whether they made the transaction; the card stays active pending reply (low customer impact,
route auto). STEP_UP_AUTH -- require a one-time passcode or app confirmation before further
activity (low customer impact, route auto).
''')

add("POLICY-R2", "bank_fraud_policy_v1.0", "§3 Rules — R2",
    "R2. Customer denies the transaction", '''
R2. Customer denies the transaction. Recommend BLOCK_CARD and CREATE_CASE. Add FILE_REPORT if
exposure exceeds $1,000 or the case connects to a shared device profile or another card's
fraud. Related actions (§1): BLOCK_CARD -- block this card and reissue (high customer impact;
route L1 if exposure is $2,500 or less, otherwise L2). CREATE_CASE -- open an internal fraud
case with the evidence attached and write it to the graph (route auto). FILE_REPORT -- file a
suspicious activity report with the regulator (route L2, always).
''')

add("POLICY-R3", "bank_fraud_policy_v1.0", "§3 Rules — R3",
    "R3. Customer confirms the transaction", '''
R3. Customer confirms the transaction. Recommend CLOSE_NO_FRAUD. Note the confirmation in the
case file. Compare R2, where the customer instead denies the transaction and the agent
recommends BLOCK_CARD and CREATE_CASE. Related action (§1): CLOSE_NO_FRAUD -- close the alert
as legitimate (no customer impact, route auto). Per the Answer Format notes, for a legitimate
verdict affected_txn_ids is empty, exposure_usd is 0, and sar.file is false.
''')

add("POLICY-R4", "bank_fraud_policy_v1.0", "§3 Rules — R4",
    "R4. No reply within 24 hours", '''
R4. No reply within 24 hours. Recommend MONITOR_CARD and DECLINE_TRANSACTION for pending
authorizations. Escalate if exposure exceeds $500. Related actions (§1): MONITOR_CARD -- card
stays active, monitoring sensitivity raised for 72 hours (route auto). DECLINE_TRANSACTION --
decline the flagged authorization only, card stays active (low customer impact, route L1).
ESCALATE_TO_ANALYST -- hand the case to a human analyst with the evidence (route auto), used
here once exposure passes the $500 threshold.
''')

add("POLICY-R5", "bank_fraud_policy_v1.0", "§3 Rules — R5",
    "R5. Card testing", '''
R5. Card testing. Three or more small online authorizations on one card within an hour,
followed by a larger purchase: recommend DECLINE_TRANSACTION and STEP_UP_AUTH. If a purchase
over $100 has already cleared, recommend BLOCK_CARD. Related actions (§1): DECLINE_TRANSACTION
-- decline the flagged authorization only, card stays active (route L1). STEP_UP_AUTH --
require a one-time passcode or app confirmation before further activity (route auto).
BLOCK_CARD -- block this card and reissue (route L1 or L2 depending on exposure). This
corresponds to the known fraud pattern card_testing.
''')

add("POLICY-R6", "bank_fraud_policy_v1.0", "§3 Rules — R6",
    "R6. Shared origin", '''
R6. Shared origin. When several cards show fraud from the same device profile, the same
billing region, or the same recipient email in one window, name the shared element, recommend
CREATE_CASE and FILE_REPORT, and MONITOR_CONNECTED_CARDS for every card that shares it. Related
action (§1): MONITOR_CONNECTED_CARDS -- put other cards linked to the same device profile,
region cluster, or ring under monitoring (no customer impact, route auto). CREATE_CASE is
auto; FILE_REPORT always routes to L2 (fraud manager).
''')

add("POLICY-R7", "bank_fraud_policy_v1.0", "§3 Rules — R7",
    "R7. Disputed but legitimate", '''
R7. Disputed but legitimate. When the customer disputes a charge that matches their own
recurring pattern (same merchant, same amount, monthly), recommend CREATE_CASE,
VERIFY_WITH_CUSTOMER, and WARN_CUSTOMER. Do not block. Related actions (§1): WARN_CUSTOMER --
send an informational message, such as a recurring-charge reminder (no customer impact, route
auto). VERIFY_WITH_CUSTOMER -- ask the cardholder whether they made the transaction; card stays
active pending reply (low impact, route auto). CREATE_CASE -- open an internal case and write
it to the graph (route auto).
''')

add("POLICY-R8", "bank_fraud_policy_v1.0", "§3 Rules — R8",
    "R8. Escalate when uncertain and exposed", '''
R8. Escalate when uncertain and exposed. If the verdict is uncertain and exposure exceeds
$500, or the evidence conflicts, recommend ESCALATE_TO_ANALYST. Related action (§1):
ESCALATE_TO_ANALYST -- hand the case to a human analyst with the evidence (no customer impact,
route auto). Per the Answer Format notes, uncertain is a valid verdict and earns full credit on
cases designed to be ambiguous, provided the actions follow policy R1 and R8.
''')

add("POLICY-R9", "bank_fraud_policy_v1.0", "§3 Rules — R9",
    "R9. Undocumented patterns", '''
R9. Undocumented patterns. When activity fits none of the known patterns but the evidence
shows coordinated or repeated abuse across customers, recommend CREATE_CASE, FILE_REPORT, and
ESCALATE_TO_ANALYST, and describe the pattern in your own words. Do not force it into a known
category. Per the Answer Format, pattern_description is required when pattern is undocumented:
two or three sentences on what the pattern is, who it affects, and how you found it; otherwise
it is an empty string.
''')

add("POLICY-R10", "bank_fraud_policy_v1.0", "§3 Rules — R10",
    "R10. Never BLOCK_ALL_CARDS without strong cause", '''
R10. Never BLOCK_ALL_CARDS unless at least two of the customer's cards show confirmed fraud or
the customer's credentials are confirmed compromised. Related action (§1): BLOCK_ALL_CARDS --
blocks every card the customer holds (very high customer impact). Per §2 Approval routing,
BLOCK_ALL_CARDS always routes to L2, the fraud manager, and per the glossary an L2 action is
one only a fraud manager may approve; the agent may recommend it but never execute it itself.
''')

add("POLICY-S3A-CASE", "bank_fraud_policy_v1.0", "§3a A case is not a report — the case",
    "A case is not a report: the case", '''
Two different things, and the agent produces both. A case (CREATE_CASE) is the bank's internal
record of an investigation. Open one whenever fraud probability reaches 0.30, whenever you
request evidence, or whenever a customer disputes a charge. A case can be closed as fraud or as
legitimate. It can be updated when new evidence arrives. It should be written into the graph so
later investigations can find it: a case that names a merchant or a device becomes evidence for
the next analyst.
''')

add("POLICY-S3A-SAR", "bank_fraud_policy_v1.0", "§3a A case is not a report — the report",
    "A case is not a report: the SAR", '''
A suspicious activity report (FILE_REPORT) is a regulatory filing sent outside the bank. File
one when fraud is confirmed or strongly suspected and at least one of these holds: exposure
exceeds $1,000; the activity connects to a shared device profile, a shared region cluster, or
another customer's fraud; the pattern is coordinated or undocumented (rule R9). A report always
has a case behind it. Most cases never need a report. The report narrative must stand on its
own: who, what, when, where, how, and why it is suspicious. Deciding correctly between "case
only" and "case plus report" is part of the next-best-action score.
''')

add("POLICY-S3B", "bank_fraud_policy_v1.0", "§3b The next best action can change",
    "The next best action can change", '''
Recommend what the evidence supports now, then request more evidence if the policy calls for
it, then recommend again. Example: probability 0.45 on a single signal, so the initial action
is VERIFY_WITH_CUSTOMER under R1. The customer denies the transaction. Probability rises, and
the final actions become BLOCK_CARD, CREATE_CASE, and possibly FILE_REPORT under R2, with
connected cards placed under monitoring. Record both the initial and the final recommendation
and what changed between them.
''')

add("POLICY-S4-EXPOSURE", "bank_fraud_policy_v1.0", "§4 Exposure", "Exposure", '''
Exposure is the sum of the absolute amounts of every transaction the agent has identified as
part of the fraud episode, including the flagged one. Report it in USD. As the glossary states,
exposure is the total dollars in the fraud episode identified. Per the Answer Format,
exposure_usd is the sum of absolute amounts of affected_txn_ids, and for a legitimate verdict
affected_txn_ids is empty and exposure_usd is 0. Exposure also determines approval routing:
BLOCK_CARD routes to L1 when exposure is $2,500 or less, and to L2 when it exceeds $2,500 (§2).
''')

add("POLICY-S5-EVIDENCE", "bank_fraud_policy_v1.0", "§5 Gathering more evidence",
    "Gathering more evidence", '''
The agent may, without approval, ask the customer to validate a transaction, request step-up
authentication, or request information from an analyst. In this round those responses are not
provided; simulate them in your own system and state the assumption you made in the case
file's evidence_requests. Per the README's "Things to know": customer and analyst replies are
not provided, so if the agent asks the customer or requests step-up authentication, it must
simulate the response in its own system and record what it assumed.
''')

add("POLICY-S6-STOP", "bank_fraud_policy_v1.0", "§6 Stopping", "Stopping", '''
Stop investigating when one of these holds: fraud probability is at or above 0.85, or at or
below 0.15, supported by at least two independent pieces of evidence; a verification response
settles the question; or further steps are unlikely to change the decision -- say so in
stop_reason. Investigations that continue past a defensible decision waste time. Investigations
that stop before one create risk. Both are marked down.
''')

add("POLICY-S7-EXPLAIN", "bank_fraud_policy_v1.0", "§7 Explaining", "Explaining", '''
Every recommendation must state what evidence was used, why more evidence was requested if it
was, and why the chosen actions follow from this policy. Cite the rule number. This maps to the
Answer Format's evidence field: each evidence item is a claim (string), a source (graph,
document, customer, or external), a ref (query name, document section, or request id), and
entity_ids (the list of IDs the claim rests on) -- the citation mechanism this policy requires.
''')

# ---------------------------------------------------------------------------
# PATTERN and README-THINGS-TO-KNOW (dataset_readme) -- verbatim from README
# ---------------------------------------------------------------------------

_PATTERN_LEAD = '''
These are the patterns the bank's analysts recognize. They are not the only patterns in the
data. Noticing activity that fits none of them, describing it in your own words, and
recommending a defensible action is scored.
'''

add("PATTERN-card_testing", "dataset_readme", "The five known fraud patterns",
    "Card testing", _PATTERN_LEAD + '''
1. Card testing. A stolen card number is checked before use: three or more tiny online
authorizations, often under $5, then a larger purchase. Confirmed by the sequence itself.
Policy R5.
''')

add("PATTERN-card_not_present_fraud", "dataset_readme", "The five known fraud patterns",
    "Card-not-present fraud", _PATTERN_LEAD + '''
2. Card-not-present fraud. The number is used online without the card. Amounts and products
that don't fit the cardholder's history, often in a burst of two to four within 48 hours. On
its own, one unusual online purchase is ambiguous: verify. Policy R1 to R4.
''')

add("PATTERN-card_not_present_new_device", "dataset_readme", "The five known fraud patterns",
    "Card-not-present fraud from a new device", _PATTERN_LEAD + '''
3. Card-not-present fraud from a new device. Same as above, with the identity record marking
the device as New for this account, sometimes behind a proxy. Stronger than pattern 2, still
not proof: people buy new phones.
''')

add("PATTERN-out_of_region_use", "dataset_readme", "The five known fraud patterns",
    "Out-of-region use", _PATTERN_LEAD + '''
4. Out-of-region use. Card-present purchases in a billing region the cardholder has no history
in, while their normal activity continues at home. Several days of purchases in one new region
is a trip, not a clone. Policy R2, R3.
''')

add("PATTERN-account_takeover", "dataset_readme", "The five known fraud patterns",
    "Account takeover", _PATTERN_LEAD + '''
5. Account takeover. Mixed-channel activity inconsistent with the cardholder, often with
device and match-flag anomalies, pointing to stolen credentials rather than a stolen number.
The README glossary defines an identity record as the device and connection details Vesta
captured for online transactions: device type and model, OS, browser, screen, proxy flag, and
encoded ratings.
''')

add("README-THINGS-TO-KNOW-01", "dataset_readme", "Things to know",
    "Risk scores, legitimate cases, and undocumented patterns", '''
From the README's "Things to know" section: a risk score is a reason to look -- never a
verdict. Half the cases in the case pack are legitimate; many look suspicious, but an agent
that blocks everything scores badly. The known patterns are not the only ones: some activity in
this data fits none of the five, and noticing it, describing it in your own words, and
recommending a defensible action is scored.
''')

add("README-THINGS-TO-KNOW-02", "dataset_readme", "Things to know",
    "Shared devices and regions, and unnamed model features", '''
From the README's "Things to know" section: devices and regions connect people. A device
profile or a billing region shared across many cards in a short window is worth a look, and
some cases can only be solved by asking what happened on other cards. The V, C, D, M, and
numeric id columns (V1-V339, C1-C14, D1-D15, M1-M9, id_01-id_11) are real model features from
the Vesta dataset with no public names; you may use them as signals, but say so explicitly in
your evidence rather than pretending to know what a specific column like V127 means.
''')

add("README-THINGS-TO-KNOW-03", "dataset_readme", "Things to know",
    "Customer and analyst replies are simulated", '''
From the README's "Things to know" section: customer and analyst replies are not provided in
this exercise. If the agent asks the customer to validate a transaction or requests step-up
authentication, it must simulate the response in its own system and record what it assumed in
evidence_requests. This mirrors Fraud Policy §5 (Gathering more evidence): the agent may,
without approval, ask the customer to validate a transaction, request step-up authentication,
or request information from an analyst, and must state the assumption made.
''')

# ---------------------------------------------------------------------------
# FinCEN: SAR Narrative Guidance (sar_guidance_narrative.pdf, Nov 2003).
# Note: sarnarrcompletguidfinal_112003.pdf is the identical document under a
# second URL -- see knowledge/SOURCES.md.
# ---------------------------------------------------------------------------

add("FINCEN-SAR-NARRATIVE-01", "fincen_sar_narrative_guidance", "Introduction",
    "Purpose of the SAR narrative", '''
FinCEN's Guidance on Preparing a Complete and Sufficient Suspicious Activity Report Narrative
(November 2003) explains that the SAR narrative is the only free-text area for summarizing
suspicious activity, so financial institution staff must write narratives that are clear,
concise, and thorough. Some institutions file SARs with incomplete, incorrect, or disorganized
narratives, or even blank narratives; the failure to adequately describe the factors making a
transaction or activity suspicious undermines the purpose of the SAR and lessens its usefulness
to law enforcement. Late filings, missing supplementary SARs, and inaccuracies also impair law
enforcement's ability to determine whether a crime occurred and its extent. Although different
financial industries use different SAR forms, the basic structure of a SAR narrative is the
same across all of them, which is why this guidance applies broadly.
''')

add("FINCEN-SAR-NARRATIVE-02", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative", "The five W's and How of a SAR narrative", '''
FinCEN's SAR narrative guidance states that a SAR narrative should identify the five essential
elements of information -- who, what, when, where, and why -- of the suspicious activity being
reported. The method of operation, or how, is also important and should be included in the
narrative. The SAR form should include any information readily available to the filing
institution obtained through the account opening process and during due diligence. In the
GraphRAG fraud-investigation context, this is the required skeleton of a sar.narrative: identify
the subjects (who), the transactions and instruments involved (what), the dates (when), the
channel and locations (where), the mechanism (how), and the reasoning for suspicion (why).
''')

add("FINCEN-SAR-NARRATIVE-03", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — Who", "Who is conducting the suspicious activity", '''
Per FinCEN's SAR narrative guidance, while one section of the SAR form calls for specific
suspect information, the narrative should further describe the suspect or suspects, including
occupation, position or title, and the nature of the suspect's business. If more than one
individual or business is involved, identify all suspects and any known relationships among
them in the narrative section. Detailed suspect information may not always be available, such
as when the subject is not an account holder, but it should be included to the maximum extent
possible. Addresses for suspects are important: note primary street addresses as well as other
known addresses, including post office boxes and apartment numbers, and any identification
numbers such as passport, alien registration, or driver's license numbers.
''')

add("FINCEN-SAR-NARRATIVE-04", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — What", "What instruments or mechanisms facilitated the activity", '''
FinCEN's SAR narrative guidance lists an illustrative set of instruments or mechanisms that may
be used in suspicious activity, including wire transfers, letters of credit and other trade
instruments, correspondent accounts, casinos, structuring, shell companies, bonds and notes,
stocks, mutual funds, insurance policies, travelers checks, bank drafts, money orders, credit
and debit cards, stored value cards, and digital currency business services. A number of
methods may also be used to initiate the movement of funds, such as the Internet, phone access,
mail, night deposit box, remote dial-up, or couriers. The narrative should always include the
source of the funds (origination) and the recipient (beneficiary), and identify all account
numbers at the filing institution affected by the activity, plus, where possible, account
numbers at other institutions.
''')

add("FINCEN-SAR-NARRATIVE-05", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — When and Where", "When and where the suspicious activity took place", '''
FinCEN's SAR narrative guidance directs filers to indicate the date the suspicious activity was
first noticed and describe its duration if it took place over time. Individual dates and
amounts of transactions should be included in the narrative rather than just an aggregated
total, since tables or spreadsheets pasted into the narrative may not convert properly when the
SAR is processed. For where, the narrative should indicate whether multiple offices of a single
institution were involved and give their addresses, and should specify whether the activity
involves a foreign jurisdiction -- naming the jurisdiction, the foreign financial institution,
its address, and any account numbers affiliated with the activity.
''')

add("FINCEN-SAR-NARRATIVE-06", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — Why", "Why the filer thinks the activity is suspicious", '''
FinCEN's SAR narrative guidance suggests that the filer first briefly describe its own industry
or business type -- depository institution, casino, mortgage broker, securities broker,
insurance, real estate, investment services, money remitter, or check casher -- and then
describe as fully as possible why the activity or transaction is unusual for the customer,
considering the types of products and services the industry offers and the nature and normally
expected activity of similar customers. This comparison to a baseline of normal, expected
behavior for that customer and that type of business is the core of the "why" element and is
what turns a bare list of transactions into a suspicious activity narrative.
''')

add("FINCEN-SAR-NARRATIVE-07", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — How", "How the suspicious activity occurred", '''
FinCEN's SAR narrative guidance instructs filers to use the narrative section to describe the
"modus operandi," or method of operation, of the subject conducting the suspicious activity, in
a concise, accurate, and logical manner, providing as complete a picture of the activity as
possible. For example, if the activity appears to be structuring of currency deposits matched
with outgoing wire transfers, the narrative should describe both the structuring and the
outbound transfers, including dates, destinations, amounts, accounts, frequency, and
beneficiaries. The same principle applies to a fraud narrative: describe the sequence of events
end to end -- how the fraud started, how it progressed, and how it was carried out -- not just
that it happened.
''')

add("FINCEN-SAR-NARRATIVE-08", "fincen_sar_narrative_guidance",
    "Organizing Information in the SAR Narrative — Introduction", "Organizing the narrative: introduction", '''
FinCEN's SAR narrative guidance recommends dividing the narrative into three parts: an
introduction, a body, and a conclusion, and including all elements of the five W's throughout.
The introductory paragraph can state the purpose of the SAR and a general description of the
known or alleged violation, including naming the type of suspicious activity being observed;
the date and reason for any previously filed SARs on the suspect or related suspects; whether
the SAR is associated with OFAC-sanctioned countries, Specially Designated Nationals, or other
government lists; any internal investigative reference number the institution uses; and a
summary of the red flags and suspicious patterns that initiated the SAR.
''')

add("FINCEN-SAR-NARRATIVE-09", "fincen_sar_narrative_guidance",
    "Organizing Information in the SAR Narrative — Body", "Organizing the narrative: body", '''
Per FinCEN's SAR narrative guidance, the body of the narrative should provide all pertinent
facts supporting why the SAR was filed: relevant facts about the parties who facilitated the
suspicious activity, including unusual observations; a specific description of the involved
accounts and transactions, identifying the origination and application of funds, usually in
chronological order by date and amount; transactor and beneficiary information, including
names, addresses, account numbers, and other identifiers; an explanation of any observed
relationships among the transactors, such as shared accounts, addresses, or employment; specific
details on how each transaction occurred; and any factual observations or incriminating
statements made by the suspect.
''')

add("FINCEN-SAR-NARRATIVE-10", "fincen_sar_narrative_guidance",
    "Organizing Information in the SAR Narrative — Conclusion and reminder",
    "Organizing the narrative: conclusion, and the no-attachments reminder", '''
FinCEN's SAR narrative guidance says the final paragraph can summarize the report and include
any follow-up actions taken by the institution, such as intent to close or actually closing
accounts, or ongoing monitoring; names and phone numbers of additional institution contacts;
and a description of any further information that could be made available to law enforcement.
An important reminder follows: do not include supporting documentation with the filed report
and do not use the phrase "see attached" in the narrative section, because only explicit
narrative text is captured into the SAR system -- tables, spreadsheets, and attachments are
not. Supporting documentation must instead be retained in the institution's own records for
five years.
''')

add("FINCEN-SAR-NARRATIVE-11", "fincen_sar_narrative_guidance",
    "Collecting Information for the SAR Narrative — Common patterns", "Examples of common suspicious activity patterns", '''
FinCEN's SAR narrative guidance lists examples of common patterns of suspicious activity that
filers should watch for, including: a lack of evidence of legitimate business activity by
parties to the transaction; unusual financial relationships between mismatched business types;
transactions not commensurate with the stated business type or unusual compared to similar
businesses in the same locale; unusually large volumes or repetitive patterns of wire transfers;
complex series of transactions indicative of layering across multiple accounts, banks, and
jurisdictions; suspected shell entities; and transactions conducted in bursts of activity within
a short period of time, especially in previously dormant accounts -- a pattern with a direct
card-fraud analogue in sudden bursts of activity on an otherwise quiet card.
''')

# ---------------------------------------------------------------------------
# FinCEN Advisory FIN-2011-A016: Account Takeover Activity
# ---------------------------------------------------------------------------

add("FINCEN-ATO-ADVISORY-01", "fincen_account_takeover_advisory",
    "Identifying Account Takeover Activity", "Identifying account takeover activity", '''
FinCEN Advisory FIN-2011-A016 (Account Takeover Activity, December 19, 2011) explains that
cybercriminals increasingly use sophisticated methods to obtain access to accounts, including
malware, SQL injection attacks, spyware, Trojans, and worms, aiming to exploit a customer's
account or gain seemingly legitimate access to another customer's account. Through ongoing
monitoring, financial institutions may identify inconsistencies with a customer's normal
account activity indicating illicit intrusion, such as unusual ATM activity, clustered ACH
transactions in different geographic areas, sudden wire transfers, or changes to customer and
account profiles. Account takeover differs from other computer intrusion because the customer,
not the institution, is the primary target, and the ultimate goal is to remove, steal, procure,
or otherwise affect the funds of that targeted customer.
''')

add("FINCEN-ATO-ADVISORY-02", "fincen_account_takeover_advisory",
    "Suspicious Activity Reporting", "Filing a SAR for account takeover", '''
FinCEN Advisory FIN-2011-A016 directs that when completing a SAR for suspected account takeover
activity, financial institutions should use the term "account takeover fraud" in the narrative
section and provide a detailed description of the activity. If the takeover involved computer
intrusion, check the "computer intrusion" box and also check "other" noting "account takeover
fraud." If it involved other channels, such as telephone banking or social engineering, check
"other" and note "account takeover fraud" with a short description. If it involved a wire
transfer, also check "wire transfer fraud"; if an ACH transfer, note "account takeover fraud -
ACH." Because takeovers often involve unauthorized access to PINs, account numbers, and other
identifying information, institutions may also need to check "identity theft."
''')

# ---------------------------------------------------------------------------
# FFIEC BSA/AML Manual: Suspicious Activity Reporting
# ---------------------------------------------------------------------------

add("FFIEC-SAR-01", "ffiec_bsaaml_manual_sar",
    "Assessing Compliance with BSA Regulatory Requirements — Suspicious Activity Reporting, Overview",
    "SAR filing objective and dollar thresholds", '''
The FFIEC BSA/AML manual states that suspicious activity reporting is the cornerstone of the
BSA reporting system, and the quality of SAR content is critical to its effectiveness. Banks
are required by federal regulation to file a SAR for: criminal violations involving insider
abuse in any amount; criminal violations aggregating $5,000 or more when a suspect can be
identified; criminal violations aggregating $25,000 or more regardless of whether a suspect is
identified; and transactions aggregating $5,000 or more that the bank knows, suspects, or has
reason to suspect involve potential money laundering or other illegal activity, are designed to
evade BSA requirements, or have no business or apparent lawful purpose given the customer's
known background.
''')

add("FFIEC-SAR-02", "ffiec_bsaaml_manual_sar",
    "Safe Harbor for Banks From Civil Liability for Suspicious Activity Reporting", "Safe harbor for filing a SAR", '''
Per the FFIEC BSA/AML manual, federal law (31 USC 5318(g)(3)) protects banks and their
directors, officers, employees, and agents from civil liability for reports of suspicious
transactions made to appropriate authorities, including supporting documentation, regardless of
whether the report was required by the SAR instructions. A bank that discloses a possible
violation of law or regulation, including in connection with preparing a SAR, is not liable
under any federal, state, or local law or regulation, or under any contract, for that
disclosure or for failing to notify the person who is the subject of the disclosure. The safe
harbor covers SARs filed within required reporting thresholds as well as those filed voluntarily
on activity below the threshold.
''')

add("FFIEC-SAR-03", "ffiec_bsaaml_manual_sar",
    "Systems to Identify, Research, and Report Suspicious Activity",
    "Five components of an effective SAR monitoring and reporting system", '''
The FFIEC BSA/AML manual describes five interdependent components of an effective suspicious
activity monitoring and reporting system: identification or alert of unusual activity, which
may come from employee identification, law enforcement inquiries, other referrals, or
transaction and surveillance monitoring output; managing alerts; SAR decision making; SAR
completion and filing; and monitoring and SAR filing on continuing activity. Breakdowns in any
one of these components may adversely affect SAR reporting and overall BSA compliance. Larger
banks typically separate these functions into distinct departments, while smaller banks may
have one or a few employees handling several of them; policies should describe the steps taken
for each component and who is responsible.
''')

add("FFIEC-SAR-04", "ffiec_bsaaml_manual_sar", "SAR Decision Making", "SAR decision making and documentation", '''
The FFIEC BSA/AML manual states that after research and analysis, findings are forwarded to a
final decision maker, whether an individual or a committee, who has the authority to make the
final SAR filing decision; when a committee is used, there should be a clear process to resolve
differences of opinion. Banks should document SAR decisions, including the specific reason for
filing or not filing, since the decision to file a SAR is an inherently subjective judgment.
Examiners focus on whether the bank has an effective SAR decision-making process, not on
second-guessing individual decisions, and should not criticize a bank for declining to file
unless the failure is significant or shows bad faith.
''')

add("FFIEC-SAR-05", "ffiec_bsaaml_manual_sar", "SAR Quality", "SAR quality and the narrative", '''
The FFIEC BSA/AML manual states that banks are required to file SARs that are complete,
thorough, and timely, including all known subject information; inaccurate information or an
incomplete or disorganized narrative may make further analysis difficult or impossible. Because
the SAR narrative section is the only area summarizing suspicious activity, it is described in
the SAR form itself as "critical," and a failure to adequately describe the factors making a
transaction or activity suspicious undermines the purpose of the SAR. A single comma-separated-
value attachment up to one megabyte may accompany a BSAR filing to carry transactional data, but
it is considered part of, not a substitute for, the narrative -- the narrative should never
simply say "see attachment."
''')

add("FFIEC-SAR-06", "ffiec_bsaaml_manual_sar", "Timing of a SAR Filing", "SAR filing deadline: 30 or 60 days", '''
Per the FFIEC BSA/AML manual, SAR rules require a SAR be electronically filed no later than 30
calendar days from the date of initial detection of facts that may constitute a basis for
filing; if no suspect can be identified, the period extends to 60 days. "Initial detection" is
not the moment a transaction is flagged for review -- many legitimate transactions raise a red
flag simply because they are inconsistent with an accountholder's normal activity. The 30- or
60-day clock starts only once an appropriate review determines the activity is actually
"suspicious" within the meaning of the SAR regulation, and that review should be completed
within a reasonable period of time given the bank's documented procedures.
''')

add("FFIEC-SAR-07", "ffiec_bsaaml_manual_sar", "SAR Filing on Continuing Activity", "Filing SARs on continuing activity", '''
The FFIEC BSA/AML manual explains that when suspicious activity continues over time, banks
should report it to law enforcement by filing a report at least every 90 calendar days;
subsequent guidance permits filing for continuing activity after a 90-day review with a filing
deadline of 120 calendar days after the previously related SAR. Banks may file earlier than the
120-day deadline if they believe the activity warrants earlier review. This practice notifies
law enforcement of the continuing nature of the activity in aggregate and reminds the bank to
keep evaluating whether other actions, such as terminating the customer relationship, may be
appropriate.
''')

add("FFIEC-SAR-08", "ffiec_bsaaml_manual_sar", "Prohibition of SAR Disclosure", "SAR confidentiality", '''
The FFIEC BSA/AML manual states that no bank, and no director, officer, employee, or agent of a
bank that reports a suspicious transaction, may notify any person involved in the transaction
that it has been reported. A SAR, and any information that would reveal its existence, is
confidential except as necessary to fulfill BSA obligations; the existence or non-existence of a
SAR must be kept confidential along with its contents to the extent they would reveal it. A bank
may reveal the existence of a SAR to fulfill BSA-consistent responsibilities, provided no person
involved in the suspicious transaction is notified, and underlying facts and documents may be
shared with another institution to prepare a joint SAR or within limits authorized by statute.
''')

# ---------------------------------------------------------------------------
# FFIEC BSA/AML Manual, Appendix F: Money Laundering and Terrorist Financing
# Red Flags -- only the parts with general or card/identity-fraud relevance.
# ---------------------------------------------------------------------------

add("FFIEC-REDFLAGS-01", "ffiec_bsaaml_manual_redflags",
    "Appendix F — Money Laundering and Terrorist Financing Red Flags, Introduction",
    "What a red flag is, and what it isn't", '''
The FFIEC BSA/AML manual's Appendix F lists examples of potentially suspicious activities, or
"red flags," for money laundering and terrorist financing, drawn from FinCEN advisories, to
help banks and examiners recognize possible schemes. The manual is explicit that these lists
are not all-inclusive, and that management's primary focus should be on reporting suspicious
activities rather than on determining whether the transactions are in fact linked to money
laundering, terrorist financing, or a particular crime. A red flag, when encountered, may
warrant additional scrutiny, but its mere presence is not by itself evidence of criminal
activity; closer scrutiny should determine whether the activity is suspicious or has a
reasonable business or legal purpose.
''')

add("FFIEC-REDFLAGS-02", "ffiec_bsaaml_manual_redflags",
    "Appendix F — Customers Who Provide Insufficient or Suspicious Information",
    "Red flags: insufficient or suspicious customer information", '''
Under FFIEC Appendix F, red flags in this category include a customer using unusual or
suspicious identification documents that cannot be readily verified; a customer whose
background differs from what would be expected given their business activities; a customer
making frequent or large transactions with no record of past or present employment; a
customer's home or business telephone being disconnected; and a business reluctant, when
opening a new account, to provide complete information about the nature and purpose of its
business, its anticipated account activity, prior banking relationships, or its officers,
directors, and location. A trust, shell company, or private investment company reluctant to
name its controlling parties and beneficial owners is also listed as a red flag.
''')

add("FFIEC-REDFLAGS-03", "ffiec_bsaaml_manual_redflags",
    "Appendix F — Other Unusual or Suspicious Customer Activity", "Red flags: activity inconsistent with the customer", '''
Under FFIEC Appendix F's "Other Unusual or Suspicious Customer Activity" list, relevant red
flags include a customer establishing multiple accounts in various corporate or individual
names that lack sufficient business purpose, or that appear to be an effort to hide beneficial
ownership; a customer conducting large deposits and withdrawals during a short period after
opening an account and then closing it or letting it go dormant, or conversely a dormant account
suddenly experiencing large activity; and a customer making high-value transactions not
commensurate with their known income. The manual frames the underlying test the same way
FinCEN's SAR narrative guidance does: whether the activity or transaction is unusual for that
particular customer given the products, services, and expected behavior of similar customers.
''')

# ---------------------------------------------------------------------------
# FinCEN: Identity-Related Suspicious Activity, 2021 Threats and Trends
# ---------------------------------------------------------------------------

add("FINCEN-IDENTITY-01", "fincen_identity_related_sar_2021", "Executive Summary",
    "Scale of identity-related suspicious activity", '''
FinCEN's Identity-Related Suspicious Activity: 2021 Threats and Trends reports that during
2021, approximately 1.6 million BSA reports -- 42% of about 3.8 million total filings,
equivalent to $212 billion in suspicious activity -- related to identity. FinCEN found that
attackers exploit three identity processes: validation, verification, and authentication,
through three corresponding exploitations: impersonation (evading validation), circumvention
(exploiting weak or insufficient verification), and compromise (using stolen credentials to
defeat authentication). Sixty-nine percent of identity-related BSA reports (about 1.7 million
filings) involved attackers impersonating others to defraud victims; 18% (about 446,000
filings) described attackers using compromised credentials for unauthorized account access; and
13% (about 323,000 filings) described attackers exploiting insufficient verification.
''')

add("FINCEN-IDENTITY-02", "fincen_identity_related_sar_2021", "Identity Processes in Financial Institutions",
    "Validation, verification, and authentication", '''
FinCEN's 2021 identity-related suspicious activity report defines the three identity process
steps, drawn from NIST's Digital Identity Guidelines. Validation is when a customer presents
identity attributes and supporting evidence, such as a passport or driver's license, and the
institution determines whether the identity exists, is unique, and is authentic by comparing it
against authoritative sources. Verification confirms that the previously validated identity
evidence belongs to the customer, for example by matching the customer's appearance to a photo
ID, using humans, biometrics like facial recognition, or automated tools. Authentication
assesses whether the customer is who they claim to be based on possession and control of valid
authenticators -- something they have, something they know, or something they are -- and is
stronger with multiple factors.
''')

add("FINCEN-IDENTITY-03", "fincen_identity_related_sar_2021", "Appendix 1: Assessed Typology Results — Account Takeover",
    "Account takeover: definition and financial impact", '''
FinCEN's 2021 identity-related suspicious activity report defines account takeover as the
deliberate compromise of a victim's account to remove, steal, procure, or otherwise affect the
victim's funds, and classifies it under the "compromise" exploitation of the authentication
step. In 2021, about 80,000 BSA reports described account takeover, totaling $9 billion in
suspicious activity. More broadly, compromise-based exploitations (which include account
takeover, business email compromise, and abuse of access) were disproportionately costly: they
accounted for only 18% of identity-related BSA reports but 32% of the total suspicious activity
dollar amount, meaning attackers who successfully compromise authentication extract far more
value per incident than those who merely impersonate or circumvent verification.
''')

add("FINCEN-IDENTITY-04", "fincen_identity_related_sar_2021", "Appendix 1 — General Fraud",
    "General fraud, including card fraud, as the top typology", '''
FinCEN's 2021 identity-related suspicious activity report finds general fraud to be the most
frequently reported typology by far: 1.2 million BSA reports totaling $149 billion in
suspicious activity, consistent with Treasury's finding that fraud is the largest driver of
money laundering by scope and magnitude. Filers reported many types of fraud under this
heading, including "bust-out" schemes, where attackers open credit card accounts with false
information and then max out the cards; check fraud, including check kiting; credit and debit
card fraud, where attackers obtain compromised card numbers and conduct unauthorized
transactions; and many types of COVID-19 relief fraud. Account takeover, business email
compromise, identity theft, and synthetic identity are tracked as separate, related typologies
rather than folded into general fraud.
''')

add("FINCEN-IDENTITY-05", "fincen_identity_related_sar_2021", "Appendix 1 — Identity Theft", "Identity theft typology", '''
FinCEN's 2021 identity-related suspicious activity report defines identity theft as using
identifying information unique to the rightful owner without that owner's permission, and
reports approximately 222,000 identity-related BSA reports describing it, totaling $36 billion
in suspicious activity. It is classified under the "compromise" exploitation and heavily
overlaps with the "false records" typology, since attackers present false information,
documentation, and signatures to carry out identity theft. Financial institutions often
identify the activity only after discovering false records or additional fraud, or after
determining the victim is deceased, incapacitated, incarcerated, or otherwise unable to have
applied at the time; in other cases, another institution in the lending process, or the victim
themselves, reports the inconsistency.
''')

add("FINCEN-IDENTITY-06", "fincen_identity_related_sar_2021", "Appendix 1 — Third-Party Money Laundering",
    "Money mules and straw buyers as third-party money laundering", '''
FinCEN's 2021 identity-related suspicious activity report describes third-party money
laundering -- laundering of proceeds by a person not involved in the predicate offense -- as
involving individuals acting as straw buyers and money mules who conduct transactions and move
funds on behalf of others, classified under the "circumvention" exploitation. Straw buyers apply
for vehicle or mortgage loans on behalf of another person while concealing the true purchaser's
identity. Money mules receive and transfer funds on behalf of others; they are often recruited
online through scams and may be witting or unwitting participants who launder fraud proceeds
while concealing the identity of the true transactor. FinCEN identified approximately 154,000
identity-related BSA reports describing this activity, totaling $18 billion.
''')

add("FINCEN-IDENTITY-07", "fincen_identity_related_sar_2021", "Appendix 1 — False Records and Synthetic Identity",
    "False records and synthetic identity typologies", '''
FinCEN's 2021 identity-related suspicious activity report defines false records as altering,
counterfeiting, or forging documentation, records, or forms of payment -- the second most
frequently reported typology, with about 423,000 BSA reports and $45 billion in suspicious
activity, classified under "impersonation." Attackers provide fake Social Security numbers,
inconsistent identifying information, false income and employment documents, forged signatures,
and counterfeit money when opening accounts or conducting transactions. A related, smaller
typology is synthetic identity: the use of a combination of real and fake personally
identifiable information to fabricate a person or entity, reported about 3,000 times for $182
million in suspicious activity, also classified under "impersonation" since it is designed to
pass the validation step.
''')

add("FINCEN-IDENTITY-08", "fincen_identity_related_sar_2021",
    "Attackers Compromise Authentication and Misuse Credentials to Gain Access", "How attackers compromise authentication", '''
FinCEN's 2021 identity-related suspicious activity report describes how attackers compromise
victims' credentials to gain unauthorized access to data, funds, information, and systems,
targeting victims directly through account takeovers, business email compromises, brute-force
login attacks, data breaches, identity theft, phishing, ransomware, and other endpoint
compromises. Attackers then generate illicit proceeds from selling stolen credentials or use
them to open accounts, apply for credit, and conduct transactions, or to access accounts and
systems for their own financial gain. Some attackers also misuse their own authorized access or
position as authenticators, such as compromised powers of attorney used to move funds from
elderly victims' accounts, which the report also classifies under the "compromise" exploitation.
''')

# ---------------------------------------------------------------------------
# FATF/Interpol/Egmont: Illicit Financial Flows from Cyber-Enabled Fraud (2023)
# ---------------------------------------------------------------------------

add("FATF-CYBERFRAUD-01", "fatf_cyber_enabled_fraud_2023", "2.3 ML techniques and typologies — Structure of ML networks",
    "Money mule networks in cyber-enabled fraud", '''
FATF's Illicit Financial Flows from Cyber-Enabled Fraud (2023) reports that criminals need to
launder cyber-enabled fraud (CEF) proceeds quickly and efficiently, often through professional
money-laundering groups or third-party enablers such as lawyers, accountants, and bankers
operating under a "crime-as-a-service" model. CEF-related laundering networks typically involve
money mules, and sometimes shell companies or legitimate businesses. Individual money mules are
recruited via job offers, advertisements, and online social media interactions; their recruiters
are known as mule "herders." Mules may be knowingly complicit or work unwittingly through
deception, or negligently, and may be offered incentives or fees to handle illicit funds. Some
jurisdictions have observed foreign nationals with no local connection directed to set up mule
accounts, either by physical travel or virtual account opening.
''')

add("FATF-CYBERFRAUD-02", "fatf_cyber_enabled_fraud_2023",
    "2.3 ML techniques and typologies — Shell companies and CEF-specific mule traits",
    "Shell companies and how CEF money mules differ from other mules", '''
FATF's cyber-enabled fraud report notes that shell companies used in CEF laundering networks are
typically controlled through strawmen or nominee directors, and individual money mules recruited
may themselves be instructed to act as strawmen and open corporate accounts to further obscure
criminal ownership, sometimes using virtual business addresses. Compared with mules used for
other crimes, CEF-related mules are more likely to be recruited online, including through job
advertisements from fake companies or spam email, and victims of CEF (for example, romance-fraud
victims) can themselves be tricked into acting as mules. CEF mule accounts are used mainly for
fast electronic payment methods rather than physical cash transfers, so targeted individuals
typically need some basic computer proficiency.
''')

add("FATF-CYBERFRAUD-03", "fatf_cyber_enabled_fraud_2023",
    "2.3 ML techniques and typologies — Account control and testing transactions",
    "Mule account control, and small-value test transactions", '''
FATF's cyber-enabled fraud report describes how, once established, fraudulently acquired funds
are rapidly layered through pass-through transactions via accounts controlled by mules or
strawmen themselves, or directly by the fraud syndicate after mules surrender banking
credentials, cards, and tokens, or grant power of attorney. Separately, the report notes that
because financial institutions or authorities may already flag an account for fraud before
laundering can begin, criminal syndicates perform "tests": small-value transactions sent first
so the destination account can be changed if the test transaction fails or is intercepted. This
mirrors, at the money-laundering-network level, the same logic behind card testing: small
probing transactions before committing larger amounts.
''')

add("FATF-CYBERFRAUD-04", "fatf_cyber_enabled_fraud_2023", "Annex A: Risk indicators for CEF — Transaction patterns",
    "Red flags: transaction patterns", '''
FATF's Annex A on cyber-enabled fraud risk indicators lists transaction-pattern red flags
including: rapid or immediate high- or low-value transactions after an account is opened,
inconsistent with the account's stated purpose; rapid cash withdrawals or transfers of large
amounts immediately after receiving a funds transfer, effectively emptying the account;
frequent, large transactions inconsistent with the account holder's economic profile, such as
sudden international transfers or cash withdrawals through payment cards at foreign ATMs; and a
small payment to a beneficiary that, once it succeeds, is rapidly followed by larger-value
payments to the same beneficiary. FATF cautions that no single indicator alone warrants
suspicion, but it should prompt further monitoring and examination.
''')

add("FATF-CYBERFRAUD-05", "fatf_cyber_enabled_fraud_2023",
    "Annex A: Risk indicators for CEF — Suspicion in account user's identity", "Red flags: device and IP indicators", '''
FATF's Annex A on cyber-enabled fraud risk indicators lists device- and connection-level red
flags: multiple IP addresses or electronic devices associated with a single online account;
conversely, a single static IP address or device associated with multiple accounts belonging to
different account holders; use of VPNs, compromised IoT devices, or hosting companies that mask
a user's IP address; remote-desktop tools such as TeamViewer that hide the true device and
location; IP addresses or GPS coordinates originating from high-risk jurisdictions; frequent
changes to contact details, email addresses, or phone numbers after account opening; email
addresses inconsistent with the account holder's name, or a pattern of similar-looking email
addresses across multiple accounts; and abnormalities in online behavior such as keystroke
delays, hesitation entering data, or signs of automation and bot control.
''')

add("FATF-CYBERFRAUD-06", "fatf_cyber_enabled_fraud_2023",
    "Annex A: Risk indicators for CEF — Account holder profile and adverse information",
    "Red flags: mule-like profile and adverse information", '''
FATF's Annex A on cyber-enabled fraud risk indicators also lists profile-level red flags
suggesting a customer may be acting as a money mule: being unwilling or unable to pass customer
due diligence checks; being unfamiliar with the source of funds moving through their own
account, or claiming to be transacting on someone else's behalf; and giving non-realistic,
confusing, or inconsistent explanations for the nature, amount, or purpose of a transaction or
relationship. Separately, adverse-information indicators include the presence of verifiable
negative news about the customer or a counterparty -- for example, an account previously
flagged as belonging to a scam victim, a mule, or a victim of identity takeover -- and fraud
reports or recalls from a correspondent institution or third-party fraud databases.
''')

add("FATF-CYBERFRAUD-07", "fatf_cyber_enabled_fraud_2023",
    "Annex B: Harnessing synergies between anti-fraud and AML/CFT controls",
    "Controls that pair anti-fraud with AML/CFT: device binding and step-up authentication", '''
FATF's Annex B compiles anti-fraud controls that financial institutions and payment providers
have paired with AML/CFT requirements to target criminals' ability to register, access, and
control mule accounts remotely. Examples include rigorous know-your-customer processes with
biometric onboarding and identification of a single trusted device to authenticate online
banking, with other devices blocked or subjected to enhanced checks; a cooling-off period after
first enrolling online banking or a new device, during which the full suite of services is not
immediately available; requiring multi-factor authentication for verification and for adding or
activating new beneficiaries; and monitoring IP addresses used to connect to online banking to
detect remote-access tools or "man-in-the-browser" attacks. FATF frames these as complementary
to, not a substitute for, suspicious transaction reporting.
''')

add("FATF-CYBERFRAUD-08", "fatf_cyber_enabled_fraud_2023",
    "2.3 ML techniques and typologies — First layer accounts by fraud type",
    "How the type of fraud predicts the mule account type", '''
FATF's cyber-enabled fraud report observes that the type of "first layer" account used to
receive CEF proceeds typically depends on the type of fraud, to preserve a facade of
legitimacy: business email compromise and online trading or trading-platform fraud tend to
route proceeds through corporate accounts, such as shell or newly registered companies, while
phishing fraud, social-media or telecommunications impersonation fraud, online romance fraud,
and employment scams tend to route proceeds through individual money mule accounts. The report
notes this is a general trend from jurisdictions' experience, not a rule that applies to every
case, but it is a useful prior when an investigator is trying to characterize an unfamiliar
coordinated-fraud pattern.
''')

# ---------------------------------------------------------------------------
# Validate and write.
# ---------------------------------------------------------------------------


def main():
    seen_sources = {c["source"] for c in CHUNKS}
    for src in seen_sources:
        files = SOURCE_FILES.get(src, [])
        if not any(f.exists() for f in files):
            raise SystemExit(f"source '{src}' has no existing file among {files}; re-download to knowledge/raw first")

    ids = [c["id"] for c in CHUNKS]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"duplicate chunk ids: {dupes}")

    bad = []
    for c in CHUNKS:
        n = len(c["text"].split())
        if not (60 <= n <= 350):
            bad.append((c["id"], n))
    if bad:
        print("WARNING: chunks outside the 60-350 word range:")
        for cid, n in bad:
            print(f"  {cid}: {n} words")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for c in CHUNKS:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    by_source = {}
    for c in CHUNKS:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    print(f"wrote {len(CHUNKS)} chunks to {OUT}")
    for src, n in sorted(by_source.items()):
        print(f"  {src}: {n}")


if __name__ == "__main__":
    main()
