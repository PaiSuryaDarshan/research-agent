# Benchmark

How we judge research-agent's quality and cost, and decide which models run which steps. Decision numbers continue the sequence from `design_decisions.md`.

## Setups
| Step | Premium | Optimized | Budget | Local |
|---|---|---|---|---|
| Scoping | Claude Sonnet 5.5 | DeepSeek V4 Pro | DeepSeek V4 Pro | Qwen |
| Gap check | Claude Sonnet 5.5 | DeepSeek V4 Pro | DeepSeek V4 Pro | Qwen |
| Synthesis & outline | Claude Sonnet 5.5 | Claude Sonnet 5.5 | DeepSeek V4 Pro | Qwen |
| Review | Gemini 4 Argon | Gemini 4 Argon | Gemini 4 Argon | Qwen |
| Re-check | Gemini 3.8 Flash | Gemini 3.8 Flash | Gemini 3.8 Flash | Qwen |

All local steps (queries, screening, extraction, drafting, revision, finishing) run on Qwen in every setup. "Local" is the setup D-017 calls "local-only"; the CLI flag is `--setup local`.

What each comparison answers:
- **Premium vs optimized:** do scoping and gap check need Claude?
- **Optimized vs budget:** is Claude worth ~4× DeepSeek for synthesis, the step that decides quality?
- **Any cloud setup vs local:** what do cloud models actually add? If local is close on a step, that step never needed the cloud.

## Expected cost (lean token budget)
| Step (input / output) | Premium | Optimized | Budget | Local |
|---|---|---|---|---|
| Scoping (3k / 2k) | $0.026 | $0.006 | $0.006 | $0 |
| Gap check (10k / 2k) | $0.040 | $0.011 | $0.011 | $0 |
| Synthesis & outline (25k / 6k) | $0.110 | $0.110 | $0.028 | $0 |
| Review (15k / 3k) | $0.120 | $0.120 | $0.120 | $0 |
| Re-check (8k / 1k) | $0.020 | $0.020 | $0.020 | $0 |
| **Per report** | **$0.32** | **$0.27** | **$0.19** | **$0** |
| Per report, batch on synthesis only (D-025) | $0.26 | $0.21 | $0.19 | $0 |
| Per report, upper bound if thinking triples output (D-026) | $0.65 | $0.54 | $0.36 | $0 |
| Per month (daily) | $9.50 | $8.00 | $5.60 | $0 |
| Per month, batch on synthesis only | $7.80 | $6.40 | $5.60 | $0 |

Output budgets above are visible output only; reasoning models bill thinking tokens as output too (D-026), so treat the first row as the floor. Prices and assumptions: `design/cost_model.md`. Add ≈ $0.02 per escalated issue. Replace these estimates with logged real tokens once the token-logging step of `plan.md` is done.

## How a benchmark run works
1. For each topic, run the Research agent **once** (discovery → ledger). All setups share that ledger.
2. Branch at the Analyst: run each setup from the same ledger.
3. Label the reports A/B/C/D at random; I grade them blind with the rubric below.
4. Log the automatic metrics for every run.
5. Audit re-check: send every fix Flash approved back to Argon and record the agreement.

## Ledger accuracy test (D-023)
Run before the Analyst exists, and again whenever the extraction model, quantisation or prompt changes.
1. Pick 50 ledger records at random from one topic's ledger (more topics later).
2. For each record I check against the paper:
   - claim matches what the source says (not overstated, not out of context)
   - numbers and units are right
   - conditions are right and complete (functional/basis set, gas phase vs solvent, ΔG vs ΔE, computed vs experimental, temperature)
   - the verbatim quote actually supports the claim (not just present in the paper)
   - DOI, section and page are right
3. Grade each record **correct / minor issue / wrong**, and tag the error type (claim, number, units, conditions, quote, location).
4. Provisional pass bar: ≥ 90% correct and ≤ 2% wrong numbers. Reset the bar after the first run if it's clearly too strict or too loose.

Quantisation comparison (D-024): same papers, same prompt, extraction run with Q4_K_M, Q6_K and Q8_0; grade each run with the test above and log runtime per paper.

## Rubric (I grade, blind, per report)
| Criterion | Scale |
|---|---|
| Factual errors | count |
| Unsupported or overstated claims | count |
| Missed contradictions between studies | count |
| Coverage of the key findings in the topic | 1–5 |
| Quality of synthesis (comparison, not summary) | 1–5 |
| Treatment of methods, limitations and uncertainty | 1–5 |
| Would I trust this as a starting point for my own work? | yes / no |

## Automatic metrics (per run)
- Discovery recall: share of the reference review's key references found (shared across setups)
- Ledger accuracy: % correct, % wrong numbers, error types (D-023; graded by me, shared across setups)
- Citation and quote check pass rate
- Re-check: Flash approvals overturned by Argon (%)
- Revision rounds and escalations
- Tokens in/out per step (thinking tokens logged separately), cost per step, runtime

## Topic set (proposed: verify each has a good 2024–2026 review before freezing)
1. Machine-learned interatomic potentials for molecular dynamics
2. DFT functional accuracy for reaction barriers in transition-metal catalysis
3. Kinetic modelling of biomass pyrolysis
4. Computational screening of MOFs for CO₂ capture
5. Implicit vs explicit solvation in reaction modelling

I may add or swap topics. Once frozen, the set stays fixed so results stay comparable over time.

## Results
Preliminary discovery-recall runs, 2026-11-25. Topic: kinetic modelling of biomass pyrolysis. Reference: W4413216169 (Shakor et al. 2025, a broad TGA kinetics review that also cites off-topic work, so raw recall is a lower bound).

| Run | Queries | Candidate recall (top 300) | Kept recall |
|---|---|---|---|
| Leaky (reference review in the run) | 1 | 8.1% | 8.1% |
| Fair (reference excluded) | 1 | 4.8% | 4.3% |
| Fair | 5, hand-written | 12.9% | 11.8% |

Finding so far: several queries covering the topic's branches (model-free, DAEM, lumped schemes, ML) raised recall 2.7×. With 5 queries, recall in the full pool of 1,249 papers was 21.5% before the top-300 cut and 12.9% after: the cut removed 16 of 40 found references, including classic TGA-method papers (Kissinger 1957, Coats–Redfern 1964, Ozawa 1966) with low keyword and recency scores. Screening excluded Friedman's 1964 method paper ("phenolic plastic" in the title): foundational method papers don't match the topic literally. Fix: D-037.

## Benchmark decisions
Newest at the bottom. Never delete an entry: if a decision changes, add a new one that says which entry it replaces.

### D-017 — Four setups: premium, optimized, budget, local-only
- **Decision:** benchmark the four setups in the table above.
- **Why:** premium vs optimized tests the cheap steps; budget tests whether Claude is worth paying for synthesis; local-only shows what the cloud adds.
- **Rejected:** premium vs optimized only
- **Date:** 2026-11-25

### D-018 — One shared ledger per topic; setups branch at the Analyst
- **Decision:** the Research agent runs once per topic; every setup starts from the same ledger.
- **Why:** differences in quality then come from the models, not from which papers were found; halves the benchmark's cost.
- **Rejected:** independent full runs per setup
- **Date:** 2026-11-25

### D-019 — Reviewer and re-check are the same in all cloud setups
- **Decision:** Gemini 4 Argon reviews and Gemini 3.8 Flash re-checks in premium, optimized and budget.
- **Why:** the reviewer shapes the final report through the feedback loop; holding it fixed isolates the steps being compared. Also avoids Claude reviewing Claude in premium.
- **Rejected:** premium = Claude on every cloud step
- **Date:** 2026-11-25

### D-020 — I grade blind; automatic metrics alongside
- **Decision:** I grade every report blind (random A/B/C/D labels) with the rubric; no model judges the benchmark.
- **Why:** a model grading its own family's reports is worthless, and I'm the domain expert.
- **Rejected:** LLM-as-judge
- **Date:** 2026-11-25

### D-021 — Fixed topic set of 3–5 topics with a recent published review
- **Decision:** Claude proposes topics (list above); I can add or swap; each needs a good 2024–2026 review; once frozen, it stays fixed.
- **Why:** comparable results across runs, and a reference list for discovery recall.
- **Rejected:** new random topics each time
- **Date:** 2026-11-25

### D-022 — Audit Flash re-check against Argon
- **Decision:** in every benchmark run, Argon re-judges every fix Flash approved. If Argon overturns more than about 1 in 10, re-check moves to Argon (replacing D-014).
- **Why:** a weaker re-checker could wave through fixes the reviewer wouldn't accept; measure it instead of trusting it.
- **Rejected:** trusting Flash without measuring
- **Date:** 2026-11-25

### D-023 — Ledger accuracy test, gating the Analyst
- **Decision:** I grade 50 random ledger records per topic against the papers (claim, numbers + units, conditions, quote supports claim, location), as described above. Provisional bar: ≥ 90% correct, ≤ 2% wrong numbers. The Analyst agent isn't built until the ledger passes.
- **Why:** the minimum version (D-007) ends at the ledger and every later step trusts it (D-010). The quote check catches made-up quotes but not a real quote filed with the wrong number or conditions. Judged only through final reports, extraction errors would be blamed on synthesis or the writer.
- **Rejected:** judging the ledger only through final reports; LLM grading (see D-020)
- **Date:** 2026-11-25

### D-024 — Choose the extraction quantisation by measurement
- **Decision:** run the D-023 test on the same papers with Qwen 3.5 9B at Q4_K_M (current), Q6_K and Q8_0. Use Q8_0 unless Q6_K scores the same within noise; keep Q4_K_M only if it matches both. Log runtime per paper alongside.
- **Why:** extraction is the most accuracy-critical local step and the heaviest reading. GPU tools run one at a time, so the extra VRAM is free; on 16 GB, Q8_0 (roughly 9–10 GB of weights) still leaves room for a long context. Measuring avoids paying in speed and context for no gain.
- **Rejected:** keeping Q4_K_M untested; switching to Q8_0 without measuring
- **Date:** 2026-11-25

### D-036 — Discovery-recall test: measured automatically against a reference review, with leakage guard
- **Decision:** `research-agent recall <run folder> --reference <DOI or OpenAlex id>` fetches the reference review's reference list from OpenAlex and reports recall = share of those references found among the run's candidates (top 300) and among the screened-kept papers, plus a CSV of missed references with titles for me to check. The reference review must not be in the run: `discover --exclude <id>` removes it before expansion, and `recall` warns if it is present, because its own reference list would otherwise leak in through backward expansion.
- **Why:** step 4 needs a number, not an impression. A recent review's reference list is an independent, expert-made list of what matters for the topic. Raw recall against all references is a lower bound, since broad reviews also cite off-topic work; the missed-references CSV shows which misses actually matter.
- **Rejected:** me picking "key references" by hand for every topic (slow, not repeatable); judging recall only from the top 10 (says nothing about coverage)
- **Date:** 2026-11-25
