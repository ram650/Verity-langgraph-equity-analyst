"""
Spin detector (v2 module, standalone — NOT part of the main graph).

Compares a company's CURRENT earnings-call transcript to the PRIOR quarter's and
flags management "spin": increased hedging, evasive non-answers to analyst
questions, quietly dropped metrics, and tone shifts. Outputs a caution score.

DATA NOTE: earnings-call transcripts are NOT on SEC EDGAR (EDGAR has 8-Ks, not
transcripts). Real use needs a transcript source (a free API like Alpha Vantage
or FMP with a key, or local .txt files). The SAMPLE below is a labeled test
fixture to exercise the analyzer — it is NOT real data.

Run:  .venv\\Scripts\\python.exe spin.py
"""

import sys
import time
import llm
import transcripts

SPIN_SCHEMA = {
    "type": "object",
    "properties": {
        "caution_score": {"type": "integer"},                       # 0-100, higher = more spin
        "hedging": {"type": "array", "items": {"type": "string"}},   # language got vaguer
        "evasiveness": {"type": "array", "items": {"type": "string"}},  # dodged questions
        "dropped_metrics": {"type": "array", "items": {"type": "string"}},  # stopped disclosing
        "tone_shift": {"type": "string"},                            # how the tone changed
        "flags": {"type": "array", "items": {"type": "string"}},     # top red flags
        "summary": {"type": "string"},
    },
    "required": ["caution_score", "hedging", "evasiveness",
                 "dropped_metrics", "tone_shift", "flags", "summary"],
    "additionalProperties": False,
}

SPIN_SYSTEM = (
    "You are a forensic earnings-call analyst. You detect management spin by "
    "comparing the CURRENT quarter's call to the PRIOR quarter's. Spin shows up "
    "as: language getting vaguer/more hedged on the same topic, evasive "
    "non-answers to direct analyst questions, metrics that were proudly "
    "disclosed before and are now quietly dropped, and a shift from confident "
    "to defensive tone (e.g. blaming external/macro factors). Be specific and "
    "cite the actual wording. Do not invent things not in the transcripts."
)


def analyze_spin(company: str, current_transcript: str, prior_transcript: str):
    prompt = (
        f"Company: {company}\n\n"
        f"=== PRIOR QUARTER CALL ===\n{prior_transcript}\n\n"
        f"=== CURRENT QUARTER CALL ===\n{current_transcript}\n\n"
        "Compare the two calls. Identify increased hedging, evasive non-answers, "
        "dropped metrics, and tone shifts. Give a caution_score 0-100 (higher = "
        "more concerning), the top flags, and a short summary."
    )
    # Real transcripts surface many findings — give the JSON room so it isn't
    # truncated mid-string (a truncated structured output fails json.loads).
    return llm.call_json(prompt, SPIN_SCHEMA, system=SPIN_SYSTEM, max_tokens=2000)


# --- SAMPLE FIXTURE (illustrative, NOT real data) -------------------------
SAMPLE_PRIOR = """
Q3 Earnings Call.
CEO: Revenue grew 22% this quarter. Net revenue retention was 118%, and churn
held steady at 4%. We are very confident we will hit 20%+ growth next quarter.
Analyst (Morgan): What is your churn rate trending toward?
CEO: Churn is 4% and stable. We expect it to stay in that range.
Analyst (Jane): How is the enterprise segment performing?
CFO: Enterprise bookings were up 30%; it is our strongest cohort.
"""

SAMPLE_CURRENT = """
Q4 Earnings Call.
CEO: We feel good about the general trajectory of the business despite a
challenging macro environment. Revenue was roughly in line with our
expectations. We remain focused on long-term value creation.
Analyst (Morgan): What is your churn rate this quarter?
CEO: We are seeing some puts and takes, but overall we are pleased with customer
engagement and we are investing in retention initiatives.
Analyst (Jane): Can you give the enterprise bookings number?
CFO: Enterprise remains an important focus area for us going forward.
"""


def run_spin(symbol: str, quarter: str):
    """Real path: fetch this quarter + the prior quarter, then analyze the shift."""
    cur = transcripts.fetch_transcript(symbol, quarter)
    prior_q = transcripts.prior_quarter(quarter)
    time.sleep(1.5)   # free Alpha Vantage key throttles to ~1 request/second
    prev = transcripts.fetch_transcript(symbol, prior_q)
    print(f"[spin] {symbol}: {prev['quarter']} ({prev['segments']} seg) "
          f"vs {cur['quarter']} ({cur['segments']} seg)")
    return analyze_spin(symbol, cur["text"], prev["text"])


def _print_result(data, usage):
    print(f"[spin] tokens in/out: {usage.input_tokens}/{usage.output_tokens}\n")
    print(f"CAUTION SCORE: {data['caution_score']}/100\n")
    print(f"TONE SHIFT: {data['tone_shift']}\n")
    print("HEDGING:");         [print(f"  - {x}") for x in data["hedging"]]
    print("EVASIVENESS:");     [print(f"  - {x}") for x in data["evasiveness"]]
    print("DROPPED METRICS:"); [print(f"  - {x}") for x in data["dropped_metrics"]]
    print("\nFLAGS:");         [print(f"  ⚑ {x}") for x in data["flags"]]
    print(f"\nSUMMARY: {data['summary']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3:
        # Real data:  spin.py TICKER 2024Q2   (needs ALPHAVANTAGE_API_KEY in .env)
        data, usage = run_spin(sys.argv[1], sys.argv[2])
    else:
        print("[spin] no ticker/quarter given — running SAMPLE fixture (not real data)")
        data, usage = analyze_spin("SampleCo", SAMPLE_CURRENT, SAMPLE_PRIOR)
    _print_result(data, usage)
