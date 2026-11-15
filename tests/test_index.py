from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

from callrag import synth
from callrag.embed import HashingEmbedder
from callrag.index import Index, InvalidIdentifier
from callrag.prepare import PreparedCall, prepare
from callrag.synth import Call, Turn

CALLS = synth.generate(25, seed=7)  # 75 calls, three tenants


def ready(calls: list[Call], embedder: HashingEmbedder) -> list[PreparedCall]:
    return [prepare(c, index_fingerprint=embedder.name) for c in calls]


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder(256)


@pytest.fixture
def index(tmp_path: Path, embedder: HashingEmbedder) -> Index:
    idx = Index(tmp_path / "index", embedder)
    idx.sync(ready(CALLS, embedder))
    embedder.calls = 0
    return idx


def edited(call: Call) -> Call:
    return replace(call, turns=(*call.turns, Turn("caller", "Please ring the side doorbell.")))


def test_first_sync_indexes_everything(tmp_path: Path, embedder: HashingEmbedder) -> None:
    idx = Index(tmp_path / "index", embedder)
    prepared = ready(CALLS, embedder)
    stats = idx.sync(prepared)
    total = sum(len(p.chunks) for p in prepared)
    assert (stats.added, stats.updated, stats.unchanged) == (75, 0, 0)
    assert stats.texts_embedded == stats.chunks_written == total == embedder.calls
    assert idx.counts() == {"calls": 75, "chunks": total, "tombstones": 0}


def test_second_sync_with_no_changes_embeds_nothing(
    index: Index, embedder: HashingEmbedder
) -> None:
    stats = index.sync(ready(CALLS, embedder))
    assert (stats.added, stats.updated, stats.unchanged, stats.texts_embedded) == (0, 0, 75, 0)
    assert embedder.calls == 0


def test_only_new_and_edited_calls_are_embedded(index: Index, embedder: HashingEmbedder) -> None:
    before = index.counts()["chunks"]
    new = [c for c in synth.generate(26, seed=7) if c not in CALLS]  # one more per tenant
    changed = [edited(CALLS[0]), *CALLS[1:], *new]
    prepared = ready(changed, embedder)
    stats = index.sync(prepared)
    assert (stats.added, stats.updated, stats.unchanged) == (3, 1, 74)
    worked_on = {CALLS[0].call_id, *[c.call_id for c in new]}
    touched = sum(len(p.chunks) for p in prepared if p.call_id in worked_on)
    assert stats.texts_embedded == embedder.calls == touched
    assert index.counts()["chunks"] == sum(len(p.chunks) for p in prepared) > before


def test_an_edited_call_is_replaced_not_duplicated(index: Index, embedder: HashingEmbedder) -> None:
    call = CALLS[0]
    shorter = replace(call, turns=call.turns[:3])
    index.sync(ready([shorter, *CALLS[1:]], embedder))
    texts = [text for _t, call_id, text in index.all_chunk_texts() if call_id == call.call_id]
    expected = [c.text for c in prepare(shorter, index_fingerprint=embedder.name).chunks]
    assert sorted(texts) == sorted(expected)  # no chunk of the old version is left behind


def test_search_never_leaves_the_tenant(index: Index) -> None:
    for tenant in ("delta-plumbing", "valley-air", "brightline-electric"):
        for query in ("Rheem leaking garage", "breaker trips kitchen", "thermostat blank"):
            hits = index.search(tenant, query, 10)
            assert len(hits) == 10
            assert {h.tenant_id for h in hits} == {tenant}


def test_a_small_tenant_still_gets_its_own_results(
    tmp_path: Path, embedder: HashingEmbedder
) -> None:
    """The filter runs before the nearest-neighbour search, not after it.

    A post-filter would take the top k overall, all from the big tenants, and return nothing.
    """
    idx = Index(tmp_path / "index", embedder)
    tiny = replace(CALLS[0], call_id="tiny-co-00001", tenant_id="tiny-co")
    idx.sync(ready([*CALLS, tiny], embedder))
    hits = idx.search("tiny-co", "breaker trips in the kitchen panel", 5)  # not what tiny has
    assert hits and {h.call_id for h in hits} == {"tiny-co-00001"}


@pytest.mark.parametrize("tenant", ["x' OR '1'='1", "delta-plumbing'--", "", "a b", "é"])
def test_a_tenant_id_that_could_alter_the_filter_is_rejected(index: Index, tenant: str) -> None:
    with pytest.raises(InvalidIdentifier):
        index.search(tenant, "anything", 5)


def test_search_order_is_reproducible(index: Index) -> None:
    first = [h.chunk_id for h in index.search("valley-air", "best number to reach you", 10)]
    second = [h.chunk_id for h in index.search("valley-air", "best number to reach you", 10)]
    assert first == second


def test_erased_call_is_gone_and_does_not_come_back(
    index: Index, embedder: HashingEmbedder
) -> None:
    victim = CALLS[5]
    assert index.erase_call(victim.call_id, dt.datetime(2026, 11, 1, tzinfo=dt.UTC)) > 0
    assert not [1 for _t, call_id, _x in index.all_chunk_texts() if call_id == victim.call_id]
    assert index.counts()["tombstones"] == 1

    stats = index.sync(ready(CALLS, embedder))  # the source still has the call
    assert (stats.added, stats.tombstoned, stats.unchanged) == (0, 1, 74)
    assert not [1 for _t, call_id, _x in index.all_chunk_texts() if call_id == victim.call_id]
    assert index.erase_call(victim.call_id) == 0  # erasing twice is harmless
    assert index.counts()["tombstones"] == 1


def test_erasure_is_not_physical_until_the_purge(index: Index, tmp_path: Path) -> None:
    """A delete hides rows; it does not remove them. Three things must be true afterwards."""
    victim = CALLS[5].call_id
    data_dir = tmp_path / "index" / "chunks.lance" / "data"
    version_before = index.chunks.version
    files_before = {p.name for p in data_dir.iterdir()}

    removed = index.erase_call(victim)

    # Still on disk: the rows are masked, and the old version can be read by anyone who asks.
    assert index.masked_rows() == removed > 0
    old = index.db.open_table("chunks")
    old.checkout(version_before)
    assert old.count_rows(f"call_id = '{victim}'") == removed
    assert {p.name for p in data_dir.iterdir()} == files_before

    index.purge()

    assert index.masked_rows() == 0  # 1. no masked rows left inside the data files
    assert not files_before & {p.name for p in data_dir.iterdir()}  # 2. old files are gone
    assert len(index.chunks.list_versions()) == 1  # 3. no older version to read
    with pytest.raises(ValueError, match="no longer exists"):
        index.db.open_table("chunks").checkout(version_before)
    assert index.search("delta-plumbing", "water heater", 3)  # and the index still works


def test_index_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "index"
    first = HashingEmbedder(256)
    Index(path, first).sync(ready(CALLS, first))
    second = HashingEmbedder(256)
    reopened = Index(path, second)
    stats = reopened.sync(ready(CALLS, second))
    assert stats.unchanged == 75 and second.calls == 0
    assert reopened.search("delta-plumbing", "water heater", 3)


def test_a_different_embedder_reindexes_or_refuses(tmp_path: Path) -> None:
    path = tmp_path / "index"
    small = HashingEmbedder(256)
    Index(path, small).sync(ready(CALLS, small))
    with pytest.raises(ValueError, match="different vector size"):
        Index(path, HashingEmbedder(128))

    class Renamed(HashingEmbedder):
        @property
        def name(self) -> str:
            return "another-model-256"

    other = Renamed(256)
    stats = Index(path, other).sync(ready(CALLS, other))  # type: ignore[arg-type]
    assert (stats.updated, stats.unchanged) == (75, 0)  # same size, new model: all re-embedded
