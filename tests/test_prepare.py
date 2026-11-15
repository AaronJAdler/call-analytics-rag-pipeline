from __future__ import annotations

from dataclasses import replace

from callrag import synth
from callrag.prepare import chunk_turns, prepare, redacted_turns
from callrag.synth import Turn

CALLS = synth.generate(30, seed=7)


def test_chunks_split_between_turns_and_overlap_by_one() -> None:
    lines = [f"Agent: {'word ' * 9}{i}" for i in range(10)]  # 11 words each
    chunks = chunk_turns(lines, max_words=35, overlap_turns=1)
    assert [(start, end) for start, end, _ in chunks] == [(0, 2), (2, 4), (4, 6), (6, 8), (8, 9)]
    assert chunks[0][2] == "\n".join(lines[0:3])
    assert all(len(text.split()) <= 35 for _, _, text in chunks)


def test_a_turn_longer_than_the_limit_is_kept_whole() -> None:
    lines = ["Caller: " + "word " * 100, "Agent: ok"]
    chunks = chunk_turns(lines, max_words=20, overlap_turns=1)
    assert [(s, e) for s, e, _ in chunks] == [(0, 0), (1, 1)]


def test_every_turn_lands_in_some_chunk() -> None:
    for call in CALLS:
        prepared = prepare(call, index_fingerprint="x")
        covered = {t for c in prepared.chunks for t in range(c.turn_start, c.turn_end + 1)}
        assert covered == set(range(len(call.turns)))
        assert [c.position for c in prepared.chunks] == list(range(len(prepared.chunks)))


def test_speakers_are_roles_never_names() -> None:
    lines = redacted_turns(CALLS[0])
    assert all(line.startswith(("Agent: ", "Caller: ")) for line in lines)


def test_redaction_does_not_move_chunk_boundaries() -> None:
    for call in CALLS:
        with_redaction = prepare(call, index_fingerprint="x")
        without = prepare(call, index_fingerprint="x", redaction=False)
        assert [(c.turn_start, c.turn_end) for c in with_redaction.chunks] == [
            (c.turn_start, c.turn_end) for c in without.chunks
        ]


def test_chunk_ids_and_hash_are_stable_and_change_with_content() -> None:
    call = CALLS[0]
    first = prepare(call, index_fingerprint="hashing-v1-2048")
    assert prepare(call, index_fingerprint="hashing-v1-2048") == first
    assert len({c.chunk_id for c in first.chunks}) == len(first.chunks)

    edited = replace(
        call, turns=(*call.turns, Turn("caller", "Also the gate code is on the note."))
    )
    changed = prepare(edited, index_fingerprint="hashing-v1-2048")
    assert changed.content_hash != first.content_hash
    assert changed.chunks[0].chunk_id == first.chunks[0].chunk_id  # untouched chunks keep ids

    assert prepare(call, index_fingerprint="other-model").content_hash != first.content_hash
    assert prepare(call, index_fingerprint="hashing-v1-2048", max_words=40).content_hash != (
        first.content_hash
    )


def test_metadata_that_is_not_indexed_does_not_change_the_hash() -> None:
    call = CALLS[0]
    relabelled = replace(call, topic="something_else", started_at="2030-01-01T00:00:00+00:00")
    assert prepare(relabelled, index_fingerprint="x").content_hash == (
        prepare(call, index_fingerprint="x").content_hash
    )
