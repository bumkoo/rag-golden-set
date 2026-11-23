"""export: candidates.jsonl을 바깥 시스템의 데이터셋 형식으로 바꿔 저장한다."""

import argparse
import sys
from pathlib import Path

from golden_set.cli.project import for_writing, project_of, read_all_candidates


def cmd_export(args: argparse.Namespace) -> int:
    """후보 파일을 읽어 --format 형식으로 쓴다. 후보가 없으면 1, 파일을 읽거나 쓰지 못하면 2.

    --project만 주면 검수본(4-check/reviewed.candidates.jsonl)이 있을 때 그것을, 없으면 3-generate/의 후보 전부를 내보낸다.
    """
    from golden_set.domain.candidate import CandidateError
    from golden_set.exporting import EXPORTERS

    project = project_of(args)
    if args.candidates:
        sources = [Path(args.candidates)]
    elif project:
        sources = [project.reviewed] if project.reviewed.is_file() else project.generated()
        if not sources:
            print(f"error: no candidates in {project.generate_dir}", file=sys.stderr)
            return 2
    else:
        print("error: candidates.jsonl 경로나 --project를 준다", file=sys.stderr)
        return 2
    if not args.out and not project:
        print("error: --out이나 --project를 준다", file=sys.stderr)
        return 2
    try:
        candidates = read_all_candidates(sources)
    except (OSError, ValueError, CandidateError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not candidates:
        print("error: no candidates", file=sys.stderr)
        return 1
    try:
        out = args.out or for_writing(project.export_file(args.format))
        count = EXPORTERS[args.format](candidates, out)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not args.candidates:
        print("from: " + ", ".join(str(p) for p in sources))
    print(f"saved: {out}  ({count} items, format={args.format})")
    return 0
