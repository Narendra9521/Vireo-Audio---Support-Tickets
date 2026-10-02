# Vireo Audio refund summary tool

Takes the raw helpdesk export and produces what Finance asked for: **monthly refunds by reason code and by agent, with a total that reconciles**. It also re-reads the free text to show what the reason codes hide, and finds tickets where a customer got both a refund and a replacement.

> **No client data is in this repo.** Put the four CSVs from the pack into `data/` yourself (git-ignored).

## 1. Problem
Finance's export "sums to well over a crore a quarter"; the helpdesk report says ~Rs 11 lakh. Reason codes come from a dropdown whose first option (GW-OTHER) is over-used, some tickets appear twice after a migration re-import, and legacy Freshdesk rows store money differently.

## 2. Inputs
`data/tickets.csv`, `agents.csv`, `orders.csv`, `products.csv` (from the pack). `customers.csv` is not needed. Python 3.10+.

## 3. Run (clean machine, no API key, no cost)
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m vireo_refunds --data data --out outputs      # writes outputs/refund_summary.xlsx (+ 2 CSVs)
python -m vireo_refunds.validate                       # proxy agreement, detector check, blind label sheet
python -m vireo_refunds.validate --score               # accuracy on validation/labels.csv
python tests/test_pipeline.py                          # 10 tests, no pytest needed
```
Open `outputs/refund_summary.xlsx` (11 tabs: Reconciliation, By reason code (agent), By reason (from text), Code vs text (GW-OTHER), By agent, By agent x month, Refund + replacement, Monthly trend, Refund+repl by quarter, Validation, Notes). Totals/rates are live Excel formulas; recalculated with 0 errors.

## 4. Method
1. **Normalise money.** `legacy_fd` rows are in paise: divide by 100. Evidence: in all 125 duplicated tickets that carry a refund, the legacy amount is exactly 100x the helpdesk amount.
2. **De-duplicate.** 638 `ticket_id`s appear under both source systems (all before 14 Sep 2025); keep the helpdesk copy. Only the amount differs between copies.
3. **Month = `created_at`** as exported (IST). See section 8 for the UTC/IST test.
4. **Join** agents (row valid on ticket date), products, orders (by `order_id`, fallback customer + SKU).
5. **Re-read the reason** with keyword rules on the customer message and the agent note (note first). Output is the policy codes plus `FAULT-DOA-WTY` (product fault / wrong item; DOA vs warranty cannot be split without a delivery date).
6. **Refund + replacement** (policy s5 forbids both): ticket has a refund and either `replacement_issued = Y` or the note says a replacement went out. Costed at `unit_cost + Rs 340` (policy s5). Evidence tiers are kept per ticket.

## 5. Results (Jan 2025 - Jun 2026)
| Step | Rs |
|---|---|
| Raw export total | 23,01,24,081 (Rs 23.01 crore) |
| After dividing legacy rows by 100 | 70,70,943 |
| After removing 638 duplicates = **clean total** | **67,09,932 (Rs 67.1 lakh), 2,340 refund tickets** |

- Last four quarters: Rs 12.1-16.3 lakh (Q4 2025 Rs 16.3 lakh, Q2 2026 Rs 12.8 lakh), in the range of the helpdesk's ~Rs 11 lakh. The remaining gap to Rs 11 lakh is **not** explained by the data; we do not know how the helpdesk report is defined.
- **Trend (association, not cause).** Monthly refund value rose from Rs 1.4 lakh (Jan 2025) to Rs 5.8 lakh (Nov 2025), then settled around Rs 3.7-4.5 lakh. Over the same time total tickets rose from 302 to 948 a month. The share of tickets with a refund stayed in a 17.5-22.8% band every month and the average refund stayed around Rs 2.6-3.2k. Pulse 2 launched 15 Jul 2025; from Q2 to Q4 2025 refund value rose Rs 9.0 lakh, of which Rs 5.4 lakh is Pulse 2 and Rs 3.6 lakh other products whose ticket volume also grew. This is consistent with "more tickets, same refund rate". The data cannot show why ticket volume grew, and it cannot test the "stopped arguing with customers" explanation (no policy-change date or interaction data). Average CSAT (blanks excluded) moved from 3.54 to 3.46; the +0.4 quoted in the thread is not visible in this file.
- GW-OTHER is 991 of 2,340 refund tickets (Rs 29.1 lakh, 43% of value) and its share of refund tickets rose from 38% (H1 2025) to 43-44% afterwards.

## 6. Validation - how we know, and how often it is wrong
| Check | Result | What it is |
|---|---|---|
| Hand-labelled GW-OTHER sample | **n = 100, 97 correct, accuracy 97.0%, error rate 3.0%, 95% CI 91.5-99.0%** | **Labels were assigned by Claude (the AI assistant) reading the ticket text, after seeing the classifier's output. They are not independent and not human ground truth.** |
| **Blind re-label** (`validation/labels_claude_blind.csv`, the 100 tickets of `label_sheet.csv`) | **n = 100, 96 correct, accuracy 96.0%, error rate 4.0%, 95% CI 90.2-98.4%** | Labelled by Claude from ticket text **without seeing the classifier output** (so better than the row above), but still an AI, not a human. Run: `python -m vireo_refunds.validate --score --labels validation/labels_claude_blind.csv` (also writes git-ignored `validation/label_review_*.csv` with text, predicted reason, true reason, correct). The two label sets cover different tickets (10 overlap; on those the labels agree once DOA/warranty/fault are merged). Errors: 2 unclassified (a wrong-colour item; a \"card charged two times\" ticket with an empty note), 1 failed-order-after-payment read as a return, 1 refund-delay read as lost-in-transit. |
| Proxy agreement with agent-picked codes | 91.7% on 1,349 non-GW-OTHER refunds (1.6% unclassified) | **Not accuracy.** Agents mis-code too. |
| Replacement detector vs agent flag | notes also detect 97.0% of the 166 flagged tickets | consistency check only |

Failure types in the sample (3): a product fault left unclassified ("display ignores my finger"), a wrong-item case read as a return, and a missed-pickup goodwill refund read as a fault. Larger known weak spots: wording the rules have not seen; "FAULT" is a bucket.
**To get a real accuracy:** `python -m vireo_refunds.validate` writes a *blind* `validation/label_sheet.csv` (different 100 tickets, no prediction shown, git-ignored); fill `true_reason`, save as `validation/labels.csv`, run `--score`.

## 7. Refund + replacement (policy s5 says "in no case")
- **368 tickets** over 18 months: 166 flagged by the agent (`replacement_issued = Y`) + 202 found only in the agent notes. (An earlier draft found 337; an audit of false negatives found missed phrasings such as "refunded Rs 1499 & also raised replacement", and the rules were fixed. Sampling 30 note-only hits found all 30 describe a replacement going out; a smaller number say only "replacement dispatched" without pairing it to the refund.)
- Evidence tiers: 161 flag + notes · 152 notes, explicit refund+replacement · 50 notes, replacement only · 5 flag only.
- **Last four quarters (Jul 2025 - Jun 2026): 301 tickets (75.3 a quarter); "strict" (excluding the replacement-only wording) 261 (65.3 a quarter).** Replacement-unit cost on strict tickets: Rs 1.19 lakh a quarter (broad: Rs 1.40 lakh).
- No double counting: unique ticket ids, counted after de-duplication.
- Association with teams/agents (volume-normalised, last four quarters, strict, resolving agent's team): Chat Frontline 83 of 319 refund tickets (26%), Logistics 67 of 292 (23%), Voice 20 of 76 (26%), Email 29 of 167 (17%), Escalations & Warranty 34 of 69 (49%), Returns Desk 22 of 484 (4.5%), Billing 6 of 468 (1%). **This is workload context, not a finding about individuals:** frontline and Logistics handle lost/damaged/faulty cases where policy allows reshipment, so some overlap may be a process or tagging problem. By first-assigned team the raw counts are Chat Frontline 89, Logistics 85, Returns Desk 25 (broad definition).

## 8. UTC vs IST
`tickets.csv` is documented as IST. Checked: hour-of-day patterns are the same for both source systems (no 5.5 h shift), no resolved/first-response time is earlier than creation, and the 638 duplicated tickets have identical `created_at` and `resolved_at`. Strongest evidence: voice callbacks are only taken 08:00-22:00 IST (policy s2) and `created_at` for voice tickets spans exactly 08:00-21:59, so it is IST (if it were UTC it would sit at about 02:30-16:30). Legacy `resolved_at` also shows no 5.5 h offset in this export (median resolve time 1.9 h legacy vs 1.8 h helpdesk, no negatives, identical in duplicate pairs), despite the policy note that it was rebuilt from UTC logs; this is an inference from the data, not proof. Decision: **no conversion**. Largest monthly effect if wrong: Rs 9.3k (3.9% of that month); 23 refund tickets would move month; no conclusion changes. Sensitivity (re-checked on the de-duplicated set): if `created_at` were actually UTC and shifted +5:30, 107 of 11,600 tickets would change month, moving Rs 59k (0.9% of Rs 67.1 lakh). Two earlier figures in this README (111 tickets / Rs 35k) could not be reproduced and were replaced. Covered by `test_month_uses_created_at_as_exported_ist_no_shift` and `test_real_data_timezone_evidence` (skipped if the client CSV is absent).

## 9. Business goal (kept separate on purpose)
- **Observed baseline:** 65.3 refund+replacement tickets a quarter (strict, last four quarters; 75.3 broad), costing Rs 1,827 each in replacement units (Rs 1.19 lakh a quarter).
- **Proposed management target (not data-proven):** at most 10 a quarter. The number 10 is a proposal; the data does not say what is achievable. Some overlap may be legitimate policy exceptions (e.g. Tier 2 escalations).
- **Estimated impact:** (65.25 - 10) x Rs 1,827 = **about Rs 1.0 lakh a quarter, Rs 4.0 lakh a year** (broad definition: Rs 1.2 lakh / Rs 4.9 lakh). A 50% reduction instead: about Rs 60k a quarter.
- **Assumptions:** only the replacement unit cost is counted as avoidable (the refund is what the customer is entitled to); no refurbishment recovery (policy s5); unit cost + Rs 340 shipping as in policy; the past four quarters repeat. Any avoided handling or goodwill cost is excluded.
- This is small against total refunds of about Rs 13 lakh a quarter. It is a control problem, not the main driver of refund growth.

## 10. Limitations
- Classifier is keyword rules, not an LLM. Labels used to test it are not independent (section 6).
- DOA vs warranty cannot be split (no delivery date).
- `agent_id` is the resolving agent, not necessarily who raised the refund; 115 refunds sit on open/pending tickets and are included.
- The Rs 11 lakh helpdesk figure is not fully reproduced (we do not know its definition).
- Orders: about 66% of refund tickets match an order directly; the rest use a customer + SKU fallback. Order value/lot columns are carried but not used in the summary.
- Agent comparisons are descriptive; no causal claim is made about any agent.

## 11. Deliberate exclusions
LangGraph / agents, LangChain / RAG, a vector database, a paid LLM API, cloud or microservices, and causal inference were **not built**: the task is a reconciliation plus a classification over 12k rows with a 5-hour budget; rules and pandas are cheaper, deterministic, auditable and run offline. A free LLM fallback for the ~3% unclassified rows was considered and left out (it would add keys, rate limits and an untested code path). Also left out: CSAT/FCR analysis, SLA breach credits, lot-level defect analysis, a dashboard.

## 12. Reproducibility
Same inputs give the same outputs (no randomness except the label-sheet sample, seeded). Tests: `python tests/test_pipeline.py` (10 tests covering normalisation, duplicates, month assignment, classification, replacement detection, end-to-end reconciliation).

## 13. AI usage
See `docs/ai_disclosure.md`. Paid API calls: none (Rs 0).

## Repo layout
`vireo_refunds/` code · `tests/` · `validation/labels.csv` (ticket ids + labels, no text) · `docs/` memo, AI disclosure · `data/` and `outputs/` git-ignored.
