"""Measures the pipeline on the synthetic corpus and writes the report.

Four questions:

1. Redaction: of the personal information the generator planted, how much was removed, and
   what was removed that should not have been?
2. Retrieval: how often does a search find the right call, with and without redaction?
3. Isolation: does any search return another tenant's data?
4. Incremental sync: after a day of new, edited and erased calls, how much work is done?
"""

from __future__ import annotations

import random
import re
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from callrag import redact, synth
from callrag.embed import Embedder, HashingEmbedder
from callrag.index import Index
from callrag.prepare import PreparedCall, prepare
from callrag.synth import Call, Turn

SEED = 7
CALLS_PER_TENANT = 200
QUERIES_PER_TENANT = 100
KS = (1, 5, 10)
# How each kind of personal information was said, in the order the report lists it.
FORMS: dict[tuple[str, str], str] = {
    ("NAME", "agent"): "agent's first name",
    ("NAME", "introduced"): 'caller\'s full name after "my name is", "this is" and similar',
    ("NAME", "known"): "caller's first name, said by the agent",
    ("NAME", "relative"): 'third person after "my husband", "our tenant" and similar',
    ("NAME", "bare"): "third person named with no cue",
    ("PHONE", "formatted"): "digits with punctuation",
    ("PHONE", "digits only"): "ten digits run together",
    ("PHONE", "spoken"): "digits spoken as words",
    ("EMAIL", "written"): "written form",
    ("EMAIL", "spoken"): '"name dot name at example dot com"',
    ("ADDRESS", "full"): "number, street, city, state, ZIP",
    ("ADDRESS", "with unit"): "number, street, apartment",
    ("ADDRESS", "lowercase"): "number and street, all lower case",
    ("ADDRESS", "described"): "described without a number",
    ("CARD", "written"): "16 digits, spaced, dashed or plain",
}


# ------------------------------------------------------------------------------------ redaction


def score_redaction(calls: Sequence[Call]) -> dict[str, Any]:
    planted: Counter[tuple[str, str]] = Counter()
    removed: Counter[tuple[str, str]] = Counter()
    wrong: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], list[str]] = {}
    for call in calls:
        known = (call.caller_name, call.agent_name)
        for number, turn in enumerate(call.turns):
            spans = redact.find(turn.text, known)
            truth = [p for p in call.pii if p.turn == number]
            for item in truth:
                planted[(item.kind, item.form)] += 1
                # Only a span covering the whole value counts. Half a phone number is a leak.
                if any(s.start <= item.start and s.end >= item.end for s in spans):
                    removed[(item.kind, item.form)] += 1
            for span in spans:
                if not any(span.start < t.end and t.start < span.end for t in truth):
                    key = (span.kind, span.rule)
                    wrong[key] += 1
                    sample = examples.setdefault(key, [])
                    if len(sample) < 3:
                        sample.append(turn.text[span.start : span.end])
    rows = [
        {
            "kind": kind,
            "form": FORMS[(kind, form)],
            "planted": planted[(kind, form)],
            "removed": removed[(kind, form)],
        }
        for kind, form in FORMS
        if planted[(kind, form)]
    ]
    return {
        "planted": sum(planted.values()),
        "removed": sum(removed.values()),
        "by_form": rows,
        "false_redactions": [
            {"placeholder": kind, "rule": rule, "count": n, "examples": examples[(kind, rule)]}
            for (kind, rule), n in sorted(wrong.items())
        ],
    }


def scan_index_for_pii(index: Index, calls: Sequence[Call]) -> dict[str, Any]:
    """Look for every planted value in the text that was actually indexed."""
    by_call: dict[str, list[str]] = {}
    for _tenant, call_id, text in index.all_chunk_texts():
        by_call.setdefault(call_id, []).append(text.lower())
    found: Counter[tuple[str, str]] = Counter()
    for call in calls:
        texts = by_call.get(call.call_id, [])
        for item in call.pii:
            pattern = rf"(?<![a-z0-9]){re.escape(item.value.lower())}(?![a-z0-9])"
            if any(re.search(pattern, t) for t in texts):
                found[(item.kind, item.form)] += 1
    return {
        "values_found": sum(found.values()),
        "by_form": [
            {"kind": k, "form": FORMS[(k, f)], "found": n} for (k, f), n in sorted(found.items())
        ],
    }


# ------------------------------------------------------------------------------------ retrieval


def build_queries(calls: Sequence[Call]) -> list[dict[str, Any]]:
    """Two questions about each sampled call, with the set of calls that answer them.

    - keyword: the caller's own vocabulary ("garage Rheem water heater leak").
    - paraphrase: the same problem in words no caller uses ("hot water tank dripping onto the
      floor, garage"). Only the location is shared with the transcripts.
    """
    queries: list[dict[str, Any]] = []
    for tenant in synth.TENANTS:
        mine = [c for c in calls if c.tenant_id == tenant.tenant_id]
        rng = random.Random(f"{SEED}/queries/{tenant.tenant_id}")
        for call in rng.sample(mine, min(QUERIES_PER_TENANT, len(mine))):
            topic = synth.topic_of(call)
            same_topic_place = [
                c.call_id for c in mine if c.topic == call.topic and c.location == call.location
            ]
            exact = [
                c.call_id
                for c in mine
                if (c.topic, c.location, c.brand) == (call.topic, call.location, call.brand)
            ]
            queries.append(
                {
                    "tenant": tenant.tenant_id,
                    "style": "keyword",
                    "text": f"{call.location} {call.brand} {topic.key.replace('_', ' ')}",
                    "relevant": exact,
                }
            )
            queries.append(
                {
                    "tenant": tenant.tenant_id,
                    "style": "paraphrase",
                    "text": f"{topic.paraphrase}, {call.location}",
                    "relevant": same_topic_place,
                }
            )
    return queries


def score_retrieval(index: Index, queries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for style in ("keyword", "paraphrase"):
        mine = [q for q in queries if q["style"] == style]
        hits = dict.fromkeys(KS, 0)
        reciprocal = 0.0
        for query in mine:
            relevant = set(query["relevant"])
            results = index.search(query["tenant"], query["text"], max(KS))
            rank = next((i for i, h in enumerate(results, 1) if h.call_id in relevant), None)
            if rank is not None:
                reciprocal += 1 / rank
                for k in KS:
                    hits[k] += rank <= k
        out[style] = {
            "queries": len(mine),
            **{f"hit_at_{k}": hits[k] for k in KS},
            "mrr_at_10": round(reciprocal / len(mine), 3),
        }
    return out


def score_isolation(index: Index, queries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """With the filter: count results from the wrong tenant. Without it: count queries that
    would have shown one in the top 5."""
    wrong_filtered = 0
    exposed_unfiltered = 0
    for query in queries:
        results = index.search(query["tenant"], query["text"], 5)
        wrong_filtered += sum(1 for h in results if h.tenant_id != query["tenant"])
        vector = index.embedder.embed([query["text"]])[0]
        raw = index.search_unfiltered(vector, 5)
        exposed_unfiltered += any(r["tenant_id"] != query["tenant"] for r in raw)
    return {
        "queries": len(queries),
        "results_from_another_tenant_with_filter": wrong_filtered,
        "queries_exposed_without_filter": exposed_unfiltered,
    }


# ---------------------------------------------------------------------------------- incremental


def _edited(call: Call) -> Call:
    extra = Turn("caller", "One more thing, please have the technician call before arriving.")
    return replace(call, turns=(*call.turns, extra))


def score_incremental(embedder: Embedder, calls: Sequence[Call], workdir: Path) -> dict[str, Any]:
    """Day 1: index 180 calls per tenant. Day 2: 20 new per tenant, 10 edited, 5 erased."""

    def ready(batch: Sequence[Call]) -> list[PreparedCall]:
        return [prepare(c, index_fingerprint=embedder.name) for c in batch]

    index = Index(workdir / "incremental", embedder)
    day_one: list[Call] = []
    day_two: list[Call] = []
    erased: list[str] = []
    for tenant in synth.TENANTS:
        mine = [c for c in calls if c.tenant_id == tenant.tenant_id]
        day_one += mine[:180]
        day_two += [_edited(c) for c in mine[:10]] + mine[10:]
        erased += [c.call_id for c in mine[170:175]]
    first = index.sync(ready(day_one))
    for call_id in erased:
        index.erase_call(call_id)
    second = index.sync(ready(day_two))  # the source still contains the erased calls
    masked_before = index.masked_rows()
    index.purge()
    again = index.sync(ready(day_two))
    remaining = sum(1 for _t, call_id, _x in index.all_chunk_texts() if call_id in set(erased))
    return {
        "day_one": first.__dict__,
        "day_two": second.__dict__,
        "rerun": again.__dict__,
        "full_rebuild_would_embed": sum(len(p.chunks) for p in ready(day_two)),
        "erased_calls": len(erased),
        "chunks_of_erased_calls_remaining": remaining,
        "masked_rows_before_purge": masked_before,
        "masked_rows_after_purge": index.masked_rows(),
        "chunk_table_versions_after_purge": len(index.chunks.list_versions()),
        "counts": index.counts(),
    }


# --------------------------------------------------------------------------------------- report


def run(workdir: Path | None = None) -> dict[str, Any]:
    calls = synth.generate(CALLS_PER_TENANT, SEED)
    queries = build_queries(calls)
    with tempfile.TemporaryDirectory() as scratch:
        base = workdir or Path(scratch)
        results: dict[str, Any] = {}
        for label, redaction in (("redacted", True), ("unredacted", False)):
            embedder = HashingEmbedder()
            index = Index(base / label, embedder)
            index.sync(
                [prepare(c, index_fingerprint=embedder.name, redaction=redaction) for c in calls]
            )
            results[label] = {"index": index, "retrieval": score_retrieval(index, queries)}
        redacted: Index = results["redacted"]["index"]
        return {
            "seed": SEED,
            "embedder": redacted.embedder.name,
            "corpus": {
                "tenants": len(synth.TENANTS),
                "calls": len(calls),
                "turns": sum(len(c.turns) for c in calls),
                "chunks": redacted.counts()["chunks"],
                "pii_items": sum(len(c.pii) for c in calls),
            },
            "redaction": score_redaction(calls),
            "index_scan": scan_index_for_pii(redacted, calls),
            "retrieval": {k: v["retrieval"] for k, v in results.items()},
            "isolation": score_isolation(redacted, queries),
            "incremental": score_incremental(HashingEmbedder(), calls, base),
        }


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def render(summary: dict[str, Any]) -> str:
    out: list[str] = []
    add = out.append
    corpus = summary["corpus"]
    add("# Evaluation")
    add("")
    add(
        "Generated by `uv run callrag eval`. Do not edit by hand: CI regenerates this file and "
        "fails if it differs."
    )
    add("")
    add(
        f"Corpus: {corpus['calls']} synthetic calls across {corpus['tenants']} tenants, "
        f"{corpus['turns']} turns, {corpus['chunks']} chunks, {corpus['pii_items']} planted "
        f"pieces of personal information. Seed {summary['seed']}; embedder "
        f"`{summary['embedder']}`. Every person, number and address is invented."
    )
    add("")
    add("## 1. Redaction")
    add("")
    red = summary["redaction"]
    add(
        f"{red['removed']} of {red['planted']} planted values were fully removed "
        f"({_pct(red['removed'], red['planted'])}). A value counts as removed only if a "
        "redaction covers all of it."
    )
    add("")
    add("| Kind | How it was said | Planted | Removed | |")
    add("|---|---|---|---|---|")
    for row in red["by_form"]:
        add(
            f"| {row['kind']} | {row['form']} | {row['planted']} | {row['removed']} "
            f"| {_pct(row['removed'], row['planted'])} |"
        )
    add("")
    add("Redactions that hit something other than planted personal information:")
    add("")
    add("| Placeholder | Rule that fired | Count | Examples |")
    add("|---|---|---|---|")
    for row in red["false_redactions"]:
        examples = ", ".join(f"`{e}`" for e in row["examples"])
        add(f"| [{row['placeholder']}] | {row['rule']} | {row['count']} | {examples} |")
    if not red["false_redactions"]:
        add("| none | | 0 | |")
    add("")
    scan = summary["index_scan"]
    add(
        f"Scanning the text that was actually indexed for every planted value finds "
        f"{scan['values_found']}:"
    )
    add("")
    for row in scan["by_form"]:
        add(f"- {row['kind']}, {row['form']}: {row['found']}")
    add("")
    add("## 2. Retrieval")
    add("")
    add(
        "For each of 100 sampled calls per tenant, two searches inside that tenant. A search "
        "succeeds at k when one of the top k chunks comes from a call that matches."
    )
    add("")
    add("| Index | Query style | Queries | Hit@1 | Hit@5 | Hit@10 | MRR@10 |")
    add("|---|---|---|---|---|---|---|")
    for label in ("redacted", "unredacted"):
        for style in ("keyword", "paraphrase"):
            r = summary["retrieval"][label][style]
            n = r["queries"]
            add(
                f"| {label} | {style} | {n} | {_pct(r['hit_at_1'], n)} | {_pct(r['hit_at_5'], n)} "
                f"| {_pct(r['hit_at_10'], n)} | {r['mrr_at_10']:.3f} |"
            )
    add("")
    add("## 3. Tenant isolation")
    add("")
    iso = summary["isolation"]
    add(
        f"Across {iso['queries']} searches, results from another tenant with the tenant filter: "
        f"**{iso['results_from_another_tenant_with_filter']}**. The same searches run without "
        f"the filter would have put another tenant's chunk in the top 5 for "
        f"{iso['queries_exposed_without_filter']} of them "
        f"({_pct(iso['queries_exposed_without_filter'], iso['queries'])})."
    )
    add("")
    add("## 4. Incremental sync and erasure")
    add("")
    inc = summary["incremental"]
    add("| Step | Added | Updated | Unchanged | Skipped (erased) | Chunks embedded |")
    add("|---|---|---|---|---|---|")
    for label, key in (
        ("Day 1: first load", "day_one"),
        ("Day 2: new, edited and erased calls", "day_two"),
        ("Day 2 again, nothing changed", "rerun"),
    ):
        s = inc[key]
        add(
            f"| {label} | {s['added']} | {s['updated']} | {s['unchanged']} | {s['tombstoned']} "
            f"| {s['texts_embedded']} |"
        )
    add("")
    add(
        f"A full rebuild on day 2 would have embedded {inc['full_rebuild_would_embed']} chunks. "
        f"{inc['erased_calls']} calls were erased before the day-2 sync and were still present in "
        f"its input; chunks of theirs in the index afterwards: "
        f"**{inc['chunks_of_erased_calls_remaining']}**."
    )
    add("")
    add(
        f"Before the purge, {inc['masked_rows_before_purge']} deleted or replaced rows were still "
        f"physically in the chunk table's data files, hidden by deletion markers. After the "
        f"purge: {inc['masked_rows_after_purge']}, with "
        f"{inc['chunk_table_versions_after_purge']} table version left."
    )
    add("")
    return "\n".join(out)
