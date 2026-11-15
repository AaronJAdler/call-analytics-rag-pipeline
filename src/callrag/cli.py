from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from callrag import evaluate, synth
from callrag.embed import HashingEmbedder
from callrag.index import Index, InvalidIdentifier
from callrag.prepare import prepare


def cmd_generate(args: argparse.Namespace) -> int:
    calls = synth.generate(args.calls_per_tenant, args.seed)
    synth.write_jsonl(calls, Path(args.out))
    print(f"wrote {len(calls)} synthetic calls to {args.out}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    embedder = HashingEmbedder()
    index = Index(args.index, embedder)
    calls = list(synth.read_jsonl(Path(args.calls)))
    stats = index.sync(prepare(c, index_fingerprint=embedder.name) for c in calls)
    print(
        f"{stats.added} added, {stats.updated} updated, {stats.unchanged} unchanged, "
        f"{stats.tombstoned} skipped as erased; {stats.texts_embedded} chunks embedded"
    )
    print(f"index now holds {index.counts()}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index = Index(args.index, HashingEmbedder())
    try:
        hits = index.search(args.tenant, args.query, args.k)
    except InvalidIdentifier as exc:
        print(exc)
        return 2
    for hit in hits:
        print(f"{hit.distance:.3f}  {hit.call_id}")
        for line in hit.text.splitlines():
            print(f"         {line}")
    return 0


def cmd_erase(args: argparse.Namespace) -> int:
    index = Index(args.index, HashingEmbedder())
    removed = index.erase_call(args.call_id)
    index.purge()
    print(f"erased {args.call_id}: {removed} chunks removed and old versions purged")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    summary = evaluate.run()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "eval.md").write_text(evaluate.render(summary), encoding="utf-8", newline="\n")
    red = summary["redaction"]
    print(
        f"redaction {red['removed']}/{red['planted']}; "
        f"keyword hit@5 {summary['retrieval']['redacted']['keyword']['hit_at_5']}/"
        f"{summary['retrieval']['redacted']['keyword']['queries']}; "
        f"cross-tenant results {summary['isolation']['results_from_another_tenant_with_filter']}. "
        f"Wrote {out / 'eval.md'}."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="callrag", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="write synthetic calls as JSON lines")
    generate.add_argument("--out", default="out/calls.jsonl")
    generate.add_argument("--calls-per-tenant", type=int, default=200)
    generate.add_argument("--seed", type=int, default=evaluate.SEED)
    generate.set_defaults(func=cmd_generate)

    build = sub.add_parser("build", help="redact, chunk, embed and sync calls into the index")
    build.add_argument("--calls", default="out/calls.jsonl")
    build.add_argument("--index", default="index")
    build.set_defaults(func=cmd_build)

    search = sub.add_parser("search", help="search one tenant's calls")
    search.add_argument("--tenant", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("-k", type=int, default=3)
    search.add_argument("--index", default="index")
    search.set_defaults(func=cmd_search)

    erase = sub.add_parser("erase", help="remove a call for good")
    erase.add_argument("call_id")
    erase.add_argument("--index", default="index")
    erase.set_defaults(func=cmd_erase)

    ev = sub.add_parser("eval", help="run the evaluation and write docs/eval.md")
    ev.add_argument("--out", default="docs")
    ev.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
