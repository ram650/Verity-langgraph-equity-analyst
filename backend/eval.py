"""
Eval harness: grade Verity's memos so quality is measurable, not vibes.

Two signals, kept separate on purpose:
  1. Citation score  -> objective grounding, computed by the verifier (in the memo).
  2. Rubric score    -> analytical quality, graded here by an LLM-as-judge.

Run:  .venv\\Scripts\\python.exe eval.py DAKT [TICKER2 ...]
(reads the memo files already in backend/output/)
"""

import os
import re
import sys
import llm

# The judge must return exactly this shape — no rambling, always parseable.
RUBRIC = {
    "type": "object",
    "properties": {
        "balance": {"type": "integer"},       # bull & bear both substantive? 1-5
        "specificity": {"type": "integer"},    # concrete figures vs vague? 1-5
        "insight": {"type": "integer"},        # non-obvious drivers/risks? 1-5
        "clarity": {"type": "integer"},        # structure / readability? 1-5
        "overall": {"type": "integer"},        # holistic 1-5
        "rationale": {"type": "string"},
    },
    "required": ["balance", "specificity", "insight", "clarity", "overall", "rationale"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You are a demanding buy-side research director grading a junior analyst's "
    "equity research memo. Grade only what is in the memo. Be strict: a 5 is "
    "genuinely excellent, a 3 is mediocre, a 1 is poor."
)


def evaluate_memo(memo_text: str):
    prompt = (
        "Grade this equity research memo on a 1-5 integer scale for each "
        "dimension:\n"
        "- balance: are the bull and bear cases BOTH strong and fair?\n"
        "- specificity: concrete figures and quotes vs vague hand-waving?\n"
        "- insight: does it surface non-obvious drivers/risks, not boilerplate?\n"
        "- clarity: is it well-structured and readable?\n"
        "- overall: your holistic judgment.\n"
        "Also give a one-paragraph rationale.\n\n"
        f"=== MEMO ===\n{memo_text}"
    )
    return llm.call_json(prompt, RUBRIC, system=JUDGE_SYSTEM)


def load_memo(ticker: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "output", f"{ticker}_memo.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    tickers = sys.argv[1:] or ["DAKT"]
    rows = []
    for t in tickers:
        memo = load_memo(t)
        m = re.search(r"Verification score: (\d+)", memo)
        citation = int(m.group(1)) if m else None
        scores, usage = evaluate_memo(memo)
        print(f"[eval] {t}: judged (tokens {usage.input_tokens}/{usage.output_tokens})")
        rows.append((t, citation, scores))

    print("\n" + "-" * 74)
    print(f"{'Ticker':7} {'Cite':>5} | {'Bal':>3} {'Spec':>4} {'Inst':>4} "
          f"{'Clar':>4} | {'Overall':>7}")
    print("-" * 74)
    for t, cite, s in rows:
        cite_str = f"{cite}" if cite is not None else "-"
        print(f"{t:7} {cite_str:>5} | {s['balance']:>3} {s['specificity']:>4} "
              f"{s['insight']:>4} {s['clarity']:>4} | {s['overall']:>5}/5")
    print("-" * 74)
    for t, cite, s in rows:
        print(f"\n{t} — judge's rationale:\n{s['rationale']}")
