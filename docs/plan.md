# research-agent plan

A science research agent: give Hermes a topic and get a rigorous ~6-page review with traceable, verifiable citations, possibly one per day. Four agents (Research, Analyst, Writer, Editor/reviewer) run on a plain-code pipeline. Local models (Qwen in LM Studio) and local parsing (MinerU) do the heavy reading; cloud models do only the highest-reasoning steps. Public repo, for my CV.

## Current state
| What works | Where |
|---|---|
| Hermes + Qwen 3.5 9B (Q4_K_M; Q6_K and Q8_0 available) in LM Studio (outside this repo) | local PC |
| Architecture and model allocation | `design_decisions.md` |
| Benchmark plan, ledger accuracy test and cost model | `benchmark.md`, `cost_model.md` |
| Pipeline diagram | `science_research_agent_whiteboard.png` / `.svg` + https://claude.ai/artifact/QoEpAaVBPE6A8E1Bw37TQj |
| Repo skeleton: package, CLI stub (`research-agent run`), 4 passing tests | `src/`, `tests/` |

## Order of work
1. ~~Repo skeleton (Python package, CLI stub, tests, .gitignore)~~ ✅ done 2026-11-25
2. Research agent, discovery: topic → seed queries → OpenAlex / Semantic Scholar / Crossref / arXiv / ChemRxiv → citation expansion (1 hop) → ranked, de-duplicated candidates ← next
3. Research agent, screening: local Qwen reads titles and abstracts (keep if unsure); stopping rule
4. Freeze the benchmark topic set and run the discovery-recall test (`benchmark.md`)
5. Research agent, evidence: fetch full texts → MinerU → sections with DOI / page / section ids
6. Evidence ledger: schema → local per-paper extraction (strict format + verbatim quote) → automatic checks
   → **minimum version done: topic in, evidence ledger out**
7. Ledger accuracy test (D-023) with the quantisation comparison Q4_K_M / Q6_K / Q8_0 (D-024) → **gate: the Analyst isn't built until the ledger passes**
8. Model layer, local first (D-033): LM Studio client; setups chosen by config, default `local`
9. Analyst agent: scoping, gap check, synthesis & outline
10. Writer + Editor/reviewer agents: draft → citation/quote checks → review with acceptance tests → targeted revision → re-check with escalation → finish
11. Hermes skill wraps the CLI
12. Token and cost logging per step (thinking tokens separately)
13. Buy API keys; cloud clients (Anthropic, DeepSeek, Gemini) with thinking budgets (D-026) and batch for synthesis (D-025); default back to optimized (D-016)
14. Full benchmark: 4 setups × the topic set; blind grading

## Current step
Discovery (step 2): OpenAlex search, one-hop expansion, ranking and abstract fallback done; screening (step 3) next. All LLM steps local until step 13 (D-033).

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
  docs/                 # project docs (D-029)
    plan.md
    design_decisions.md
    engineering_decisions.md
    benchmark.md
    inspirations_from_prior_work.md
    cost_model.md
    science_research_agent_whiteboard.png / .svg
  tests/
  data/                 # gitignored: pdfs, parsed text, index, runs
  README.md             # links into docs/
```

## How the docs work
Claude keeps the five project docs (plus `cost_model.md`) up to date and hands over full replacement files; I drop them into `docs/` and commit with the block Codex prints.
