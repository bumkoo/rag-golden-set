"""인자 해석과 명령 분기."""

import argparse
import sys

from golden_set.cli.commands.check import cmd_check
from golden_set.cli.commands.compare import cmd_compare
from golden_set.cli.commands.generate import cmd_generate
from golden_set.cli.commands.ping import cmd_ping
from golden_set.cli.commands.prepare import cmd_prepare
from golden_set.cli.commands.validate import cmd_validate
from golden_set.cli.llm_options import add_llm_options


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
    add_llm_options(pi)
    pi.set_defaults(func=cmd_ping)

    g = sub.add_parser("generate", help="chunks.jsonl로 골든 후보를 생성해 candidates.jsonl로 저장한다")
    g.add_argument("chunks", metavar="chunks.jsonl")
    g.add_argument("--generator", required=True, choices=["ragas", "deepeval"])
    g.add_argument("--size", type=int, default=30, metavar="N", help="만들 후보 수 (기본 30)")
    g.add_argument("--out", default="candidates.jsonl", metavar="candidates.jsonl")
    g.add_argument("--language", default="auto", choices=["auto", "ko", "en"], help="질문 언어. auto는 청크의 한글 비율로 정한다")
    g.add_argument("--no-adapt-prompts", action="store_true", help="ragas: 프롬프트 예시 번역(adapt_prompts)을 하지 않는다")
    g.add_argument("--context-chunks", type=int, default=3, choices=[1, 2, 3], help="deepeval: context 하나에 넣는 이웃 청크 수 (기본 3)")
    g.add_argument("--log-file", metavar="generate.log", help="단계 요약과 마지막 리포트를 이 파일에도 쓴다 (본문, 서버 주소, 키는 쓰지 않는다)")
    add_llm_options(g)
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
