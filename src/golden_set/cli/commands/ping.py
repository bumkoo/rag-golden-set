"""ping: LLM과 임베딩에 한 번씩 요청해 연결과 JSON 응답 여부를 확인한다."""

import argparse
import sys

from golden_set.cli.llm_options import llm_settings


def cmd_ping(args: argparse.Namespace) -> int:
    """LLM과 임베딩에 한 번씩 요청해 연결과 JSON 응답 여부를 확인한다."""
    from golden_set.generation.llm.ping import ping
    from golden_set.generation.llm.settings import EMBED_ENV, LLM_ENV, ConfigError

    try:
        settings = llm_settings(args, need_embed=False)
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
