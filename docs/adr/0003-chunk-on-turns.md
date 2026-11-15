# 3. Chunk on turn boundaries, decided before redaction

- Status: Accepted
- Date: 2026-11-14

## Context

A call is a sequence of short turns. A fixed-size window cuts through the middle of them and
separates questions from their answers. Chunk size also interacts with redaction in a way that
was not obvious until it was measured.

## Decision

- A chunk is a run of whole turns totalling at most 70 words, with the last turn repeated at
  the start of the next chunk. A single turn over the limit is kept whole.
- Chunk boundaries are computed on the original turns. The chunk's text is the redacted turns
  between those boundaries.
- A chunk's id is a hash of the call id, its position and its text, so a chunk that did not
  change keeps its id when the call is edited.

## Consequences

- A question and its answer usually sit in the same chunk.
- Redaction cannot change how a call is split. A test asserts that the redacted and unredacted
  indexes have identical boundaries for every call.
- Boundary decisions read raw text, but only word counts leave that step.
- 70 words is small. It suits short service calls; long calls with long turns would want a
  larger limit and probably a sentence splitter inside turns.

## What prompted this

The first version chunked the redacted text. `[ADDRESS]` is one word where the address was six,
so redacted calls packed more turns into each chunk: 1,589 chunks against 1,716 for the same
calls unredacted. Retrieval on the redacted index was worse (paraphrase Hit@5 of 45% against
53%, at the 512 dimensions used then), and holding the boundaries fixed recovered most of that
gap (50%). The comparison was confounded: it was measuring chunk size, not the effect of
removing personal information. These figures are from development runs and are not in the
committed report.

## Alternatives considered

- **Fixed token windows**: simplest, and blind to who is speaking.
- **One chunk per call**: fine for these short calls, and it would hide a specific answer
  inside a long vector.
