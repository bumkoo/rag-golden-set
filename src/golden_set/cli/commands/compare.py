"""compare: 파일 하나에 그 형식의 모든 로더를 돌려 지표를 나란히 출력한다."""

import argparse
import sys
from pathlib import Path

from golden_set.cli.commands.validate import print_samples, print_table, run_one
from golden_set.loading.registry import loaders_for


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
