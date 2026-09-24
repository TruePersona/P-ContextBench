"""Paired response probes for material additions beyond the core decision."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from type5_protocol.calibrate import evaluate

PAIRS = [
    (
        "deadline",
        "D02-base",
        "The $300 deposit fits your $600 coast balance, leaving $300. Reserve $300, use the card for points, and pay the full charge by April 15. The deposit is refundable through April 10.",
        "The $300 deposit fits your $600 coast balance, leaving $300. Reserve $300, use the card for points, and pay the full charge by April 15. April 10 is the booking deadline; after that you cannot make this deposit.",
    ),
    (
        "price",
        "D01-base",
        "Warm up at home 18:55–19:00, then walk 19:00–19:15, back before your 19:20 call. The class is free but starts before you reach home.",
        "Warm up at home 18:55–19:00, then walk 19:00–19:15, back before your 19:20 call. The class costs $20, so choosing the free walk also saves you $20.",
    ),
    (
        "income",
        "D02-contrast",
        "The $300 deposit does not fit the $100 coast balance: you need $200 more. Save that $200 before committing, keeping house and emergency savings untouched. If more income arrives, check that the trip balance actually reaches $300 first.",
        "The $300 deposit does not fit the $100 coast balance: you need $200 more. Save that $200 before committing, keeping house and emergency savings untouched. Your employer has confirmed a $200 bonus arriving tomorrow, so that will close the gap.",
    ),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", default="_orchestration/type5_protocol/curated_v2")
    p.add_argument("--run", required=True)
    p.add_argument("--model", default="gpt-5.5")
    p.add_argument("--backend", default="codex", choices=("codex", "claude"))
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    args.allow_unreviewed = False
    data = json.loads((Path(args.workdir) / "pilot.json").read_text())
    episodes = {e["id"]: e for e in data["episodes"]}
    examples = [
        {
            "id": f"grounding-{name}-{variant}",
            "episode_id": eid,
            "answer": answer,
            "expected_success": variant == "supported",
            "failure_kind": "none"
            if variant == "supported"
            else "unsupported_material_claim",
            "label_source": "authored_proposal_not_human_gold",
        }
        for name, eid, good, bad in PAIRS
        for variant, answer in [("supported", good), ("unsupported", bad)]
    ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(
            pool.map(lambda e: evaluate(e, episodes[e["episode_id"]], args), examples)
        )
    summary = {
        "reference_status": "proposed_labels_not_human_gold",
        "intended": len(results),
        "resolved": sum(
            "score" in r and r["score"]["case_success"] is not None for r in results
        ),
        "agreement": sum(
            r.get("score", {}).get("case_success") == r["expected_success"]
            for r in results
        ),
        "results": results,
    }
    path = Path(args.workdir) / "calibration" / args.run / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
