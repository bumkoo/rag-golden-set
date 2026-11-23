"""check: candidates.jsonl을 LLM 없이 검증하고 생성기별 요약을 낸다."""

import argparse
import sys
from pathlib import Path

from golden_set.cli.project import for_writing, project_of, read_all_candidates


def cmd_check(args: argparse.Namespace) -> int:
    """candidates.jsonl을 LLM 없이 검증하고 생성기별 요약을 낸다. 출처 확인에 chunks.jsonl이 필요하다."""
    from golden_set.domain.candidate import CandidateError
    from golden_set.domain.store import read_chunks
    from golden_set.evaluation.checks import check_candidates
    from golden_set.evaluation.output import print_table, write_csv
    from golden_set.evaluation.summary import format_summary, summarize

    project = project_of(args)
    if args.candidates:
        candidate_files = [Path(args.candidates)]
    elif project:
        candidate_files = project.generated()
        if not candidate_files:
            print(f"error: no candidates in {project.generate_dir}", file=sys.stderr)
            return 2
    else:
        print("error: candidates.jsonl 경로나 --project를 준다", file=sys.stderr)
        return 2
    chunks_path = args.chunks
    if chunks_path is None and project and project.chunks.is_file():
        chunks_path = str(project.chunks)
    if chunks_path is None:  # 후보 파일 옆, 그다음 현재 폴더의 chunks.jsonl
        for p in (candidate_files[0].parent / "chunks.jsonl", Path("chunks.jsonl")):
            if p.is_file():
                chunks_path = str(p)
                break
    if chunks_path is None:
        print("error: chunks.jsonl not found; pass --chunks (출처의 chunk_id를 대조하는 데 필요하다)", file=sys.stderr)
        return 2
    try:
        candidates = read_all_candidates(candidate_files)
        chunk_ids = {c.chunk_id for c in read_chunks(chunks_path)}
    except (OSError, ValueError, CandidateError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    results = check_candidates(candidates, chunk_ids)
    print_table(results)
    print()
    print(format_summary(summarize(results)))
    out = args.out or (for_writing(project.check_csv) if project else None)
    if out:
        write_csv(results, out)
        print(f"\nsaved: {out}")
    return 0 if any(r.passed for r in results) else 1
