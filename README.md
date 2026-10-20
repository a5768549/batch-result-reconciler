# batch-result-reconciler

Reconcile batch results against **the exact `(row_id, value)` pairs submitted**,
not every source row that happens to contain a returned value.

Python 3.11+. No runtime dependencies; uses SQLite, JSON, and SHA-256 from the
standard library. [繁體中文](README.zh-TW.md)

## Install from a checkout

```sh
python -m pip install .
```

## Python API

```python
from batch_result_reconciler import create_snapshot, reconcile

rows = [
    {"row_id": "row-a", "values": ["item-shared"], "payload": {"label": "unselected"}},
    {"row_id": "row-b", "values": ["item-shared", "item-b"], "payload": {"label": "selected"}},
]
snapshot = create_snapshot(
    "submission.sqlite3", rows,
    [("row-b", "item-shared"), ("row-b", "item-b")],
)
results = list(reconcile(
    snapshot, ["item-shared"],
    provider_completed=True, expected_returned_count=1,
))
```

Only `row-b` receives annotations: `item-shared` is `returned`, `item-b` is
`not_returned`. `row-a` is never implicitly selected. `not_returned` does **not**
mean invalid, rejected, or failed.

### Contracts

- Source rows are mappings with `row_id`, `values`, and `payload`. IDs and values
  must be nonempty strings; values must be a list. No trimming, case folding,
  normalization, or identifier coercion is performed.
- `payload` accepts JSON objects (string keys), arrays, strings, finite numbers,
  booleans, and null. Source input objects are not mutated. JSON representation
  is canonicalized; source formatting is not preserved.
- Rows, submitted pairs, and returned values may be one-pass iterables. Each
  submitted pair is a two-element list or tuple. Duplicate row IDs, duplicate
  values within a row, duplicate pairs, and duplicate returned values are errors.
- A returned value may annotate multiple **submitted** rows. The expected count
  counts distinct returned values, not rows or pairs. Values in the source but
  absent from the submission are foreign results and are rejected.
- `provider_completed` must be exactly `True`; `expected_returned_count` must
  be a nonnegative integer (not a boolean). The caller must obtain both from
  its provider. This package does not contact or independently verify providers.
  Empty results require an explicit count of zero. Empty submissions are allowed.
- `Snapshot` is a frozen dataclass containing `path`, `sha256`, and
  `source_digest`. The new database embeds all source rows and exact pairs;
  existing paths are never overwritten. Preserve the returned descriptor before
  submission. To reopen, construct `Snapshot(Path(path), sha256, source_digest)`
  from your retained descriptor, not newly calculated expected digests.
- The source digest covers canonical payloads, row IDs, and sorted source-value
  membership. The snapshot digest covers the entire SQLite file, including the
  submitted selection. SHA-256 digests are **not signatures** or authentication;
  keep expected digests in a trusted location. Anyone able to replace both a
  snapshot and its descriptor can redefine the input.
- Reconciliation copies the snapshot to private temporary storage, validates
  that copy and its membership, and uses disk-backed SQLite tables for matching.
  It never writes the original snapshot. No annotations are persisted in it.
- Results are dictionaries with `row_id`, `value`, `status`, `payload`, sorted
  by SQLite binary `(row_id, value)` ordering. All input results are validated
  before the first annotation is yielded. Consume or close the generator to
  release its temporary files. Errors occur when the generator is consumed.
- Invalid input raises `ValueError`; filesystem errors use standard `OSError`
  subclasses. Corrupt SQLite may raise `sqlite3.Error`. No fallback is attempted.

## CLI: JSON and JSONL

The synthetic files in `examples/` contain no real personal data.

```sh
batch-result-reconciler snapshot --rows examples/rows.jsonl --pairs examples/pairs.jsonl --database submission.sqlite3 > manifest.json
batch-result-reconciler reconcile --manifest manifest.json --values examples/returned.jsonl --provider-completed --expected-returned-count 1 > results.jsonl
```

`python -m batch_result_reconciler` is equivalent. Both commands default to
`--input-format jsonl`; use `json` for a top-level array. A JSONL row is an object,
a pair is `["row-id", "value"]`, and a returned value is a JSON string such as
`"item-shared"` (not bare text). Blank lines are rejected. Empty JSONL files
represent empty streams. `--output-format json` emits an array instead of JSONL.
The manifest uses an absolute database path; preserve/update that path when
moving the snapshot. Shell redirection examples assume a UTF-8-capable shell;
PowerShell users should use PowerShell 7+ rather than UTF-16 redirection.

CLI validation errors exit with code 2 and a message on stderr. Successful output
is JSON on stdout. Unicode may be escaped in CLI JSON and decodes unchanged.
A failed command can leave an empty shell-redirection output file; always check
its exit status. Input-validation failures emit no result annotations.

## Scope and limitations

This is a small reconciliation core, not a provider SDK, normalization engine,
spreadsheet exporter, authentication mechanism, or concurrent database service.
Use caller-controlled snapshot and temporary directories. Do not edit snapshots
or use this API for live SQLite databases. Memory is proportional to individual
rows/payloads and SQLite buffers for the core; JSON array CLI input/output loads
the full array, while JSONL streams records. Disk space is needed for the snapshot
and a working copy. No benchmark, production readiness, or security guarantee is
claimed.

## Development

```sh
python -m pip install ".[test]"
python -m unittest discover -s tests -p "test_smoke_unittest.py" -v
python -m pytest -q
python -m build
```

CI is configured for Ubuntu and Windows on Python 3.11 and 3.13. It builds and
installs the wheel; it does not publish packages. MIT license.
