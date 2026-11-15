# 2. Redact before anything is stored, and redact when unsure

- Status: Accepted
- Date: 2026-11-14

## Context

An index is copied, backed up, queried by other systems and fed to language models. Personal
information that reaches it is hard to get back out. Redacting at query time, or in the
application, leaves the raw text in every copy.

## Decision

- Redaction happens in `prepare`, before chunking output is built and before any embedding.
  The index never receives raw text, and the vectors are computed from redacted text, so they
  do not encode the removed values either.
- Detectors are rules: regular expressions for emails (written and spelled out), phone numbers
  (punctuated, run together, or seven or more spoken digits), street addresses, and names after
  an introduction, a relation or a title.
- Card numbers must pass the check digit, so order and confirmation numbers are left alone.
- Names the business already holds for the call (caller and agent) are removed wherever they
  appear, as whole words, in any case.
- Where spans overlap, the longest wins: a card number is one redaction, not a card and the
  phone-shaped run inside it.
- Values are replaced with a typed placeholder (`[PHONE]`). The type stays searchable context;
  the embedder ignores the placeholder itself.
- **When a detector cannot tell, it redacts.** Any ten-digit number is treated as a phone
  number.
- Speaker labels are roles (`Agent`, `Caller`), never names.

## Consequences

- 4,141 of 4,271 planted values are removed. The 130 misses are two forms: a third person named
  with no cue (61) and an address described in words (69). Both reach the index, and the report
  counts them there.
- 215 appliance serial numbers are redacted as phone numbers. A technician searching by serial
  number will not find the call. That is the accepted price.
- Keyword retrieval is the same with and without redaction (98% Hit@5 both).
- Redaction is not reversible. If the application needs the caller's number, it reads it from
  the system of record, not from the index.
- Three tests pin the known limits, so an improvement to the rules forces the documentation to
  be updated.

## Alternatives considered

- **A named-entity model**: would catch bare names. It adds a model download, non-determinism
  across versions, and misses that are harder to enumerate. It belongs behind the same
  interface as a second detector, with its own measured recall.
- **Hash or tokenise values instead of removing them**: keeps "same caller" joins possible and
  keeps a re-identification risk with it.
