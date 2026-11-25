# Engineering decisions

How research-agent is built: stack, repo, workflow. What the system *is* lives in `design_decisions.md`; how we test it lives in `benchmark.md`. Decision numbers run in one sequence across all three files. Newest at the bottom. Never delete an entry: if a decision changes, add a new one that says which entry it replaces.

### D-001 — Claude writes Codex prompts and owns the docs; Codex never commits
- **Decision:** I talk to Claude; Claude writes Codex prompts (GOAL / CONTEXT / TASK / CONSTRAINTS / DONE WHEN) ending in a PowerShell `git add -A / git commit -m "<type>: <summary>" / git push` block. Claude hands over full replacement files for the root docs. No AGENTS.md, no OpenCode.
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
