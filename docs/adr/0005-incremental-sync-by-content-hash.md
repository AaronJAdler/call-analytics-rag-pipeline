# 5. Incremental sync by content hash

- Status: Accepted
- Date: 2026-11-14

## Context

Embedding is the expensive step. Most calls never change after they are indexed; a few are
corrected, and new ones arrive daily. Rebuilding the index every day pays for all of them
again.

## Decision

- Each prepared call has a content hash over its redacted turns, the chunk settings and the
  embedder's name: everything that decides what its rows contain, and nothing else.
- A `calls` table stores the hash last indexed for each call. A sync compares hashes and sorts
  calls into new, changed, unchanged and erased, before embedding anything.
- A changed call is replaced in one commit: a merge on `chunk_id` that inserts the new rows
  and deletes rows of the same call that are not in the new set.
- The `calls` table is written after the chunks. A crash between the two leaves the old hash,
  so the next sync repeats the same replacement.
- A call missing from a sync's input is left alone. Removal is explicit (ADR 0007), never
  inferred from absence, so a partial input cannot empty the index.

## Consequences

- A day with 60 new and 30 edited calls embeds 266 chunks. A rebuild would embed 1,725.
- A second sync with the same input embeds 0.
- Changing the embedder or the chunk size re-indexes everything on the next sync, with no
  separate migration step.
- Metadata that is not indexed (the call's topic label, its start time) does not change the
  hash.
- A chunk that did not change inside an edited call is still re-embedded, because the unit of
  work is the call. Per-chunk reuse is possible, since chunk ids are stable, and was not built.
- Two syncs at the same time are not protected against each other.

## Alternatives considered

- **Timestamps ("modified since")**: cheap, and wrong when a clock is off or a file is
  re-delivered unchanged.
- **Delete and re-add the call in two steps**: a reader between the steps finds the call
  missing.
