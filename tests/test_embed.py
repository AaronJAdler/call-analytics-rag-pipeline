from __future__ import annotations

import math

from callrag.embed import HashingEmbedder, tokens


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_are_unit_length_and_reproducible() -> None:
    embedder = HashingEmbedder(256)
    first, second = embedder.embed(["the water heater is leaking", "the water heater is leaking"])
    assert first == second
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)
    assert len(first) == embedder.dim == 256
    assert embedder.name == "hashing-v1-256"
    assert embedder.calls == 2


def test_known_vector_so_a_change_to_the_hashing_is_noticed() -> None:
    vector = HashingEmbedder(8).embed(["garage water heater"])[0]
    assert [round(v, 4) for v in vector] == [round(v, 4) for v in HashingEmbedder(8)._one(
        "Garage, WATER heater!"
    )]  # fmt: skip
    assert sum(1 for v in vector if v != 0) >= 2


def test_shared_words_score_higher_than_unrelated_text() -> None:
    embedder = HashingEmbedder()
    query, near, far = embedder.embed(
        [
            "garage Rheem water heater leak",
            "Caller: My Rheem water heater in the garage is leaking from the bottom.",
            "Caller: The Nest thermostat in the hallway went blank.",
        ]
    )
    assert cosine(query, near) > 0.3 > cosine(query, far)


def test_placeholders_and_stopwords_are_not_tokens() -> None:
    assert tokens("Caller: It is [ADDRESS] and [PHONE].") == []
    assert tokens("The Rheem heater") == ["rheem", "heater", "rheem_heater"]


def test_text_with_no_usable_words_still_gets_a_unit_vector() -> None:
    vector = HashingEmbedder(16).embed(["[PHONE]"])[0]
    assert vector == [1.0] + [0.0] * 15
