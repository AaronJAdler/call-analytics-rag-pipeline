# 7. Erasure in three layers

- Status: Accepted
- Date: 2026-11-14

## Context

A customer asks for their call to be removed. "Delete the rows" sounds like the whole answer.
A test written to prove the rows were gone showed that it is not.

After `delete`, on LanceDB 0.41:

- The table's statistics reported the deleted rows as still present in the data file. A delete
  writes a small deletion file that hides them.
- The previous version of the table could be opened by number, and it returned the deleted
  rows.
- Dropping old versions was still not enough: the data file was the same file as before.
- And the next day's sync would have re-indexed the call, because it was still in the source.

## Decision

Erasing a call does three things, in this order:

1. **Tombstone.** The call id is written to a `tombstones` table first. Every sync skips
   tombstoned calls, whatever its input contains.
2. **Delete.** The call's rows are deleted from `chunks` and `calls`.
3. **Purge.** `optimize` runs with deletion materialisation forced (threshold 0), which
   rewrites each data file without its hidden rows, and with a cleanup age of zero, which drops
   every older version and the files only they used.

The tombstone comes first so that a failure part-way leaves the call unable to return, and
erasing again completes the rest.

## Consequences

- A test checks each layer: hidden rows drop to 0, no data file from before the purge remains,
  only one table version exists, and opening the old version by number fails.
- In the evaluation, 15 erased calls that are still in the next sync's input stay out, and 125
  hidden rows (from the erasures and from replaced chunks) drop to 0.
- The purge breaks any reader holding an older version, and LanceDB warns about that. It is a
  maintenance step for a quiet moment, not something to run per request. Between the delete
  and the purge, the call is unsearchable but not yet physically gone; how long that window
  may be is a policy decision.
- The tombstone table itself holds the call id and tenant, and must be kept.
- This covers the index only. The transcript in the system it came from, backups of the index
  directory and any copy made downstream are outside it.
- The check is against LanceDB's own statistics and file listing. The data files are
  compressed, so searching them for the erased text proves nothing either way; that was the
  first version of the test, and it could not find the text even before the delete.

## Alternatives considered

- **Delete only**: what most code does. The data stays on disk.
- **Rebuild the index without the call**: certainly clean, and costs a full re-embedding per
  request.
