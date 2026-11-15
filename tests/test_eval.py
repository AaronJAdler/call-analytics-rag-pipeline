"""The full evaluation, run once (about 40 seconds), checked against the committed report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from callrag import evaluate

DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.fixture(scope="module")
def summary() -> dict[str, Any]:
    return json.loads(json.dumps(evaluate.run()))


def test_committed_report_matches_a_fresh_run(summary: dict[str, Any]) -> None:
    assert json.loads((DOCS / "eval.json").read_text(encoding="utf-8")) == summary
    assert (DOCS / "eval.md").read_text(encoding="utf-8") == evaluate.render(summary)


def test_no_search_returned_another_tenants_data(summary: dict[str, Any]) -> None:
    isolation = summary["isolation"]
    assert isolation["results_from_another_tenant_with_filter"] == 0
    assert isolation["queries_exposed_without_filter"] > 0  # so the filter is doing real work


def test_redaction_misses_are_exactly_the_documented_forms(summary: dict[str, Any]) -> None:
    missed = {
        (row["kind"], row["form"])
        for row in summary["redaction"]["by_form"]
        if row["removed"] < row["planted"]
    }
    assert missed == {
        ("NAME", "third person named with no cue"),
        ("ADDRESS", "described without a number"),
    }
    for row in summary["redaction"]["by_form"]:
        if (row["kind"], row["form"]) in missed:
            assert row["removed"] == 0
    # What the index scan finds is the same set: nothing leaked that the scoring missed.
    assert {(r["kind"], r["form"]) for r in summary["index_scan"]["by_form"]} == missed
    planted, removed = summary["redaction"]["planted"], summary["redaction"]["removed"]
    assert summary["index_scan"]["values_found"] == planted - removed


def test_false_redactions_are_only_serial_numbers(summary: dict[str, Any]) -> None:
    wrong = summary["redaction"]["false_redactions"]
    assert [(w["placeholder"], w["rule"]) for w in wrong] == [("PHONE", "phone number")]
    assert all(len(e) == 10 and e.isdigit() for e in wrong[0]["examples"])


def test_incremental_sync_does_only_the_changed_work(summary: dict[str, Any]) -> None:
    inc = summary["incremental"]
    day_two = inc["day_two"]
    assert (day_two["added"], day_two["updated"], day_two["unchanged"], day_two["tombstoned"]) == (
        60, 30, 495, 15,
    )  # fmt: skip
    assert day_two["texts_embedded"] < inc["full_rebuild_would_embed"] / 5
    assert inc["rerun"]["texts_embedded"] == 0
    assert inc["chunks_of_erased_calls_remaining"] == 0
    assert inc["chunk_table_versions_after_purge"] == 1
    assert inc["masked_rows_before_purge"] > 0 == inc["masked_rows_after_purge"]


def test_keyword_search_works_and_redaction_costs_it_little(summary: dict[str, Any]) -> None:
    redacted = summary["retrieval"]["redacted"]["keyword"]
    unredacted = summary["retrieval"]["unredacted"]["keyword"]
    assert redacted["hit_at_5"] / redacted["queries"] >= 0.95
    assert abs(redacted["hit_at_5"] - unredacted["hit_at_5"]) <= 3
