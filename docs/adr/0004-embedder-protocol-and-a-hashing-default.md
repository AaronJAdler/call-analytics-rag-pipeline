# 4. An embedder protocol with a deterministic default

- Status: Accepted
- Date: 2026-11-14

## Context

The interesting parts of this pipeline are redaction, incremental sync, tenant isolation and
erasure. None of them depends on which embedding model is used. A real model would add a
download of hundreds of megabytes to every CI run and make results vary with its version.

## Decision

- `Embedder` is a protocol with three members: `name`, `dim` and `embed(texts)`.
- The shipped implementation, `HashingEmbedder`, hashes lower-cased words and adjacent word
  pairs into 2,048 dimensions with a signed hash (BLAKE2, so it is the same on every platform
  and Python process), weights by `1 + log(count)` and normalises to unit length.
- Stopwords and redaction placeholders are not tokens.
- The embedder's `name` is part of every call's content hash. A new model re-embeds everything
  on the next sync; the same model re-embeds nothing.
- An index refuses to open with an embedder of a different vector size.

## Consequences

- Tests and the evaluation are exactly reproducible, with no network.
- The embedder counts the texts it is given, which is how the tests prove that an unchanged
  call costs no embedding work.
- It matches words, not meaning. Keyword queries hit 98% at 5; paraphrase queries 73%, and
  mostly through the one word they share with the transcript. The paraphrase number is a floor
  for a real model to beat, not a result to be proud of.

## What prompted 2,048 dimensions

At 512 dimensions the unredacted index beat the redacted one on paraphrase Hit@1, 40% to 30%.
Names do not help search, so this needed explaining. With few dimensions, unrelated words land
on the same component. Redacted chunks from similar calls are identical, so they collide
identically and rise or fall together. Each unredacted chunk carries its own names and
addresses, so each gets different collisions, and with several matching calls one of them gets
lucky. At 2,048 dimensions the gap is 59% to 56% and reverses at Hit@5; at 8,192 the gap is no
smaller and indexing takes three times as long. The 512 and 8,192 figures are from
development runs and are not in the committed report.

## Alternatives considered

- **A small sentence-embedding model**: the right choice for a real deployment, and it plugs
  in through the protocol. Not run here.
- **TF-IDF**: also lexical, but its vocabulary and weights change when documents are added,
  which fights with incremental indexing.
