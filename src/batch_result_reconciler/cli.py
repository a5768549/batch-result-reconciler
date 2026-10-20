import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import Snapshot, create_snapshot, reconcile


def _items(path, input_format):
    with Path(path).open(encoding="utf-8") as stream:
        if input_format == "json":
            data = json.load(stream)
            if not isinstance(data, list):
                raise ValueError("JSON input must be an array")
            yield from data
        else:
            for line in stream:
                yield json.loads(line)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile only exact submitted row/value pairs.")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = commands.add_parser("snapshot", help="Create a new submission snapshot")
    snapshot_parser.add_argument("--rows", required=True)
    snapshot_parser.add_argument("--pairs", required=True)
    snapshot_parser.add_argument("--database", required=True)
    snapshot_parser.add_argument("--input-format", choices=("json", "jsonl"), default="jsonl")
    result_parser = commands.add_parser("reconcile", help="Validate and emit result annotations")
    result_parser.add_argument("--manifest", required=True)
    result_parser.add_argument("--values", required=True)
    result_parser.add_argument("--input-format", choices=("json", "jsonl"), default="jsonl")
    result_parser.add_argument("--output-format", choices=("json", "jsonl"), default="jsonl")
    result_parser.add_argument("--provider-completed", action="store_true", required=True)
    result_parser.add_argument("--expected-returned-count", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            snapshot = create_snapshot(args.database, _items(args.rows, args.input_format),
                                       _items(args.pairs, args.input_format))
            print(json.dumps({"path": str(snapshot.path), "sha256": snapshot.sha256,
                              "source_digest": snapshot.source_digest}, ensure_ascii=True))
        else:
            with Path(args.manifest).open(encoding="utf-8") as stream:
                manifest = json.load(stream)
            snapshot = Snapshot(Path(manifest["path"]), manifest["sha256"], manifest["source_digest"])
            results = reconcile(snapshot, _items(args.values, args.input_format),
                                provider_completed=args.provider_completed,
                                expected_returned_count=args.expected_returned_count)
            if args.output_format == "json":
                print(json.dumps(list(results), ensure_ascii=True))
            else:
                for result in results:
                    print(json.dumps(result, ensure_ascii=True))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    return 0
