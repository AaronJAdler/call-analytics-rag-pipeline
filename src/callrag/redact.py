"""Rule-based PII redaction for call transcripts.

Detectors are regular expressions plus two checks that regular expressions cannot do: the card
check digit, and a lookup of the names the business already holds for the call. Each detector
returns character spans; overlapping spans are merged, longest first, and replaced with a
typed placeholder such as [PHONE].

The rule when a detector is unsure is to redact. A serial number hidden by mistake costs a
little retrieval quality. A phone number left in the index is a leak.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from callrag.synth import luhn_valid


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str  # NAME, PHONE, EMAIL, ADDRESS, CARD
    rule: str


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
SPOKEN_EMAIL = re.compile(
    r"\b[a-z0-9]+(?: (?:dot|underscore|dash) [a-z0-9]+)* at [a-z0-9]+(?: dot [a-z]{2,})+\b",
    re.IGNORECASE,
)
CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
PHONE = re.compile(
    r"(?<![\d-])(?:\+?1[ .-]?)?(?:\(\d{3}\)[ ]?|\d{3}[ .-]?)\d{3}[ .-]?\d{4}(?![\d-])"
)
_DIGIT_WORD = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
SPOKEN_NUMBER = re.compile(rf"\b{_DIGIT_WORD}(?:[ ,-]+{_DIGIT_WORD}){{6,}}\b", re.IGNORECASE)
_SUFFIX = r"(?:street|st|avenue|ave|road|rd|drive|dr|court|ct|way|lane|ln|boulevard|blvd|place|pl)"
ADDRESS = re.compile(
    rf"\b\d{{1,6}} (?:[A-Za-z]+ ){{1,3}}{_SUFFIX}\b\.?"
    r"(?:,? (?:apt|apartment|unit|suite|#) ?\w+)?"
    r"(?:, [A-Z][a-z]+(?: [A-Z][a-z]+)*, [A-Z]{2}(?: \d{5}(?:-\d{4})?)?)?",
    re.IGNORECASE,
)
_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z]+)?)"
INTRODUCED = re.compile(rf"\b(?:[Mm]y name is|[Tt]his is|[Ii]t's|[Ii]t is|I'm|I am) {_NAME}")
_RELATION = (
    r"(?:husband|wife|son|daughter|neighbor|tenant|landlord|roommate|partner|mother|father|"
    r"mom|dad|brother|sister|friend)"
)
RELATIVE = re.compile(rf"\b(?:my|our) {_RELATION},? ([A-Z][a-z]+)")
TITLED = re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.? ([A-Z][a-z]+)")
# Capitalised words that follow "this is" or "it's" without being a name.
NOT_NAMES = frozenset(
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May "
    "June July August September October November December Hard Just Not The A An About Really "
    "Probably Fine Okay Sure".split()
)


def _known_name_spans(text: str, known_names: Iterable[str]) -> list[Span]:
    spans: list[Span] = []
    for name in known_names:
        parts = [p for p in name.split() if len(p) > 1]
        # The full name first, then each part on its own ("Maria Lopez", "Maria", "Lopez").
        for candidate in [name, *parts]:
            for m in re.finditer(rf"\b{re.escape(candidate)}\b", text, re.IGNORECASE):
                spans.append(Span(m.start(), m.end(), "NAME", "known name"))
    return spans


def find(text: str, known_names: Iterable[str] = ()) -> list[Span]:
    """Every span to redact in one piece of text, merged so that none overlap."""
    found: list[Span] = []
    for m in EMAIL.finditer(text):
        found.append(Span(m.start(), m.end(), "EMAIL", "email"))
    for m in SPOKEN_EMAIL.finditer(text):
        found.append(Span(m.start(), m.end(), "EMAIL", "spoken email"))
    for m in CARD.finditer(text):
        if luhn_valid(re.sub(r"\D", "", m.group())):
            found.append(Span(m.start(), m.end(), "CARD", "card number with a valid check digit"))
    for m in PHONE.finditer(text):
        found.append(Span(m.start(), m.end(), "PHONE", "phone number"))
    for m in SPOKEN_NUMBER.finditer(text):
        found.append(Span(m.start(), m.end(), "PHONE", "seven or more spoken digits"))
    for m in ADDRESS.finditer(text):
        found.append(Span(m.start(), m.end(), "ADDRESS", "street address"))
    for pattern, rule in ((INTRODUCED, "introduction"), (RELATIVE, "relative"), (TITLED, "title")):
        for m in pattern.finditer(text):
            if m.group(1).split()[0] not in NOT_NAMES:
                found.append(Span(m.start(1), m.end(1), "NAME", rule))
    found += _known_name_spans(text, known_names)

    # Longest span wins where two overlap; a card number beats the phone-shaped piece inside it.
    found.sort(key=lambda s: (-(s.end - s.start), s.start))
    kept: list[Span] = []
    for span in found:
        if all(span.end <= k.start or span.start >= k.end for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s.start)


def apply(text: str, spans: Sequence[Span]) -> str:
    out: list[str] = []
    cursor = 0
    for span in spans:
        out.append(text[cursor : span.start])
        out.append(f"[{span.kind}]")
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)


def redact(text: str, known_names: Iterable[str] = ()) -> str:
    return apply(text, find(text, known_names))
