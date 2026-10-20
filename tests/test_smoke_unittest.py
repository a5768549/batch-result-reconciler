import tempfile
import unittest
from pathlib import Path

from batch_result_reconciler import create_snapshot, reconcile


class EmptySubmissionSmoke(unittest.TestCase):
    def test_empty_submission_requires_explicit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_snapshot(Path(directory) / "snapshot.sqlite3", [], [])
            self.assertEqual(list(reconcile(snapshot, [], provider_completed=True,
                                            expected_returned_count=0)), [])

    def test_shared_value_counts_once_for_two_submitted_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{"row_id": row, "values": ["shared"], "payload": None}
                    for row in ("a", "b")]
            snapshot = create_snapshot(Path(directory) / "snapshot.sqlite3", rows,
                                       [("a", "shared"), ("b", "shared")])
            result = list(reconcile(snapshot, ["shared"], provider_completed=True,
                                    expected_returned_count=1))
            self.assertEqual([r["row_id"] for r in result], ["a", "b"])
            self.assertTrue(all(r["status"] == "returned" for r in result))
