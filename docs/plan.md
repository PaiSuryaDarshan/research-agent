# research-agent plan

A science research agent: give Hermes a topic and get a rigorous ~6-page review with traceable, verifiable citations, possibly one per day. Four agents (Research, Analyst, Writer, Editor/reviewer) run on a plain-code pipeline. Local models (Qwen in LM Studio) and local parsing (MinerU) do the heavy reading; cloud models do only the highest-reasoning steps. Public repo, for my CV.

## Current state
| What works | Where |
|---|---|
| Hermes + Qwen 3.5 9B (Q4_K_M; Q6_K and Q8_0 available) in LM Studio (outside this repo) | local PC |
| Architecture and model allocation | `design_decisions.md` |
| Benchmark plan, ledger accuracy test and cost model | `benchmark.md`, `design/cost_model.md` |
| Pipeline diagram | `docs/` (exported) + https://claude.ai/artifact/QoEpAaVBPE6A8E1Bw37TQj |
| Repo | not created yet |

## Order of work
1. Repo skeleton (Python package, CLI stub, tests, .gitignore) ← next
2. Research agent, discovery: topic → seed queries → OpenAlex / Semantic Scholar / Crossref / arXiv / ChemRxiv → citation expansion (1 hop) → ranked, de-duplicated candidates
3. Research agent, screening: local Qwen reads titles and abstracts (keep if unsure); stopping rule
4. Freeze the benchmark topic set and run the discovery-recall test (`benchmark.md`)
5. Research agent, evidence: fetch full texts → MinerU → sections with DOI / page / section ids
6. Evidence ledger: schema → local per-paper extraction (strict format + verbatim quote) → automatic checks
   → **minimum version done: topic in, evidence ledger out**
7. Ledger accuracy test (D-023) with the quantisation comparison Q4_K_M / Q6_K / Q8_0 (D-024) → **gate: the Analyst isn't built until the ledger passes**
8. Model layer: one client for LM Studio, Anthropic, OpenAI-compatible, DeepSeek, Gemini; setups (premium / optimized / budget / local) chosen by config; thinking budget per cloud step (D-026); batch for synthesis only (D-025)
9. Analyst agent: scoping, gap check, synthesis & outline
10. Writer + Editor/reviewer agents: draft → citation/quote checks → review with acceptance tests → targeted revision → re-check with escalation → finish
11. Hermes skill wraps the CLI
12. Token and cost logging per step (thinking tokens separately)
13. Full benchmark: 4 setups × the topic set; blind grading

## Current step
Run `codex/00_setup_prompt.md` to create the repo skeleton.

## Folder layout
```
research-agent/
  src/research_agent/
    cli.py              # `research-agent` command (Hermes skill calls this)
    pipeline.py         # plain state machine: ordered steps, saved state, retries
    agents/
      research/         # discovery, screening, acquisition, parsing, extraction
      analyst/          # scoping, gap check, synthesis & outline
      writer/           # draft, targeted revision, finish
      editor/           # citation/quote checks, review, re-check, escalation
    ledger/             # evidence ledger schema + storage
    llm/                # model clients + setup configs
  profiles/science/     # prompts, report template, review checklist (config, not code)
  benchmark/            # topic set, grading rubric, results
  hermes_skill/         # Hermes skill that calls the CLI
  docs/                 # whiteboard export
  tests/
  data/                 # gitignored: pdfs, parsed text, index, runs
  plan.md
  design_decisions.md
  engineering_decisions.md
  benchmark.md
  inspirations_from_prior_work.md
```

## How the docs work
Claude keeps the five root docs up to date and hands over full replacement files; I drop them into the repo root and commit with the block Codex prints.
