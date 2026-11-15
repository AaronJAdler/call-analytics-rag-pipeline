# 1. Synthetic calls with an answer key

- Status: Accepted
- Date: 2026-11-14

## Context

Call transcripts are full of personal information: names, numbers, addresses, cards read out
loud. A public repository cannot hold real ones, and real ones would not help measure
redaction anyway, because nobody has marked where the personal information is.

## Decision

- Every call is generated. Three invented businesses (plumbing, heating and cooling,
  electrical), 200 calls each, six problems per business.
- All personal information is visibly fake: phone numbers in the reserved 555-01xx range,
  emails at example.com, invented street and town names, random card numbers with a valid
  check digit.
- The generator builds each turn from pieces and records the character span, kind and form of
  every planted value. That record is the answer key.
- Values are planted in forms rules can catch and forms they cannot: a phone number spoken as
  words, an email spelled out, a lower-case address, a third person named with no cue, an
  address described without a number.
- Things that look like personal information but are not are planted too: ten-digit serial
  numbers, sixteen-digit confirmation codes that fail the card check digit, job numbers,
  prices, appointment times.
- Each call is seeded from the seed, tenant and call number, so adding calls never changes
  earlier ones.

## Consequences

- Redaction is scored exactly: 4,271 planted values, each either fully covered or not.
- False redactions can be counted, because everything that is not in the key is not personal.
- Retrieval has ground truth: each call's problem, brand and location are known.
- **The score is circular where it is 100%.** The same person wrote the patterns and the rules.
  The 100% rows show the rules do what they were written to do. They do not estimate recall on
  real transcripts, which have recognition errors and phrasings nobody planned.
- The transcripts are tidier than real calls: no interruptions, no misheard words, no small
  talk.

## Alternatives considered

- **A public call dataset**: closer to real speech, with licences and privacy questions of its
  own and no answer key.
- **Transcripts written by a language model**: more varied, not reproducible, and still
  without exact spans.
