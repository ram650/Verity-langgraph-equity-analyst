"""
Adversarial eval: MEASURE the verifier's catch rate instead of guessing.

We hand-label a bank of claims per company:
  fake=False -> genuinely supported by the filing (real figures)
  fake=True  -> deliberately fabricated (wrong number or invented fact)

We feed the numbered claims + the filing to the verifier and check, per claim,
whether it says supported/unsupported. Then:
  catch rate (recall)   = fabrications correctly flagged / total fabrications
  false-positive rate   = real claims wrongly flagged     / total real claims

Runs on Haiku vs Sonnet to show the model-upgrade lever.
Run:  .venv\\Scripts\\python.exe adversarial_eval.py
"""

import sys
import time
import edgar
import llm

MODELS = ["claude-haiku-4-5", "claude-sonnet-5"]

# Ground-truth labeled claims. Real figures were confirmed in earlier runs;
# fakes are unambiguous (numbers wildly off, or facts absent from the filing).
CLAIM_BANK = {
    "DAKT": [
        {"text": "Operating income was $60.8 million in fiscal 2026.", "fake": False},
        {"text": "Net sales grew 10.9% to $838.7 million.", "fake": False},
        {"text": "Orders increased 10.2% to $860.8 million.", "fake": False},
        {"text": "Gross margin was 27.3%.", "fake": False},
        {"text": "Revenue reached $2.4 billion in fiscal 2026.", "fake": True},
        {"text": "Net income was $210 million.", "fake": True},
        {"text": "Daktronics operates manufacturing facilities in 30 countries.", "fake": True},
        {"text": "Daktronics holds a 70% share of the global LED display market.", "fake": True},
        {"text": "Gross margin expanded to 55%.", "fake": True},
    ],
    "MSFT": [
        {"text": "Azure and cloud services revenue grew 34% in fiscal 2025.", "fake": False},
        {"text": "Microsoft Cloud revenue was $168.9 billion.", "fake": False},
        {"text": "Microsoft has approximately 228,000 employees.", "fake": False},
        {"text": "Azure and cloud services revenue grew 120% in fiscal 2025.", "fake": True},
        {"text": "Microsoft Cloud revenue exceeded $500 billion.", "fake": True},
        {"text": "Microsoft acquired OpenAI outright in 2025.", "fake": True},
        {"text": "The company employs 1.2 million people.", "fake": True},
    ],
}

EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "supported": {"type": "boolean"},
                },
                "required": ["id", "supported"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

EVAL_SYSTEM = (
    "You are a strict fact-checker. For each numbered claim, decide if it is "
    "SUPPORTED by the filing excerpts. A claim is supported ONLY if its facts "
    "and numbers appear in, or clearly follow from, the text. If a number is "
    "wrong or a fact is absent, it is NOT supported."
)


def get_sections(ticker: str) -> str:
    d = edgar.get_key_sections(ticker)
    return (f"=== BUSINESS ===\n{d['business']}\n\n"
            f"=== RISK FACTORS ===\n{d['risk_factors']}\n\n"
            f"=== MD&A ===\n{d['mdna']}")


def run_one(ticker: str, claims: list, model: str, source: str):
    numbered = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(claims))
    prompt = (f"FILING EXCERPTS:\n{source}\n\n"
              f"CLAIMS TO CHECK:\n{numbered}\n\n"
              "For each claim id, return whether it is supported by the filing.")
    data, usage = llm.call_json(prompt, EVAL_SCHEMA, system=EVAL_SYSTEM,
                                model=model, max_tokens=500)
    verdict = {v["id"]: v["supported"] for v in data["verdicts"]}
    fakes = [i for i, c in enumerate(claims) if c["fake"]]
    reals = [i for i, c in enumerate(claims) if not c["fake"]]
    caught = sum(1 for i in fakes if verdict.get(i) is False)   # fake flagged = caught
    fp = sum(1 for i in reals if verdict.get(i) is False)       # real flagged = false alarm
    return caught, len(fakes), fp, len(reals), usage


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Fetching filings (once) ...")
    sources = {t: get_sections(t) for t in CLAIM_BANK}
    for model in MODELS:
        print(f"\n=== MODEL: {model} ===")
        tc = tf = tp = tr = 0
        for t, claims in CLAIM_BANK.items():
            caught, nf, fp, nr, usage = run_one(t, claims, model, sources[t])
            tc += caught; tf += nf; tp += fp; tr += nr
            print(f"  {t}: caught {caught}/{nf} fabrications | "
                  f"{fp}/{nr} real claims wrongly flagged "
                  f"(tok {usage.input_tokens}/{usage.output_tokens})")
            time.sleep(0.5)
        recall = 100 * tc / tf if tf else 0
        fpr = 100 * tp / tr if tr else 0
        print(f"  --> CATCH RATE (recall on fabrications): {recall:.0f}%  "
              f"|  false-positive rate: {fpr:.0f}%")
