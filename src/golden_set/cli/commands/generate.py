"""generate: chunks.jsonl로 생성기 하나를 돌려 candidates.jsonl을 만든다."""

import argparse
import sys

from golden_set.cli.llm_options import llm_settings


def cmd_generate(args: argparse.Namespace) -> int:
    """chunks.jsonl로 생성기 하나를 돌려 candidates.jsonl을 만든다."""
    from golden_set.domain.store import read_chunks, write_candidates
    from golden_set.generation import GenerateError, GenerateReport, get_generator
    from golden_set.generation.progress import ConsoleReporter
    from golden_set.generation.llm.settings import EMBED_ENV, LLM_ENV, ConfigError

    try:
        settings = llm_settings(args, need_embed=args.generator == "ragas")
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
    log = None
    if args.log_file:
        try:
            log = open(args.log_file, "w", encoding="utf-8")
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    # 단계 요약과 마지막 리포트는 reporter를 거쳐 화면과 로그 파일에 같이 찍힌다. 본문, 주소, 키는 여기로 가지 않는다.
    reporter = ConsoleReporter(log=log)
    report = GenerateReport(args.generator)
    try:
        try:
            generator = get_generator(args.generator, settings, report=report, reporter=reporter, **options)
            candidates = generator.generate(chunks, args.size)
        except GenerateError as e:
            reporter.line(report.summary())
            print(f"error: {e}", file=sys.stderr)
            return 1
        reporter.line(report.summary())
        write_candidates(candidates, args.out)
        reporter.line(f"saved: {args.out}  ({len(candidates)} candidates, chunks={len(chunks)})")
        return 0 if candidates else 1
    finally:
        if log is not None:
            log.close()
