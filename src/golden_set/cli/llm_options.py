"""ping과 generate가 같이 쓰는 LLM 옵션."""

import argparse


def add_llm_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("LLM 옵션 (접속 정보는 환경 변수 GOLDEN_LLM_* / GOLDEN_EMBED_*)")
    g.add_argument("--concurrency", type=int, default=4, metavar="N", help="동시 요청 수 (기본 4)")
    g.add_argument("--timeout", type=float, default=120.0, metavar="SEC", help="요청 하나의 제한 시간 (기본 120)")
    g.add_argument("--max-tokens", type=int, default=4096, metavar="N", help="응답 최대 토큰 (기본 4096)")
    g.add_argument("--temperature", type=float, default=0.2, help="도구가 온도를 주지 않는 요청의 온도 (기본 0.2)")
    g.add_argument("--keep-thinking", action="store_true", help="추론 끄기(chat_template_kwargs.enable_thinking=false)를 보내지 않는다")
    g.add_argument("--reasoning-effort", default=None, metavar="LEVEL", help="reasoning_effort 값을 보낸다. Ollama는 enable_thinking을 무시하므로 none을 줘야 추론이 꺼진다")
    g.add_argument("--no-json-mode", action="store_true", help="response_format=json_object 를 붙이지 않는다 (서버가 거부할 때)")


def llm_settings(args: argparse.Namespace, need_embed: bool):
    """LLM 옵션을 환경 변수와 합쳐 LLMSettings를 만든다. 접속 정보가 없으면 ConfigError."""
    from golden_set.generation.llm.settings import settings_from_env

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
