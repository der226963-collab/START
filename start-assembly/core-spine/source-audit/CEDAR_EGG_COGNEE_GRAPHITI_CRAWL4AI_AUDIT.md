# Source-code audit for borrowing — Cedar, egg, Cognee, Graphiti, Crawl4AI

Date: 2026-11-11. Audit only. No code was copied from any of these
repos into START, the v0.3.2 review copy, or the core-spine assembly,
and nothing was pushed to GitHub. This is batch 2 of the borrowing
audit; batch 1 (AlphaZero.jl and LangGraph) is
`ALPHAZERO_LANGGRAPH_AUDIT.md` in the same folder, and this report
matches its structure. Local sources audited: shallow clones
(`git clone --depth 1`) at
`~/workspace/start-assembly/core-spine/source-audit/<name>/`
(Cedar and Cognee at the top level of their clone; egg, Graphiti and
Crawl4AI inside a nested `repo/` subdirectory — the clones were made
by the auditing subagents and kept as audit evidence only).
Licences were verified from each repo's own LICENSE file in the
clone; the counts below were re-checked by the coordinator
(`wc -l`) after the per-project audits came back.

Rule (Eric, 2026-11-04/05, binding): check the code AND its licensing
first; if code cannot be directly copied, write original code producing
similar effects instead.

## Verdicts

| Repo | Licence (verified) | Source size (counted) | Verdict |
|---|---|---|---|
| Cedar (`cedar-policy/cedar`) | Apache-2.0 | 233,228 lines of Rust across all `*.rs` files in the clone, incl. tests/benches/examples (src-only 217,959; `cedar-policy-core` src 132,535) | **Dependency only — use the package as a dependency; nothing is small and self-contained enough to copy** |
| egg (`egraphs-good/egg`) | MIT, Copyright 2019 Max Willsey | 10,721 lines of Rust in `src/` at HEAD (0.11.0); the pinned 0.10.0 registry copy is 9,551 lines | **Mixed — dependency only for the e-graph core; the only separable pieces (UnionFind, EClass) are trivial structs cheaper to rewrite originally** |
| Cognee (`topoteretes/cognee`) | Apache-2.0 | 248,631 lines of Python in the `cognee/` package, non-test (1,700 files); 547,655 incl. tests; 660,374 repo-wide | **Mixed — defer the system; copy only two stdlib-only chunking helpers (109 lines together)** |
| Graphiti (`getzep/graphiti`) | Apache-2.0 | 40,844 lines of Python in `graphiti_core/` (166 files); tests/, examples/, server/, mcp_server/ excluded | **Mixed — defer the system; rewrite only the temporal-edge/episode field schema as original code** |
| Crawl4AI (`unclecode/crawl4ai`) | Apache-2.0 | 47,234 lines of Python in `crawl4ai/` (80 files, v0.9.5); tests/ (58,909 lines) excluded | **Mixed — dependency only for the crawler; copy one stdlib-only URL canonicaliser (~100 lines); rewrite the small chunking/filter pieces originally** |

The pattern across all five is the same as batch 1: the licences
permit copying (Apache-2.0 and MIT both allow it with the notice
kept), but **coupling is the barrier, not the licence**. The only
genuinely copyable units found in the whole batch are three small
stdlib-only helpers — Cognee's chunking helpers (109 lines) and
Crawl4AI's `normalize_url` (~100 lines) — plus two trivial Rust
structs in egg that are cheaper to rewrite than to copy. Everything
else is either a dependency, a rewrite-original of the *idea*, or a
defer.

## 1. Licences (verified from each repo's own LICENSE file)

All five are permissively licensed. Apache-2.0 (Cedar, Cognee,
Graphiti, Crawl4AI) permits use, copying, modification and
distribution, including in a differently-licensed project, provided
the licence notice and any NOTICE file are kept, changes are marked,
and the patent grant in the licence is preserved. MIT (egg) permits
the same subject to including the copyright + permission notice in
all copies or substantial portions. Neither is copyleft; neither
imposes a same-licence requirement. None of the five has a
licence-metadata problem of the kind the triage flagged for
DifferentialEquations.jl (NOASSERTION) — all five state their
licence in their own LICENSE file, verified here.

- **Cedar:** Apache-2.0. Verified: local `LICENSE` in the clone
  (Apache License Version 2.0, January 2004); copyright holder
  stated in NOTICE as "Copyright Cedar Contributors", no year
  stated; workspace `Cargo.toml` also declares
  `license = "Apache-2.0"`. Upstream GitHub licence page was not
  separately checked (local LICENSE + registry `Cargo.toml`
  corroboration only).
- **egg:** MIT, Copyright 2019 Max Willsey. Verified: local
  `LICENSE` in the clone; corroborated by the registry copy at
  `~/.cargo/registry/src/*/egg-0.10.0/`.
- **Cognee:** Apache-2.0. Verified: local `LICENSE` in the clone.
- **Graphiti:** Apache-2.0. Verified: local `LICENSE` in the clone.
  Note: the repo has a Zep contributor agreement / CLA; any copied
  file must keep its Apache header and notice.
- **Crawl4AI:** Apache-2.0. Verified: local `LICENSE` in the clone.

Dependency licences that would travel with borrowed code are
listed per project below; the headline is that none of the five
drags in a copyleft licence for its core, but Cognee, Graphiti and
Crawl4AI all drag in paid external services, which is a bigger
barrier for START than any licence term.

## 2. Cedar — file inventory and how it works

Top-level layout (workspace): `cedar-policy-core/` (the engine),
`cedar-policy/` (public API), `cedar-policy-formatter/`,
`cedar-policy-cli/`, `cedar-policy-symcc/` (symbolic compiler),
`cedar-language-server/`, `cedar-testing/`, `cedar-wasm/`.
HEAD audited: `bdcd6a5` (2026-11-10, "Bump the github-actions group
across 3 directories with 5 updates (#2685)"). Workspace version
4.14.0; the spine already uses registry `cedar-policy` 4.14.1 —
that version skew was not diffed.

Most important files for START (line counts counted, not guessed):

| File | Lines | What it does |
|---|---|---|
| `cedar-policy/src/api.rs` | 6,694 | Public API: `Authorizer`, `PolicySet`, `Request`, `Entities`, validation entry points. The interface START's `rust/src/cedar_eval.rs` already uses. |
| `cedar-policy-core/src/evaluator.rs` | 6,708 | Core expression/policy evaluator — the heart of the engine. |
| `cedar-policy-core/src/parser/cst_to_ast.rs` | 6,290 | Converts the LALRPOP-generated concrete syntax tree to the AST. Inseparable from the grammar and AST types. |
| `cedar-policy-core/src/validator/schema.rs` | 6,451 | Schema model for policy validation. |
| `cedar-policy-core/src/est.rs` | 5,185 | EST (expression syntax tree) JSON representation of policies; tied to the AST. |
| `cedar-policy-core/src/entities.rs` | 4,663 | Entity store and JSON entity loading (`Entities::from_json_value`, used by START's `cedar_eval.rs`). |
| `cedar-policy-core/src/ast/policy.rs` | 2,624 | Policy AST types (permit/forbid, conditions, templates). |
| `cedar-policy-core/src/ast/expr.rs` | 2,616 | Expression AST — the expression language is the engine. |
| `cedar-policy-core/src/validator/typecheck.rs` | 2,522 | Policy typechecker against a schema. |
| `cedar-policy-core/src/authorizer.rs` | 708 | Authorizer orchestration (permit/forbid resolution, default-deny). Smallest engine-level file, but only works on top of the AST/evaluator/entities. |
| `cedar-policy-formatter/src/pprint/doc.rs` | 1,097 | Policy pretty-printer core. Smallest plausible borrow — but it depends on `cedar-policy-core` and only formats Cedar text, which START authors by hand. |
| `cedar-policy-symcc/src/` (crate total) | 19,614 | Symbolic compiler for policy analysis. Requires an external cvc5 1.3.1 SMT solver binary (not a cargo dependency). |
| `cedar-policy-cli/src/` (crate total) | 4,308 | CLI wrapper (`authorize`, `link`, `partial-eval`, `run-test`). A dev tool, not a library piece. |
| `cedar-language-server/` (crate total) | 17,443 | Language server for editors. Not relevant to START. |

How it actually works, in our own words: Cedar is a policy
language plus an authorizer. Policies are written in Cedar text
(`permit`/`forbid` with conditions on principals, actions and
resources), parsed through a LALRPOP grammar into a concrete syntax
tree, converted to an AST, optionally validated against a schema
(types of entities and actions), and then evaluated: for a given
request (principal, action, resource, context) and entity store,
the authorizer collects applicable policies, applies
forbid-wins-then-default-deny, and returns Allow or Deny. Entities
and policies can also be loaded from JSON (EST for policies,
JSON entities). The validator/schema machinery is 52,425 lines on
its own — far beyond what START uses (3 policies, no schema).

Already used by the spine: `cedar-policy = "4"` in
`rust/Cargo.toml`, `policies.cedar` (planner may plan only synthetic
plans; forbid Publish/Execute unless verified AND human-approved;
permit Publish/Execute when both hold), evaluated by
`rust/src/cedar_eval.rs`, 4/4 Rust tests. The spine already caught
one Cedar bug in this setup: a missing `permit` meant default-deny
blocked even verified+approved publishes.

Dependencies dragged in (from the workspace `Cargo.toml` files):
`serde`, `serde_json`, `serde_with`, `lalrpop-util`, `either`,
`itertools`, `ref-cast`, `rustc-literal-escaper`, `thiserror`,
`smol_str`, `stacker`, `miette`, `nonempty`, `educe`,
`unicode-security`, `regex`, `linked-hash-map`, `linked_hash_set`,
`chrono` (optional, datetime extension); `cedar-policy` adds
`semver` and optional `prost`; the formatter adds `pretty` and
`logos`; symcc adds `tokio`, `num-bigint` and the external cvc5
binary. No LLM APIs, no GPU, no external network services at
runtime for the core/policy crates. The workspace forbids unsafe
code — the coordinator re-checked: the only "unsafe" strings in
`cedar-policy-core/src/` are error-variant names
(`unsafe_attribute_access`, `unsafe_tag_access`), not unsafe blocks.
MSRV is Rust 1.89.

## 3. egg — file inventory and how it works

Top-level layout: `src/` (library), `tests/`, `tutorials/`,
`doc/`. HEAD audited: `73975c9` (egg 0.11.0); the spine pins
0.10.0 (9,551 src lines) — 0.11.0 is 10,721 src lines, edition
2024, Rust 1.94 toolchain, and replaces `coin_cbc` with `good_lp`
for the LP feature, so upgrading is not a drop-in.

Most important files for START:

| File | Lines | What it does |
|---|---|---|
| `src/egraph.rs` | 1,511 | EGraph core: add/union/rebuild, congruence closure, memo, `classes_by_op`, explanation hooks. Interdependent with Language, Analysis, EClass, UnionFind, Explain. |
| `src/language.rs` | 1,000 | `Language` trait, `RecExpr`, `define_language!` support, and the `Analysis` trait (per-eclass `Data` with make/remake/merge/pre_union hooks). Analysis is the only place numeric per-class data could live — and egg supplies no numeric analysis. |
| `src/run.rs` | 995 | `Runner`: the equality-saturation loop — saturation/iteration/node/time limits, `BackoffScheduler`, iteration reporting. |
| `src/rewrite.rs` | 702 | `Rewrite`/`Searcher`/`Applier` types and the `rewrite!` macro; validates that applier variables are bound by the searcher, but trusts the rule itself — a wrong rule silently equates non-equivalent terms. |
| `src/pattern.rs` | 536 | Pattern as Searcher/Applier, `FromStr` parsing of s-expressions; coupled to `machine.rs` and `subst.rs`. |
| `src/lp_extract.rs` | 466 | Optional `lp` feature: `LpExtractor` via `good_lp` ILP, optimises DAG extraction cost (shared sub-expressions counted once). Does not check plan feasibility under land/water constraints; needs a separate solver backend (e.g. CBC/HiGHS). |
| `src/machine.rs` | 345 | Compiled pattern-matching VM (Bind/Compare/Lookup/Scan instructions); internal to pattern search. |
| `src/extract.rs` | 333 | `Extractor` and `CostFunction` trait; built-ins are only `AstSize` and `AstDepth` (syntactic size/depth), not plan cost, shortage, or feasibility. |
| `src/explain.rs` | 1,961 | Largest module: proof/explanation generation for equivalences (`Explanation`/`Justification`/`TreeExplanation`). Useful for auditability in principle; 1,961 lines START does not need for a rewrite demo. |
| `src/macros.rs` | 465 | `define_language!` and `rewrite!` macros; only meaningful with the Language/Rewrite types. |
| `src/eclass.rs` | 115 | EClass struct: id, nodes, data, parents, small iterators. Trivial. |
| `src/unionfind.rs` | 93 | Union-find (make_set/find/find_mut/union, no rank/size heuristic — union always makes root1 the leader). Trivial. |

How it actually works, in our own words: egg implements
equality saturation. You define a language (an enum of operators,
via `define_language!`), add terms to an e-graph (a set of
e-classes, each holding equivalent terms), and run a `Runner` that
repeatedly applies rewrite rules (pattern → replacement) until
saturation or a node/iteration/time limit. Congruence closure keeps
equivalent terms in the same e-class. An optional `Analysis`
attaches per-eclass data (computed on `make`, merged on `merge`).
Finally an `Extractor` with a `CostFunction` picks the cheapest
term from each e-class — or `LpExtractor` picks the cheapest DAG
via an ILP solver. The key point for START: **egg rewrites
symbolic terms; it has no native numeric constraints, interval or
feasibility reasoning, and no shortage/cost model.** `Analysis`
and `CostFunction` are user-supplied hooks that START would have
to design and prove sound itself, and `AstSize`/`AstDepth` measure
syntax, not plan quality.

Already used by the spine: `rust/src/egg_demo.rs` — a demo only
(`define_language! Math`, 3 rules: add-zero, mul-one, mul-zero,
`Runner` saturation, `Extractor` with `AstSize`), with no Analysis,
no LP, and no planning semantics. 2/2 Rust tests.

Dependencies dragged in: already a dependency in the spine (egg
0.10.0 in `rust/Cargo.lock`: `env_logger`, `hashbrown` 0.15.5,
`indexmap` 2.14.2, `log`, `num-bigint`, `num-traits`, `quanta`,
`rustc-hash`, `saturating`, `smallvec`, `symbol_table`,
`symbolic_expressions`, `thiserror` 1.0.69). At HEAD (0.11.0):
mandatory `hashbrown`, `indexmap`, `log`, `num-bigint`,
`num-traits`, `rustc-hash`, `smallvec`, `spin`, `symbol_table`
(a **git** dependency, rev
`a716c39a4aa4757c910c93fc10c5c7fa8f467133`, not crates.io),
`thiserror` 2; default features add `env_logger` and
`symbolic_expressions`; optional `serde`/`serde_json` behind
`serde-1`, `good_lp` behind `lp` (solver backend such as CBC/HiGHS
not bundled).

## 4. Cognee — file inventory and how it works

Top-level layout: `cognee/` (the package — 1,700 non-test files),
plus `cognee-mcp/`, `cognee-connectors/`, `cognee-frontend/`,
`cognee_db_workers/`, `examples/`, `tests/`. HEAD audited:
`8853378` (cognee 1.6.7). This is an application, not a library:
a FastAPI server, multi-user auth, cloud/Slack/Gmail integrations,
an MCP server, a frontend, and an evaluation framework.

Most important files for START:

| File | Lines | What it does |
|---|---|---|
| `cognee/api/v1/cognify/cognify.py` | 813 | Top-level `cognify()` entrypoint: two pipeline runs per dataset (indexing, then graph extraction); docstring requires `LLM_API_KEY` on the default LLM extractor, plus a vector DB and a graph DB. |
| `cognee/modules/cognify/memory_pipelines.py` | 392 | Indexing pipeline (classify/chunk/embed, no LLM) followed by the cognify pipeline (LLM entity/relationship extraction, summarise, write graph), with per-item rollback. The two-stage *shape* is a useful design pattern to rewrite originally, not code to copy. |
| `cognee/modules/cognify/config.py` | 315 | Extractor resolution: auto picks `llm` when an LLM key is configured, else `gliner_demo`; `gliner_auto_install` defaults true, so a keyless run silently installs gliner2 + CPU torch at runtime, and the demo is explicitly a demo of an enterprise GLiNER extractor. |
| `cognee/infrastructure/llm/config.py` | 504 | `LLMConfig` defaults: OpenAI provider, model `openai/gpt-5.6-luna`. Known providers: openai, ollama, anthropic, custom, gemini, mistral, azure, bedrock, llama_cpp, mcp-sampling; only ollama/llama_cpp (and `lm_studio/` prefix) count as local. |
| `cognee/infrastructure/llm/LLMGateway.py` | 236 | Single choke point for structured LLM output via litellm (default `litellm_native`, instructor/BAML opt-ins), with session usage tracking and quota/budget errors. The gateway *pattern* is sound but wired to Cognee config/session code — a thin original wrapper is better than copying. |
| `cognee/modules/graph/cognee_graph/CogneeGraph.py` | 535 | In-memory graph object over Cognee's own node/edge models; tied to its storage backends (default local ladybug graph DB, plus kuzu/neo4j/postgres/turso) and its pydantic `DataPoint` model. |
| `cognee/infrastructure/databases/vector/vector_db_interface.py` | 506 | Vector-store interface; only meaningful with a backend (default LanceDB local file, plus pgvector and Turso). |
| `cognee/infrastructure/databases/vector/embeddings/FastembedEmbeddingEngine.py` | 397 | Local CPU embedding engine (fastembed, default fallback `BAAI/bge-small-en-v1.5` when no LLM key); usable only as the fastembed dependency, not as copied code. |
| `cognee/modules/retrieval/graph_completion_retriever.py` | 572 | `GRAPH_COMPLETION` retriever: resolves graph triplets to text and feeds them to an LLM completion (21 `SearchType` values incl. RAG/HYBRID/GRAPH_COMPLETION/CYPHER/NATURAL_LANGUAGE). Retrieved LLM-extracted text is presented as context for an LLM answer with no verification gate. |
| `cognee/modules/retrieval/bm25_retriever.py` | 103 | Lexical BM25 retrieval over chunks; BM25 is a standard algorithm and the file is tied to Cognee's retriever base — rewrite originally. |
| `cognee/modules/provenance/manager.py` | 708 | `ProvenanceManager` tracks entity/relationship/chunk lineage, checksums and revision history. That is integrity (was this record tampered with / where did it come from), **not** verification that a retrieved claim is true — it must not be mistaken for a verification layer. |
| `cognee/tasks/chunks/chunk_by_word.py` | 87 | **COPY** — stdlib-only (`re`, `collections.abc`) sentence/paragraph boundary helpers; no Cognee imports, no LLM/vector coupling. |
| `cognee/tasks/chunks/chunk_by_paragraph.py` | 97 | REWRITE ORIGINAL — paragraph chunking with exact reconstruction, but it delegates to `chunk_by_sentence.py`, which imports Cognee's embedding engine for token sizing, so it is not self-contained as written. |
| `cognee/modules/chunking/chunk_id.py` | 22 | **COPY** — stdlib-only (`hashlib`, `uuid`) content-derived chunk identity: sha256 of text plus occurrence counter, so ids survive edits that shift positions and re-ingest is idempotent. |
| `cognee/modules/graph/models/Node.py` | 64 | REWRITE ORIGINAL — SQLAlchemy relational Node model (dataset/user/slug, JSON attributes) tied to Cognee's relational Base; START needs its own node model. |

How it actually works, in our own words: `cognify()` runs two
pipelines per dataset. First, indexing: classify, chunk, embed,
store vectors. Then graph extraction: an LLM extracts entities
and relationships from the chunks, summarises them, and writes
them into a graph store (default the embedded ladybug graph DB,
plus vector store LanceDB). Retrieval then resolves graph triplets
or chunks to text and feeds them to an LLM to complete an answer.
The triage claim — Cognee needs LLM APIs / vector stores — is
verified **with nuance**: the real (non-demo) behaviour needs a
paid external LLM (default OpenAI `gpt-5.6-luna`) and external
embeddings (`text-embedding-3-large`), but local defaults exist
(LanceDB + ladybug files, fastembed, Ollama/llama.cpp) in a
degraded demo mode. The production-grade local GLiNER extractor
is enterprise-licensed; the open-source path is explicitly a demo
with lower accuracy/coverage, and a keyless run silently
auto-installs gliner2 + torch.

Dependencies dragged in (core `pyproject.toml`, cognee 1.6.7):
`openai`, `litellm`, `pydantic`/`pydantic-settings`,
`sqlalchemy`+`aiosqlite`, `lancedb`+`pylance` (default vector
store), `ladybug` (default graph DB, pinned 0.19.0, custom embedded
DB), `fastembed`+`onnxruntime` (local CPU embeddings), `rdflib`,
`networkx`, `fastapi`+`uvicorn`+`gunicorn`, `dlt`+`pandas`,
`enola-cli` (code graph), `tiktoken`, `cryptography`, `alembic`,
`fakeredis`, `langdetect`, `dateparser`. Optional extras: neo4j,
postgres/pgvector, turso, ollama/anthropic/mistral/groq/azure/
bedrock, langchain, llama-index, unstructured/docling,
gliner2+torch (GLiNER extra), playwright/tavily scraping, redis,
deepeval, posthog, Gmail/Drive/Calendar Google APIs. No GPU
required by default, but torch is pulled in by the GLiNER path.

## 5. Graphiti — file inventory and how it works

Top-level layout: `graphiti_core/` (the library — 166 files),
plus `server/`, `mcp_server/`, `tests/`, `examples/`. HEAD
audited: `ebef986a0b2360211b65751c111cacb4a7d790eb`. The library
is the temporal knowledge graph; the server/MCP layers were not
counted.

Most important files for START:

| File | Lines | What it does |
|---|---|---|
| `graphiti_core/graphiti.py` | 2,251 | `Graphiti` orchestrator: defaults are `Neo4jDriver` + `OpenAIClient` + `OpenAIEmbedder` when no clients are passed; `add_episode` runs LLM node/edge extraction, dedup and resolution throughout. |
| `graphiti_core/nodes.py` | 1,166 | `EpisodicNode` (source/content/`valid_at`), `EntityNode`, `CommunityNode`, `SagaNode`. REWRITE ORIGINAL — the schema is the useful model, but every save/get method is Cypher + `GraphDriver` provider branches + embedder. |
| `graphiti_core/edges.py` | 1,051 | `EntityEdge` temporal fields (`fact`, `valid_at`, `invalid_at`, `expired_at`, `reference_time`, `attributes`, `episodes`). REWRITE ORIGINAL — the fields are the smallest useful borrowed unit, but the file is coupled to `GraphDriver`/Cypher/embedder (`generate_embedding`, `load_fact_embedding`, `save`). |
| `graphiti_core/driver/` (whole subtree) | 15,724 | 4 backends (Neo4j, FalkorDB, Kuzu, Neptune, each with ~11 per-operation files). Neo4j is the default and a mandatory dependency; Kuzu (the only embedded/local option) is deprecated and slated for removal; Neptune is AWS. DEFER. |
| `graphiti_core/llm_client/` (whole dir) | 4,482 | LLM abstraction plus OpenAI (default), Anthropic, Gemini, Groq, Azure, GLiNER2 (local CPU NER only) and Jev clients. Extraction, dedup and resolution all go through an LLM; there is no no-LLM ingestion path in the code. DEFER. |
| `graphiti_core/search/search.py` + `search/search_utils.py` | 2,966 | Hybrid search (fulltext + vector similarity + BFS + RRF/MMR + cross-encoder reranking). Needs a graph DB, an embedder and a reranker; returns LLM-extracted facts as search results with no verified/unverified distinction. DEFER. |
| `graphiti_core/prompts/extract_nodes.py` + `prompts/extract_edges.py` | 1,078 | LLM prompt templates for extracting nodes/edges/facts from episodes; extraction quality (and therefore every temporal bound) depends entirely on the LLM, with no independent check in the code. DEFER. |
| `graphiti_core/utils/maintenance/edge_operations.py` + `node_operations.py` + `combined_extraction.py` | 2,853 | LLM-driven dedup, resolution, invalidation (`expired_at`) and bulk extraction (17 + 22 `llm_client` references in edge/node operations). Invalidation is decided by the LLM, not by a verifier. DEFER. |
| `graphiti_core/utils/maintenance/temporal_edge_utils.py` | 96 | `normalize_future_temporal_bounds` + `apply_extracted_timestamps`: the one genuinely separable temporal idea (future-tense facts use episode reference time as `valid_at`; soft deadlines are not `invalid_at`). REWRITE ORIGINAL — it imports `EntityEdge` and is regex heuristics over LLM-extracted fact text; reimplement as a plain function over START's own edge dicts. |
| `graphiti_core/utils/datetime_utils.py` | 60 | Trivial `utc_now`/`ensure_utc`/`convert_datetimes_to_strings` helpers. REWRITE ORIGINAL — a few lines if needed. |
| `graphiti_core/telemetry/telemetry.py` | 117 | PostHog telemetry, **enabled by default** (`GRAPHITI_TELEMETRY_ENABLED` defaults to true), writes an anonymous id to `~/.cache/graphiti` and phones home to `us.i.posthog.com`. Incompatible with local-first / privacy-by-design. DEFER. |

How it actually works, in our own words: an episode (a chunk of
text with a timestamp) is added; an LLM extracts entity nodes and
fact edges from it, with temporal bounds (`valid_at`,
`invalid_at`, `expired_at`) also LLM-extracted; the nodes/edges
are stored in a graph database (Neo4j by default) with embeddings;
later episodes trigger LLM-driven dedup, resolution and
invalidation of older edges. Search is hybrid (fulltext + vector +
graph traversal + reranking) over those LLM-extracted facts. The
temporal model is the right *shape* for agent memory — episodes
with validity windows — but in Graphiti every temporal bound is
LLM-extracted text processed by regex heuristics, stored as graph
truth, and invalidated by the LLM, with no verification step
anywhere.

Dependencies dragged in (mandatory, `pyproject.toml`):
`pydantic>=2.11.5`, `neo4j>=5.26.0`, `openai>=1.91.0`, `tenacity`,
`numpy`, `python-dotenv`, `posthog`, `certifi`. Optional extras:
`anthropic`, `groq`, `google-genai` (Gemini), `voyageai`,
`gliner2` (local CPU NER), `kuzu` (deprecated/unmaintained
upstream), `falkordb`/`falkordblite`, `boto3` + `opensearch-py` +
`langchain-aws` (Neptune/AWS), `sentence-transformers`,
`opentelemetry`. External/paid services required in the default
configuration: a Neo4j (or FalkorDB/Neptune) graph-DB server plus
OpenAI LLM + embedding APIs; no GPU required. Local-only paths
are marginal: Kuzu deprecated, FalkorDBLite embedded only, GLiNER2
covers NER only while edge extraction still needs an LLM.

## 6. Crawl4AI — file inventory and how it works

Top-level layout: `crawl4ai/` (the package — 80 files, v0.9.5),
plus `tests/` (243 files, 58,909 lines, not counted), `docs/`,
`deploy/`, `scripts/`, `examples/`, `crawl4ai/cloud/`. HEAD
audited: `cae74b203a33994f7e13b9052c3b0d5c93daa0e6`.

Most important files for START:

| File | Lines | What it does |
|---|---|---|
| `crawl4ai/utils.py` | 3,786 | God-module: `RobotsParser`, `normalize_url`, `sanitize_html`, LLM completion helpers, embeddings, metadata extraction — all in one file. Module-level imports bs4, lxml, httpx, numpy, requests, xxhash and (via prompts/config) litellm. Only `normalize_url` is stdlib-only and extractable; copying the file is not viable. DEFER (except `normalize_url`, COPY). |
| `crawl4ai/async_webcrawler.py` | 1,262 | Crawler entry point (`AsyncWebCrawler.arun`); wires robots.txt check (**off by default**, `check_robots_txt=False`), browser, dispatcher, cache and extraction together. Inseparable from the Playwright browser stack. DEPENDENCY ONLY. |
| `crawl4ai/async_crawler_strategy.py` | 2,903 | Playwright page-driving core (navigation, JS execution, screenshots, sessions, hooks). Entirely browser-bound. DEPENDENCY ONLY. |
| `crawl4ai/browser_manager.py` | 2,147 | Browser lifecycle for chromium/firefox/webkit via Playwright + Patchright, incl. stealth and system-browser paths. Requires downloaded browser binaries (`crawl4ai-setup` runs `playwright install --with-deps chromium`, and the same for patchright). DEPENDENCY ONLY. |
| `crawl4ai/async_url_seeder.py` | 1,799 | URL discovery from sitemaps, Common Crawl, Certificate Transparency, path probing and robots.txt mining (default sources `sitemap+cc+crt+probe`). Depends on external services and the crawler's HTTP stack. DEPENDENCY ONLY. |
| `crawl4ai/extraction_strategy.py` | 2,827 | `LLMExtractionStrategy` (default provider `openai/gpt-4o`, API key required, calls litellm with backoff) is the headline extractor; `JsonCss`/`JsonXPath`/`JsonLxml`/`Regex` strategies are LLM-free but embedded in this 2,827-line file with heavy imports (numpy, lxml, model_loader/torch embedding helpers). LLM part: DEFER. CSS/XPath part: only via the package as a dependency, not by copying. |
| `crawl4ai/content_filter_strategy.py` | 1,138 | `PruningContentFilter` and `BM25ContentFilter` are LLM-free (link/text-density pruning, BM25 ranking) and conceptually small, but the module imports `rank_bm25`, `snowballstemmer` and `utils` (litellm, bs4). `LLMContentFilter` is a separate LLM-dependent class in the same file. REWRITE ORIGINAL — the pruning/BM25 idea, not the file. |
| `crawl4ai/markdown_generation_strategy.py` | 260 | `DefaultMarkdownGenerator` converts cleaned HTML to Markdown with link-to-citation rewriting, but depends on the vendored html2text fork (2,045 lines) and `RelevantContentFilter`. The idea is small; REWRITE ORIGINAL against upstream html2text or stdlib `html.parser`. |
| `crawl4ai/html2text/__init__.py` | 1,215 | Vendored fork of html2text (whole `html2text/` dir is 2,045 lines incl. `config.py`, `elements.py`, `utils.py`). Do not copy the fork; if HTML-to-Markdown is needed, depend on the upstream html2text PyPI package. DEPENDENCY ONLY. |
| `crawl4ai/chunking_strategy.py` | 255 | `RegexChunking`, `FixedLengthWordChunking`, `SlidingWindowChunking`, `OverlappingWindowChunking` are each ~20–40 lines of trivial `re`/`str.split` logic; `NlpSentenceChunking` needs NLTK punkt downloaded at runtime via `model_loader`. REWRITE ORIGINAL. |
| `crawl4ai/async_dispatcher.py` | 788 | Concurrency + per-domain `RateLimiter` (base delay 1–3 s, exponential backoff on 429/503, max 60 s). The `RateLimiter` pattern itself is ~60 lines of stdlib and could be rewritten, but the dispatcher is woven into the crawler. DEPENDENCY ONLY. |
| `crawl4ai/deep_crawling/filters.py` | 697 | `URLPatternFilter`/`DomainFilter`/`FilterChain` are simple fnmatch/regex URL allow/deny lists, but the module top-level imports `HeadPeekr` from the `utils.py` god-module (used only by `ContentRelevanceFilter`/`SEOFilter`), so it is not separable as-is. REWRITE ORIGINAL (~100 original lines). |
| `crawl4ai/models.py` | 415 | Pydantic `CrawlResult`/`MarkdownGenerationResult` models are JSON-serialisable, but carry **no licence or provenance fields** (grep: no `licen` or `provenance` in the file) and no `needs_human_decision` flag. START must define its own result wrapper with provenance + `needs_human_decision=true` rather than adopt these models. REWRITE ORIGINAL. |

The one cleanly copyable piece: `normalize_url()` in
`crawl4ai/utils.py` (lines 2259–2358), a ~100-line stdlib-only
(`urllib.parse`) URL canonicaliser — resolves relative links,
lowercases netloc, strips utm/gclid/fbclid tracking params, sorts
query keys — extractable as a single function with the Apache-2.0
notice. Nothing else is cleanly separable: every other candidate
lives in or imports the 3,786-line `utils.py` god-module or the
browser/LLM stack.

How it actually works, in our own words: `AsyncWebCrawler.arun`
takes a URL, checks robots.txt (only if enabled), drives a
Playwright browser (Chromium by default, via Patchright, with
stealth options), extracts the page, converts cleaned HTML to
Markdown (vendored html2text fork), optionally filters content
(pruning, BM25, or LLM) and extracts structured data (CSS/XPath
selectors or an LLM), and returns a pydantic `CrawlResult`. A
dispatcher handles concurrency and per-domain rate limiting; a
seeder discovers URLs from sitemaps, Common Crawl and Certificate
Transparency. The crawler is a real, working fetch-and-convert
pipeline — but it is a browser pipeline, not a library of small
helpers, and its governance surface is thin: robots.txt off by
default, no licence/provenance tracking, LLM extraction defaulting
to a paid external API.

Dependencies dragged in (core `pyproject.toml`, 33 deps):
`playwright>=1.49` + `patchright>=1.49` + `playwright-stealth`
(downloads Chromium binaries via `crawl4ai-setup`, plus OS deps),
`unclecode-litellm==1.81.13` (LLM API keys; default provider
`openai/gpt-4o`, empty default key), `aiohttp`, `httpx`,
`beautifulsoup4`, `lxml`, `numpy`, `nltk` (downloads punkt model
at runtime), `rank-bm25`, `snowballstemmer`, `pydantic`,
`aiosqlite`, `pillow`, `shapely`/`alphashape`, `fake-useragent`,
`chardet`, `brotli`. Optional: `torch` + `transformers` +
`sentence-transformers` (cosine/transformer extraction), `pypdf`
(PDF), `selenium` (sync mode). `crawl4ai/cloud/` adds a hosted
Crawl4AI Cloud service (httpx client, API-key auth, profile
upload). No browser, no crawl without the Playwright/Chromium
install.

## 7. Borrowable vs dependency vs rewrite

| Repo | Piece | Recommendation | Reason |
|---|---|---|---|
| Cedar | Everything (`cedar-policy-core` 132,535 lines, `api.rs`, evaluator, parser, validator, EST, entities) | **Dependency only** | The engine is one coupled unit (AST + LALRPOP grammar + schema + evaluator); even the smallest candidate, the formatter (2,205 lines), depends on `cedar-policy-core`. The spine already uses it correctly as a dependency. |
| Cedar | `cedar-policy-symcc` (19,614 lines) | **Dependency only — do not adopt** | Needs an external cvc5 1.3.1 binary and tokio; START has no demonstrated need for SMT policy analysis. |
| Cedar | `cedar-policy-cli` (4,308 lines) | **Dependency only — do not adopt** | A dev tool, not a library piece. |
| egg | E-graph core (`egraph.rs`, `language.rs`, `rewrite.rs`, `run.rs`, `extract.rs`, `lp_extract.rs`, `explain.rs`, `machine.rs`, `pattern.rs`) | **Dependency only** | Interdependent; cannot be copied piecemeal. The spine already uses it as a dependency (demo only). |
| egg | `UnionFind` (93 lines), `EClass` (115 lines) | **Rewrite original** | Trivial structs; cheaper to rewrite than to copy, and no standalone value without the core. |
| egg | A numeric `Analysis` / `CostFunction` for plans | **Rewrite original** | egg supplies no numeric analysis; START would have to design and prove sound any per-eclass land/water/shortage bounds itself. |
| Cognee | `chunk_by_word.py` (87 lines) | **Copy** | Stdlib-only sentence/paragraph boundary helpers; no Cognee imports, no LLM/vector coupling. Smallest genuinely copyable unit in Cognee. |
| Cognee | `chunk_id.py` (22 lines) | **Copy** | Stdlib-only content-derived chunk identity (sha256 + occurrence counter); re-ingest is idempotent. |
| Cognee | `LLMGateway.py` pattern, `bm25_retriever.py`, `Node.py` schema | **Rewrite original** | The patterns are sound; the files are wired to Cognee config/session/retriever bases. |
| Cognee | `cognify.py`, `memory_pipelines.py`, `config.py`, `LLMConfig`, `CogneeGraph.py`, `graph_completion_retriever.py`, `ProvenanceManager` | **Defer** | The system is a 248k-line application with a paid-LLM default, bespoke embedded stores, and no verification gate. The two-stage pipeline *shape* is a design pattern to rewrite, not code to copy. |
| Graphiti | Temporal-edge/episode field schema (`EntityEdge` fields, `EpisodicNode.valid_at`) | **Rewrite original** | The ~10-field schema (`fact`, `valid_at`, `invalid_at`, `expired_at`, `reference_time`, `attributes`, `episodes`) is the useful model; the files are Pydantic models whose save/load methods embed Cypher, driver branches and embedder calls. |
| Graphiti | `temporal_edge_utils.py` (96 lines) | **Rewrite original** | The future-tense bound-normalisation idea is separable in concept, but the file imports `EntityEdge` and is regex heuristics over LLM text; reimplement as a plain function over START's own edge dicts. |
| Graphiti | `graphiti.py`, drivers (15,724 lines), `llm_client/` (4,482), search (2,966), prompts (1,078), maintenance ops (2,853), telemetry (117) | **Defer** | Default is Neo4j server + OpenAI LLM + embeddings; only embedded backend (Kuzu) is deprecated; telemetry phones home by default. |
| Crawl4AI | `normalize_url()` (~100 lines, `utils.py` 2259–2358) | **Copy** | Stdlib-only (`urllib.parse`) URL canonicaliser; extractable as a single function with the Apache-2.0 notice. |
| Crawl4AI | Chunking strategies, content filters (pruning/BM25), deep-crawl URL filters, markdown generator idea, `RateLimiter` pattern, `CrawlResult` wrapper | **Rewrite original** | Each idea is small and stdlib-level, but every file is coupled to the `utils.py` god-module, the browser stack, or litellm. Rewrite the ideas; do not copy the files. |
| Crawl4AI | Crawler core (`async_webcrawler.py`, `async_crawler_strategy.py`, `browser_manager.py`, `async_dispatcher.py`, `async_url_seeder.py`, vendored html2text fork) | **Dependency only** | Browser-bound; use the package if crawling is wanted at all. The vendored html2text fork should be replaced by the upstream PyPI package, not copied. |
| Crawl4AI | `LLMExtractionStrategy` (default `openai/gpt-4o`) | **Defer** | Paid external API dependency conflicts with local-first. |

## 8. Fit to START

**Cedar — what START would gain:** nothing beyond what it
already has as a dependency. START already uses the real Cedar
engine for governance, and the spine tests prove the
no-bypass property (publish denied unless verified AND
human-approved). The smallest useful borrowed unit is therefore
none: keep it a dependency. What must be generalised or stripped:
nothing — but the trust boundary must be guarded on START's side.
Cedar authorizes; it does not verify plans. The `verified` and
`human_approved` attributes are inputs supplied by START, and plan
verification stays separate (the JuMP+HiGHS LP cross-check and
`verify.jl` in Julia). Cedar must never be fed entity attributes
constructed by the planner itself, or a planner could self-certify.
A Cedar Allow is a permit decision, not a verification verdict,
and human approval remains a required input attribute, not
something Cedar grants. Policies themselves are Cedar text, not
JSON; entities and results are JSON, so the wire format is intact.

**egg — what START would gain:** a real, tested equality-saturation
engine for symbolic rewriting, usable as an in-process Rust kernel.
The smallest useful borrowed unit is none for the core — keep it a
dependency — and the two trivial structs are cheaper rewritten.
What must be generalised or stripped: everything numeric. START's
constraints are numeric (land, water, delivered/shortage tonnes)
while egg rewrites symbolic terms; it has no native numeric
constraints, interval/feasibility reasoning, or shortage/cost model.
A rewritten plan stays a candidate that must still pass the
separate verify step and the LP cross-check plus human approval, so
egg need not collapse Planning/Verification — egg itself never
certifies anything. JSON wire format and `needs_human_decision`
are unaffected (egg is internal Rust; s-expression/`RecExpr`
internally, no JSON wire format of its own; serde is optional).
Realistic use is narrow: symbolic simplification/normalisation of
plan expressions (constant folding, algebraic identities) *before*
the real numeric solver/verify steps, not solving the allocation.
The fit for the actual planning problem is **weak** — that is a
finding, not a failure of the audit.

**Cognee — what START would gain:** in subject matter, a memory /
retrieval / knowledge-graph layer; in practice, an application
START cannot absorb. The smallest useful borrowed unit is the two
chunking helpers (109 lines together). What must be generalised or
stripped: the whole system. Its retrieval layer collapses
Evaluation/Verification into retrieval: `GRAPH_COMPLETION` and
similar search types feed LLM-extracted triplets/chunks straight
into LLM-generated answers, with **no `needs_human_decision` flag
anywhere in the non-test code** (grep: zero hits, re-checked by the
coordinator) and no verified/unverified distinction on retrieved
facts — provenance checksums track lineage, not truth. Wire format
is pydantic `DataPoint`/SQLAlchemy models, not START's JSON wire
format, and there is no human-approval gate on generated plans or
answers. The default path is a paid external LLM plus external
embeddings; the local path is a degraded demo whose production
extractor is enterprise-licensed. Defer the system; copy the two
helpers if chunking is needed.

**Graphiti — what START would gain:** in concept, the right shape
for agent memory (temporal episodes + fact edges with validity
windows); in practice, a system that breaks the local-first design.
The smallest useful borrowed unit is the temporal schema, as an
original rewrite — not a copy. What must be generalised or
stripped: the LLM extraction, the graph-DB server, and the
telemetry. It collapses Evaluation/Verification into retrieval:
LLM-extracted facts become graph edges with `valid_at`/`invalid_at`
windows, there is **no verified flag and no `needs_human_decision`
anywhere in `graphiti_core`** (grep: zero hits, re-checked by the
coordinator), so a retrieved episode/edge or a validity window
could be treated as a verified fact or planning constraint with no
separate check. Pydantic models serialise to JSON, but there is no
JSON wire-format contract and no `needs_human_decision` concept,
so both would have to be added by START, not inherited. Defer the
system; rewrite the schema if temporal memory is built.

**Crawl4AI — what START would gain:** a real fetch-and-convert
pipeline for web data integration (Module 7), usable as a
dependency for the fetch step only. The smallest useful borrowed
unit is `normalize_url` (~100 lines). What must be generalised or
stripped: the governance surface. Crawled web content is untrusted
input and Crawl4AI provides no help here — `CrawlResult` has no
licence or provenance fields, robots.txt checking defaults to OFF
(`check_robots_txt=False`), and there is no per-source licence
verification, so every crawled item must enter START as unverified
data with START-added provenance (source URL, fetch time, licence
check) and must pass START's ideal-domains-only + per-source
licence rules before any use. JSON wire format is preserved
(pydantic models serialise to JSON) but `needs_human_decision` is
absent — START must wrap results and set it itself. Nothing in
Crawl4AI may certify a plan or mark data verified, so the
Planning/Verification/Governance boundary is intact only if START
treats all crawler output as unverified input. The browser weight
(full Chromium download) and the fingerprint-spoofing stealth
surface (`navigator_overrider.js`, consent-popup removers,
fake-useragent) are things START does not need and should not
inherit; the hosted Crawl4AI Cloud module must be excluded from
any use.

## 9. Risks

- **Cedar — self-certification hazard:** Cedar trusts the entity
  attributes it is given. If planner code ever constructs the Plan
  entity, `verified=true` becomes planner-asserted. Entity
  construction must stay in the governance/verifier side, isolated
  from the planner. Default-deny plus forbid-wins semantics are
  subtle: the spine already caught one bug where a missing permit
  denied even verified+approved publish. Any policy edit needs the
  existing Rust tests re-run. Version skew: spine uses registry
  4.14.1, audited workspace is 4.14.0; pin and re-check on upgrade.
  `cedar-policy-symcc` silently changes the deployment story
  (external cvc5 binary, tokio runtime) — it must stay out of START
  unless SMT analysis is explicitly approved later. The
  validator/schema machinery (52,425 lines) is far beyond START's
  needs.
- **Cedar — scale mismatch:** 233,228 lines to gate 3 policies.
  The dependency is justified only as an opaque, audited engine,
  never as code to read or fork.
- **egg — soundness is the user's responsibility:** egg trusts
  rewrite rules; an incorrect rule silently merges non-equivalent
  plans, and `EGraph::union_trusted` (egraph.rs:1128) allows
  asserting equality with only a string reason. Saturation can
  blow up / not terminate without node/iteration/time limits, which
  the `Runner` defaults must set deliberately. Nothing in egg
  prevents a rewrite that is algebraically valid but violates
  land/water/shortage feasibility — that check lives entirely in
  START's separate verify step, which must never be skipped for a
  rewritten candidate. Extraction cost pitfalls: `CostFunction`
  only requires `PartialOrd`, and the docs warn NaN costs panic
  and `AstSize` can overflow `usize` on shared sub-expressions; a
  START cost function must use saturating arithmetic. Serde
  round-trip hazard: the docs state `EGraph::rebuild` must be
  called after deserialising an e-graph; a stale deserialised graph
  is not safe to read. Version drift: spine pins 0.10.0 while HEAD
  is 0.11.0 (edition 2024, Rust 1.94, `good_lp` replacing
  `coin_cbc`, a git dependency on `symbol_table`) — upgrading is
  not a drop-in.
- **Cognee — LLM-extracted "facts":** LLM-extracted entities and
  relationships are stored as the knowledge graph and then fed back
  to an LLM as answer context, so an extraction error becomes a
  retrieved "fact" with no verification step and no
  `needs_human_decision` gate. Default path depends on a paid
  external LLM (OpenAI `gpt-5.6-luna`) and external embeddings; a
  keyless install silently auto-installs gliner2 + torch at runtime
  (`gliner_auto_install=true`). Absorbing it would import an
  application, not a module, and would collapse
  Planning/Evaluation/Verification/Governance/Execution boundaries.
  Storage defaults are bespoke embedded engines (ladybug graph DB,
  LanceDB vector store) with their own on-disk formats and
  migration code, not plain JSON/SQLite that START controls.
- **Graphiti — LLM-extracted temporal truth:** LLM-extracted facts
  (including `valid_at`/`invalid_at`) become stored graph truth
  with no verification step; invalidation (`expired_at`) is also
  LLM-decided, so the planner could certify its own output via
  retrieval. Default configuration silently depends on paid
  external services (OpenAI + Neo4j) and phones home via PostHog
  telemetry unless `GRAPHITI_TELEMETRY_ENABLED=false` is set. The
  only embedded/local backend (Kuzu) is deprecated and will be
  removed; the remaining backends are servers or AWS, so a
  dependency would lock START to a serverful graph DB. Temporal
  bounds are regex heuristics over LLM-extracted text; a wrong
  `valid_at`/`invalid_at` is stored as a fact window, not flagged
  as uncertain. 40,844 lines in `graphiti_core` — far too large to
  vendor; only the ~10-field temporal schema is borrowable, and
  only as a rewrite.
- **Crawl4AI — browser weight and stealth surface:** full Chromium
  download via Playwright/Patchright plus OS deps contradicts
  local-first lightness and needs a post-install step on every
  machine. `js_snippet/` ships fingerprint-spoofing JavaScript
  (`navigator_overrider.js`), consent-popup removers and overlay
  removers, plus fake-useragent and proxy strategies — behaviour
  START does not need and should not inherit. Robots.txt off by
  default: a careless `arun()` call crawls disallowed paths; START
  would have to force `check_robots_txt=True` and still cannot
  rely on it for licence compliance. No licence/provenance
  tracking: licence verification must be built in START, not
  expected from the crawler. LLM extraction defaults to a paid
  external API (`openai/gpt-4o` via litellm) with keys in config.
  God-module coupling: `utils.py` (3,786 lines) is imported by
  nearly every module, so extracting any helper other than the
  stdlib-only `normalize_url` drags in bs4/lxml/httpx/numpy/litellm.
  The Cloud module phones home to a hosted Crawl4AI Cloud service
  (API key, profile upload over httpx) — must be excluded. The
  seeder queries external third-party indexes (Common Crawl,
  Certificate Transparency) by default — extra egress and
  provenance surface beyond the target site.
- **Guardrail conflicts (all five):** none of these repos knows
  START's guardrails. Cedar's authorizer has no concept of a
  human-approval hook beyond the attributes it is given; egg has
  no verification concept at all; Cognee and Graphiti have no
  verified/unverified distinction and no `needs_human_decision`;
  Crawl4AI has no provenance or licence tracking. Any borrowing
  route must wrap the borrowed piece so that search/planning
  proposes, a separate verifier disposes, and `needs_human_decision`
  is always True. Neither borrowing route touches self-edit or
  guardrail files, and neither should: all five are audit-only here.

## 10. Notes on unverified claims

- Line counts are from the shallow clones at the HEAD commits
  listed above, re-checked by the coordinator with `wc -l`
  (Cedar 233,228; egg `src/` 10,721; Cognee non-test 248,631;
  Graphiti `graphiti_core/` 40,844; Crawl4AI `crawl4ai/` 47,234).
  The upstream repos have moved on since (Cedar HEAD was
  2026-11-10; Cognee/Graphiti/Crawl4AI HEADs are the clone
  HEADs recorded by the auditing subagents), so a newer commit may
  differ slightly. Licences were verified from the local LICENSE
  files; upstream licence pages were not separately checked.
- Cedar: README performance claims (fast, scalable, bounded
  latency) not benchmarked on START's workload; symcc behaviour
  not run (cvc5 not installed on this VM); whether 4.14.1 differs
  materially from audited 4.14.0 not diffed; experimental features
  (`tpe`, `partial-eval`, `partial-validate`, `entity-manifest`)
  not exercised; formatter round-trip fidelity on `policies.cedar`
  not tested; no check that the Python stub evaluator in
  `adapters/governance.py` stays in sync with the real Cedar
  policies (its file header says it is NOT Cedar).
- egg: whether 0.11.0 builds and its test suite passes on this VM
  was not checked (the clone was read only, no cargo build/test);
  whether `LpExtractor` with a HiGHS (or CBC) backend via `good_lp`
  works locally for START is unverified (the spine does not enable
  the `lp` feature); whether a numeric `Analysis` (per-eclass
  land/water/shortage bounds with a sound merge) can be designed
  for plan expressions at all is unverified — no such analysis
  exists in egg or in the spine demo, which uses `Analysis=()`;
  whether saturation terminates and stays within node limits on a
  realistic START plan language is unverified (only the toy
  `(+ x 0)` demo has been run); API compatibility between pinned
  0.10.0 and HEAD 0.11.0 was not diffed in full.
- Cognee: no end-to-end run was executed (audit only, as
  instructed); the keyless GLiNER-demo + fastembed path was read in
  config/code but not run on this VM, so its working state, speed
  and accuracy here are unverified; whether the conflicts/improve
  flow actually resolves contradictory extracted facts correctly,
  rather than merely listing them, was not traced end to end;
  DeepEval/LLM-as-judge evaluation claims in the eval framework
  were not exercised; MCP server, frontend, cloud sync and
  Slack/Gmail integration behaviour were not exercised; scale,
  concurrency and long-corpus performance claims were not tested.
- Graphiti: `EpisodeType.fact_triple` exists as an enum value but
  no ingestion path handling it was found in the code — whether
  fact triples can bypass LLM extraction is unverified; claimed
  local/embedded operation (Kuzu, FalkorDBLite, GLiNER2) was not
  exercised (no DB or LLM was available, no tests were run, no
  `add_episode`/search round-trip was executed); accuracy of
  LLM-extracted `valid_at`/`invalid_at` and of LLM
  dedup/invalidation on real planning text was not measured; search
  recall/quality and community/saga summarisation claims were not
  demonstrated by running the code, only read in source; whether
  the PostHog telemetry opt-out is honoured at runtime was not
  tested.
- Crawl4AI: whether Playwright/Chromium actually installs and runs
  on this VM (not installed or executed during this audit;
  `install.py` only read); end-to-end robots.txt enforcement
  (`check_robots_txt=True` path) — code read, not executed against
  a live site; claimed extraction/markdown quality
  ("LLM-friendly") — no test run performed; tests/ (58,909 lines)
  not executed; adaptive crawler / deep-crawl scoring
  effectiveness (BM25/SEO/freshness scorers) — code read only, no
  live crawl to validate ranking behaviour; Crawl4AI Cloud service
  availability, terms and data handling — CLI code read only, no
  account or live call; whether the vendored html2text fork
  diverges from upstream html2text in ways that matter — not
  diffed against upstream; performance/concurrency claims for the
  dispatcher and memory-cache behaviour under load — not
  benchmarked.
- Dependency licence statements (e.g. pydantic BSD-3, `lalrpop-util`
  Apache-2.0) are from the packages' own metadata as installed or
  as declared in their manifests; they were not each verified
  against upstream in this audit.
- The claim that copying Cognee's `chunk_by_word.py` +
  `chunk_id.py` or Crawl4AI's `normalize_url()` needs only the
  standard library is by reading their imports, not by running a
  stripped-down copy — no such copy was made in this audit, per
  the no-copy rule.
