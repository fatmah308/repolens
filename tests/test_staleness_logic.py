"""Dedicated tests for compute_stale_prs: the staleness-threshold logic.

flag_stale_prs is the tool whose value-add is real computation rather than
an API passthrough, so its pure logic function gets its own focused test
module covering boundary conditions, sorting, and input validation - fully
deterministic (a fixed `now` is always passed in) and with no network layer
involved at all, on top of the network-level tests in test_pull_requests.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from repolens.tools.pull_requests import compute_stale_prs

NOW = datetime(2024, 6, 15, tzinfo=timezone.utc)


def _pr(number, days_ago, state="open"):
    updated_at = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "number": number,
        "title": f"PR #{number}",
        "state": state,
        "updated_at": updated_at,
        "user": {"login": "someone"},
        "html_url": f"https://github.com/o/r/pull/{number}",
    }


def test_prs_within_threshold_are_not_flagged():
    prs = [_pr(1, days_ago=5)]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert result == []


def test_prs_past_threshold_are_flagged():
    prs = [_pr(1, days_ago=20)]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert len(result) == 1
    assert result[0]["number"] == 1
    assert result[0]["days_inactive"] == 20


def test_exact_boundary_is_not_flagged():
    """A PR updated *exactly* stale_after_days ago is not yet stale.

    The tool's contract is "no activity past the threshold" - strictly
    greater than, not greater-or-equal - so day 14 itself is still fine
    and day 15 is the first stale day.
    """
    prs = [_pr(1, days_ago=14)]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert result == []


def test_one_day_past_boundary_is_flagged():
    prs = [_pr(1, days_ago=15)]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert len(result) == 1
    assert result[0]["number"] == 1


def test_closed_prs_are_never_flagged_regardless_of_age():
    prs = [_pr(1, days_ago=365, state="closed")]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert result == []


def test_results_sorted_most_stale_first():
    prs = [
        _pr(1, days_ago=20),  # mildly stale
        _pr(2, days_ago=100),  # very stale
        _pr(3, days_ago=15),  # barely stale
    ]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert [pr["number"] for pr in result] == [2, 1, 3]
    assert [pr["days_inactive"] for pr in result] == [100, 20, 15]


def test_default_threshold_is_14_days():
    prs = [_pr(1, days_ago=15), _pr(2, days_ago=13)]

    result = compute_stale_prs(prs, now=NOW)  # no stale_after_days passed

    assert [pr["number"] for pr in result] == [1]


def test_zero_day_threshold_flags_any_inactivity():
    prs = [_pr(1, days_ago=1)]

    result = compute_stale_prs(prs, stale_after_days=0, now=NOW)

    assert len(result) == 1


def test_negative_threshold_raises_value_error():
    with pytest.raises(ValueError):
        compute_stale_prs([_pr(1, days_ago=1)], stale_after_days=-1, now=NOW)


def test_missing_updated_at_is_skipped_not_crashed():
    prs = [{"number": 1, "state": "open", "title": "no timestamp"}]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert result == []


def test_empty_pr_list_returns_empty():
    assert compute_stale_prs([], stale_after_days=14, now=NOW) == []


def test_output_includes_author_and_url():
    prs = [_pr(1, days_ago=20)]

    result = compute_stale_prs(prs, stale_after_days=14, now=NOW)

    assert result[0]["author"] == "someone"
    assert result[0]["url"] == "https://github.com/o/r/pull/1"
