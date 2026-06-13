# CiteSeek — Citation Evidence Workbench

**Credit Where Credit Is Due: A Lightweight Agentic Citation Support Tool** (COMPSCI 792)

Select a sentence in a paper and CiteSeek searches the open scholarly record
(arXiv, Semantic Scholar, OpenAlex) for papers that plausibly support or
originated the claim — returning ranked candidates with **passage-level
evidence** quoted from the fetched full texts and a **confidence score** per
candidate. Fetched papers open in the built-in reader, where you can select
the next claim and recurse; the whole exploration is persisted as a tree you
can backtrack through and export as a Markdown evidence-chain report.

Two interfaces share one engine:

- **Web UI** — a three-pane reading workbench (exploration tree · paper reader · evidence panel)
- **MCP server** — eight tools usable from Claude Code or any MCP client

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env            # add at least one LLM API key (optional but recommended)

# Web UI
cd frontend && npm install && npm run build && cd ..
.venv/bin/citeseek-api          # serves http://127.0.0.1:8000

# MCP (Claude Code)
claude mcp add citeseek -- $PWD/.venv/bin/citeseek-mcp
```

Without an LLM key everything still works in degraded mode: queries fall back
to stopword-stripping, ranking falls back to embedding similarity, and
translation is disabled.

### CLI (development / evaluation)

```bash
.venv/bin/citeseek run "chain-of-thought prompting improves reasoning" # full pipeline
.venv/bin/citeseek query "..."        # persistent session query
.venv/bin/citeseek sessions / tree <id> / export <id>
.venv/bin/citeseek translate "adversarial training" --lang Chinese
```

## How it works

```
claim ──> LLM query generation (3-5 keyword queries)
      ──> arXiv + Semantic Scholar + OpenAlex (rate-limited, fault-tolerant)
      ──> dedup (arXiv id / DOI exact + fuzzy title)
      ──> first-pass ranking (bge-small-en-v1.5 embeddings, local)
      ──> citation expansion (references of top-10 seeds + seed-citation
          frequency signal with fuzzy-title aggregation; OpenAlex → S2)
      ──> full text for top open-access candidates (arxiv html → ar5iv → PDF)
      ──> chunking + passage retrieval (sqlite-vec)
      ──> LLM judge (verdict + confidence + rationale, batched)
      ──> final score = 0.4·embed + 0.6·llm + cite-freq + year prior − survey penalty
```

Every stage emits progress events consumed by the web UI (SSE) and MCP
progress reporting. State lives in SQLite (`var/citeseek.db`, WAL) so the web
and MCP servers can run simultaneously and sessions survive restarts.

The LLM layer supports **Claude, OpenAI, Gemini, DeepSeek, and Ollama** behind
one interface (`citeseek/llm/`): Anthropic via its official SDK, the rest via
the OpenAI-compatible API with per-provider base URLs.

## Evaluation

```bash
.venv/bin/python eval/run_eval.py                 # lexical vs embedding vs +year prior
.venv/bin/python eval/run_eval.py --cite          # adds citation-expansion configs
.venv/bin/python eval/run_eval.py --llm --cite    # full table incl. LLM judge
.venv/bin/python eval/failure_analysis.py         # per-claim attribution table
```

28 claims with known antecedent papers (`eval/benchmark.jsonl`); metrics are
Recall@k, Hit@k, and MRR. Search and citation-expansion results are cached
under `eval/cache/` so reranking experiments are offline-reproducible.
Results land in `eval/results.md`. Citation expansion lifts the retrieval
ceiling from 21/28 to 28/28 claims and is the single largest quality win.

## Project layout

```
citeseek/
  engine.py          single core service layer (REST + MCP both wrap this)
  sources/           arXiv / Semantic Scholar / OpenAlex clients + rate limiting
  fetch/             fulltext chain (arxiv html → ar5iv → PDF) + LaTeXML parser
  pipeline/          query_gen, dedup, embeddings, index, chunking, evidence, judge, rank
  llm/               unified provider layer (anthropic SDK + OpenAI-compatible)
  session/           exploration tree store + Markdown report export
  api/               FastAPI REST + SSE
  mcp_server.py      FastMCP stdio server (8 tools)
frontend/            React 19 + Vite + Tailwind v4 workbench
eval/                benchmark + metrics harness
tests/               unit tests (no network)
```

## Tests

```bash
.venv/bin/pytest -q                     # 26 unit tests, offline
cd frontend && node scripts/smoke.mjs   # browser smoke test (needs running API)
```
