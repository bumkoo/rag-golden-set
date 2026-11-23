"""명령행 진입점: python -m golden_set.cli validate | compare | prepare | ping | generate | check"""

import argparse
import csv
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, UnsupportedError
from golden_set.registry import get_loader, list_files, load_dir, loaders_for
from golden_set.validate import FileReport, validate_docs

SAMPLE_CHARS = 300
CSV_COLUMNS = [
    "path",
    "file_type",
    "loader",
    "status",
    "doc_count",
    "empty_ratio",
    "avg_chars",
    "broken_ratio",
    "hangul_ratio",
    "meta_ok",
    "elapsed_sec",
    "reasons",
]


@dataclass
class Row:
    """표의 한 줄. status는 pass, fail(기준 미달), error(읽기 실패), unsupported 중 하나다."""

    path: str
    loader: str
    status: str
    report: FileReport | None = None
    reason: str = ""
    docs: list[Document] = field(default_factory=list)


def run_one(path: str, loader_name: str | None = None) -> Row:
    """파일 하나를 읽고 검증한다. 읽기 실패는 예외 대신 error/unsupported 줄로 돌려준다."""
    try:
        loader = get_loader(path, loader_name)
    except UnsupportedError as e:
        return Row(path, loader_name or "-", "unsupported", reason=str(e))
    start = time.perf_counter()
    try:
        docs = loader.load(path)
    except UnsupportedError as e:  # 예: 확장자는 .doc인데 내용이 RTF가 아닌 파일
        return Row(path, "-", "unsupported", reason=str(e))
    except LoadError as e:
        return Row(path, loader.name, "error", reason=str(e))
    elapsed = time.perf_counter() - start
    report = validate_docs(path, loader.name, docs, elapsed_sec=elapsed)
    return Row(path, loader.name, "pass" if report.passed else "fail", report, "; ".join(report.reasons), docs)


def row_values(row: Row) -> dict[str, str]:
    """Row를 CSV_COLUMNS 순서의 문자열 값으로 바꾼다. 지표가 없는 줄은 빈칸이다."""
    values = dict.fromkeys(CSV_COLUMNS, "")
    values.update(path=row.path, loader=row.loader, status=row.status, reasons=row.reason)
    values["file_type"] = Path(row.path).suffix.lower().lstrip(".")
    r = row.report
    if r is not None:
        values.update(
            file_type=r.file_type,
            doc_count=str(r.doc_count),
            empty_ratio=f"{r.empty_ratio:.3f}",
            avg_chars=f"{r.avg_chars:.1f}",
            broken_ratio=f"{r.broken_ratio:.4f}",
            hangul_ratio=f"{r.hangul_ratio:.3f}",
            meta_ok=str(r.meta_ok),
            elapsed_sec="" if r.elapsed_sec is None else f"{r.elapsed_sec:.3f}",
        )
    return values


def print_table(rows: list[Row]) -> None:
    """한 줄에 하나씩 표로 출력한다. 폭이 일정하지 않은 path와 reasons는 뒤에 둔다."""
    columns = [c for c in CSV_COLUMNS if c not in ("path", "file_type", "reasons")] + ["path", "reasons"]
    table = [row_values(r) for r in rows]
    widths = {c: max(len(c), *(len(v[c]) for v in table)) if table else len(c) for c in columns}
    fixed = columns[:-2]
    print("  ".join(c.ljust(widths[c]) for c in fixed) + "  path  (reasons)")
    for v in table:
        tail = v["path"] + (f"  ({v['reasons']})" if v["reasons"] else "")
        print("  ".join(v[c].ljust(widths[c]) for c in fixed) + "  " + tail)


def write_csv(rows: list[Row], out: str) -> None:
    """표를 CSV로 저장한다. Excel에서 한글이 깨지지 않게 utf-8-sig로 쓴다."""
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(row_values(r) for r in rows)


def print_samples(rows: list[Row], n: int) -> None:
    """파일마다 앞에서 N개 문서의 본문 앞 300자를 출력한다. 사람이 눈으로 확인하는 용도다."""
    for row in rows:
        for doc in row.docs[:n]:
            page = doc.metadata.get("page")
            where = f" page={page}" if page is not None else ""
            print(f"\n--- {row.path} [{row.loader}]{where}")
            print(doc.page_content[:SAMPLE_CHARS])


def cmd_validate(args: argparse.Namespace) -> int:
    """폴더의 모든 파일을 기본 로더로 읽고 검증한다."""
    try:
        paths = list_files(args.folder)
    except LoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    rows = [run_one(p) for p in paths]
    print_table(rows)
    counts = {s: sum(r.status == s for r in rows) for s in ("pass", "fail", "error", "unsupported")}
    print("\n" + "  ".join(f"{k}={v}" for k, v in counts.items()))
    if args.samples:
        print_samples(rows, args.samples)
    if args.out:
        write_csv(rows, args.out)
        print(f"\nsaved: {args.out}")
    return 1 if counts["fail"] or counts["error"] else 0


def cmd_compare(args: argparse.Namespace) -> int:
    """파일 하나에 그 형식의 모든 로더를 돌려 지표를 나란히 출력한다. 첫 줄이 기본 로더다."""
    if not Path(args.file).is_file():
        print(f"error: not a file: {args.file}", file=sys.stderr)
        return 2
    loaders = loaders_for(args.file)
    if not loaders:
        print(f"error: unsupported: {args.file}", file=sys.stderr)
        return 2
    rows = [run_one(args.file, loader.name) for loader in loaders]
    print_table(rows)
    if args.samples:
        print_samples(rows, args.samples)
    return 0 if rows[0].status == "pass" else 1


def cmd_prepare(args: argparse.Namespace) -> int:
    """폴더를 읽고 반복 머리글·바닥글을 지운 뒤 청크로 나눠 chunks.jsonl로 저장한다."""
    from collections import Counter

    from golden_set.domain.store import write_chunks
    from golden_set.prepare import ChunkSettings, CleanSettings, chunk_docs, clean_docs

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


def _llm_settings(args: argparse.Namespace, need_embed: bool):
    """LLM 옵션을 환경 변수와 합쳐 LLMSettings를 만든다. 접속 정보가 없으면 ConfigError."""
    from golden_set.llm import settings_from_env

    return settings_from_env(
        need_embed=need_embed,
        concurrency=args.concurrency,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        disable_thinking=not args.keep_thinking,
        json_mode=not args.no_json_mode,
        reasoning_effort=args.reasoning_effort,
    )


def cmd_ping(args: argparse.Namespace) -> int:
    """LLM과 임베딩에 한 번씩 요청해 연결과 JSON 응답 여부를 확인한다."""
    from golden_set.llm import EMBED_ENV, LLM_ENV, ConfigError, ping

    try:
        settings = _llm_settings(args, need_embed=False)
    except ConfigError as e:
        print(f"error: {e}  (환경 변수: {', '.join(LLM_ENV)}, {', '.join(EMBED_ENV)})", file=sys.stderr)
        return 2
    result = ping(settings)
    print(f"llm    {'ok' if result.llm_ok else 'FAIL'}  json={'yes' if result.llm_json else 'NO'}  {result.llm_detail}")
    print(f"       reasoning_content field={'yes' if result.reasoning_separated else 'no'}  <think> in content={'yes' if result.think_in_content else 'no'}")
    if result.embed_ok is None:
        print(f"embed  skipped ({EMBED_ENV[0]} not set)")
    else:
        print(f"embed  {'ok' if result.embed_ok else 'FAIL'}  {result.embed_detail}")
    return 0 if result.ok else 1


def cmd_generate(args: argparse.Namespace) -> int:
    """chunks.jsonl로 생성기 하나를 돌려 candidates.jsonl을 만든다."""
    from golden_set.domain.store import read_chunks, write_candidates
    from golden_set.generators import GenerateError, GenerateReport, get_generator
    from golden_set.llm import EMBED_ENV, LLM_ENV, ConfigError

    try:
        settings = _llm_settings(args, need_embed=args.generator == "ragas")
    except ConfigError as e:
        print(f"error: {e}  (환경 변수: {', '.join(LLM_ENV)}, {', '.join(EMBED_ENV)})", file=sys.stderr)
        return 2
    try:
        chunks = read_chunks(args.chunks)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    options: dict = {"language": args.language}
    if args.generator == "ragas":
        options["adapt_prompts"] = not args.no_adapt_prompts
    else:
        options["context_chunks"] = args.context_chunks
    report = GenerateReport(args.generator)
    try:
        generator = get_generator(args.generator, settings, report=report, **options)
        candidates = generator.generate(chunks, args.size)
    except GenerateError as e:
        print(report.summary())
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    write_candidates(candidates, args.out)
    print(f"saved: {args.out}  ({len(candidates)} candidates, chunks={len(chunks)})")
    return 0 if candidates else 1


def cmd_check(args: argparse.Namespace) -> int:
    """candidates.jsonl을 LLM 없이 검증하고 생성기별 요약을 낸다. 출처 확인에 chunks.jsonl이 필요하다."""
    from golden_set.check import check_candidates, format_summary, print_table, summarize, write_csv
    from golden_set.domain.candidate import CandidateError
    from golden_set.domain.store import read_candidates, read_chunks

    chunks_path = args.chunks
    if chunks_path is None:  # 후보 파일 옆, 그다음 현재 폴더의 chunks.jsonl
        for p in (Path(args.candidates).parent / "chunks.jsonl", Path("chunks.jsonl")):
            if p.is_file():
                chunks_path = str(p)
                break
    if chunks_path is None:
        print("error: chunks.jsonl not found; pass --chunks (출처의 chunk_id를 대조하는 데 필요하다)", file=sys.stderr)
        return 2
    try:
        candidates = read_candidates(args.candidates)
        chunk_ids = {str(c.metadata["chunk_id"]) for c in read_chunks(chunks_path)}
    except (OSError, ValueError, CandidateError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    results = check_candidates(candidates, chunk_ids)
    print_table(results)
    print()
    print(format_summary(summarize(results)))
    if args.out:
        write_csv(results, args.out)
        print(f"\nsaved: {args.out}")
    return 0 if any(r.passed for r in results) else 1


def _add_llm_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("LLM 옵션 (접속 정보는 환경 변수 GOLDEN_LLM_* / GOLDEN_EMBED_*)")
    g.add_argument("--concurrency", type=int, default=4, metavar="N", help="동시 요청 수 (기본 4)")
    g.add_argument("--timeout", type=float, default=120.0, metavar="SEC", help="요청 하나의 제한 시간 (기본 120)")
    g.add_argument("--max-tokens", type=int, default=4096, metavar="N", help="응답 최대 토큰 (기본 4096)")
    g.add_argument("--temperature", type=float, default=0.2, help="도구가 온도를 주지 않는 요청의 온도 (기본 0.2)")
    g.add_argument("--keep-thinking", action="store_true", help="추론 끄기(chat_template_kwargs.enable_thinking=false)를 보내지 않는다")
    g.add_argument("--reasoning-effort", default=None, metavar="LEVEL", help="reasoning_effort 값을 보낸다. Ollama는 enable_thinking을 무시하므로 none을 줘야 추론이 꺼진다")
    g.add_argument("--no-json-mode", action="store_true", help="response_format=json_object 를 붙이지 않는다 (서버가 거부할 때)")


def build_parser() -> argparse.ArgumentParser:
    """명령행 파서를 만든다."""
    parser = argparse.ArgumentParser(prog="golden_set.cli", description="문서 로더 출력 검증과 골든 후보 생성")
    sub = parser.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="폴더의 파일을 모두 읽어 파일별 지표를 출력한다")
    v.add_argument("folder")
    v.add_argument("--out", metavar="report.csv", help="표를 CSV로 저장한다")
    v.add_argument("--samples", type=int, default=0, metavar="N", help="파일마다 본문 앞 300자를 N개 출력한다")
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("compare", help="파일 하나에 그 형식의 모든 로더를 돌려 지표를 나란히 출력한다")
    c.add_argument("file")
    c.add_argument("--samples", type=int, default=0, metavar="N", help="로더마다 본문 앞 300자를 N개 출력한다")
    c.set_defaults(func=cmd_compare)

    p = sub.add_parser("prepare", help="폴더를 읽고 머리글·바닥글을 지운 뒤 청크로 나눠 JSONL로 저장한다")
    p.add_argument("folder")
    p.add_argument("--out", default="chunks.jsonl", metavar="chunks.jsonl", help="청크 JSONL 저장 경로")
    p.add_argument("--chunk-size", type=int, default=1200, metavar="N", help="청크 최대 글자 수 (기본 1200)")
    p.add_argument("--overlap", type=int, default=150, metavar="N", help="청크 사이 겹침 글자 수 (기본 150)")
    p.add_argument("--min-chars", type=int, default=100, metavar="N", help="공백 제거 후 이보다 짧은 청크는 버린다 (기본 100)")
    p.add_argument("--header-ratio", type=float, default=0.6, metavar="R", help="이 비율 이상의 쪽에서 반복되는 첫/끝 줄을 지운다 (기본 0.6)")
    p.set_defaults(func=cmd_prepare)

    pi = sub.add_parser("ping", help="LLM과 임베딩 서버에 한 번씩 요청해 연결과 JSON 응답을 확인한다")
    _add_llm_options(pi)
    pi.set_defaults(func=cmd_ping)

    g = sub.add_parser("generate", help="chunks.jsonl로 골든 후보를 생성해 candidates.jsonl로 저장한다")
    g.add_argument("chunks", metavar="chunks.jsonl")
    g.add_argument("--generator", required=True, choices=["ragas", "deepeval"])
    g.add_argument("--size", type=int, default=30, metavar="N", help="만들 후보 수 (기본 30)")
    g.add_argument("--out", default="candidates.jsonl", metavar="candidates.jsonl")
    g.add_argument("--language", default="auto", choices=["auto", "ko", "en"], help="질문 언어. auto는 청크의 한글 비율로 정한다")
    g.add_argument("--no-adapt-prompts", action="store_true", help="ragas: 프롬프트 예시 번역(adapt_prompts)을 하지 않는다")
    g.add_argument("--context-chunks", type=int, default=3, choices=[1, 2, 3], help="deepeval: context 하나에 넣는 이웃 청크 수 (기본 3)")
    _add_llm_options(g)
    g.set_defaults(func=cmd_generate)

    k = sub.add_parser("check", help="candidates.jsonl을 LLM 없이 검증하고 생성기별 요약을 낸다")
    k.add_argument("candidates", metavar="candidates.jsonl")
    k.add_argument("--chunks", metavar="chunks.jsonl", help="출처 대조용. 없으면 후보 파일 옆이나 현재 폴더의 chunks.jsonl을 쓴다")
    k.add_argument("--out", metavar="report.csv", help="후보별 결과를 CSV로 저장한다")
    k.set_defaults(func=cmd_check)
    return parser


def force_utf8_output() -> None:
    """stdout과 stderr를 utf-8로 바꾼다. cp949 등에 없는 글자가 본문에 있어도 죽지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # capsys 같은 대체 스트림에는 없다
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 불합격 파일이 하나라도 있으면 1을 돌려준다."""
    force_utf8_output()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
