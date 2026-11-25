# Cost model (prices checked 2026-11-25; re-check before relying on them)

All prices are USD per million tokens (input / output), standard rate. Batch processing halves the price at Anthropic, OpenAI and Google; we use it for synthesis only (D-025). Thinking tokens are billed as output (D-026).

## API prices
| Provider | Model | Input | Output | Notes |
|---|---|---|---|---|
| Anthropic | Claude Opus 5.5 | 4 | 20 | |
| Anthropic | Claude Sonnet 5.5 | 2 | 10 | cache hit 0.10; **synthesis** |
| Anthropic | Claude Sonnet 5 | 2 | 10 | cache hit 0.20 |
| Anthropic | Claude Haiku 5.5 | 0.10 | 0.50 | prompts ≤100K tokens (0.50 / 2.50 above) |
| OpenAI | gpt-6.2-astra | 8 | 40 | |
| OpenAI | gpt-6.2-sol | 2 | 10 | |
| OpenAI | gpt-6.1-terra | 0.50 | 2.50 | verify, page label unclear |
| OpenAI | gpt-6-luna | 0.05 | 0.25 | verify, page label unclear |
| DeepSeek | V4 Pro | 0.66 / 1.32 | 1.98 / 3.96 | off-peak / peak; **scoping, gap check** |
| DeepSeek | Flash (V4.1) | 0.15 / 0.30 | 0.60 / 1.20 | off-peak / peak |
| Google | Gemini 4 Argon | 4 | 20 | from 2026-12-01 (2 / 10 before); **review** |
| Google | Gemini 3.8 Flash | 1.50 | 7.50 | from 2027-01-01 (0.75 / 3.75 before); **re-check** |
| Google | Gemini 3.5 Flash-Lite | 0.30 | 2.50 | |
| Perplexity | Search API | $5 per 1K requests | | possible discovery source; Sonar chat endpoint deprecated |

DeepSeek peak hours: 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri; all other times off-peak. No batch discount assumed for DeepSeek.

Sources: platform.claude.com/docs/en/about-claude/pricing · developers.openai.com/api/docs/pricing · api-docs.deepseek.com/quick_start/pricing · aistudio.google.com/docs/pricing · docs.perplexity.ai/getting-started/pricing

## Model quality notes (general benchmarks, not literature reviews)
- Claude Sonnet 5.5 vs Gemini 4 Argon, Vals Science Index: 59.1% vs 55.4% (vals.ai).
- Artificial Analysis Intelligence Index: Sonnet 5.5 56, Argon 53 (artificialanalysis.ai).
- Gemini 4 Argon: lowest hallucination rate among leading models on AA-Omniscience (15%); led GPQA Diamond at 96.5% on 2026-11-19 (openrouter.ai).
Our own benchmark overrides these.

## History of the cost estimate
| Version | Setup | Per report |
|---|---|---|
| 1 | Claude Sonnet on all cloud steps, original token budget | ≈ $0.53 |
| 2 | Same, lean token budget | ≈ $0.27 ($0.13 batch) |
| 3 | DeepSeek scoping/gap, Claude synthesis, GPT-6.2 Sol review + re-check | ≈ $0.21 ($0.11 batch) |
| 4 | Same, Gemini 4 Argon review + re-check | ≈ $0.30 ($0.16 batch) |
| 5 | Same, Gemini 3.8 Flash re-check | ≈ $0.27 ($0.14 batch) |
| 6 (current, optimized) | Same as 5; batch on synthesis only (D-025); thinking tokens counted (D-026) | ≈ $0.27–0.54 ($0.21 floor with synthesis batch) |

Per-setup costs: `benchmark.md`.

## Notes
- Use official APIs for the automated pipeline, not browser harnesses on consumer subscriptions (fragile, and usually against terms for unattended use).
- Local steps cost GPU time and electricity, not API fees.
- Output budgets in `benchmark.md` are visible output only; the upper bound assumes thinking triples output. Replace with logged tokens once logging exists.
