# Engineering decisions

How research-agent is built: stack, repo, workflow. What the system *is* lives in `design_decisions.md`; how we test it lives in `benchmark.md`. Decision numbers run in one sequence across all three files. Newest at the bottom. Never delete an entry: if a decision changes, add a new one that says which entry it replaces.

### D-001 — Claude writes Codex prompts and owns the docs; Codex never commits
- **Decision:** I talk to Claude; Claude writes Codex prompts (GOAL / CONTEXT / TASK / CONSTRAINTS / DONE WHEN) ending in a PowerShell `git add -A / git commit -m "<type>: <summary>" / git push` block. Claude hands over full replacement files for the project docs. No AGENTS.md, no OpenCode.
- **Why:** my standard workflow; I keep control of every commit and the docs stay consistent.
- **Rejected:** not recorded
- **Date:** 2026-11-25

### D-002 — Public repo, for my CV
- **Decision:** public GitHub repo. PDFs, parsed text, API keys, model files and run outputs are gitignored.
- **Why:** CV project, like BAP and boardgen.
- **Rejected:** private repo
- **Date:** 2026-11-25

### D-003 — Python
- **Decision:** Python package `research_agent` under `src/`.
- **Why:** MinerU, scholarly search clients and the LM Studio / provider APIs are all easy to use from Python.
- **Rejected:** TypeScript/Node
- **Date:** 2026-11-25

### D-004 — Triggered through a Hermes skill that calls a CLI
- **Decision:** a `research-agent` command line tool does the work; a Hermes skill calls it.
- **Why:** Hermes stays the daily interface; the CLI keeps the pipeline testable and usable without Hermes, including when Qwen is unloaded.
- **Rejected:** CLI only; scheduled daily run (can be added later)
- **Date:** 2026-11-25

### D-005 — Named research-agent, not litreview-agent
- **Decision:** repo, package and CLI are named `research-agent` / `research_agent`.
- **Why:** it's a science research agent, not only a literature-review tool.
- **Rejected:** litreview-agent (first working name)
- **Date:** 2026-11-25

### D-006 — Five root docs, one decision numbering
- **Decision:** `plan.md`, `design_decisions.md` (what the system is), `engineering_decisions.md` (how it's built), `benchmark.md` (how we test it, with its own "Benchmark decisions" section), `inspirations_from_prior_work.md`. Decisions are numbered D-001, D-002, … in one sequence across all files.
- **Why:** keeps design, engineering and testing apart without anything being written twice; a D-number means the same thing everywhere.
- **Rejected:** one decisions file for everything
- **Date:** 2026-11-25

### D-027 — Own repo, not a folder in the Anjali (agent system) repo
- **Decision:** research-agent lives in its own fresh public repo `research-agent`, separate from the Anjali multi-agent system repo. Shared pieces (Hermes, LM Studio client code) are duplicated for now rather than imported.
- **Why:** a standalone repo is a clearer CV piece (own README, benchmark and cost story), and keeps its five docs and decision log apart from Anjali's. It reuses little Anjali code so far.
- **Rejected:** a `research_agent/` folder inside the Anjali repo (buried on the CV, mixed decision logs; could be split out later with `git subtree split`)
- **Date:** 2026-11-25

### D-029 — Project docs live in `docs/`, not the repo root (replaces the location part of D-006)
- **Decision:** the five project docs (`plan.md`, `design_decisions.md`, `engineering_decisions.md`, `benchmark.md`, `inspirations_from_prior_work.md`), `cost_model.md` and the whiteboard images all live in `docs/`. The repo root keeps only `README.md`, config and code folders; the README links into `docs/`. D-006's split into five docs and one decision numbering still stands.
- **Why:** a tidy root reads better on GitHub for a CV repo; all documentation in one place.
- **Rejected:** five docs in the repo root (D-006's original location)
- **Date:** 2026-11-25

### D-030 — Discovery starts with OpenAlex; candidates saved as JSONL per run
- **Decision:** the first discovery source is the OpenAlex works search (free API key in `.env` as `OPENALEX_API_KEY`, required since 2026-02-13). Each run writes `data/runs/<timestamp>_<slug>/candidates.jsonl` (one de-duplicated paper per line, keyed by normalised DOI, else OpenAlex id) plus `run.json` (topic, queries, counts, API calls). Semantic Scholar, Crossref, arXiv and ChemRxiv come later behind the same candidate format.
- **Why:** OpenAlex has the broadest free coverage, abstracts and reference lists in one call, which citation expansion needs next. A search call costs $0.001 against a free $1/day budget, so a topic costs about a cent. JSONL is easy to diff, append and read back; `data/` is gitignored, so no paper metadata enters the repo.
- **Rejected:** all five sources at once (more code before anything is tested); a database (not needed yet)
- **Date:** 2026-11-25

### D-034 — Doc changes go inside Codex prompts (replaces the hand-over part of D-001)
- **Decision:** Claude no longer hands over replacement doc files. Each Codex prompt that changes docs has a DOC EDITS section with exact, word-for-word edits (append this text / replace this line with that line) for files in `docs/`. Codex applies them verbatim and touches nothing else in `docs/`. Claude keeps the claude.ai Project copies in sync. Codex still never commits (D-001).
- **Why:** downloading and dropping in files every step was tedious; one paste now covers code and docs.
- **Rejected:** full replacement files (D-001's original hand-over); letting Codex write doc text itself (docs would drift from the decisions made with Claude)
- **Date:** 2026-11-25
