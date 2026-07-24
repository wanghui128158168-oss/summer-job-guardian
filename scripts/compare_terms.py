#!/usr/bin/env python3
"""Strictly compare normalized job terms across successive evidence stages."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from typing import Any


EXAMPLE = {
    "stages": [
        {
            "name": "Recruitment ad",
            "terms": {
                "job_title": "Subway security screening",
                "work_location": "Beijing",
                "monthly_wage": 5500,
                "fees": [],
                "required_certificates": [],
                "training_paid": True
            }
        },
        {
            "name": "Arrival instructions",
            "terms": {
                "job_title": "Security guard placement pending",
                "work_location": "Another site",
                "monthly_wage": 5500,
                "fees": [{"type": "medical exam", "amount": 328}],
                "required_certificates": ["security screening certificate", "security guard certificate"],
                "training_paid": False
            }
        }
    ]
}


class InputError(ValueError):
    """Raised when comparison input is malformed."""


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _canonical(value: Any) -> str:
    if isinstance(value, str):
        value = value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise InputError("input must be a JSON object")
    stages = document.get("stages")
    if not isinstance(stages, list) or len(stages) < 2:
        raise InputError("input.stages must contain at least two stages")

    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, stage in enumerate(stages):
        path = f"stages[{index}]"
        if not isinstance(stage, dict):
            raise InputError(f"{path} must be an object")
        name = stage.get("name")
        terms = stage.get("terms")
        if not isinstance(name, str) or not name.strip():
            raise InputError(f"{path}.name must be a non-empty string")
        clean_name = name.strip()
        if clean_name in names:
            raise InputError(f"stage names must be unique: {clean_name}")
        if not isinstance(terms, dict):
            raise InputError(f"{path}.terms must be an object")
        for field in terms:
            if not isinstance(field, str) or not field.strip():
                raise InputError(f"{path}.terms keys must be non-empty strings")
        names.add(clean_name)
        normalized.append({"name": clean_name, "terms": terms})
    return normalized


def compare_document(document: Any) -> dict[str, Any]:
    stages = _validate(document)
    fields = sorted({field for stage in stages for field in stage["terms"]})
    comparisons: list[dict[str, Any]] = []

    for field in fields:
        values: list[dict[str, Any]] = []
        present_indices: list[int] = []
        canonical_values: list[str] = []
        for index, stage in enumerate(stages):
            value = stage["terms"].get(field)
            missing = field not in stage["terms"] or _is_missing(value)
            values.append({
                "stage": stage["name"],
                "value": None if missing else value,
                "missing": missing,
            })
            if not missing:
                present_indices.append(index)
                canonical_values.append(_canonical(value))

        if not present_indices:
            status = "missing"
            first_seen = None
            introduced_later = False
            missing_after_introduction = False
            changed = False
        else:
            first_index = present_indices[0]
            first_seen = stages[first_index]["name"]
            introduced_later = first_index > 0
            missing_after_introduction = any(
                values[index]["missing"] for index in range(first_index + 1, len(values))
            )
            changed = len(set(canonical_values)) > 1
            if changed:
                status = "changed"
            elif missing_after_introduction:
                status = "missing_later"
            elif introduced_later:
                status = "introduced_later"
            else:
                status = "consistent"

        comparisons.append({
            "field": field,
            "status": status,
            "first_seen_stage": first_seen,
            "introduced_later": introduced_later,
            "missing_after_introduction": missing_after_introduction,
            "changed": changed,
            "values": values,
        })

    summary = {
        "consistent": sum(item["status"] == "consistent" for item in comparisons),
        "changed": sum(item["status"] == "changed" for item in comparisons),
        "introduced_later": sum(item["status"] == "introduced_later" for item in comparisons),
        "missing_later": sum(item["status"] == "missing_later" for item in comparisons),
        "missing": sum(item["status"] == "missing" for item in comparisons),
    }
    attention_fields = [
        item["field"]
        for item in comparisons
        if item["status"] != "consistent"
        or item["introduced_later"]
        or item["missing_after_introduction"]
    ]

    return {
        "stage_order": [stage["name"] for stage in stages],
        "summary": summary,
        "attention_fields": attention_fields,
        "fields": comparisons,
        "warnings": [
            "This is a literal comparison of normalized inputs, not a legal or safety judgment.",
            "Equivalent terms written in different units or language must be normalized before comparison.",
            "A missing value means the supplied evidence did not state it; it does not prove the term did not exist."
        ],
    }


def _load_json(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"could not read valid JSON: {exc}") from exc


class ComparisonTests(unittest.TestCase):
    def test_detects_changes_and_late_terms(self) -> None:
        result = compare_document(EXAMPLE)
        by_field = {item["field"]: item for item in result["fields"]}
        self.assertEqual(by_field["monthly_wage"]["status"], "consistent")
        self.assertEqual(by_field["work_location"]["status"], "changed")
        self.assertEqual(by_field["training_paid"]["status"], "changed")
        self.assertEqual(by_field["fees"]["status"], "introduced_later")
        self.assertTrue(by_field["fees"]["introduced_later"])

    def test_detects_missing_later(self) -> None:
        document = {
            "stages": [
                {"name": "Ad", "terms": {"pay_date": "15th", "wage": 200}},
                {"name": "Contract", "terms": {"wage": 200}},
            ]
        }
        by_field = {
            item["field"]: item
            for item in compare_document(document)["fields"]
        }
        self.assertEqual(by_field["pay_date"]["status"], "missing_later")

    def test_marks_changed_after_late_introduction(self) -> None:
        document = {
            "stages": [
                {"name": "Ad", "terms": {}},
                {"name": "Chat", "terms": {"fee": 100}},
                {"name": "Arrival", "terms": {"fee": 300}},
            ]
        }
        item = compare_document(document)["fields"][0]
        self.assertEqual(item["status"], "changed")
        self.assertTrue(item["introduced_later"])

    def test_rejects_duplicate_stage_names(self) -> None:
        document = {
            "stages": [
                {"name": "Chat", "terms": {}},
                {"name": "Chat", "terms": {}},
            ]
        }
        with self.assertRaises(InputError):
            compare_document(document)

    def test_rejects_single_stage(self) -> None:
        with self.assertRaises(InputError):
            compare_document({"stages": [{"name": "Ad", "terms": {}}]})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="JSON file path, or - for stdin")
    group.add_argument("--example", action="store_true", help="print an example input document")
    group.add_argument("--self-test", action="store_true", help="run bundled tests")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.example:
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2))
        return 0
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ComparisonTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1

    try:
        output = compare_document(_load_json(args.input))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
