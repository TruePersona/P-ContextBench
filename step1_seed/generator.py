"""Step 1 — Seed persona generator.

Pulls a single persona record from the NVIDIA Nemotron-Personas-USA dataset by
UUID and writes it to a seed JSON file. This step performs no LLM generation —
it is a dataset lookup and field pass-through.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline_integrity.artifacts import digest, write_json

DATASET_REVISION = "5b4cd35ab46490c1da1bd2b5a2324d6f871be180"

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


def fetch_record(uuid: str, revision: str = DATASET_REVISION) -> dict[str, Any]:
    """Fetch a persona record from the Nemotron dataset by UUID.

    Requires the `datasets` library. Loads the dataset lazily so this module
    remains importable without the dependency when records are supplied from
    local fixtures instead.
    """
    from datasets import load_dataset  # type: ignore[import-not-found]

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Dataset revision must be an immutable 40-character commit ID")
    ds = load_dataset("nvidia/Nemotron-Personas-USA", split="train", revision=revision)
    match = ds.filter(lambda row: row["uuid"] == uuid)
    if len(match) == 0:
        raise ValueError(f"UUID not found in dataset: {uuid}")
    record = dict(match[0])
    record["source_revision"] = revision
    return record


def derive_filename(record: dict[str, Any]) -> str:
    if not isinstance(record.get("uuid"), str) or not re.fullmatch(
        r"[A-Za-z0-9-]+", record["uuid"]
    ):
        raise ValueError("Seed UUID must be a safe nonempty identifier")
    persona_text = record.get("persona", "") or record.get("professional_persona", "")
    name_match = re.match(r"\s*([A-Z][a-z]+)\s+([A-Z][a-z]+)", persona_text)
    if not name_match:
        return f"{record['uuid']}_seed.json"
    first, last = name_match.group(1), name_match.group(2)
    return f"{first.lower()}_{last.lower()}_{record['uuid']}_seed.json"


def emit_seed(record: dict[str, Any], output_dir: Path) -> Path:
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise ValueError(f"Dataset record missing required fields: {missing}")

    seed = {f: record[f] for f in REQUIRED_FIELDS}
    seed["source"] = {
        "dataset": "nvidia/Nemotron-Personas-USA",
        "revision": record.get("source_revision"),
        "record_sha256": digest(seed),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / derive_filename(record)
    if output_path.exists():
        if json.loads(output_path.read_text(encoding="utf-8")) != seed:
            raise ValueError(
                "Seed identity already exists with different contents; use a new output directory"
            )
    else:
        write_json(output_path, seed, exclusive=True)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uuid", required=True, help="Persona UUID in Nemotron-Personas-USA")
    parser.add_argument("--dataset-revision", default=DATASET_REVISION)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "runs",
        help="Directory to write the seed JSON into",
    )
    args = parser.parse_args()

    record = fetch_record(args.uuid, args.dataset_revision)
    path = emit_seed(record, args.output)
    print(f"Wrote seed: {path}")


if __name__ == "__main__":
    main()
