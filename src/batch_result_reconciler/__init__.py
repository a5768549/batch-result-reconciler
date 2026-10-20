import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Snapshot:
    path: Path
    sha256: str
    source_digest: str


def _file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_digest(db):
    digest = hashlib.sha256(b"batch-result-reconciler/source/v1\n")
    for row_id, payload in db.execute("SELECT row_id,payload FROM source_rows ORDER BY row_id"):
        digest.update((json.dumps(["row", row_id, json.loads(payload)], ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    for row_id, value in db.execute("SELECT row_id,value FROM source_values ORDER BY row_id,value"):
        digest.update((json.dumps(["value", row_id, value], ensure_ascii=False,
                                  separators=(",", ":")) + "\n").encode("utf-8"))
    return digest.hexdigest()


def _validate_membership(db):
    if db.execute(
        "SELECT 1 FROM submitted p WHERE NOT EXISTS "
        "(SELECT 1 FROM source_values s WHERE s.row_id=p.row_id AND s.value=p.value) "
        "OR NOT EXISTS (SELECT 1 FROM source_rows r WHERE r.row_id=p.row_id) LIMIT 1"
    ).fetchone():
        raise ValueError("submitted pair fails source membership")


def _json(value):
    def validate(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("payload must contain only JSON types")

    validate(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def _text(value):
    if type(value) is not str or not value:
        raise ValueError("row_id and value must be nonempty strings")
    return value


def create_snapshot(path, rows, pairs):
    path = Path(path)
    with path.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(path)) as db:
            db.executescript(
                "CREATE TABLE source_rows(row_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
                "CREATE TABLE source_values(row_id TEXT, value TEXT, PRIMARY KEY(row_id,value));"
                "CREATE TABLE submitted(row_id TEXT, value TEXT, PRIMARY KEY(row_id,value));"
                "CREATE INDEX submitted_value ON submitted(value);"
            )
            for row in rows:
                row_id = _text(row["row_id"])
                if type(row["values"]) is not list:
                    raise ValueError("values must be a list")
                db.execute("INSERT INTO source_rows VALUES (?,?)", (row_id, _json(row["payload"])))
                db.executemany("INSERT INTO source_values VALUES (?,?)",
                               ((row_id, _text(value)) for value in row["values"]))
            for pair in pairs:
                if type(pair) not in (tuple, list) or len(pair) != 2:
                    raise ValueError("pair must be a two-item list or tuple")
                db.execute("INSERT INTO submitted VALUES (?,?)", (_text(pair[0]), _text(pair[1])))
            _validate_membership(db)
            source_digest = _source_digest(db)
            db.commit()
    except BaseException as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, (sqlite3.Error, KeyError, TypeError, RecursionError)):
            raise ValueError("invalid source or duplicate row/value/pair") from exc
        raise
    return Snapshot(path.resolve(), _file_digest(path), source_digest)


def reconcile(snapshot, returned_values, *, provider_completed, expected_returned_count):
    if isinstance(returned_values, (str, bytes)):
        raise ValueError("returned_values must be an iterable of strings, not a string")
    if provider_completed is not True:
        raise ValueError("provider_completed must be True")
    if type(expected_returned_count) is not int or expected_returned_count < 0:
        raise ValueError("expected_returned_count must be a nonnegative integer")
    with tempfile.TemporaryDirectory(prefix="reconcile-") as directory:
        working = Path(directory) / "working.sqlite3"
        shutil.copyfile(snapshot.path, working)
        if _file_digest(working) != snapshot.sha256:
            raise ValueError("snapshot digest mismatch")
        with closing(sqlite3.connect(working)) as db:
            if _source_digest(db) != snapshot.source_digest:
                raise ValueError("source digest mismatch")
            _validate_membership(db)
            db.execute("CREATE TABLE returned(value TEXT PRIMARY KEY)")
            try:
                db.executemany("INSERT INTO returned VALUES (?)", ((_text(v),) for v in returned_values))
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate returned value") from exc
            if db.execute(
                "SELECT 1 FROM returned r WHERE NOT EXISTS "
                "(SELECT 1 FROM submitted p WHERE p.value=r.value) LIMIT 1"
            ).fetchone():
                raise ValueError("foreign returned value")
            if db.execute("SELECT count(*) FROM returned").fetchone()[0] != expected_returned_count:
                raise ValueError("returned count does not match expected_returned_count")
            for row_id, value, payload, returned in db.execute(
                "SELECT p.row_id,p.value,s.payload,r.value FROM submitted p "
                "JOIN source_rows s ON s.row_id=p.row_id "
                "LEFT JOIN returned r ON r.value=p.value ORDER BY p.row_id,p.value"
            ):
                yield {"row_id": row_id, "value": value,
                       "status": "returned" if returned is not None else "not_returned",
                       "payload": json.loads(payload)}
