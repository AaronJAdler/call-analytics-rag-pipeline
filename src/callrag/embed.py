"""Embedders. The pipeline depends on the protocol, not on any model.

`HashingEmbedder` is the one that ships: a bag of words and word pairs hashed into a fixed
number of dimensions. It needs no download, no GPU and no network, and gives the same vectors
on every machine, so the tests and the evaluation are exactly reproducible.

It matches words, not meaning. "Water heater leaking" will not find "hot water tank dripping".
The evaluation measures that gap on purpose (see docs/eval.md).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

WORD = re.compile(r"[a-z0-9]+")
PLACEHOLDER = re.compile(r"\[(?:NAME|PHONE|EMAIL|ADDRESS|CARD)\]")
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it its my of on or our so that the "
    "this to was we with you your agent caller will not do does did can".split()
)


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Identifies the model and its settings. A different name means re-index everything."""
        ...

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def tokens(text: str) -> list[str]:
    """Lower-case words without stopwords or redaction placeholders, plus adjacent pairs."""
    words = [w for w in WORD.findall(PLACEHOLDER.sub(" ", text).lower()) if w not in STOPWORDS]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]


class HashingEmbedder:
    def __init__(self, dim: int = 2048) -> None:
        self._dim = dim
        self.calls = 0  # how many texts have been embedded; the tests count work with this

    @property
    def name(self) -> str:
        return f"hashing-v1-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token, count in Counter(tokens(text)).items():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # No usable words: a fixed unit vector, so cosine distance stays defined.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]
