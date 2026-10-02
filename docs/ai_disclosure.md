# AI disclosure

**Tools used :** Claude  for reasoning, data exploration, writing all code in this repo, debugging, writing tests, drafting the README, memo and recording script, and for labelling the 100-ticket validation sample.

**Other tools:** Chat GPT used for the assisstance for the results given by Claude.

**Paid API calls made by the tool or by me:** none. API cost = Rs 0. The tool itself uses no LLM. 

**Where it helped:** spotting the paise/duplicate explanation quickly; reading free text to design rules; the audit pass that found false negatives in the replacement detector.

**Where it wasted time / was wrong:** the first PDF export of tickets (truncated columns, dates shown as ####) cost a round trip before the CSV arrived; the first replacement detector undercounted (337 vs 368 after the audit); an early agent ranking by raw rupees was misleading.

**What I discarded:** (1) parsing the PDF export; (2) an optional free-LLM fallback for unclassified rows (not needed for ~3% of rows, would add keys and an untested path); (3) ranking agents by raw refund rupees; (4) treating the 91.7% agreement with agent codes as accuracy.

**Honesty notes:** the 100 validation labels were assigned by the AI assistant after it had seen the classifier output; they are not independent ground truth. The business target (10 a quarter) is a proposal, not a finding.