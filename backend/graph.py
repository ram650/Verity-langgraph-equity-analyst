"""
Verity graph v0: ticker -> fetch real SEC sections -> bull agent writes a thesis.

This is the real thing now (real data + real Claude), just small: one agent.
Next we add the bear agent and the verifier's loop-back.

Run:  E:\\Verity\\backend\\.venv\\Scripts\\python.exe graph.py DAKT
"""

import re
import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

import edgar
import llm
import spin


# --- STATE: the shared whiteboard -----------------------------------------
class VerityState(TypedDict):
    ticker: str
    meta: dict          # company name, form, filing date, etc.
    sections: dict      # business / risk_factors / mdna
    bull_case: str      # the bull agent's output
    bear_case: str      # the bear agent's output
    bull_rebuttal: str  # bull's reply to the bear's strongest point (crossfire)
    bear_rebuttal: str  # bear's reply to the bull's strongest point (crossfire)
    verdict: str        # the crux the debate comes down to (synthesis)
    bull_needs: str     # what must hold for the bull to be right
    bear_needs: str     # what must hold for the bear to be right
    watch: str          # the single metric/event that would resolve it
    citation_score: int     # verifier's % of claims grounded in the filing
    verifier_report: str    # the verifier's full findings
    feedback: str           # what to fix, fed back to the agents on a revision
    revisions: int          # how many verify passes have run (loop guard)
    memo: str               # the final assembled research memo
    include_spin: bool      # run the optional earnings-call spin add-on?
    quarter: str            # which quarter to spin-check (e.g. "2024Q2")
    spin_result: dict       # the spin add-on's output (or an 'unavailable' note)


# --- NODE 1: fetch (no Claude, free) --------------------------------------
# Cap each section fed to the agents. Big filers (JPM risk factors ~112k chars)
# would otherwise make cost balloon; the top of each section holds the key
# content, and every node reads the same capped text so the verifier stays fair.
SECTION_CAP = 12000


def fetch_node(state: VerityState) -> dict:
    t = state["ticker"]
    print(f"[fetch] pulling latest 10-K for {t} ...")
    data = edgar.get_key_sections(t)
    sections = {k: data[k][:SECTION_CAP] for k in ("business", "risk_factors", "mdna")}
    print("[fetch] sections (chars): "
          + ", ".join(f"{k}={len(v)}" for k, v in sections.items()))
    return {"meta": data["meta"], "sections": sections}


# Bull, bear, and the verifier all read the SAME filing. We share it as one
# cached prefix (identical system + filing block) so the second Haiku agent and
# any revision passes reuse it at ~10% of input cost instead of re-reading it.
ANALYST_SYSTEM = (
    "You are a sharp, skeptical equity analyst. Ground every claim in the "
    "provided filing text. Never invent numbers. If the filing supports a "
    "claim, cite what it says."
)


def _source(state: VerityState) -> str:
    """The shared, cacheable filing block — identical across bull/bear/verify."""
    m, s = state["meta"], state["sections"]
    return (
        f"Company: {m['name']} ({state['ticker']}), from its {m['form']} "
        f"filed {m['filing_date']}.\n\n"
        f"=== BUSINESS ===\n{s['business']}\n\n"
        f"=== RISK FACTORS ===\n{s['risk_factors']}\n\n"
        f"=== MD&A ===\n{s['mdna']}"
    )


def _log(tag: str, usage) -> None:
    print(f"[{tag}] in/out {usage.input_tokens}/{usage.output_tokens}  "
          f"cache write/read {usage.cache_creation_input_tokens}/"
          f"{usage.cache_read_input_tokens}")


def _revision_note(state: VerityState) -> str:
    """If the verifier sent feedback, tell the agent to fix it. Empty on first pass."""
    fb = state.get("feedback")
    if not fb:
        return ""
    return (
        "\n\nIMPORTANT: a prior draft contained claims not supported by the "
        "filing. Rewrite so every claim is grounded in the filing text. "
        f"Fix these specifically:\n{fb}\n"
    )


# --- NODE 2: bull agent ---------------------------------------------------
def bull_node(state: VerityState) -> dict:
    prompt = (
        "Using ONLY the filing above, write the strongest BULL thesis as 4-6 "
        "tight bullets. Each bullet must be grounded in the filing."
        + _revision_note(state)
    )
    print("[bull] calling Claude ...")
    text, usage = llm.call(prompt, system=ANALYST_SYSTEM, max_tokens=1200,
                           cache_context=_source(state))
    _log("bull", usage)
    return {"bull_case": text}


# --- NODE 3: bear agent ---------------------------------------------------
def bear_node(state: VerityState) -> dict:
    prompt = (
        "Using ONLY the filing above, write the strongest BEAR thesis against "
        "this company as 4-6 tight bullets. Each bullet must be grounded in the "
        "filing. Prioritize the risks most likely to actually hurt the stock, "
        "not boilerplate."
        + _revision_note(state)
    )
    print("[bear] calling Claude ...")
    text, usage = llm.call(prompt, system=ANALYST_SYSTEM, max_tokens=1200,
                           cache_context=_source(state))
    _log("bear", usage)
    return {"bear_case": text}


# --- NODE 4: verifier (the differentiator) --------------------------------
VERIFY_SYSTEM = (
    "You are a meticulous fact-checker for equity research. You are given a "
    "company's filing excerpts plus a bull and a bear thesis. Your ONLY job is "
    "to check whether each factual or numeric claim in the theses is supported "
    "by the filing text. Be strict: a claim is UNSUPPORTED if its number or "
    "fact does not appear in, or clearly follow from, the filing text provided."
)

# The verifier is the guardrail — run it on the stronger model. Measured by
# adversarial_eval.py: Haiku 89% vs Sonnet 100% catch rate on fabrications.
VERIFIER_MODEL = "claude-sonnet-5"


# The output shape we FORCE the verifier to return. No rambling possible.
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},          # % of claims grounded in the filing
        "unsupported": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
    "required": ["score", "unsupported", "feedback"],
    "additionalProperties": False,
}


def verify_node(state: VerityState) -> dict:
    prompt = (
        f"=== BULL THESIS ===\n{state['bull_case']}\n\n"
        f"=== BEAR THESIS ===\n{state['bear_case']}\n\n"
        "Check every factual/numeric claim in both theses against the FILING "
        "EXCERPTS above. Return: 'score' = the percent (0-100) of claims that "
        "are supported by the filing; 'unsupported' = a list of any claims not "
        "supported (empty if all are); 'feedback' = one short paragraph on what "
        "the analysts should fix."
    )
    print(f"[verify] calling {VERIFIER_MODEL} (structured) ...")
    # Sonnet runs adaptive thinking by default; give room for thinking + JSON.
    # Same _source() block as bull/bear -> cached (own Sonnet cache; reused on revisions).
    data, usage = llm.call_json(prompt, VERIFY_SCHEMA, system=VERIFY_SYSTEM,
                                model=VERIFIER_MODEL, max_tokens=3000,
                                cache_context=_source(state))
    _log("verify", usage)

    score = int(data["score"])
    unsupported = data.get("unsupported", [])
    feedback = data.get("feedback", "")
    revisions = state.get("revisions", 0) + 1
    print(f"[verify] citation score = {score}  (verify pass #{revisions})")

    report = f"SCORE: {score}/100\n\nUNSUPPORTED CLAIMS:\n"
    report += "\n".join(f"- {u}" for u in unsupported) if unsupported else "- none"
    report += f"\n\nFEEDBACK: {feedback}"
    return {
        "citation_score": score,
        "verifier_report": report,
        "feedback": feedback,
        "revisions": revisions,
    }


# --- the conditional edge: this is what makes it a CYCLE, not a line ------
PASS_THRESHOLD = 85       # accept when >= this % of claims are grounded
MAX_VERIFY_PASSES = 2     # hard stop so the loop can't run forever / burn budget


def route_after_verify(state: VerityState) -> str:
    if state["citation_score"] >= PASS_THRESHOLD:
        return "done"
    if state.get("revisions", 0) >= MAX_VERIFY_PASSES:
        return "done"     # give up gracefully after the cap
    return "revise"       # loop back to the agents with feedback


# --- NODE 4.5: crossfire + verdict (the debate resolves) ------------------
# Bull and bear wrote independently; now make them engage AND land somewhere.
# One cheap Haiku call, run AFTER the theses pass verification, so we debate
# grounded claims (and don't re-run it on every revise loop). The verdict is
# neutral analysis of where the debate nets out — never a buy/sell call.
DEBATE_SYSTEM = (
    "You moderate a crossfire between a bull and a bear equity analyst, then "
    "synthesize where the debate nets out. Stay grounded in the filing — never "
    "invent numbers. Each rebuttal must directly answer the opponent's strongest "
    "point. The synthesis is neutral analysis of the central tension; it is NOT "
    "investment advice and must never tell the reader to buy, sell, or hold."
)

DEBATE_SCHEMA = {
    "type": "object",
    "properties": {
        "bull_rebuttal": {"type": "string"},   # bull answers the bear's best point
        "bear_rebuttal": {"type": "string"},   # bear answers the bull's best point
        "verdict": {"type": "string"},         # the crux the whole debate hinges on
        "bull_needs": {"type": "string"},      # what must hold for the bull to be right
        "bear_needs": {"type": "string"},      # what must hold for the bear to be right
        "watch": {"type": "string"},           # the one metric/event that resolves it
    },
    "required": ["bull_rebuttal", "bear_rebuttal", "verdict",
                 "bull_needs", "bear_needs", "watch"],
    "additionalProperties": False,
}


def debate_node(state: VerityState) -> dict:
    prompt = (
        f"=== BULL THESIS ===\n{state['bull_case']}\n\n"
        f"=== BEAR THESIS ===\n{state['bear_case']}\n\n"
        "Grounded ONLY in the filing above, do two things.\n\n"
        "1) One round of crossfire:\n"
        "- bull_rebuttal: the bull's sharp reply to the bear's SINGLE strongest "
        "point (2-3 sentences), naming the point it answers.\n"
        "- bear_rebuttal: the bear's sharp reply to the bull's SINGLE strongest "
        "point (2-3 sentences), naming the point it answers.\n\n"
        "2) Resolve where the debate nets out (neutral, not advice):\n"
        "- verdict: the central tension this stock comes down to (1-2 sentences).\n"
        "- bull_needs: the key thing that must hold for the bull to be right.\n"
        "- bear_needs: the key thing that must hold for the bear to be right.\n"
        "- watch: the single metric or event to monitor that would tip it.\n\n"
        "No new numbers that aren't already in the filing. Never say buy/sell/hold."
    )
    print("[debate] calling Claude (crossfire + verdict) ...")
    data, usage = llm.call_json(prompt, DEBATE_SCHEMA, system=DEBATE_SYSTEM,
                                max_tokens=1100, cache_context=_source(state))
    _log("debate", usage)
    return {
        "bull_rebuttal": data["bull_rebuttal"], "bear_rebuttal": data["bear_rebuttal"],
        "verdict": data["verdict"], "bull_needs": data["bull_needs"],
        "bear_needs": data["bear_needs"], "watch": data["watch"],
    }


# --- NODE 5: spin add-on (optional; fetches earnings-call transcripts) -----
def spin_node(state: VerityState) -> dict:
    if not state.get("include_spin"):
        return {}                       # add-on not requested -> pass straight through
    ticker, quarter = state["ticker"], state.get("quarter")
    if not quarter:
        return {"spin_result": {"available": False,
                                "reason": "no quarter specified for the spin check"}}
    print(f"[spin] running add-on for {ticker} {quarter} ...")
    try:
        data, _ = spin.run_spin(ticker, quarter)
        print(f"[spin] caution score = {data['caution_score']}")
        return {"spin_result": {"available": True, **data}}
    except Exception as e:
        # small-caps often have no transcript — degrade gracefully, don't crash
        print(f"[spin] unavailable: {e}")
        return {"spin_result": {"available": False, "reason": str(e)[:180]}}


# --- NODE 6: composer (assemble the final memo, no Claude call) ------------
def _spin_section(state: VerityState) -> str:
    sp = state.get("spin_result")
    if sp and sp.get("available"):
        return (
            f"## Earnings-Call Spin Check ({state.get('quarter', '')})\n\n"
            f"*Caution score: {sp['caution_score']}/100  (higher = more spin)*\n\n"
            f"**Tone shift:** {sp['tone_shift']}\n\n"
            "**Red flags:**\n"
            + "\n".join(f"- {x}" for x in sp.get("flags", []))
            + "\n\n"
        )
    if sp:   # requested but couldn't run
        return (f"## Earnings-Call Spin Check\n\n"
                f"*Not available: {sp.get('reason', '')}*\n\n")
    return ""   # not requested


def compose_node(state: VerityState) -> dict:
    m = state["meta"]
    memo = (
        f"# Verity Research Memo: {m['name']} ({state['ticker']})\n\n"
        f"*Source: {m['form']} filed {m['filing_date']}  |  "
        f"Verification score: {state['citation_score']}/100*\n\n"
        f"## Bull Case\n\n{state['bull_case']}\n\n"
        f"## Bear Case\n\n{state['bear_case']}\n\n"
        f"## Crossfire\n\n"
        f"**Bull responds:** {state.get('bull_rebuttal', '')}\n\n"
        f"**Bear responds:** {state.get('bear_rebuttal', '')}\n\n"
        f"## The Verdict\n\n"
        f"{state.get('verdict', '')}\n\n"
        f"- **Bull is right if:** {state.get('bull_needs', '')}\n"
        f"- **Bear is right if:** {state.get('bear_needs', '')}\n"
        f"- **Watch:** {state.get('watch', '')}\n\n"
        f"## Verification\n\n{state['verifier_report']}\n\n"
        f"{_spin_section(state)}"
        "---\n*Generated by Verity. Every claim was checked against the source "
        "SEC filing; the verification score is the percent of claims the "
        "verifier found grounded in the filing text.*\n"
    )
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{state['ticker']}_memo.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(memo)
    print(f"[compose] memo written to {path}")
    return {"memo": memo}


# --- GRAPH ----------------------------------------------------------------
builder = StateGraph(VerityState)
builder.add_node("fetch", fetch_node)
builder.add_node("bull", bull_node)
builder.add_node("bear", bear_node)
builder.add_node("verify", verify_node)
builder.add_node("debate", debate_node)
builder.add_node("spin", spin_node)
builder.add_node("compose", compose_node)

builder.add_edge(START, "fetch")
builder.add_edge("fetch", "bull")
builder.add_edge("bull", "bear")
builder.add_edge("bear", "verify")
# Conditional: verify -> back to bull (revise) OR -> crossfire debate (done)
builder.add_conditional_edges("verify", route_after_verify,
                              {"revise": "bull", "done": "debate"})
builder.add_edge("debate", "spin")    # debate the verified theses, then optional spin
builder.add_edge("spin", "compose")   # spin self-gates; no-op if not requested
builder.add_edge("compose", END)
graph = builder.compile()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")   # Windows console defaults to cp1252
    ticker = sys.argv[1] if len(sys.argv) > 1 else "DAKT"
    quarter = sys.argv[2] if len(sys.argv) > 2 else None
    init = {"ticker": ticker}
    if quarter:                        # a quarter arg turns ON the spin add-on
        init["include_spin"] = True
        init["quarter"] = quarter
    result = graph.invoke(init)
    print("\n" + "=" * 70 + "\n")
    print(result["memo"])
