"""Eval runner — replays test conversations through the live agent and scores
replies with an LLM-as-a-Judge.

Run with:
    python -m evals.run_evals

STUB — implementation needed. Suggested approach:

1. Load `evals/test_conversations.json`.
2. For each case:
     - Build the graph (or hit the local /chat endpoint via httpx).
     - Invoke with the case messages.
     - Capture the final reply.
3. Score each reply:
     - Hard checks: every `must_mention` substring present (case-insensitive),
       no `must_not_mention` substring present.
     - LLM-as-a-Judge (Haiku): rate 1-5 on relevance, factuality (relative to
       the synthetic data), and tone. Use a strict JSON-only prompt.
4. Aggregate to evals/reports/<timestamp>.json:
     - pass_rate, mean_judge_score, per-case results, total cost.
5. Exit non-zero if pass_rate drops below ENV-configurable threshold (default 0.7).

Notes:
- Don't run evals against a production backend — use a local instance with a
  fresh DB, or import the graph directly.
- This file is the single hook for CI: a future GitHub Action runs `python -m evals.run_evals`
  on every PR that touches `backend/app/agent/`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_CASES_PATH = Path(__file__).resolve().parent / "test_conversations.json"


def main() -> int:
    cases = json.loads(_CASES_PATH.read_text())
    print(f"Loaded {len(cases)} eval cases.")
    print("Eval runner is a stub — implement scoring (see module docstring).")
    print("\nCase summary:")
    for c in cases:
        print(f"  - {c['id']:30s} category={c['category']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
