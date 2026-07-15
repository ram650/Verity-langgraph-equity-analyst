"""
Lesson 1: the three mechanics of LangGraph, with NO AI yet.

We build a graph that takes a stock ticker, "fetches" a company profile
(stubbed for now), and writes a one-line summary. This is deliberately
boring so the plumbing is obvious. In Week 1 we swap the stub node for a
real bull agent that calls Claude on real SEC data.

Run it:  E:\\Verity\\backend\\.venv\\Scripts\\python.exe lesson1_graph.py
"""

from typing import TypedDict
from langgraph.graph import StateGraph, START, END


# 1) STATE -------------------------------------------------------------
# The state is the shared "whiteboard" that every node reads from and
# writes to. It is just a typed dict. Each node returns a PARTIAL update,
# and LangGraph merges it in. Think of keys as slots that get filled as
# the graph runs.
class ResearchState(TypedDict):
    ticker: str        # input: the stock we are researching
    profile: dict      # filled by the fetch node
    memo: str          # filled by the summary node


# 2) NODES -------------------------------------------------------------
# A node is just a function: it receives the current state and returns a
# dict with the slots it wants to update. It does NOT mutate state in
# place; it returns the change.

def fetch_profile(state: ResearchState) -> dict:
    ticker = state["ticker"]
    print(f"[fetch_profile] looking up {ticker} ...")
    # Stub. Later this becomes a real SEC EDGAR call.
    fake = {
        "name": f"{ticker} Industries Inc.",
        "sector": "Industrials",
        "revenue_musd": 42.0,
        "employees": 310,
    }
    return {"profile": fake}          # only updates the 'profile' slot


def write_summary(state: ResearchState) -> dict:
    p = state["profile"]              # reads what the previous node wrote
    print("[write_summary] composing memo ...")
    memo = (
        f"{p['name']} is a {p['sector'].lower()} company with "
        f"${p['revenue_musd']}M revenue and {p['employees']} employees."
    )
    return {"memo": memo}             # only updates the 'memo' slot


# 3) GRAPH -------------------------------------------------------------
# We register the nodes, then wire the edges that define the order of
# execution: START -> fetch_profile -> write_summary -> END.
builder = StateGraph(ResearchState)
builder.add_node("fetch_profile", fetch_profile)
builder.add_node("write_summary", write_summary)

builder.add_edge(START, "fetch_profile")
builder.add_edge("fetch_profile", "write_summary")
builder.add_edge("write_summary", END)

graph = builder.compile()            # turns the blueprint into a runnable


# 4) RUN ---------------------------------------------------------------
if __name__ == "__main__":
    # We invoke with the initial state (just the ticker). LangGraph runs
    # each node in order, threading the state through, and returns the
    # final state with every slot filled.
    result = graph.invoke({"ticker": "ACME"})
    print("\n--- FINAL STATE ---")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("\nMEMO:", result["memo"])
