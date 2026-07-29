"""Step 1 — Seed persona generator.

Pulls persona records from the NVIDIA Nemotron-Personas-USA dataset by
UUID and writes to seed JSON files. This step performs no LLM generation —
it is a dataset lookup and field pass-through.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

STEP_DIR = Path(__file__).parent

REQUIRED_FIELDS = [
    "uuid",
    "professional_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "persona",
    "cultural_background",
    "skills_and_expertise",
    "skills_and_expertise_list",
    "hobbies_and_interests",
    "hobbies_and_interests_list",
    "career_goals_and_ambitions",
    "sex",
    "age",
    "marital_status",
    "education_level",
    "bachelors_field",
    "occupation",
    "city",
    "state",
    "zipcode",
    "country",
]


def fetch_record(uuid: str) -> dict[str, Any]:
    """Fetch a persona record from the Nemotron dataset by UUID.

    Requires the `datasets` library. Loads the dataset lazily so this module
    remains importable without the dependency when records are supplied from
    local fixtures instead.
    """
    from datasets import load_dataset  # type: ignore[import-not-found]

    ds = load_dataset("nvidia/Nemotron-Personas-USA", split="train")
    match = ds.filter(lambda row: row["uuid"] == uuid)
    if len(match) == 0:
        raise ValueError(f"UUID not found in dataset: {uuid}")
    return dict(match[0])

def fetch_selected(output_dir: Path) -> Path:
    from datasets import load_dataset

    selected_path = STEP_DIR / "selected_personas.json"

    ds = load_dataset("nvidia/Nemotron-Personas-USA", split="train")
    selected_personas = json.loads(selected_path.read_text(encoding="utf-8"))
    for seed_file in output_dir.glob("*_seed.json"):
        seed_file.unlink()
    match = ds.filter(lambda row: row["uuid"] in selected_personas)

    for row in match:
        emit_seed(row, output_dir)

    print(f"Seeded {len(match)} persona(s) from {selected_path}")
    return selected_path

def select_random(
    count: int,
    min_age: int,
    max_age: int,
    sex: list[str],
    marital_status: list[str],
    education_level: list[str],
    output_dir: str
) -> Path:
    from datasets import load_dataset

    ds = load_dataset("nvidia/Nemotron-Personas-USA", split="train")
    shuffled_data = ds.shuffle(seed=360)
    for seed_file in output_dir.glob("*_seed.json"):
        seed_file.unlink()
    selected_personas = {}
    
    for row in shuffled_data:
        try:
            selection_filter = [
                min_age <= row["age"] <= max_age,
                row["sex"] in sex,
                row["marital_status"] in marital_status,
                row["education_level"] in education_level,
            ]
            if all(selection_filter):
                output_path = emit_seed(row, output_dir)
                persona_name = output_path.stem.replace("_seed", "")
                selected_personas[row["uuid"]] = persona_name
            if len(selected_personas) == count:
                break
        except:
            continue
    
    sorted_personas = dict(sorted(selected_personas.items(), key=lambda item: item[1]))
    
    selected_path = STEP_DIR / "selected_personas.json"
    selected_path.write_text(
        json.dumps(sorted_personas, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Seeded {len(sorted_personas)} persona(s) listed at {selected_path}")
    return selected_path


def derive_filename(record: dict[str, Any]) -> str:
    persona_text = record.get("persona", "") or record.get("professional_persona", "")
    name_match = re.match(r"\s*([A-Z][a-z]+)\s+([A-Z][a-z]+)", persona_text)
    if not name_match:
        raise ValueError(f"A name cannot be found for this record. Retry with a different UUID.")
    first, last = name_match.group(1), name_match.group(2)
    return f"{first.lower()}_{last.lower()}_seed.json"


def emit_seed(record: dict[str, Any], output_dir: Path) -> Path:
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise ValueError(f"Dataset record missing required fields: {missing}")

    seed = {f: record[f] for f in REQUIRED_FIELDS}
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / derive_filename(record)
    output_path.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path

def list_seeded_personas(output_dir: Path = STEP_DIR / "data_samples") -> Path:
    # Create selected_personas.json from *_seed.json files

    selected_path = STEP_DIR / "selected_personas.json"
    selected_personas = {}

    for seed_file in output_dir.glob("*_seed.json"):
        persona_name = seed_file.stem.replace("_seed", "")
        record = json.loads(seed_file.read_text(encoding="utf-8"))
        selected_personas[record["uuid"]] = persona_name
    
    sorted_personas = dict(sorted(selected_personas.items(), key=lambda item: item[1]))

    selected_path.write_text(
        json.dumps(sorted_personas, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(sorted_personas)} persona(s) listed to {selected_path}")

    return selected_path


def fetch_single(uuid: str, output_dir: Path) -> Path:
    selected_path = STEP_DIR / "selected_personas.json"
    selected_personas = {}
    if selected_path.exists():
        selected_personas = json.loads(selected_path.read_text(encoding="utf-8"))
    record = fetch_record(uuid)
    path = emit_seed(record, output_dir)

    persona_name = path.stem.replace("_seed", "")
    selected_personas[record["uuid"]] = persona_name

    sorted_personas = dict(sorted(selected_personas.items(), key=lambda item: item[1]))

    selected_path.write_text(
        json.dumps(sorted_personas, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote seed: {path}")
    return path

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uuid", help="Persona UUID in Nemotron-Personas-USA")
    parser.add_argument(
        "--output",
        type=Path,
        default=STEP_DIR / "data_samples",
        help="Directory to write the seed JSON into",
    )
    parser.add_argument(
        "--use-selected",
        action="store_true",
        help="Generate seeds from step1_seed/selected_personas.json (overwrites existing seeds)",
    )
    parser.add_argument(
        "--random-count",
        type=int,
        default=30,
        help="Number of personas to randomly select and generate when --uuid and --use-selected are omitted (overwrites existing seeds)",
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=0,
        help="Minimum age for random selection pool",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=106,
        help="Maximum age for random selection pool",
    )
    parser.add_argument(
        "--sex",
        type=str,
        default=["Male", "Female"],
        nargs="+",
        choices=["Male", "Female"],
        help="Field filter (sex) for random selection pool",
    )
    parser.add_argument(
        "--marital-status",
        type=str,
        default=["never_married", "married_present", "divorced", "widowed", "separated"],
        nargs="+",
        choices=["never_married", "married_present", "divorced", "widowed", "separated"],
        help="Field filter (marital_status) for random selection pool",
    )
    parser.add_argument(
        "--education-level",
        type=str,
        default=["less_than_9th", "high_school", "some_college", "bachelors", "graduate", "associates", "9th_12th_no_diploma"],
        nargs="+",
        choices=["less_than_9th", "high_school", "some_college", "bachelors", "graduate", "associates", "9th_12th_no_diploma"],
        help="Field filter (education_level) for random selection pool",
    )
    
    args = parser.parse_args()

    if args.uuid:
        fetch_single(uuid=args.uuid, output_dir=args.output)
    elif args.use_selected:
        fetch_selected(args.output)
    else:
        select_random(
            args.random_count,
            args.min_age,
            args.max_age,
            args.sex,
            args.marital_status,
            args.education_level,
            args.output
        )

if __name__ == "__main__":
    main()
