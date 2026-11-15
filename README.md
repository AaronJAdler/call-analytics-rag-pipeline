# call-analytics-rag-pipeline

[![CI](https://github.com/AaronJAdler/call-analytics-rag-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/AaronJAdler/call-analytics-rag-pipeline/actions/workflows/ci.yml)

A data pipeline that turns call transcripts into a search index a retrieval-augmented (RAG)
application can use safely: personal information is redacted before anything is stored, the
index is updated incrementally, every search is confined to one tenant, and an erased call is
physically gone. It runs on **synthetic transcripts only**: three invented home-service
businesses, 600 invented calls.

**[Full evaluation](docs/eval.md)** (generated; a test fails if it is out of date)

## What it demonstrates

- **Redaction measured against an answer key.** The generator records where it planted every
  name, phone number, email, address and card number. The redactor is scored on all 4,271,
  including the forms it cannot catch.
- **Incremental indexing.** A content hash per call decides what to re-embed. A day with 60 new
  and 30 edited calls embeds 266 chunks where a rebuild would embed 1,725.
- **Tenant isolation by construction.** Search takes a tenant, validates it, filters before the
  nearest-neighbour search and checks the results again. There is no cross-tenant search to
  call by mistake.
- **Erasure that is really erasure.** Deleting rows in LanceDB hides them; it does not remove
  them. The purge step rewrites the data files, drops old versions, and a tombstone stops the
  next sync from bringing the call back.
- **A model-free, reproducible build.** The embedder is a protocol. The one that ships hashes
  words into 2,048 dimensions: no download, no GPU, the same vectors on every machine.
- **Measurement that changed the design three times.** Each case is described below.

## Results

All numbers are from `uv run callrag eval` on the synthetic corpus (seed 7).

### Redaction: 4,141 of 4,271 planted values removed (97%)

| What | Removed |
|---|---|
| Phone numbers: punctuated, ten digits run together, spoken as words | 600 of 600 |
| Emails: written, and spoken ("name dot name at example dot com") | 355 of 355 |
| Card numbers: spaced, dashed or plain | 152 of 152 |
| Addresses with a house number: full, with apartment, or all lower case | 531 of 531 |
| Names the business holds for the call (caller and agent), anywhere they appear | 2,400 of 2,400 |
| A third person introduced by a relation ("my husband ...") | 103 of 103 |
| **A third person named with no cue ("Naomi will let the technician in")** | **0 of 61** |
| **An address described in words ("the blue house on Alder past the school")** | **0 of 69** |

What that table does and does not show:

- **The 100% rows are less impressive than they look.** I wrote the generator and the redactor.
  The rules catch the forms I thought of because I thought of them. Real transcripts have
  speech-recognition errors, interruptions and phrasings nobody planned for. Treat these rows as
  a regression test, not as an estimate of recall on real calls.
- **The 0% rows are the honest part.** Rules cannot find a bare first name or a described
  location. Those need a named-entity model, and then a way to measure its misses. All 130
  missed values are in the index, and the report says so: a scan of the indexed text for every
  planted value finds exactly those 130.
- **215 false redactions**, all ten-digit appliance serial numbers taken for phone numbers.
  That is the rule working as designed: when a detector cannot tell, it redacts. A hidden
  serial number costs a little search quality; a leaked phone number is a leak.
- Sixteen-digit confirmation codes are left alone, because the card detector checks the check
  digit.

### Retrieval

300 searches of each style, each inside one tenant. A hit at k means one of the top k chunks
comes from a matching call.

| Index | Query style | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---|---|---|---|---|
| redacted | keyword ("garage Rheem water heater leak") | 96% | 98% | 100% | 0.968 |
| unredacted | keyword | 96% | 98% | 100% | 0.971 |
| redacted | paraphrase ("hot water tank dripping onto the floor, garage") | 56% | 73% | 77% | 0.628 |
| unredacted | paraphrase | 59% | 72% | 80% | 0.647 |

- **Redaction costs keyword search nothing measurable.**
- **The paraphrase rows are a floor, and say so on purpose.** The shipped embedder matches
  words. The paraphrase queries share only the room or location with the transcripts, so a hit
  means "found a call in the right place about the right thing, mostly by the place". A real
  embedding model would do far better here. This number is the baseline to beat when one is
  plugged in.
- These measure the pipeline, not answer quality. There is no language model here and nothing
  generates an answer.

### Tenant isolation

Across 600 searches, results from another tenant: **0**. Run without the tenant filter, the
same searches would have put another tenant's chunk in the top 5 for 125 of them (21%), because
"And the best number to reach you?" sounds the same at every company.

### Incremental sync and erasure

| Step | Added | Updated | Unchanged | Skipped (erased) | Chunks embedded |
|---|---|---|---|---|---|
| Day 1: first load | 540 | 0 | 0 | 0 | 1,542 |
| Day 2: new, edited and erased calls | 60 | 30 | 495 | 15 | 266 |
| Day 2 again, nothing changed | 0 | 0 | 585 | 15 | 0 |

Fifteen calls were erased before the day-2 sync and were still in its input. None came back.

Before the purge, 125 deleted or replaced rows were still physically in the data files, hidden
by deletion markers. After it: 0, with one table version left.

## Three things measuring it changed

1. **Redaction was moving chunk boundaries.** Chunks are sized by word count, and `[ADDRESS]`
   is one word where the address was six. Redacted calls packed more turns per chunk (1,589
   chunks against 1,716) and retrieval got worse for a reason that had nothing to do with the
   information removed. Boundaries are now decided on the original turns and only redacted text
   is stored. A test asserts the two indexes have identical boundaries.
2. **The unredacted index looked better, and it was noise.** At 512 dimensions the unredacted
   index beat the redacted one on paraphrase Hit@1 by 40% to 30%, as if names helped search.
   They do not. With few dimensions, unrelated words collide; redacted chunks from similar
   calls are identical and so collide identically, while each unredacted chunk gets its own
   random collisions and one of several matching calls gets lucky. At 2,048 dimensions the gap
   is 59% to 56% and reverses at Hit@5. The default is now 2,048.
3. **"Deleted" did not mean gone.** After a delete, LanceDB's table statistics still counted
   the rows inside the data file, and the previous table version could still be opened and
   read. Dropping old versions was not enough either: the data file was unchanged. The purge
   now forces a rewrite of the data files, and a test checks all three layers.

The first two were measured during development with settings the committed report no longer
uses, so they are not reproduced by `callrag eval`.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run pytest                 # 75 tests, about 45 seconds (one runs the full evaluation)
uv run callrag eval           # rewrites docs/eval.md and docs/eval.json

uv run callrag generate       # 600 synthetic calls to out/calls.jsonl
uv run callrag build          # redact, chunk, embed, sync into index/
uv run callrag build          # again: 600 unchanged, 0 chunks embedded
uv run callrag search --tenant delta-plumbing --query "garage Rheem water heater leak"
uv run callrag erase delta-plumbing-00003
```

```
$ uv run callrag search --tenant delta-plumbing --query "garage Rheem water heater leak" -k 1
0.721  delta-plumbing-00125
         Agent: Thanks for calling Delta Plumbing, this is [NAME]. How can I help?
         Caller: Yeah, I'm [NAME]. There is water pooling under the Rheem water heater in the garage.
         Agent: How old is the tank?
         Caller: About twelve years, it came with the house.
         ...
```

To use a real embedding model, implement the three members of `Embedder` in
[embed.py](src/callrag/embed.py) (`name`, `dim`, `embed`) and pass it to `Index`. The name is
part of every call's content hash, so the next sync re-embeds everything once.

## How it was verified

| Check | Where it ran |
|---|---|
| ruff lint and format, strict mypy | Locally (Linux, Python 3.12.13, LanceDB 0.41.0) |
| 75 tests: the generator's answer key; each redaction rule, including the three documented limits; chunking; the embedder; sync counts and embedder call counts; tenant filter, including five malformed tenant ids, two of them built to alter the filter; erasure through all three layers; reopening the index; the evaluation matching the committed report | Locally |
| The full evaluation | Locally; the numbers above are copied from its output |
| The command-line flow shown above | Locally |
| GitHub Actions, first push (commit 304f072, Ubuntu 24.04) | Passed: lint, types, 75 tests including the evaluation matching the committed report on a different machine, and the command-line run. The badge shows the current state. |
| A real embedding model | Not run. Only the hashing embedder was used. |
| Real call transcripts | Not used, by design. Nothing here says how the redactor does on real speech. |
| Concurrent readers and writers | Not tested. The purge is documented as unsafe during them. |
| Windows | Not run. |

## Design

- [Architecture](docs/architecture.md): diagrams of the pipeline, a sync, and an erasure.
- [ADR 0001](docs/adr/0001-synthetic-calls-with-an-answer-key.md): synthetic calls with an answer key
- [ADR 0002](docs/adr/0002-redact-before-anything-is-stored.md): redact before anything is stored, and redact when unsure
- [ADR 0003](docs/adr/0003-chunk-on-turns.md): chunk on turn boundaries, decided before redaction
- [ADR 0004](docs/adr/0004-embedder-protocol-and-a-hashing-default.md): an embedder protocol with a deterministic default
- [ADR 0005](docs/adr/0005-incremental-sync-by-content-hash.md): incremental sync by content hash
- [ADR 0006](docs/adr/0006-tenant-isolation.md): tenant isolation by construction
- [ADR 0007](docs/adr/0007-erasure-in-three-layers.md): erasure in three layers

## Limits

- Redaction is rules only. It misses names with no cue and locations described in words, and
  would miss more on real transcripts. It covers US-style phone numbers and addresses only.
- No dates of birth, account numbers, licence plates or health details are generated or
  detected.
- The hashing embedder matches words, not meaning.
- Search is exact (a scan), which is right for 1,716 chunks. A large index needs an approximate
  index, and then the pre-filter and its recall need measuring again.
- One process at a time. The sync has no locking and the purge breaks concurrent readers.
- The raw transcripts are outside this pipeline's control. Erasing a call from the index does
  not erase it from wherever the transcript came from.
- There is no answer generation, so nothing here measures whether a RAG answer would be right.

## Data

Everything is generated by [synth.py](src/callrag/synth.py): companies, people, phone numbers
(the reserved 555-01xx range), emails (example.com), addresses (invented streets and towns) and
card numbers (random digits with a valid check digit, on the 4000 00 prefix that payment
processors use for test cards). No real call was
used as a source or a template. [data/sample_calls.jsonl](data/sample_calls.jsonl) holds six
generated calls to read; a test checks it matches the generator.
