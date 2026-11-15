"""From a call to the chunks that get indexed: redact each turn, then split on turn boundaries."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from callrag import redact
from callrag.synth import Call

SPEAKER = {"agent": "Agent", "caller": "Caller"}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    call_id: str
    tenant_id: str
    position: int
    turn_start: int
    turn_end: int  # inclusive
    text: str


@dataclass(frozen=True)
class PreparedCall:
    call_id: str
    tenant_id: str
    started_at: str
    content_hash: str  # of everything that decides what is indexed for this call
    chunks: tuple[Chunk, ...]


def redacted_turns(call: Call, *, redaction: bool = True) -> list[str]:
    """Each turn as "Speaker: text", with PII replaced. Speakers are roles, never names."""
    known = (call.caller_name, call.agent_name)
    lines = []
    for turn in call.turns:
        text = redact.redact(turn.text, known) if redaction else turn.text
        lines.append(f"{SPEAKER[turn.speaker]}: {text}")
    return lines


def chunk_turns(
    lines: Sequence[str], max_words: int = 70, overlap_turns: int = 1
) -> list[tuple[int, int, str]]:
    """Group whole turns into chunks of at most `max_words`, repeating the last turn or two.

    Splitting only between turns keeps a question with its answer more often than a fixed
    window would. A single turn longer than the limit becomes its own chunk, unsplit.
    """
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(lines):
        end = start
        words = len(lines[start].split())
        while end + 1 < len(lines) and words + len(lines[end + 1].split()) <= max_words:
            end += 1
            words += len(lines[end].split())
        chunks.append((start, end, "\n".join(lines[start : end + 1])))
        if end + 1 >= len(lines):
            break
        start = max(end + 1 - overlap_turns, start + 1)
    return chunks


def prepare(
    call: Call,
    *,
    index_fingerprint: str,
    max_words: int = 70,
    overlap_turns: int = 1,
    redaction: bool = True,
) -> PreparedCall:
    """Redact and chunk one call.

    `index_fingerprint` names the embedder and anything else that changes what a chunk's row
    would contain. It is part of the content hash, so swapping the embedder re-indexes every
    call and changing nothing re-indexes none.
    """
    lines = redacted_turns(call, redaction=redaction)
    settings = f"{index_fingerprint}|{max_words}|{overlap_turns}|{redaction}"
    content_hash = hashlib.sha256((settings + "\n" + "\n".join(lines)).encode()).hexdigest()[:24]
    # Boundaries are decided on the original turns, so a placeholder standing in for a
    # six-word address does not change where a chunk ends. Only redacted text is kept.
    original = redacted_turns(call, redaction=False)
    chunks = []
    for position, (start, end, _) in enumerate(chunk_turns(original, max_words, overlap_turns)):
        text = "\n".join(lines[start : end + 1])
        chunk_id = hashlib.sha256(f"{call.call_id}|{position}|{text}".encode()).hexdigest()[:20]
        chunks.append(Chunk(chunk_id, call.call_id, call.tenant_id, position, start, end, text))
    return PreparedCall(call.call_id, call.tenant_id, call.started_at, content_hash, tuple(chunks))
