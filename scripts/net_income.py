#!/usr/bin/env python3
"""Compare known net-income scenarios without inventing missing assumptions."""

from __future__ import annotations

import argparse
import json
import math
import sys
import unittest
from pathlib import Path
from typing import Any


EXAMPLE = {
    "currency": "CNY",
    "period": "2026-07-20 to 2026-08-20",
    "scenarios": [
        {
            "name": "Self-rent plus flexible gigs",
            "gross_income": 7800,
            "income_realization_rate": 0.8,
            "downside_income_realization_rate": 0.5,
            "work_days": 24,
            "total_work_hours": 192,
            "recurring_costs": {
                "rent": 1200,
                "food": 1200,
                "utilities": 200,
                "commute": 360
            },
            "one_time_costs": {
                "travel": 300,
                "bedding": 120
            },
            "refundable_cash_locked": {
                "housing_deposit": 1200
            },
            "costs_due_before_first_payday": {
                "housing_payment": 2400,
                "travel": 300,
                "first_week_food_and_commute": 400
            },
            "assumptions": [
                "Gross income is the sum of gigs that could be booked in the period.",
                "The expected case realizes 80% of that advertised opportunity value."
            ],
            "sources": [
                {
                    "label": "Current housing listing sample",
                    "url": "https://example.invalid/replace-with-real-source",
                    "accessed": "2026-07-16"
                }
            ]
        }
    ]
}


class InputError(ValueError):
    """Raised when a scenario input is incomplete or misleading."""


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise InputError(f"{path} must be finite")
    if positive and number <= 0:
        raise InputError(f"{path} must be greater than zero")
    if not positive and number < 0:
        raise InputError(f"{path} must not be negative")
    return number


def _rate(value: Any, path: str) -> float:
    rate = _number(value, path)
    if rate > 1:
        raise InputError(f"{path} must be between 0 and 1")
    return rate


def _money_map(value: Any, path: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise InputError(f"{path} must be an object, even when empty")
    normalized: dict[str, float] = {}
    for key, amount in value.items():
        if not isinstance(key, str) or not key.strip():
            raise InputError(f"{path} keys must be non-empty strings")
        normalized[key.strip()] = _number(amount, f"{path}.{key}")
    return normalized


def _required(data: dict[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise InputError(f"{path}.{key} is required; provide an explicit value")
    return data[key]


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def calculate_scenario(scenario: Any, index: int) -> dict[str, Any]:
    path = f"scenarios[{index}]"
    if not isinstance(scenario, dict):
        raise InputError(f"{path} must be an object")

    name = _required(scenario, "name", path)
    if not isinstance(name, str) or not name.strip():
        raise InputError(f"{path}.name must be a non-empty string")

    gross_income = _number(_required(scenario, "gross_income", path), f"{path}.gross_income")
    expected_rate = _rate(
        _required(scenario, "income_realization_rate", path),
        f"{path}.income_realization_rate",
    )
    downside_rate = _rate(
        _required(scenario, "downside_income_realization_rate", path),
        f"{path}.downside_income_realization_rate",
    )
    if downside_rate > expected_rate:
        raise InputError(
            f"{path}.downside_income_realization_rate must not exceed the expected rate"
        )

    work_days = _number(_required(scenario, "work_days", path), f"{path}.work_days", positive=True)
    total_hours = _number(
        _required(scenario, "total_work_hours", path),
        f"{path}.total_work_hours",
        positive=True,
    )
    recurring = _money_map(
        _required(scenario, "recurring_costs", path),
        f"{path}.recurring_costs",
    )
    one_time = _money_map(
        _required(scenario, "one_time_costs", path),
        f"{path}.one_time_costs",
    )
    locked = _money_map(
        _required(scenario, "refundable_cash_locked", path),
        f"{path}.refundable_cash_locked",
    )
    due_before_payday = _money_map(
        _required(scenario, "costs_due_before_first_payday", path),
        f"{path}.costs_due_before_first_payday",
    )

    expected_income = gross_income * expected_rate
    downside_income = gross_income * downside_rate
    recurring_total = sum(recurring.values())
    one_time_total = sum(one_time.values())
    expense_total = recurring_total + one_time_total
    locked_total = sum(locked.values())
    minimum_cash = sum(due_before_payday.values())
    expected_net = expected_income - expense_total
    downside_net = downside_income - expense_total
    expected_daily_income = expected_income / work_days
    break_even_days = None if expected_daily_income == 0 else expense_total / expected_daily_income

    assumptions = scenario.get("assumptions", [])
    sources = scenario.get("sources", [])
    if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
        raise InputError(f"{path}.assumptions must be a list of strings")
    if not isinstance(sources, list) or not all(isinstance(item, dict) for item in sources):
        raise InputError(f"{path}.sources must be a list of objects")

    return {
        "name": name.strip(),
        "inputs": {
            "gross_income": _rounded(gross_income),
            "expected_income_realization_rate": expected_rate,
            "downside_income_realization_rate": downside_rate,
            "work_days": _rounded(work_days),
            "total_work_hours": _rounded(total_hours),
            "recurring_costs": recurring,
            "one_time_costs": one_time,
            "refundable_cash_locked": locked,
            "costs_due_before_first_payday": due_before_payday,
        },
        "results": {
            "expected_income": _rounded(expected_income),
            "downside_income": _rounded(downside_income),
            "recurring_cost_total": _rounded(recurring_total),
            "one_time_cost_total": _rounded(one_time_total),
            "total_expense": _rounded(expense_total),
            "expected_net_income": _rounded(expected_net),
            "downside_net_income": _rounded(downside_net),
            "expected_effective_hourly_net": _rounded(expected_net / total_hours),
            "downside_effective_hourly_net": _rounded(downside_net / total_hours),
            "refundable_cash_locked": _rounded(locked_total),
            "minimum_known_cash_before_first_payday": _rounded(minimum_cash),
            "expected_break_even_work_days": _rounded(break_even_days),
        },
        "assumptions": assumptions,
        "sources": sources,
        "warnings": [
            "The calculator verifies arithmetic, not whether the assumptions or sources are true.",
            "Refundable cash is excluded from expense but may remain at risk or unavailable.",
            "Costs due before first payday are a liquidity view and may overlap with listed expenses."
        ],
    }


def calculate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise InputError("input must be a JSON object")
    currency = _required(document, "currency", "input")
    if not isinstance(currency, str) or not currency.strip():
        raise InputError("input.currency must be a non-empty string")
    scenarios = _required(document, "scenarios", "input")
    if not isinstance(scenarios, list) or not scenarios:
        raise InputError("input.scenarios must be a non-empty list")

    results = [calculate_scenario(item, index) for index, item in enumerate(scenarios)]
    return {
        "currency": currency.strip(),
        "period": document.get("period"),
        "scenario_count": len(results),
        "scenarios": results,
    }


def _load_json(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"could not read valid JSON: {exc}") from exc


class CalculatorTests(unittest.TestCase):
    def test_fixed_job_math(self) -> None:
        document = {
            "currency": "CNY",
            "scenarios": [{
                "name": "Fixed job",
                "gross_income": 6000,
                "income_realization_rate": 1,
                "downside_income_realization_rate": 0.8,
                "work_days": 24,
                "total_work_hours": 240,
                "recurring_costs": {"food": 600},
                "one_time_costs": {"travel": 200},
                "refundable_cash_locked": {},
                "costs_due_before_first_payday": {"travel": 200},
            }],
        }
        result = calculate_document(document)["scenarios"][0]["results"]
        self.assertEqual(result["expected_net_income"], 5200.0)
        self.assertEqual(result["expected_effective_hourly_net"], 21.67)
        self.assertEqual(result["expected_break_even_work_days"], 3.2)

    def test_downside_flexible_work(self) -> None:
        scenario = EXAMPLE["scenarios"][0]
        result = calculate_scenario(scenario, 0)["results"]
        self.assertEqual(result["expected_net_income"], 2860.0)
        self.assertEqual(result["downside_net_income"], 520.0)
        self.assertEqual(result["refundable_cash_locked"], 1200.0)
        self.assertEqual(result["minimum_known_cash_before_first_payday"], 3100.0)

    def test_rejects_negative_cost(self) -> None:
        scenario = dict(EXAMPLE["scenarios"][0])
        scenario["one_time_costs"] = {"travel": -1}
        with self.assertRaises(InputError):
            calculate_scenario(scenario, 0)

    def test_rejects_zero_hours(self) -> None:
        scenario = dict(EXAMPLE["scenarios"][0])
        scenario["total_work_hours"] = 0
        with self.assertRaises(InputError):
            calculate_scenario(scenario, 0)

    def test_requires_explicit_cost_maps(self) -> None:
        scenario = dict(EXAMPLE["scenarios"][0])
        del scenario["recurring_costs"]
        with self.assertRaises(InputError):
            calculate_scenario(scenario, 0)


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
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CalculatorTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1

    try:
        output = calculate_document(_load_json(args.input))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
