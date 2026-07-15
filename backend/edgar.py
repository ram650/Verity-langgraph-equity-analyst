"""
SEC EDGAR data access. No API key needed — it's a free public service.

Three hops to get a company's latest filing:
  1. ticker -> CIK        (SEC's master ticker list)
  2. CIK    -> filings    (the company's submission history)
  3. filing -> text       (download the actual 10-K document)

SEC requires a User-Agent header identifying you, or it returns HTTP 403.
"""

import re
import html as html_lib
import functools
import requests

# SEC asks for a descriptive User-Agent with a contact email. Be a good citizen.
SEC_HEADERS = {"User-Agent": "Verity Research ramanathanm52108@gmail.com"}
TIMEOUT = 30


# --- hop 1: ticker -> CIK -------------------------------------------------
@functools.lru_cache(maxsize=1)
def _ticker_map() -> dict:
    """Download SEC's ticker->CIK master list once, cache it in memory."""
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    # The JSON is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    return {row["ticker"].upper(): row for row in r.json().values()}


def resolve_cik(ticker: str) -> tuple[str, str]:
    """Return (10-digit zero-padded CIK, company name) for a ticker."""
    row = _ticker_map().get(ticker.upper())
    if not row:
        raise ValueError(f"Ticker '{ticker}' not found in SEC's ticker list.")
    cik = str(row["cik_str"]).zfill(10)  # SEC APIs want the CIK padded to 10 digits
    return cik, row["title"]


def resolve_query(q: str) -> tuple[str, str]:
    """Turn a user query (a ticker OR a company name) into (ticker, name).

    An exact ticker wins outright. Otherwise we score every company name:
    exact title > name starts with the query > the query is a whole word in the
    name > the query appears anywhere. Shorter titles break ties, so "apple"
    lands on "Apple Inc." rather than "Apple Hospitality REIT"."""
    q = (q or "").strip()
    if not q:
        raise ValueError("Empty query.")
    m = _ticker_map()
    up = q.upper()
    if up in m:                                   # already a valid ticker
        return m[up]["ticker"].upper(), m[up]["title"]

    ql = q.lower()
    best, best_score = None, 0.0
    for row in m.values():
        title = row["title"]
        tl = title.lower()
        if tl == ql:
            score = 100.0
        elif tl.startswith(ql):
            score = 80.0
        elif ql in tl.split():
            score = 60.0
        elif ql in tl:
            score = 40.0
        else:
            continue
        score -= len(title) * 0.01                # prefer the shorter, canonical name
        if score > best_score:
            best, best_score = row, score
    if best:
        return best["ticker"].upper(), best["title"]
    raise ValueError(f"No company or ticker matching '{q}'.")


# --- hop 2: CIK -> latest filing metadata ---------------------------------
def get_latest_filing(ticker: str, form: str = "10-K") -> dict:
    """Find the most recent filing of a given form type (default: 10-K)."""
    cik, name = resolve_cik(ticker)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    recent = r.json()["filings"]["recent"]  # parallel lists: form[i], date[i], etc.

    for i, f in enumerate(recent["form"]):
        if f == form:
            accession = recent["accessionNumber"][i]        # e.g. 0001234567-24-000012
            primary = recent["primaryDocument"][i]          # e.g. dakt-20240330.htm
            acc_nodash = accession.replace("-", "")
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{acc_nodash}/{primary}"
            )
            return {
                "name": name,
                "ticker": ticker.upper(),
                "cik": cik,
                "form": form,
                "filing_date": recent["filingDate"][i],
                "accession": accession,
                "primary_doc_url": doc_url,
            }
    raise ValueError(f"No {form} filing found for {ticker}.")


# --- hop 3: filing -> plain text ------------------------------------------
def _html_to_text(html: str) -> str:
    """Crude HTML -> text: drop scripts/styles/tags, collapse whitespace.
    Good enough to feed an LLM; we'll target specific sections later."""
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", raw)     # strip remaining tags
    text = html_lib.unescape(text)          # decode &#8217; &amp; &nbsp; etc.
    text = re.sub(r"\s+", " ", text)        # collapse whitespace
    return text.strip()


def fetch_filing_text(doc_url: str) -> str:
    """Download a filing document and return it as plain text."""
    r = requests.get(doc_url, headers=SEC_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return _html_to_text(r.text)


# --- section extraction ---------------------------------------------------
# Each 10-K item header, matched loosely. Patterns for the sections we care
# about include the title keyword (e.g. "risk factors") so a passing mention
# like "see Item 7" doesn't get mistaken for the real header.
# Two anchor sets. STRICT requires the "Item N" prefix — reliable heading
# detection for standard filers (most small-caps). LOOSE makes the prefix
# optional for distinctive titles, a fallback for filers (e.g. Intel) that print
# "Item 1A" only in the table of contents and head the body with just "Risk
# Factors". We try STRICT first and fall back to LOOSE only when STRICT comes
# back nearly empty, so the clean cases don't regress.
_STRICT = [
    ("item1",  r"item\s*1\b\.?\s*business"),
    ("item1a", r"item\s*1a\b\.?\s*risk\s*factors"),
    ("item1b", r"item\s*1b\b"),
    ("item1c", r"item\s*1c\b\.?\s*cyber"),
    ("item2",  r"item\s*2\b\.?\s*propert"),
    ("item3",  r"item\s*3\b\.?\s*legal"),
    ("item4",  r"item\s*4\b\.?\s*mine"),
    ("item5",  r"item\s*5\b\.?\s*market"),
    ("item6",  r"item\s*6\b"),
    ("item7",  r"item\s*7\b\.?\s*management"),
    ("item7a", r"item\s*7a\b\.?\s*quantitative"),
    ("item8",  r"item\s*8\b\.?\s*financial"),
    ("item9",  r"item\s*9\b\.?\s*changes"),
    ("item9a", r"item\s*9a\b\.?\s*controls"),
]
_LOOSE = [
    ("item1",  r"item\s*1\b\.?\s*business"),
    ("item1a", r"(?:item\s*1a\b\.?\s*)?risk\s+factors"),
    ("item1b", r"item\s*1b\b"),
    ("item1c", r"item\s*1c\b\.?\s*cyber"),
    ("item2",  r"(?:item\s*2\b\.?\s*)?propert(?:y|ies)"),
    ("item3",  r"(?:item\s*3\b\.?\s*)?legal\s+proceedings"),
    ("item4",  r"item\s*4\b\.?\s*mine"),
    ("item5",  r"item\s*5\b\.?\s*market\s+for"),
    ("item6",  r"item\s*6\b"),
    ("item7",  r"(?:item\s*7\b\.?\s*)?management.?s\s+discussion\s+and\s+analysis"),
    ("item7a", r"(?:item\s*7a\b\.?\s*)?quantitative\s+and\s+qualitative"),
    ("item8",  r"(?:item\s*8\b\.?\s*)?financial\s+statements\s+and\s+supplementary"),
    ("item9",  r"item\s*9\b\.?\s*changes"),
    ("item9a", r"(?:item\s*9a\b\.?\s*)?controls\s+and\s+procedures"),
]

# Friendly names -> the item key that holds that section
SECTION_KEYS = {"business": "item1", "risk_factors": "item1a", "mdna": "item7"}
MIN_SECTION_CHARS = 1200   # below this, a strict match probably missed the body


def _positions(text_lower: str, headers) -> list[tuple[int, str]]:
    """Every header hit in the doc as (char_position, item_key), sorted."""
    hits = []
    for key, pat in headers:
        for m in re.finditer(pat, text_lower):
            hits.append((m.start(), key))
    hits.sort()
    return hits


def _span(text: str, section: str, headers) -> tuple[int, int]:
    """(start, end) of the longest slice for a section; (0, 0) if none found."""
    target = SECTION_KEYS[section]
    positions = _positions(text.lower(), headers)
    best = (0, 0)
    for start, key in positions:
        if key != target:
            continue
        later = [p for p, _ in positions if p > start]
        end = min(later) if later else len(text)
        if end - start > best[1] - best[0]:   # longest slice = real body, not TOC
            best = (start, end)
    return best


def _extract_with(text: str, section: str, headers) -> str:
    s, e = _span(text, section, headers)
    return text[s:e].strip()


def extract_section(text: str, section: str) -> str:
    """Pull one section ('business' | 'risk_factors' | 'mdna'), strict then loose."""
    strict = _extract_with(text, section, _STRICT)
    if len(strict) >= MIN_SECTION_CHARS:
        return strict
    loose = _extract_with(text, section, _LOOSE)   # fallback for odd heading layouts
    best = loose if len(loose) > len(strict) else strict

    # Business is the hardest to anchor ("business" is too common a word). If it
    # came back thin, use the fact that Business always precedes Risk Factors:
    # grab the ~18k chars right before the real Risk Factors body starts.
    if section == "business" and len(best) < MIN_SECTION_CHARS:
        rf_start, _ = _span(text, "risk_factors", _LOOSE)
        if rf_start > MIN_SECTION_CHARS:      # a real (deep) Risk Factors start
            cand = text[max(0, rf_start - 18000):rf_start].strip()
            if len(cand) > len(best):
                best = cand
    return best


def get_key_sections(ticker: str, form: str = "10-K") -> dict:
    """One call: fetch the latest filing and return its 3 key narrative sections."""
    meta = get_latest_filing(ticker, form)
    full = fetch_filing_text(meta["primary_doc_url"])
    return {
        "meta": meta,
        "business": extract_section(full, "business"),
        "risk_factors": extract_section(full, "risk_factors"),
        "mdna": extract_section(full, "mdna"),
    }


# --- quick manual test ----------------------------------------------------
if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "DAKT"
    print(f"Fetching {ticker} ...")
    data = get_key_sections(ticker)
    m = data["meta"]
    print(f"  {m['name']}  |  {m['form']} filed {m['filing_date']}\n")
    for name in ("business", "risk_factors", "mdna"):
        chars = len(data[name])
        print(f"  {name:13} {chars:>8,} chars  (~{chars//4:>6,} tokens)")
    print(f"\n  business preview: {data['business'][:400]}")
