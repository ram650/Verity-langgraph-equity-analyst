"""
Earnings-call transcript source for the spin detector (Alpha Vantage).

Alpha Vantage is free: get a key instantly (no card) at
https://www.alphavantage.co/support/#api-key  (free tier ~25 requests/day).
Put it in backend/.env as  ALPHAVANTAGE_API_KEY=...

The public 'demo' key only works for IBM 2024Q1, so real comparisons need a key.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "demo").strip()
BASE = "https://www.alphavantage.co/query"


def fetch_transcript(symbol: str, quarter: str, api_key: str | None = None) -> dict:
    """Fetch one earnings-call transcript. quarter is like '2024Q1'."""
    key = api_key or AV_KEY
    r = requests.get(BASE, params={
        "function": "EARNINGS_CALL_TRANSCRIPT",
        "symbol": symbol.upper(),
        "quarter": quarter,
        "apikey": key,
    }, timeout=30)
    r.raise_for_status()
    d = r.json()
    segs = d.get("transcript")
    if not isinstance(segs, list) or not segs:
        # Alpha Vantage returns {"Information": ...} on rate limit / bad key / no data
        msg = d.get("Information") or d.get("Note") or d.get("Error Message") or str(d)[:200]
        raise ValueError(f"No transcript for {symbol} {quarter}: {msg}")
    # Flatten the segments into readable "Speaker (Title): text" lines.
    text = "\n".join(
        f"{s.get('speaker', '?')} ({s.get('title', '')}): {s.get('content', '')}"
        for s in segs
    )
    return {"symbol": symbol.upper(), "quarter": quarter,
            "text": text, "segments": len(segs)}


def prior_quarter(quarter: str) -> str:
    """'2024Q1' -> '2023Q4'."""
    y, q = int(quarter[:4]), int(quarter[-1])
    return f"{y-1}Q4" if q == 1 else f"{y}Q{q-1}"


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "IBM"
    q = sys.argv[2] if len(sys.argv) > 2 else "2024Q1"
    t = fetch_transcript(sym, q)
    print(f"{t['symbol']} {t['quarter']}: {t['segments']} segments, "
          f"{len(t['text']):,} chars (~{len(t['text'])//4:,} tokens)")
    print("---")
    print(t["text"][:500])
