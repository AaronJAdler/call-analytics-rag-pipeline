"""The retrieval index, in LanceDB.

Three tables:

- `chunks`: one row per chunk, with its vector, tenant and call.
- `calls`: one row per indexed call with the hash of what was indexed. This is how a sync
  knows which calls changed without embedding anything.
- `tombstones`: calls that were erased on request. A later sync that still sees the call in
  its source skips it, so an erased call cannot come back by accident.

Every search takes a tenant. There is no method that searches across tenants.
"""

from __future__ import annotations

import datetime as dt
import re
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

from callrag.embed import Embedder
from callrag.prepare import PreparedCall

IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BATCH = 500


class InvalidIdentifier(ValueError):
    """A tenant or call id that is not safe to place in a filter expression."""


def _check(value: str) -> str:
    if not IDENTIFIER.match(value):
        raise InvalidIdentifier(f"not a valid identifier: {value!r}")
    return value


@dataclass(frozen=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    tombstoned: int = 0  # present in the source but erased earlier, so skipped
    chunks_written: int = 0
    chunks_removed: int = 0
    texts_embedded: int = 0


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    call_id: str
    tenant_id: str
    text: str
    distance: float


class Index:
    def __init__(self, path: Path | str, embedder: Embedder) -> None:
        self.embedder = embedder
        self.db = lancedb.connect(str(path))
        names = set(self.db.list_tables().tables)
        self.chunks = self._table(
            names,
            "chunks",
            pa.schema(
                [
                    ("chunk_id", pa.string()),
                    ("tenant_id", pa.string()),
                    ("call_id", pa.string()),
                    ("position", pa.int32()),
                    ("turn_start", pa.int32()),
                    ("turn_end", pa.int32()),
                    ("text", pa.string()),
                    ("vector", pa.list_(pa.float32(), embedder.dim)),
                ]
            ),
        )
        self.calls = self._table(
            names,
            "calls",
            pa.schema(
                [
                    ("call_id", pa.string()),
                    ("tenant_id", pa.string()),
                    ("content_hash", pa.string()),
                    ("chunk_count", pa.int32()),
                ]
            ),
        )
        self.tombstones = self._table(
            names,
            "tombstones",
            pa.schema(
                [("call_id", pa.string()), ("tenant_id", pa.string()), ("erased_at", pa.string())]
            ),
        )

    def _table(self, existing: set[str], name: str, schema: pa.Schema) -> Any:
        if name in existing:
            table = self.db.open_table(name)
            if (
                name == "chunks"
                and table.schema.field("vector").type != schema.field("vector").type
            ):
                raise ValueError(
                    "this index was built with a different vector size; use a new index path"
                )
            return table
        return self.db.create_table(name, schema=schema)

    # ------------------------------------------------------------------------------------ sync

    def _state(self) -> dict[str, tuple[str, int]]:
        rows = self.calls.to_arrow().to_pylist()
        return {r["call_id"]: (r["content_hash"], r["chunk_count"]) for r in rows}

    def _tombstoned(self) -> set[str]:
        return {r["call_id"] for r in self.tombstones.to_arrow().to_pylist()}

    def sync(self, calls: Iterable[PreparedCall]) -> SyncStats:
        """Bring the index in line with `calls`, embedding only what changed.

        A changed call's chunks are replaced in one commit: new rows inserted, rows of the same
        call that are no longer wanted deleted. The `calls` table is updated after that. If the
        process dies in between, the next sync sees the old hash and repeats the same
        replacement, which gives the same result.
        """
        state = self._state()
        erased = self._tombstoned()
        todo: list[PreparedCall] = []
        added = updated = unchanged = tombstoned = 0
        for call in calls:
            _check(call.call_id)
            _check(call.tenant_id)
            if call.call_id in erased:
                tombstoned += 1
            elif call.call_id not in state:
                added += 1
                todo.append(call)
            elif state[call.call_id][0] != call.content_hash:
                updated += 1
                todo.append(call)
            else:
                unchanged += 1

        written = removed = embedded = 0
        for offset in range(0, len(todo), BATCH):
            batch = todo[offset : offset + BATCH]
            chunks = [c for call in batch for c in call.chunks]
            vectors = self.embedder.embed([c.text for c in chunks])
            embedded += len(chunks)
            rows = [
                {
                    "chunk_id": c.chunk_id,
                    "tenant_id": c.tenant_id,
                    "call_id": c.call_id,
                    "position": c.position,
                    "turn_start": c.turn_start,
                    "turn_end": c.turn_end,
                    "text": c.text,
                    "vector": v,
                }
                for c, v in zip(chunks, vectors, strict=True)
            ]
            ids = ", ".join(f"'{call.call_id}'" for call in batch)
            before = self.chunks.count_rows(f"call_id IN ({ids})")
            if rows:
                (
                    self.chunks.merge_insert("chunk_id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .when_not_matched_by_source_delete(f"call_id IN ({ids})")
                    .execute(rows)
                )
            else:
                self.chunks.delete(f"call_id IN ({ids})")
            written += len(rows)
            new_ids = {r["chunk_id"] for r in rows}
            removed += max(0, before - len(new_ids)) if before else 0
            (
                self.calls.merge_insert("call_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(
                    [
                        {
                            "call_id": call.call_id,
                            "tenant_id": call.tenant_id,
                            "content_hash": call.content_hash,
                            "chunk_count": len(call.chunks),
                        }
                        for call in batch
                    ]
                )
            )
        return SyncStats(added, updated, unchanged, tombstoned, written, removed, embedded)

    # ---------------------------------------------------------------------------------- erasure

    def erase_call(self, call_id: str, now: dt.datetime | None = None) -> int:
        """Remove a call for good. Returns the number of chunks removed.

        The tombstone is written first: if anything after it fails, the call is at worst still
        partly present but can no longer be re-indexed, and erasing again finishes the job.
        """
        _check(call_id)
        owners = [r for r in self.calls.to_arrow().to_pylist() if r["call_id"] == call_id]
        tenant = owners[0]["tenant_id"] if owners else ""
        if call_id not in self._tombstoned():
            stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
            self.tombstones.add([{"call_id": call_id, "tenant_id": tenant, "erased_at": stamp}])
        removed = int(self.chunks.count_rows(f"call_id = '{call_id}'"))
        self.chunks.delete(f"call_id = '{call_id}'")
        self.calls.delete(f"call_id = '{call_id}'")
        return removed

    def purge(self) -> None:
        """Physically remove deleted rows. Erasure is not finished until this has run.

        A delete in LanceDB does two things short of removing data. It writes a deletion file
        that masks the rows, leaving them in the data file. And it creates a new table version,
        leaving the old one, with the rows visible, readable by version number. So this
        rewrites every data file without its masked rows, then drops all older versions and
        the files only they used.

        It must not run while another process is reading or writing the index.
        """
        with warnings.catch_warnings():
            # LanceDB warns that dropping old versions breaks concurrent readers; see above.
            warnings.simplefilter("ignore", UserWarning)
            for table in (self.chunks, self.calls):
                table.optimize(
                    cleanup_older_than=dt.timedelta(0),
                    delete_unverified=True,
                    compaction_options={
                        "materialize_deletions": True,
                        "materialize_deletions_threshold": 0.0,
                    },
                )

    def masked_rows(self) -> int:
        """Rows deleted logically but still present in the chunk table's data files."""
        return int(self.chunks.stats()["num_deleted_rows"])

    # ----------------------------------------------------------------------------------- search

    def search(self, tenant_id: str, query: str, k: int = 5) -> list[Hit]:
        """The k nearest chunks to `query` among one tenant's chunks.

        The tenant filter is applied before the nearest-neighbour search (a pre-filter), so a
        tenant with few chunks still gets k results from its own data. The id is validated, and
        the results are checked again on the way out.
        """
        _check(tenant_id)
        vector = self.embedder.embed([query])[0]
        rows = (
            self.chunks.search(vector)
            .distance_type("cosine")
            .where(f"tenant_id = '{tenant_id}'", prefilter=True)
            .limit(k * 3 + 10)
            .to_list()
        )
        # Identical chunks from different calls tie exactly. Breaking ties by chunk id makes
        # the top k the same on every run and every machine.
        rows.sort(key=lambda r: (round(float(r["_distance"]), 6), r["chunk_id"]))
        hits = [
            Hit(r["chunk_id"], r["call_id"], r["tenant_id"], r["text"], float(r["_distance"]))
            for r in rows[:k]
        ]
        if any(h.tenant_id != tenant_id for h in hits):
            raise RuntimeError("tenant filter returned another tenant's data")
        return hits

    def search_unfiltered(self, vector: Sequence[float], k: int) -> list[dict[str, Any]]:
        """Nearest chunks regardless of tenant. For the evaluation only: it shows what the
        tenant filter prevents. Nothing in the pipeline or the CLI calls this."""
        rows: list[dict[str, Any]] = (
            self.chunks.search(list(vector)).distance_type("cosine").limit(k).to_list()
        )
        return rows

    # ------------------------------------------------------------------------------------ stats

    def counts(self) -> dict[str, int]:
        return {
            "calls": int(self.calls.count_rows()),
            "chunks": int(self.chunks.count_rows()),
            "tombstones": int(self.tombstones.count_rows()),
        }

    def all_chunk_texts(self) -> list[tuple[str, str, str]]:
        """(tenant, call, text) for every indexed chunk. Used to scan the index for leaks."""
        rows = self.chunks.to_arrow().select(["tenant_id", "call_id", "text"]).to_pylist()
        return [(r["tenant_id"], r["call_id"], r["text"]) for r in rows]
