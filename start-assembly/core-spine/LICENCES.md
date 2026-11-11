# Licences — core spine components

Licences as stated in the repo triage
(`~/workspace/v032-review/blueprint-triage/REPO_TRIAGE.md`, 2026-11-10).
Verify against each repo's LICENSE file before any redistribution;
this file is a triage record, not legal advice.

| Component | Repo | Licence (as triaged) | Notes |
|---|---|---|---|
| HiGHS | ERGO-Code/HiGHS | MIT | Core is C++; HiPO extras Apache-2.0. Used here via SciPy (HiGHS). |
| CPMpy | CPMpy/cpmpy | Apache-2.0 | Core library Apache-2.0; some optional solvers it can call (Gurobi, CPLEX, IBM CP Optimizer, Hexaly) are commercial — not used here. |
| CVXPY | cvxpy/cvxpy | Apache-2.0 | Modelling layer, not a solver; backends used here are open (HiGHS). |
| JuMP.jl | jump-dev/JuMP.jl | MPL-2.0 | Modelling layer; needs a solver backend (HiGHS.jl, MIT). |
| Agents.jl | JuliaDynamics/Agents.jl | MIT | |
| ModelingToolkit.jl | SciML/ModelingToolkit.jl | MIT | Triage noted a licence-metadata mismatch — confirm the LICENSE file before adopting. |
| Symbolics.jl | JuliaSymbolics/Symbolics.jl | MIT | Triage noted a licence-detection mismatch — confirm before adopting. |
| Turing.jl | TuringLang/Turing.jl | MIT | |
| DifferentialEquations.jl | SciML/DifferentialEquations.jl | **NOASSERTION** | GitHub reports no licence assertion. **Do not adopt until the licence is confirmed.** This is the one licence caution inside the spine. |
| AlphaZero.jl | jonathan-laurent/AlphaZero.jl | MIT | |
| LangGraph | langchain-ai/langgraph | MIT | |
| Cedar | cedar-policy/cedar | Apache-2.0 | Source audit batch 2 (2026-11-11): dependency only, nothing small enough to copy. |
| egg | egraphs-good/egg | MIT | Source audit batch 2 (2026-11-11): dependency only for the e-graph core. |
| Cognee | topoteretes/cognee | Apache-2.0 | Source audit batch 2 (2026-11-11): defer the system; only two stdlib chunking helpers copyable. **Copied 2026-11-11:** `chunk_by_word.py` (87 lines) + `chunk_id.py` (22 lines) into `helpers/borrowed_helpers.py`, Apache-2.0 notice kept, stdlib-only, provenance in `helpers/PROVENANCE.md`. |
| Graphiti | getzep/graphiti | Apache-2.0 | Source audit batch 2 (2026-11-11): defer the system; temporal-edge schema as original rewrite only. |
| Crawl4AI | unclecode/crawl4ai | Apache-2.0 | Source audit batch 2 (2026-11-11): dependency only for the crawler; only `normalize_url` copyable. **Copied 2026-11-11:** `normalize_url` (`utils.py` lines 2259–2358, ~100 lines, that function only) into `helpers/borrowed_helpers.py`, Apache-2.0 notice kept, stdlib-only, provenance in `helpers/PROVENANCE.md`. |
| Tonic / gRPC | grpc/grpc-rust | MIT | |
| Apache Arrow | apache/arrow | Apache-2.0 | Used here via pyarrow. |
| DeepEval | confident-ai/deepeval | Apache-2.0 | |
| ODYM | IndEcol/ODYM | MIT (LICENSE.txt, Copyright (c) 2025 International Society for Industrial Ecology and Contributors) | **Added 2026-11-11 as a dependency only — no ODYM code copied.** Installed from git, pinned to commit 9792c23 (2025-09-26), version 0.1.0, because ODYM was never published to PyPI (`pip install ODYM` fails, pypi.org 404; see ASSEMBLY_REPORT.md item 9). Cautions: xlwt/xlrd are legacy Excel deps — the adapter never calls any ODYM Excel read/write (in-memory only); MFAsystem uses mutable default arguments (ProcessList=[], FlowDict={}) — the adapter always passes explicit, freshly built collections. Governance: ODYM computes accounts; outputs are model results, not verified plans — verified=false, needs_human_decision=true, through the separate verify step. |

## Not in this spine (and why their licence cautions do not apply here)

- **MAX Engine / Modular** — not used. Triage: MAX portions are under
  the MAX License (source-available, not OSI open source).
- **Pymrio** — not in the spine. Triage: licence wording inconsistent
  (LGPL-3.0 vs GPL v3 vs NOASSERTION).
- **AI-Scientist** — not used. Triage: custom restrictive source licence.
- **Delibera, Agent-O1** — not used. Triage: no licence stated at all.

## This assembly's own code

The adapters, tests, Rust crate, Julia draft, .proto and policies in
`~/workspace/start-assembly/core-spine/` are original local work for
START. No licence is asserted for them here; if this folder is ever
published, add a LICENSE file first (the PCAC planning engine used
MIT for code; the START repo's own licence should be checked first).
No engine code was vendored into this folder.
