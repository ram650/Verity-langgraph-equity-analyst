# Verity — Project Notes (for future me)

A multi-agent equity-research tool. Give it a ticker, it pulls the company's
latest SEC 10-K, a **bull** agent and a **bear** agent argue the stock, and a
**verifier** agent fact-checks every claim against the filing. If too many
claims aren't grounded, it loops back and makes the agents fix them. The wedge:
**verifiability** (no unsupported claims) on **under-covered small-caps**.

Full spec: `SPEC.md`.

---

## How to run it

CLI (backend only):
```bash
# from E:\Verity\backend
.venv\Scripts\python.exe graph.py DAKT             # ticker only = memo
.venv\Scripts\python.exe graph.py INTC 2024Q2      # ticker + quarter = memo + spin
.venv\Scripts\python.exe edgar.py DAKT             # data layer only (free, no Claude)
```

Full app (backend API + React frontend):
```bash
# terminal 1 — API on :8000
cd E:\Verity\backend
.venv\Scripts\python.exe -m uvicorn api:app --port 8000 --reload

# terminal 2 — frontend on :5173  (Node is at "C:\Program Files\nodejs")
cd E:\Verity\frontend
npm run dev
```
Then open http://localhost:5173. Landing = free (only /suggested). Clicking a
cached ticker = free/instant; a new ticker runs the pipeline (~30s, ~5 cents).
Reports cache to `backend/output/cache/`. `frontend/src/api.js` points at :8000.

The Anthropic API key lives in `backend\.env` (git-ignored). Never commit it.

---

## File map

| File | Job | Uses |
|---|---|---|
| `backend/edgar.py` | Pull SEC filings: ticker → CIK → filing → clean text, then extract the Business / Risk Factors / MD&A sections. Cuts a ~98K-token 10-K to ~15K of signal. | `requests` (no API key — SEC is free, just needs a User-Agent header) |
| `backend/llm.py` | One place to talk to Claude. `call()` returns text; `call_json()` forces structured JSON. Model set here (`DEFAULT_MODEL`). | `anthropic` SDK |
| `backend/graph.py` | **The LangGraph wiring.** Defines the state, the agent nodes, and the flow (including the verifier loop). | `langgraph` |
| `lesson1_graph.py` | Throwaway teaching graph (no AI) that shows state/nodes/edges. | — |

---

## The LangGraph mental model (the part that confuses people)

LangGraph is **only the wiring** — it decides what runs next and carries the
shared state between steps. It does NOT fetch data or call Claude. Those happen
*inside* the nodes, in plain Python.

Three concepts, all visible in `graph.py`:

1. **State** (`VerityState`, a TypedDict) = the shared whiteboard. LangGraph
   threads it through every node. A node returns a *partial update*
   (`return {"bull_case": text}`), it does NOT mutate state in place.
2. **Nodes** = plain functions `(state) -> partial update`. LangGraph doesn't
   care what's inside; `bull_node` happens to call Claude, but it could compute
   anything.
3. **Edges** = the flow. `add_edge(a, b)` = always go a→b.
   `add_conditional_edges("verify", router, {...})` = ask a function where to go
   next. **That one conditional line is what makes it a cycle instead of a
   straight line.**

The whole LangGraph footprint is ~15 lines at the bottom of `graph.py`
(`StateGraph`, `add_node`, `add_edge`, `add_conditional_edges`, `compile`,
`invoke`). Everything else is normal Python that LangGraph runs.

---

## The pipeline

```
ticker
  → fetch     (edgar.py; free, no Claude)
  → bull      (reads Business + MD&A, writes the upside)
  → bear      (reads Business + Risk Factors, writes the downside)
  → verify    (fact-checks every claim vs the filing → citation score)
       │
       ├─ score < 85 and under the pass cap → REVISE: loop back to bull/bear
       │                                       with feedback (this is the cycle)
       └─ else → DONE
```

- Each agent reads only the sections it needs (cheaper + more focused).
- The verifier returns **structured JSON** (`score`, `unsupported`, `feedback`)
  so parsing can't fail. `route_after_verify` reads the score and decides.
- Loop is capped (`MAX_VERIFY_PASSES`) so it can't run forever or burn budget.

---

## Cost discipline (why this is cheap)

The only thing that costs money is Claude. Levers we use:

- **Mock the model** for pure plumbing/UI work → $0.
- **Debug on Haiku** (`claude-haiku-4-5`, $1/$5 per 1M), ship the synthesis on
  **Sonnet 5** later. Switch is one line in `llm.py`.
- **Section extraction** feeds ~15K tokens, not the raw ~98K.
- **Structured outputs** stop the verifier from rambling past `max_tokens`
  (which once caused a wasteful loop — see lesson below).
- **TODO (Wk3):** prompt-cache the filing sections so the verifier's re-reads
  cost ~10% instead of full price. Also Batch API (50% off) for eval runs.

Rough cost: a full run with one revision ≈ 5-8 cents on Haiku. Whole build
target: ~$15-40. Key has ~$10.

---

## Lessons learned

- **Structured outputs > "please use this format".** The first verifier used
  plain text + a regex to find `SCORE:`. Haiku narrated a long checklist,
  ran out of tokens before printing the score, regex found nothing → score
  parsed as 0 → pointless revision loop (~7 cents wasted). Fix: `call_json()`
  with a JSON schema. The API constrains the output; parsing can't fail.
- **Windows console is cp1252.** Printing model output (which has Unicode like
  `‑`) crashes unless you `sys.stdout.reconfigure(encoding="utf-8")`.
- **SEC needs a User-Agent header** with contact info or it returns 403.
- **Structured-output truncation strikes twice.** Real earnings calls produced
  so many spin findings that the JSON hit `max_tokens=900` and cut off mid-string
  → `json.loads` crash. Same class of bug as the verifier. Fix: give real-data
  calls generous `max_tokens` (spin uses 2000). Watch `stop_reason == max_tokens`.
- **A node returns a partial state update, not the whole state.** Easy to forget.
- **Prompt caches are model-scoped and prefix-matched.** Haiku (bull/bear) and
  Sonnet (verify) keep separate caches, so tiering models splits the cache pool.
  Caching only pays off when reuse probability beats the ~1.25x write premium:
  bull→bear reuse is guaranteed (win); verifier reuse needs a revision (wash on
  clean runs). Watch `usage.cache_creation_input_tokens` / `cache_read_input_tokens`.
- **10-K section extraction is format-dependent.** Standard filers head the body
  "Item 1A. Risk Factors"; some large-caps (Intel, MSFT) / REITs (O) print
  "Item 1A" only in the TOC and head the body with just "Risk Factors", and omit
  the "Item 1" prefix on Business. `edgar.py` handling, in order:
  (1) STRICT prefixed anchors (clean for small-caps),
  (2) LOOSE title-only fallback when strict < ~1200 chars (fixes Risk Factors / MD&A),
  (3) Business-specific fallback: since Business always precedes Risk Factors,
      grab the ~18k chars right before the real Risk Factors start.
  Tested on UFPT / CROX / JPM / O / MSFT / INTC — all 6 now extract all three
  sections. Guardrails hold regardless: on thin input the agents refuse to
  fabricate. A fuller fix (perfect section boundaries) = a dedicated SEC parser
  (sec-parser / edgartools) [future work]. `test_extraction.py` re-runs the sweep.

---

## Status / next

- [x] EDGAR fetch + section extractor
- [x] Bull agent, Bear agent
- [x] Verifier + loop-back cycle (structured outputs)
- [x] Composer — assembles final memo, writes `backend/output/{ticker}_memo.md`
- [x] Eval harness (`eval.py`) — LLM-judge rubric (balance/specificity/insight/
      clarity/overall) + reuses the verifier citation score. DAKT: 85 cite, 4/5 overall.
- [x] Spin detector (`spin.py`, standalone v2) — compares 2 earnings-call quarters
      for hedging / evasiveness / dropped metrics / tone shift → caution score.
- [x] Real transcript source (`transcripts.py`, Alpha Vantage). Key in `.env`
      (`ALPHAVANTAGE_API_KEY`). `spin.py TICKER 2024Q2` fetches that quarter + the
      prior one and compares. Real demo: INTC 2024Q2 vs Q1 → caution 72/100,
      caught margin collapse, foundry losses, dropped metrics. Free tier: ~25
      req/day, ~1 req/sec (spin.py sleeps 1.5s between fetches). Coverage skews
      large/mid-cap; small-caps often have no transcript.
- [x] Adversarial eval (`adversarial_eval.py`) — labeled real/fake claim bank,
      measures verifier CATCH RATE. Result: Haiku 89% (8/9), Sonnet 5 100% (9/9),
      both 0% false-positive. Decision: draft on Haiku, VERIFY on Sonnet.
      Caveats: small set (16 claims, 2 cos); fakes are blatant — subtle
      misrepresentation catch rate is lower. Expand the bank to tighten.
- [x] Prompt caching — shared cached filing block across bull/bear/verify
      (`llm._messages` + `cache_context` param). Verified: bear reads bull's
      cache (5,424 tok at ~10%). bull+bear share a Haiku cache (guaranteed
      reuse = always a win); verifier has its OWN Sonnet cache (caches are
      model-scoped) reused only on revisions.
- [ ] React UI (Wk3, needs Node.js installed)
- [ ] Deploy, PRD writeup, demo video
