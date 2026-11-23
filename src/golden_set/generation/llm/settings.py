"""접속 설정. 접속 정보는 환경 변수로만 받는다."""

import os
from dataclasses import dataclass

LLM_ENV = ("GOLDEN_LLM_BASE_URL", "GOLDEN_LLM_MODEL", "GOLDEN_LLM_API_KEY")
EMBED_ENV = ("GOLDEN_EMBED_BASE_URL", "GOLDEN_EMBED_MODEL", "GOLDEN_EMBED_API_KEY")
DEFAULT_API_KEY = "EMPTY"  # vLLM, SGLang은 키를 검사하지 않는다. 비어 있으면 이 값을 보낸다


class ConfigError(Exception):
    """접속 정보가 없거나 모자랄 때."""


@dataclass(frozen=True)
class Endpoint:
    """OpenAI 호환 서버 하나."""

    base_url: str
    model: str
    api_key: str = DEFAULT_API_KEY


@dataclass(frozen=True)
class LLMSettings:
    """연결 설정. 환경 변수 밖의 값(동시 요청 수 등)은 CLI 옵션으로 바꾼다."""

    llm: Endpoint
    embed: Endpoint | None = None
    concurrency: int = 4  # 서버 한 대를 상대하므로 도구 기본값을 쓰지 않는다
    timeout: float = 120.0  # 요청 하나의 제한 시간(초)
    max_tokens: int = 4096
    temperature: float = 0.2  # 호출자가 온도를 주지 않을 때
    disable_thinking: bool = True  # Qwen3 계열: chat_template_kwargs.enable_thinking=false 를 보낸다
    json_mode: bool = True  # JSON 응답을 기대하는 요청에 response_format=json_object 를 붙인다
    reasoning_effort: str | None = None  # Ollama처럼 chat_template_kwargs를 무시하는 서버용. "none"이면 추론을 끈다


def endpoint_from_env(names: tuple[str, str, str], env: dict[str, str] | None = None) -> Endpoint | None:
    """세 환경 변수로 Endpoint를 만든다. 주소와 모델이 둘 다 없으면 None, 하나만 있으면 ConfigError."""
    e = os.environ if env is None else env
    base_url, model, key = (e.get(n, "").strip() for n in names)
    if not base_url and not model:
        return None
    missing = [n for n, v in zip(names[:2], (base_url, model)) if not v]
    if missing:
        raise ConfigError(f"missing {', '.join(missing)}")
    return Endpoint(base_url=base_url, model=model, api_key=key or DEFAULT_API_KEY)


def settings_from_env(need_embed: bool = False, env: dict[str, str] | None = None, **overrides) -> LLMSettings:
    """환경 변수에서 설정을 읽는다. LLM이 없으면 ConfigError, need_embed인데 임베딩이 없으면 ConfigError."""
    llm = endpoint_from_env(LLM_ENV, env)
    if llm is None:
        raise ConfigError(f"missing {LLM_ENV[0]}, {LLM_ENV[1]}")
    embed = endpoint_from_env(EMBED_ENV, env)
    if need_embed and embed is None:
        raise ConfigError(f"missing {EMBED_ENV[0]}, {EMBED_ENV[1]}")
    return LLMSettings(llm=llm, embed=embed, **overrides)
