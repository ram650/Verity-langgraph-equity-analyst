"""
Verity API — a thin FastAPI wrapper around the LangGraph pipeline.

  GET  /suggested          -> curated companies by market-cap tier
  POST /analyze {ticker, quarter?} -> runs the graph, returns the report JSON

Report caching: results are cached to output/cache/ by ticker+quarter, so a
repeat view is instant and costs nothing (important once this is deployed).

Run:  .venv\\Scripts\\python.exe -m uvicorn api:app --port 8000 --reload
"""

import os
import io
import json
import re
import time
import threading
import traceback
import requests
from collections import deque
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel

import graph   # importing compiles the LangGraph pipeline (graph.graph)
import edgar   # ticker / company-name resolution
import llm     # for the /health LLM self-test

app = FastAPI(title="Verity API")
# CORS: "*" for local dev; in production set VERITY_CORS_ORIGINS to your site(s).
_origins = [o.strip() for o in os.environ.get("VERITY_CORS_ORIGINS", "*").split(",") if o.strip()]
if not _origins:                  # empty/blank env -> don't accidentally block everything
    _origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "output", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# --- cost / abuse guardrails ---------------------------------------------
# Each uncached /analyze runs the Claude pipeline (real money), so a public
# deployment needs limits. Per-IP burst limit + a global daily cap on NEW
# analyses (cached views are free and don't count). Tune via env vars.
RATE_PER_MIN = int(os.environ.get("VERITY_RATE_PER_MIN", "10"))
DAILY_NEW_CAP = int(os.environ.get("VERITY_DAILY_NEW_ANALYSES", "150"))
_rl_lock = threading.Lock()
_ip_hits: dict[str, deque] = {}
_day = {"date": "", "count": 0}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")   # set by hosts behind a proxy
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(ip: str) -> bool:
    """False if this IP has exceeded RATE_PER_MIN requests in the last 60s."""
    now = time.time()
    with _rl_lock:
        dq = _ip_hits.setdefault(ip, deque())
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= RATE_PER_MIN:
            return False
        dq.append(now)
        return True


def _budget_ok_and_reserve() -> bool:
    """True (and reserves a slot) if a new paid analysis is allowed today."""
    today = time.strftime("%Y-%m-%d")
    with _rl_lock:
        if _day["date"] != today:
            _day["date"], _day["count"] = today, 0
        if _day["count"] >= DAILY_NEW_CAP:
            return False
        _day["count"] += 1
        return True


def _friendly_error(msg: str) -> str:
    """Turn a raw pipeline exception into something a visitor can understand."""
    low = msg.lower()
    if "no 10-k" in low:
        return ("Verity currently covers US companies that file a 10-K. This one files a "
                "different form (foreign issuers use a 20-F), so it isn't supported yet.")
    if "not found" in low or "no company or ticker" in low:
        return "That ticker or company name wasn't found in SEC's EDGAR database. Check the spelling and try again."
    return "Something went wrong analyzing this company. Please try another ticker."

# Curated "hottest" names per tier (editorial, rotate as you like).
SUGGESTED = {
    "large": [{"ticker": "NVDA", "name": "Nvidia"},
              {"ticker": "MSFT", "name": "Microsoft"},
              {"ticker": "JPM",  "name": "JPMorgan"}],
    "mid":   [{"ticker": "CROX", "name": "Crocs"},
              {"ticker": "DECK", "name": "Deckers"},
              {"ticker": "WING", "name": "Wingstop"}],
    "small": [{"ticker": "DAKT", "name": "Daktronics"},
              {"ticker": "UFPT", "name": "UFP Technologies"},
              {"ticker": "CRVL", "name": "CorVel"}],
}


class AnalyzeRequest(BaseModel):
    ticker: str
    quarter: str | None = None   # pass a quarter (e.g. "2024Q2") to add the spin check


def _cache_path(ticker: str, quarter: str | None) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.upper()}_{quarter or 'none'}.json")


def _shape(state: dict) -> dict:
    """Trim the graph's full state down to what the frontend needs."""
    m = state["meta"]
    spin = state.get("spin_result")
    return {
        "ticker": state["ticker"].upper(),
        "name": m["name"],
        "form": m["form"],
        "filing_date": m["filing_date"],
        "filing_url": m["primary_doc_url"],
        "citation_score": state.get("citation_score"),
        "bull_case": state.get("bull_case", ""),
        "bear_case": state.get("bear_case", ""),
        "bull_rebuttal": state.get("bull_rebuttal", ""),
        "bear_rebuttal": state.get("bear_rebuttal", ""),
        "verdict": state.get("verdict", ""),
        "bull_needs": state.get("bull_needs", ""),
        "bear_needs": state.get("bear_needs", ""),
        "watch": state.get("watch", ""),
        "verifier_report": state.get("verifier_report", ""),
        "spin": spin if (spin and spin.get("available")) else None,
        "spin_unavailable": (spin.get("reason") if (spin and not spin.get("available")) else None),
        "memo": state.get("memo", ""),
    }


@app.get("/health")
def health(request: Request, ping_llm: int = 0):
    """Deploy sanity check. Booleans only, never secret values. ping_llm=1 makes
    a tiny Claude call and reports the error class if it fails (rate-limited)."""
    out = {
        "ok": True,
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "alphavantage_key_set": bool(os.environ.get("ALPHAVANTAGE_API_KEY")),
        "cors_origins": _origins,
    }
    if ping_llm:
        if not _rate_ok(_client_ip(request)):
            out["llm"] = "rate-limited, try later"
            return out
        try:  # raw HTTPS reachability, independent of the SDK's client
            r = requests.get("https://api.anthropic.com/v1/models", timeout=15)
            out["anthropic_http"] = f"reachable (HTTP {r.status_code})"
        except Exception as e:
            out["anthropic_http"] = f"{type(e).__name__}: {str(e)[:120]}"
        try:
            text, _ = llm.call("Reply with the single word OK.", max_tokens=8)
            out["llm"] = f"ok ({text.strip()[:20]})"
        except Exception as e:
            chain, cur, seen = [], e, set()
            while cur is not None and id(cur) not in seen and len(chain) < 5:
                seen.add(id(cur))
                chain.append(f"{type(cur).__name__}: {str(cur)[:140]}")
                cur = cur.__cause__ or cur.__context__
            # never let a secret leak through an exception message
            out["llm"] = re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "sk-ant-***", " <- ".join(chain))
    return out


@app.get("/suggested")
def suggested():
    return SUGGESTED


@app.get("/resolve")
def resolve(q: str):
    """Map a ticker or company name to a ticker, so the search box accepts both."""
    try:
        ticker, name = edgar.resolve_query(q)
        return {"ticker": ticker, "name": name}
    except ValueError as e:
        raise HTTPException(404, str(e))


_QUOTE_SYMBOLS = ["AAPL", "NVDA", "GME", "MSFT", "AMZN", "SHOP", "TSLA", "PLTR",
                  "GOOGL", "META", "F", "CROX", "BRK-B", "DECK", "WING", "DAKT",
                  "JPM", "UFPT", "CRVL"]
_quotes_cache = {"ts": 0.0, "data": []}


def _spark(closes: list, n: int = 24) -> list:
    """Downsample an intraday close series to ~n clean points for a sparkline."""
    pts = [c for c in closes if c is not None]
    if len(pts) < 2:
        return []
    if len(pts) <= n:
        return [round(c, 2) for c in pts]
    step = len(pts) / n
    return [round(pts[int(i * step)], 2) for i in range(n)]


def _fetch_quote(sym: str) -> dict:
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res = r.json()["chart"]["result"][0]
        m = res["meta"]
        price = m.get("regularMarketPrice")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        pct = ((price - prev) / prev * 100) if price and prev else None
        try:
            closes = res["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError):
            closes = []
        return {"symbol": sym, "price": round(price, 2) if price else None,
                "pct": round(pct, 2) if pct is not None else None,
                "spark": _spark(closes)}
    except Exception:
        return {"symbol": sym, "price": None, "pct": None, "spark": []}


@app.get("/quotes")
def quotes():
    """Real (delayed ~15m) quotes for the ticker tape, via Yahoo's public chart
    endpoint (no key). Cached ~60s so we don't hammer the source."""
    now = time.time()
    if now - _quotes_cache["ts"] < 60 and _quotes_cache["data"]:
        return _quotes_cache["data"]
    data = [_fetch_quote(s) for s in _QUOTE_SYMBOLS]
    _quotes_cache.update(ts=now, data=data)
    return data


LOGO_DIR = os.path.join(os.path.dirname(__file__), "output", "logos")
os.makedirs(LOGO_DIR, exist_ok=True)


def _whiten(raw: bytes) -> bytes:
    """Turn any logo PNG into a clean white silhouette on transparency: drop the
    background (transparent or near-white) and paint the rest white. So it reads
    uniformly on a colored tile regardless of the source logo's own colors."""
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 24 or (r > 232 and g > 232 and b > 232):
                px[x, y] = (255, 255, 255, 0)          # background -> transparent
            else:
                px[x, y] = (255, 255, 255, a or 255)    # logo -> white, keep edges
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


@app.get("/logo/{ticker}")
def logo(ticker: str, raw: int = 0):
    """Serve a company logo (fetched from FMP, cached). Default is whitened to a
    silhouette for colored tiles; raw=1 keeps the original colors (for logos like
    Ford's, whose white lettering disappears when whitened)."""
    tk = ticker.strip().upper()
    suffix = "_raw" if raw else ""
    path = os.path.join(LOGO_DIR, f"{tk}{suffix}.png")
    if not os.path.exists(path):
        try:
            r = requests.get(f"https://financialmodelingprep.com/image-stock/{tk}.png",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code != 200 or len(r.content) < 200:
                raise HTTPException(404, "no logo")
            with open(path, "wb") as f:
                f.write(r.content if raw else _whiten(r.content))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(404, "no logo")
    with open(path, "rb") as f:
        return Response(content=f.read(), media_type="image/png")


@app.post("/analyze")
def analyze(req: AnalyzeRequest, request: Request):
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "A ticker is required.")
    if not _rate_ok(_client_ip(request)):
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")

    path = _cache_path(ticker, req.quarter)
    if os.path.exists(path):                       # cache hit -> instant, free
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    if not _budget_ok_and_reserve():               # new analysis costs money -> capped
        raise HTTPException(429, "Verity has hit its daily analysis limit. Try again tomorrow, or view a cached company.")

    init = {"ticker": ticker}
    if req.quarter:
        init["include_spin"] = True
        init["quarter"] = req.quarter
    try:
        state = graph.graph.invoke(init)
    except Exception as e:
        print(f"[analyze] {ticker} failed: {e!r}")
        traceback.print_exc()
        raise HTTPException(400, _friendly_error(str(e)))

    result = _shape(state)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return result


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.get("/analyze/stream")
def analyze_stream(ticker: str, request: Request, quarter: str | None = None):
    """Like /analyze, but streams one Server-Sent Event per pipeline step as it
    actually finishes, then a final {done, result}. Powers the live progress UI."""
    tk = ticker.strip().upper()
    qq = quarter or None
    ip = _client_ip(request)

    def gen():
        path = _cache_path(tk, qq)
        if os.path.exists(path):                       # cached -> send result immediately (free)
            with open(path, encoding="utf-8") as f:
                yield _sse({"done": True, "result": json.load(f)})
            return
        if not _rate_ok(ip):
            yield _sse({"error": "Too many requests. Please wait a minute and try again."})
            return
        if not _budget_ok_and_reserve():
            yield _sse({"error": "Verity has hit its daily analysis limit. Try again tomorrow, or view a cached company."})
            return
        init = {"ticker": tk}
        if qq:
            init["include_spin"] = True
            init["quarter"] = qq
        state = dict(init)
        try:
            # stream_mode="updates" yields {node_name: partial_state} as each node finishes
            for update in graph.graph.stream(init, stream_mode="updates"):
                for node, partial in update.items():
                    if partial:
                        state.update(partial)
                    yield _sse({"step": node})
            result = _shape(state)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f)
            yield _sse({"done": True, "result": result})
        except Exception as e:
            print(f"[stream] {tk} failed: {e!r}")
            traceback.print_exc()
            yield _sse({"error": _friendly_error(str(e))})

    return StreamingResponse(gen(), media_type="text/event-stream")
