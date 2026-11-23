"""prepare: 폴더를 읽고 반복 머리글·바닥글을 지운 뒤 청크로 나눠 chunks.jsonl로 저장한다."""

import argparse
import sys

from golden_set.loading.loaders.base import LoadError
from golden_set.loading.registry import load_dir


def cmd_prepare(args: argparse.Namespace) -> int:
    """폴더를 읽고 반복 머리글·바닥글을 지운 뒤 청크로 나눠 chunks.jsonl로 저장한다."""
    from collections import Counter

    from golden_set.domain.store import write_chunks
    from golden_set.chunking import ChunkSettings, CleanSettings, chunk_docs, clean_docs

    try:
        docs, failures = load_dir(args.folder)
    except LoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        chunk_settings = ChunkSettings(size=args.chunk_size, overlap=args.overlap, min_chars=args.min_chars)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    errors = [f for f in failures if f.reason != "unsupported"]
    for f in failures:
        print(f"skip  {f.path}  ({f.reason})")

    cleaned, reports = clean_docs(docs, CleanSettings(min_ratio=args.header_ratio))
    for r in reports:
        if not r.removed:
            continue
        print(f"\nremoved from {r.source} ({r.page_count} pages):")
        for line in r.removed:
            print(f"  [{line.position}] x{line.count}  {line.example!r}  (pattern {line.pattern!r})")

    chunks = chunk_docs(cleaned, chunk_settings)
    per_file = Counter(str(c.metadata.get("source", "")) for c in chunks)
    print(f"\n{'chunks':>6}  source")
    for source in sorted({str(d.metadata.get('source', '')) for d in docs}):
        print(f"{per_file.get(source, 0):>6}  {source}")
    sizes = [len(c.page_content) for c in chunks]
    print(
        f"\ndocs={len(docs)}  chunks={len(chunks)}  "
        f"chars min/avg/max={min(sizes) if sizes else 0}/{(sum(sizes) / len(sizes)) if sizes else 0:.0f}/{max(sizes) if sizes else 0}  "
        f"errors={len(errors)}"
    )
    if not chunks:
        print("error: no chunks", file=sys.stderr)
        return 2
    write_chunks(chunks, args.out)
    print(f"saved: {args.out}")
    return 1 if errors else 0
