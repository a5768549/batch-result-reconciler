import hashlib
import importlib.util


def test_multivalue_selection_reports_not_returned_without_expanding(tmp_path):
    from batch_result_reconciler import create_snapshot, reconcile

    rows = [{"row_id": "row-a", "values": ["item-a", "item-b", "item-skipped"],
             "payload": ["任意", {"nested": [True, None, 1.5]}]}]
    snapshot = create_snapshot(tmp_path / "submission.sqlite3", rows,
                               [("row-a", "item-a"), ("row-a", "item-b")])
    result = list(reconcile(snapshot, ["item-b"], provider_completed=True,
                            expected_returned_count=1))
    assert [(r["value"], r["status"]) for r in result] == [
        ("item-a", "not_returned"), ("item-b", "returned")]
    assert [r["payload"] for r in result] == [rows[0]["payload"]] * 2
import json
import sqlite3
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest


@pytest.mark.parametrize("completed,count,returned", [
    (False, 1, ["item-a"]), (1, 1, ["item-a"]), (True, None, []),
    (True, True, ["item-a"]), (True, -1, []), (True, 1, []),
    (True, 0, ["item-a"]), (True, 1.0, ["item-a"]),
])
def test_completion_and_exact_integer_count_are_required(tmp_path, completed, count, returned):
    from batch_result_reconciler import create_snapshot, reconcile

    snapshot = create_snapshot(tmp_path / "submission.sqlite3",
                               [{"row_id": "row-a", "values": ["item-a"], "payload": None}],
                               [("row-a", "item-a")])
    with pytest.raises(ValueError, match="completed|count"):
        list(reconcile(snapshot, returned, provider_completed=completed,
                       expected_returned_count=count))


@pytest.mark.parametrize("returned,message", [
    (["item-a", "item-a"], "duplicate"), (["item-skipped"], "foreign"),
])
def test_untrusted_result_values_rejected_before_any_output(tmp_path, returned, message):
    from batch_result_reconciler import create_snapshot, reconcile

    snapshot = create_snapshot(tmp_path / "submission.sqlite3",
                               [{"row_id": "row-a", "values": ["item-a", "item-skipped"],
                                 "payload": None}], [("row-a", "item-a")])
    with pytest.raises(ValueError, match=message):
        next(reconcile(snapshot, iter(returned), provider_completed=True,
                       expected_returned_count=len(returned)))


@pytest.mark.parametrize("pair", [("missing", "item-a"), ("row-a", "item-other")])
def test_submission_requires_exact_source_membership_without_leftover_file(tmp_path, pair):
    from batch_result_reconciler import create_snapshot

    target = tmp_path / "submission.sqlite3"
    rows = [{"row_id": "row-a", "values": ["item-a"], "payload": None},
            {"row_id": "row-b", "values": ["item-other"], "payload": None}]
    with pytest.raises(ValueError, match="membership"):
        create_snapshot(target, rows, [pair])
    assert not target.exists()


def test_snapshot_identity_is_frozen_and_preserves_inputs(tmp_path):
    from batch_result_reconciler import create_snapshot, reconcile

    rows = [{"row_id": "列甲", "values": ["項目甲"], "payload": {"資料": [False, None]}}]
    before = deepcopy(rows)
    snapshot = create_snapshot(tmp_path / "submission.sqlite3", iter(rows), [("列甲", "項目甲")])
    assert hasattr(snapshot, "sha256") and hasattr(snapshot, "source_digest")
    assert snapshot.sha256 == hashlib.sha256(snapshot.path.read_bytes()).hexdigest()
    assert len(snapshot.source_digest) == 64
    with pytest.raises(FrozenInstanceError):
        snapshot.path = tmp_path / "other"
    data = snapshot.path.read_bytes()
    rows[0]["payload"]["資料"].append("changed after submission")
    assert list(reconcile(snapshot, [], provider_completed=True, expected_returned_count=0)) == [
        {"row_id": "列甲", "value": "項目甲", "status": "not_returned", "payload": before[0]["payload"]}]
    assert snapshot.path.read_bytes() == data
    assert rows[0]["values"] == before[0]["values"]


@pytest.mark.parametrize("case,message", [
    ("bytes", "snapshot digest"), ("source", "source digest"), ("membership", "membership"),
    ("bad_digest", "digest"),
])
def test_reconciliation_validates_snapshot_before_output(tmp_path, case, message):
    from dataclasses import replace
    from batch_result_reconciler import create_snapshot, reconcile

    snapshot = create_snapshot(tmp_path / "submission.sqlite3",
                               [{"row_id": "row-a", "values": ["item-a"], "payload": None}],
                               [("row-a", "item-a")])
    if case == "bad_digest":
        snapshot = replace(snapshot, sha256="not-a-digest")
    else:
        with sqlite3.connect(snapshot.path) as db:
            if case == "membership":
                db.execute("UPDATE submitted SET row_id='missing'")
            else:
                db.execute("UPDATE source_rows SET payload='42'")
        if case != "bytes":
            snapshot = replace(snapshot, sha256=hashlib.sha256(snapshot.path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match=message):
        next(reconcile(snapshot, ["item-a"], provider_completed=True, expected_returned_count=1))


def test_existing_snapshot_is_never_overwritten_or_deleted(tmp_path):
    from batch_result_reconciler import create_snapshot

    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"existing content")
    with pytest.raises(FileExistsError):
        create_snapshot(target, [], [])
    assert target.read_bytes() == b"existing content"


@pytest.mark.parametrize("case", [
    "row_id", "value", "values_container", "payload_nan", "payload_key", "payload_tuple",
    "duplicate_row", "duplicate_value", "duplicate_pair", "malformed_pair", "missing_payload",
])
def test_source_contract_rejects_invalid_or_duplicate_input(tmp_path, case):
    from batch_result_reconciler import create_snapshot

    rows = [{"row_id": "row-a", "values": ["item-a"], "payload": None}]
    pairs = [("row-a", "item-a")]
    if case == "row_id":
        rows[0]["row_id"] = True
    elif case == "value":
        rows[0]["values"] = [None]
    elif case == "values_container":
        rows[0]["values"] = "item-a"
    elif case == "payload_nan":
        rows[0]["payload"] = float("nan")
    elif case == "payload_key":
        rows[0]["payload"] = {1: "not a JSON string key"}
    elif case == "payload_tuple":
        rows[0]["payload"] = ("not a JSON array",)
    elif case == "duplicate_row":
        rows.append(deepcopy(rows[0]))
    elif case == "duplicate_value":
        rows[0]["values"] *= 2
    elif case == "duplicate_pair":
        pairs *= 2
    elif case == "malformed_pair":
        pairs = ["xy"]
    else:
        del rows[0]["payload"]
    with pytest.raises(ValueError):
        create_snapshot(tmp_path / "submission.sqlite3", rows, pairs)
    assert not (tmp_path / "submission.sqlite3").exists()


@pytest.mark.parametrize("row", [
    {"row_id": 1, "values": [], "payload": None},
    {"row_id": "", "values": [], "payload": None},
    {"row_id": "row-a", "values": [None], "payload": None},
    {"row_id": "row-a", "values": [""], "payload": None},
    {"row_id": "row-a", "values": "abc", "payload": None},
])
def test_unselected_rows_also_enforce_string_identity_contract(tmp_path, row):
    from batch_result_reconciler import create_snapshot

    with pytest.raises(ValueError):
        create_snapshot(tmp_path / "submission.sqlite3", [row], [])


@pytest.mark.parametrize("value", [None, 1, True, "", ["item-a"]])
def test_returned_values_require_nonempty_strings(tmp_path, value):
    from batch_result_reconciler import create_snapshot, reconcile

    snapshot = create_snapshot(tmp_path / "submission.sqlite3", [], [])
    with pytest.raises(ValueError):
        list(reconcile(snapshot, [value], provider_completed=True, expected_returned_count=1))


@pytest.mark.parametrize("pairs", [["xy"], [["x", "y", "extra"]], [("x", 1)]])
def test_submission_pair_shape_is_not_coerced(tmp_path, pairs):
    from batch_result_reconciler import create_snapshot

    with pytest.raises(ValueError):
        create_snapshot(tmp_path / "submission.sqlite3",
                        [{"row_id": "x", "values": ["y", "1"], "payload": None}], pairs)


def test_result_stream_does_not_accept_a_bare_string(tmp_path):
    from batch_result_reconciler import create_snapshot, reconcile

    snapshot = create_snapshot(tmp_path / "submission.sqlite3",
                               [{"row_id": "x", "values": ["y"], "payload": None}], [("x", "y")])
    with pytest.raises(ValueError):
        list(reconcile(snapshot, "y", provider_completed=True, expected_returned_count=1))


def test_exact_pair_scope_does_not_expand_shared_values(tmp_path):
    assert importlib.util.find_spec("batch_result_reconciler") is not None
    from batch_result_reconciler import create_snapshot, reconcile

    rows = [
        {"row_id": "row-a", "values": ["item-shared"], "payload": {"label": "first"}},
        {"row_id": "row-b", "values": ["item-shared"], "payload": {"label": "second"}},
    ]
    snapshot = create_snapshot(tmp_path / "submission.sqlite3", rows, [("row-b", "item-shared")])
    assert list(reconcile(snapshot, ["item-shared"], provider_completed=True,
                          expected_returned_count=1)) == [
        {"row_id": "row-b", "value": "item-shared", "status": "returned",
         "payload": {"label": "second"}},
    ]
