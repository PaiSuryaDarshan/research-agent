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
2. ~~Discovery: OpenAlex search, one-hop citation expansion, ranking, abstract fallback~~ ✅ done 2026-11-25 (D-030, D-031, D-032, D-037)
3. ~~Screening: local Qwen reads titles and abstracts, keep if unsure~~ ✅ done 2026-11-25 (D-035)
4. Query generation: local Qwen turns the topic into research questions and branch queries (D-038) ← next
5. Discovery-recall validation on a second topic with a strong reference review, automatic queries only; freeze the topic set (D-021, D-036)
6. Thin `research-agent run` (topic → queries → discover → screen) on the plain state machine, plus the Hermes skill that calls it (D-039)
7. Research agent, evidence: fetch full texts → MinerU → sections with DOI / page / section ids
8. Evidence ledger: schema → local per-paper extraction (strict format + verbatim quote) → automatic checks
   → **minimum version done: topic in, evidence ledger out**
9. Ledger accuracy test (D-023) with the quantisation comparison Q4_K_M / Q6_K / Q8_0 (D-024) → **gate: the Analyst isn't built until the ledger passes**
10. Model layer, local first (D-033): setups chosen by config, default `local`
11. Analyst agent: scoping, gap check, synthesis & outline
12. Writer + Editor/reviewer agents: draft → citation/quote checks → review with acceptance tests → targeted revision → re-check with escalation → finish
13. Token and cost logging per step (thinking tokens separately)
14. Buy API keys; cloud clients (Anthropic, DeepSeek, Gemini) with thinking budgets (D-026) and batch for synthesis (D-025); default back to optimized (D-016)
15. Full benchmark: 4 setups × the topic set; blind grading

More search sources (Semantic Scholar search, Crossref, arXiv, ChemRxiv) are added only if a recall test shows OpenAlex missing papers.

## Current step
Step 4: query generation (D-038), then the recall validation on a second topic (step 5). All LLM steps local until step 14 (D-033).

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
