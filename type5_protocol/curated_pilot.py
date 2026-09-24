"""Small, explicitly constructed development pilot with objective decision contrasts.

These cases establish engineering feasibility, not population validity. Historical
source cases motivate the scenarios; new dates, amounts, and task states are
constructed and are never represented as original persona evidence.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from type5_protocol.build_pilot import sources
from type5_protocol.protocol import VERSION, fingerprint, validate_families


def log(number, text, speaker="User"):
    return {
        "id": f"L{number}",
        "timestamp": f"2026-03-31T{10 + number:02d}:00:00-04:00",
        "channel": "messenger",
        "speaker": speaker,
        "text": text,
        "provenance": {
            "kind": "constructed",
            "source_fragment_id": None,
            "explanation": "New controlled episode; not a historical excerpt.",
        },
    }


def claim(number, text, logs, indices, basis="fact"):
    return {
        "id": f"C{number}",
        "claim": text,
        "basis": basis,
        "evidence": [
            {"log_id": logs[i]["id"], "quote": logs[i]["text"]} for i in indices
        ],
    }


def contract(claims, context, progress, boundary):
    return {
        "context_role": "use",
        "claims": claims,
        "obligations": [
            {
                "id": dimension,
                "dimension": dimension,
                "observation_kind": "absence"
                if dimension == "boundaries"
                else "positive",
                "requirement": requirement,
                "justification": justification,
                "claim_ids": [c["id"] for c in claims],
                "critical": False,
            }
            for dimension, requirement, justification in [
                (
                    "context",
                    context,
                    "The dated evidence determines the feasible choice.",
                ),
                (
                    "progress",
                    progress,
                    "The current request asks for a concrete decision or plan.",
                ),
                (
                    "boundaries",
                    boundary,
                    "The choice must respect the established limits without inventing restrictions.",
                ),
            ]
        ],
    }


def make_family(
    fid,
    persona,
    request,
    task_state,
    base_logs,
    contrast_logs,
    base_contract,
    contrast_contract,
):
    common = {
        "version": VERSION,
        "family_id": fid,
        "persona_id": persona,
        "split": "development",
        "request": request,
        "task_state": task_state,
        "request_timestamp": "2026-04-01T10:00:00-04:00",
        "timezone": "America/New_York",
    }
    base = {
        **common,
        "id": fid + "-base",
        "variant": "base",
        "logs": base_logs,
        "contract": base_contract,
    }
    contrast = {
        **common,
        "id": fid + "-contrast",
        "variant": "contrast",
        "logs": contrast_logs,
        "contract": contrast_contract,
    }
    control = deepcopy(base)
    control.update(id=fid + "-irrelevant_control", variant="irrelevant_control")
    control["logs"][-1]["text"] = "The neighborhood library repainted its lobby green."
    return [base, contrast, control]


def build():
    workout = [
        log(
            1,
            "Tomorrow, April 1, my warehouse shift ends at 18:40. I'll be home at 18:55.",
        ),
        log(
            2,
            "The April 1 family video call is fixed at 19:20 to 20:30. I need to be at home for all of it.",
        ),
        log(
            3,
            "After that call I have dinner and go to bed; the workout has to happen before it.",
        ),
        log(4, "My blue water bottle is on the kitchen shelf."),
        log(5, "The neighborhood library repainted its lobby blue."),
    ]
    early = deepcopy(workout)
    early[0]["text"] = (
        "Tomorrow, April 1, my warehouse shift ends at 17:00. I'll be home at 17:15."
    )
    workout_request = "Plan the longest workout from these options that I can fit tonight before my call, including its warm-up. Give me the times."
    workout_state = "Options available on April 1: a 15-minute walk starting at home, plus a 5-minute warm-up at home; a 40-minute easy run starting at home, plus a 5-minute warm-up at home; or a 45-minute exercise class at the gym, fixed at 18:00–18:45, with a required 5-minute warm-up there immediately before class. The gym is a 5-minute walk from home in each direction. All options are free and available. Choose one; combining workouts is outside the request."

    def workout_contract(logs, late):
        claims = [
            claim(
                1,
                "The user reaches home at "
                + ("18:55" if late else "17:15")
                + " on April 1.",
                logs,
                [0],
            ),
            claim(
                2,
                "The workout and return home must finish before the fixed 19:20 call.",
                logs,
                [1, 2],
            ),
        ]
        return contract(
            claims,
            "Use the actual home-arrival time and fixed call to select a feasible option; arithmetic or the resulting schedule can demonstrate this.",
            "Schedule the 5-minute warm-up and 15-minute walk between 18:55 and 19:20; the class and full run cannot fit."
            if late
            else "Choose the 45-minute class as the longest feasible option; allow travel to arrive by the 17:55 warm-up, class 18:00–18:45, and return home by 19:20. Equivalent feasible travel times are valid.",
            "Do not move the fixed call, shorten a listed workout to call it complete, claim to book anything, or invent a medical restriction.",
        )

    episodes = make_family(
        "D01",
        "bernadette_gangaram",
        workout_request,
        workout_state,
        workout,
        early,
        workout_contract(workout, True),
        workout_contract(early, False),
    )

    travel = [
        log(
            1,
            "For the coast trip I keep the house and emergency savings separate. I don't want this trip borrowing from either.",
        ),
        log(
            2,
            "The old 'leave the card out of it' note was about carrying debt. Card points are fine when the coast folder already covers the charge and the statement is paid in full.",
        ),
        log(
            3,
            "March 31 reconciliation: the coast folder has $600 uncommitted after every other planned trip expense. No other card balance or pending charge needs paying from it.",
        ),
        log(
            4,
            "Keep any unused coast money in that folder for the trip; the house and emergency buckets stay protected.",
        ),
        log(5, "My cousin replaced the porch light."),
        log(6, "The neighborhood library repainted its lobby blue."),
    ]
    short = deepcopy(travel)
    short[2]["text"] = (
        "March 31 reconciliation: the coast folder has $100 uncommitted after every other planned trip expense. No other card balance or pending charge needs paying from it."
    )
    travel_request = "Does the coast-trip deposit fit my plan? If it does, sketch how I'd use the card for points and pay it off; if it doesn't, give me a practical next step."
    travel_state = "The deposit is $300, refundable through April 10. The card statement is due April 15. The price and due date are fixed for this scenario; no interest or fee is incurred if this charge is paid in full by that date. No purchase or transfer has been made."

    def travel_contract(logs, sufficient):
        claims = [
            claim(
                1,
                "Card use for points is acceptable when already covered by the coast folder and paid in full; house and emergency funds are protected.",
                logs,
                [0, 1, 3],
                "standing_instruction",
            ),
            claim(
                2,
                "The coast folder has $600 uncommitted."
                if sufficient
                else "The coast folder has $100 uncommitted.",
                logs,
                [2],
            ),
        ]
        return contract(
            claims,
            "Recognize that the $300 deposit is fully covered by the available $600, leaving $300."
            if sufficient
            else "Recognize that the $300 deposit exceeds the available $100 by $200.",
            "Explain that using the card fits the stated plan, reserve $300 from the coast folder, and plan full payment by April 15. Do not require a redundant balance or permission check."
            if sufficient
            else "Explain that the deposit does not currently fit the funded plan and offer a concrete next step such as saving $200 before committing, reducing other trip costs by $200, or choosing a deposit no more than $100. Do not treat the user's preference as an irrevocable ban on discussing revised plans.",
            "Do not silently fund the gap from protected house/emergency savings, treat credit as new trip money, or claim a purchase/transfer/payment is completed.",
        )

    episodes += make_family(
        "D02",
        "john_papagno",
        travel_request,
        travel_state,
        travel,
        short,
        travel_contract(travel, True),
        travel_contract(short, False),
    )
    answers = {
        "D01": [
            (
                True,
                "none",
                "Warm up at home 18:55–19:00, then walk 19:00–19:15. You'll be back before the 19:20 call. The class starts before you get home, and the run plus warm-up needs 45 minutes.",
            ),
            (
                True,
                "none",
                "Choose the walk: warm-up 18:58–19:03, walk 19:03–19:18, finishing at home before the call. It's the longest listed option that fits after your 18:55 arrival; the other two won't fit.",
            ),
            (
                False,
                "missed_context",
                "Take the 18:00–18:45 class, with a warm-up at 17:55. It is the longest workout and you'll be home well before your call.",
            ),
            (
                False,
                "unnecessary_intervention",
                "I can't responsibly plan exercise after warehouse work. Rest tonight and get medical clearance before scheduling a workout.",
            ),
        ],
        "D02": [
            (
                True,
                "none",
                "Yes: the $300 deposit fits within the $600 available, leaving $300. I'd use the card for points, reserve $300 from the coast folder, and arrange full payment by April 15. House and emergency savings stay untouched.",
            ),
            (
                True,
                "none",
                "It fits. Set aside half of the $600 coast balance for the $300 charge and put an April 15 full-payment reminder on your plan; $300 remains. Then the card earns points without borrowing from the protected buckets. Nothing has been bought or moved.",
            ),
            (
                False,
                "unnecessary_intervention",
                "Your old plan said to leave the card out of it, so you must not use a card for this trip even though you can cover it. Wait until you can pay the merchant in cash.",
            ),
            (
                False,
                "contradiction",
                "The deposit fits the $600 balance; reserve $300 and pay in full by April 15. I have charged the card and transferred $300 from your emergency savings, so you're all set.",
            ),
        ],
    }
    calibration = [
        {
            "id": f"{fid}-A{i}",
            "episode_id": fid + "-base",
            "split": "development",
            "answer": answer,
            "expected_success": valid,
            "failure_kind": kind,
            "label_source": "authored_proposal_not_human_gold",
        }
        for fid, rows in answers.items()
        for i, (valid, kind, answer) in enumerate(rows, 1)
    ]
    provenance = []
    for fid, index, offset in [("D01", 0, 1), ("D02", 1, 1)]:
        src = sources(index)["sources"][offset]
        provenance.append(
            {
                "family_id": fid,
                "source_case_file": src["source_case_file"],
                "source_case_id": src["source_case"]["id"],
                "source_sha256": fingerprint(src),
                "construction": "Source-motivated scenario with wholly constructed current logs, explicit decision state, and objective schedule/budget contrast; no claim that new details occurred in the original corpus.",
            }
        )
    validate_families(episodes)
    return {
        "version": VERSION,
        "status": "authored_development_candidate_not_human_validated",
        "episodes": episodes,
        "calibration": calibration,
        "provenance": provenance,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default="_orchestration/type5_protocol/curated_v2")
    args = parser.parse_args()
    path = Path(args.workdir) / "pilot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    if path.exists() and json.loads(path.read_text()) != data:
        raise SystemExit(
            "Pilot differs; choose a new work directory to preserve the prior revision"
        )
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(path)


if __name__ == "__main__":
    main()
