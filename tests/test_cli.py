import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def invoke(*args):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "batch_result_reconciler", *map(str, args)],
                          env=env, text=True, encoding="utf-8", capture_output=True)


@pytest.mark.parametrize("input_format", ["json", "jsonl"])
def test_cli_snapshot_then_reconcile_preserves_source(tmp_path, input_format):
    rows = [{"row_id": "row-a", "values": ["item-a", "item-b"], "payload": {"標記": "測試"}},
            {"row_id": "row-b", "values": ["item-a"], "payload": None}]
    pairs = [["row-a", "item-a"], ["row-a", "item-b"]]
    values = ["item-a"]
    inputs = {}
    for name, data in [("rows", rows), ("pairs", pairs), ("values", values)]:
        path = tmp_path / (name + "." + input_format)
        text = json.dumps(data, ensure_ascii=False) if input_format == "json" else "".join(
            json.dumps(item, ensure_ascii=False) + "\n" for item in data)
        path.write_text(text, encoding="utf-8")
        inputs[name] = path
    original = inputs["rows"].read_bytes()
    snapshot = tmp_path / "snapshot.sqlite3"
    run = invoke("snapshot", "--rows", inputs["rows"], "--pairs", inputs["pairs"],
                 "--database", snapshot, "--input-format", input_format)
    assert run.returncode == 0, run.stderr
    manifest = tmp_path / "manifest.json"
    manifest.write_text(run.stdout, encoding="utf-8")
    args = ["reconcile", "--manifest", manifest, "--values", inputs["values"],
            "--input-format", input_format, "--provider-completed", "--expected-returned-count", "1"]
    run = invoke(*args)
    assert run.returncode == 0, run.stderr
    result = [json.loads(line) for line in run.stdout.splitlines()]
    assert [(r["row_id"], r["status"]) for r in result] == [
        ("row-a", "returned"), ("row-a", "not_returned")]
    assert result[0]["payload"] == {"標記": "測試"}
    assert inputs["rows"].read_bytes() == original
    run = invoke(*args, "--output-format", "json")
    assert run.returncode == 0 and json.loads(run.stdout) == result
    run = invoke(*args[:-1], "2")
    assert run.returncode == 2 and run.stdout == ""
    assert "count" in run.stderr and "Traceback" not in run.stderr
