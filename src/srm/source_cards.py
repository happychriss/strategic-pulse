"""Source cards: one structured YAML file per dataset.

A source card is the onboarding unit for new data. It records where a dataset lives,
how it may be used, how it is revised, and whether it can supply knowledge-time
(vintage) information. Cards later map one-to-one onto the `source` / `dataset` objects
in the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CARDS_DIR = Path(__file__).resolve().parents[2] / "sources"

ROLES = {"structural_indicator", "state_variable", "event", "context"}
VINTAGE_SUPPORT = {"none", "release_snapshots", "full_history"}
VERIFICATION = {"unverified", "verified"}
AUTH = {"none", "free_token", "registration", "paid"}

REQUIRED: dict[str, set[str]] = {
    "": {
        "id",
        "provider",
        "name",
        "role",
        "phase",
        "endpoint",
        "access",
        "coverage",
        "temporal",
        "python_access",
        "pitfalls",
        "verification",
        "docs_urls",
    },
    "endpoint": {"protocol", "base_url", "dataset_id"},
    "access": {"auth", "licence", "terms_url"},
    "coverage": {"geography", "frequency", "start"},
    "temporal": {"revision_policy", "vintage_support", "knowledge_time_basis"},
    "verification": {"status", "date", "note"},
}


@dataclass(frozen=True)
class Card:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]


def validate(data: dict[str, Any], filename_stem: str | None = None) -> list[str]:
    """Return a list of problems; an empty list means the card is valid."""
    problems: list[str] = []
    for section, keys in REQUIRED.items():
        node = data if section == "" else data.get(section)
        if section and not isinstance(node, dict):
            problems.append(f"missing section: {section}")
            continue
        for key in sorted(keys - set(node)):
            problems.append(f"missing key: {section + '.' if section else ''}{key}")
    if problems:
        return problems

    if filename_stem is not None and data["id"] != filename_stem:
        problems.append(f"id '{data['id']}' does not match filename '{filename_stem}'")
    if data["role"] not in ROLES:
        problems.append(f"role must be one of {sorted(ROLES)}")
    if data["access"]["auth"] not in AUTH:
        problems.append(f"access.auth must be one of {sorted(AUTH)}")
    if data["temporal"]["vintage_support"] not in VINTAGE_SUPPORT:
        problems.append(f"temporal.vintage_support must be one of {sorted(VINTAGE_SUPPORT)}")
    if data["verification"]["status"] not in VERIFICATION:
        problems.append(f"verification.status must be one of {sorted(VERIFICATION)}")
    if data["verification"]["status"] == "verified" and not data["verification"]["date"]:
        problems.append("verified cards need verification.date")
    if data["phase"] not in (1, 2, 3):
        problems.append("phase must be 1, 2 or 3")
    if not data["docs_urls"] or not all(str(u).startswith("https://") for u in data["docs_urls"]):
        problems.append("docs_urls must be a non-empty list of https URLs")
    return problems


def load_cards(directory: Path = CARDS_DIR) -> list[Card]:
    cards = []
    for path in sorted(directory.glob("*.yaml")):
        cards.append(Card(path=path, data=yaml.safe_load(path.read_text(encoding="utf-8"))))
    return cards


def main() -> int:
    bad = 0
    cards = load_cards()
    for card in cards:
        problems = validate(card.data, card.path.stem)
        status = card.data.get("verification", {}).get("status", "?")
        print(f"{'OK ' if not problems else 'BAD'} {card.path.stem:<34} [{status}]")
        for problem in problems:
            print(f"      - {problem}")
        bad += bool(problems)
    print(f"{len(cards)} cards, {bad} invalid")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
