# Architecture

Calls go in as transcripts with a tenant id. What comes out is a LanceDB index of redacted
chunks that can only be searched one tenant at a time.

## The pipeline

```mermaid
flowchart LR
    calls["Call transcripts<br/>turns, tenant id,<br/>caller and agent names"] --> redact

    subgraph prepare["prepare (per call, no I/O)"]
        redact["redact each turn<br/>email, phone, card (check digit),<br/>address, names"]
        bounds["chunk boundaries<br/>from the original turns"]
        chunk["chunks of redacted text<br/>whole turns, 1 turn overlap"]
        hash["content hash<br/>text + chunk settings + embedder name"]
        redact --> chunk
        bounds --> chunk
        chunk --> hash
    end

    hash --> sync

    subgraph index["Index (LanceDB)"]
        sync["sync<br/>compare hashes,<br/>embed only what changed"]
        chunks[("chunks<br/>text, vector, tenant, call")]
        state[("calls<br/>content hash per call")]
        tomb[("tombstones<br/>erased calls")]
        sync --> chunks
        sync --> state
        tomb -. "skip" .-> sync
    end

    embedder{{"Embedder (protocol)<br/>hashing, 2048 dims"}} --> sync
    query(["search(tenant, query, k)"]) --> filter["validate tenant id,<br/>filter, then nearest k"]
    embedder --> filter
    chunks --> filter
    filter --> hits["chunks from that tenant only"]
```

Raw text never reaches the index. `prepare` returns redacted chunks, and `Index` accepts only
what `prepare` returns.

## One sync

```mermaid
flowchart TB
    start(["sync(prepared calls)"]) --> each{"for each call"}
    each -- "id in tombstones" --> skip["skip: erased"]
    each -- "not in calls table" --> add["new"]
    each -- "hash differs" --> upd["changed"]
    each -- "hash equal" --> same["unchanged: no work"]
    add --> embed["embed the chunks of new and changed calls"]
    upd --> embed
    embed --> merge["one merge on chunks:<br/>insert new rows,<br/>delete those calls' old rows"]
    merge --> record["update the calls table"]
    record --> done(["stats: added, updated, unchanged,<br/>skipped, chunks embedded"])
```

The chunk replacement is a single commit. The `calls` table is updated after it. If the process
stops between the two, the next sync sees the old hash and does the same replacement again,
which gives the same result.

## Erasure

```mermaid
sequenceDiagram
    participant U as erase_call
    participant T as tombstones
    participant C as chunks
    participant F as data files
    U->>T: add the call id (first, so it cannot be re-indexed)
    U->>C: delete rows of the call
    Note over C,F: rows are hidden by a deletion marker,<br/>still inside the data file,<br/>and readable through the previous version
    U->>C: purge: rewrite data files without hidden rows
    U->>C: purge: drop every older version
    Note over F: old data files removed
    Note over T: a later sync still sees the call in its input and skips it
```

## Modules

| Module | Does |
|---|---|
| `synth.py` | Generates calls and the answer key of planted personal information |
| `redact.py` | Finds and replaces personal information |
| `prepare.py` | Redacts and chunks one call; computes its content hash |
| `embed.py` | The embedder protocol and the hashing embedder |
| `index.py` | Sync, search, erase and purge on LanceDB |
| `evaluate.py` | Scores redaction, retrieval, isolation and incremental sync; writes the report |
