"""Free robustness check: run section extraction across varied filers (no Claude)."""
import time
import edgar

TICKERS = ["UFPT", "CROX", "JPM", "O", "MSFT"]   # small industrial, consumer, bank, REIT, tech
MIN = 1200

print(f"{'Ticker':7} {'Filed':11} {'business':>9} {'risk':>9} {'mdna':>9}  verdict")
print("-" * 62)
for t in TICKERS:
    try:
        d = edgar.get_key_sections(t)
        b, r, m = len(d["business"]), len(d["risk_factors"]), len(d["mdna"])
        bad = [n for n, v in (("business", b), ("risk", r), ("mdna", m)) if v < MIN]
        verdict = "OK" if not bad else "THIN: " + ",".join(bad)
        print(f"{t:7} {d['meta']['filing_date']:11} {b:>9,} {r:>9,} {m:>9,}  {verdict}")
    except Exception as e:
        print(f"{t:7} {'ERROR':11} {str(e)[:60]}")
    time.sleep(0.5)
