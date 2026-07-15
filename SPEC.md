# Verity — a verifiable small-cap equity research agent

**One line:** A multi-agent system that produces a bull/bear research memo on an
under-covered small-cap stock, where a verifier agent refuses to let any claim ship
unless it is traceable to a real SEC filing.

**The wedge (why it is not a tutorial clone):** Aimed at small-caps with zero analyst
coverage (a real gap), and verifiability is the product, not the memo. Trust is the
unsolved problem in AI finance, so we make "zero unsupported claims" the headline.

## The problem (mini-PRD)
- **User:** a retail investor or aspiring analyst researching a small-cap with no Wall Street coverage.
- **Pain today:** they either get nothing, or a confident AI summary that quietly hallucinates numbers they cannot trust with real money.
- **Job to be done:** "Give me a balanced, cited view of this company where I can click every claim back to the source."

## Scope
- **v1 (build + learn first):** bull agent, bear agent, verifier agent, one small-cap at a time, output a cited memo.
- **v2 module:** earnings-call spin detector (compare this call to prior calls, flag evasiveness and tone shifts). Bolt-on, not v1.

## The agents
| Agent | Job | Reads / writes |
|---|---|---|
| Supervisor | Routes the flow, decides when the debate is done | Orchestrates state |
| Bull | Builds the strongest positive thesis from filings | bull_case, bull_evidence |
| Bear | Builds the strongest risk/negative thesis | bear_case, bear_evidence |
| Verifier (3rd agent) | Extracts every claim, checks each against source, hard-fails or loops back uncited claims | citation_score, loop-back |
| Composer | Assembles final memo with inline citations | memo |
| Spin Detector (v2) | Compares current earnings call to prior quarters, flags hedging/evasiveness | separate transcript pipeline |

## Architecture (LangGraph)
`intake -> retriever (EDGAR) -> [bull || bear] -> verifier -> (fail? loop back : pass) -> composer -> memo`
The verifier's conditional loop-back is a real cycle, not a straight line.

## Data
- SEC EDGAR API (free, public): 10-K / 10-Q / 8-K filings. No faked data.
- v2: earnings-call transcripts (public sources).

## Success metrics
- Citation coverage % (claims with a valid source / total claims) — headline metric
- Hallucination rate (unsupported claims per memo) — target near zero
- Memo quality via an LLM-judge rubric
- Time-to-memo

## Stack
Python, LangGraph + LangChain, Claude (Sonnet 5 for agents, Haiku 4.5 for cheap
sub-steps), SEC EDGAR API, Streamlit for a fast UI (or React), LangGraph checkpointer
for state.

## Timeline (part-time, learn-as-we-build)
- Week 1 (~15 hrs): LangGraph basics, EDGAR ingestion, bull agent end to end.
- Week 2 (~15 hrs): bear agent, supervisor routing, verifier with loop-back cycle.
- Week 3 (~15 hrs): composer, eval harness, Streamlit UI, deploy, PRD + demo writeup.
- Week 4 (optional, ~10 hrs): spin detector v2.

## Agent complexity (first-timer view)
| Agent | Difficulty | Teaches |
|---|---|---|
| Bull | Easy | Nodes, state schema, prompting, tool binding |
| Bear | Easy | Opposing agents sharing state |
| Supervisor | Medium | StateGraph control flow, routing |
| Verifier | Medium-Hard | Structured output, claim extraction, grounding, cycles |
| Composer | Easy-Medium | Assembling state into an artifact |
| Spin Detector (v2) | Medium-Hard | RAG over transcripts, temporal comparison |

## PM discipline note
Ship v1 (bull/bear/verifier) before touching the spin detector. Building spin first is
the scope trap that kills side projects. Sequencing is itself a good PM story.
