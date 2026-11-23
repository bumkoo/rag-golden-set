"""ping: LLM과 임베딩에 한 번씩 요청해 연결을 확인한다."""

from dataclasses import dataclass

from golden_set.generation.llm.client import ChatClient, EmbedClient, LLMError
from golden_set.generation.llm.settings import LLMSettings

PING_PROMPT = 'Reply with exactly this JSON object and nothing else: {"ok": true, "lang": "ko"}'


@dataclass
class PingResult:
    """ping 결과. 리포트에 그대로 찍는다."""

    llm_ok: bool
    llm_json: bool
    llm_detail: str
    reasoning_separated: bool = False
    think_in_content: bool = False
    embed_ok: bool | None = None  # None이면 임베딩 설정이 없어 건너뛰었다
    embed_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.llm_ok and self.llm_json and self.embed_ok is not False


def ping(settings: LLMSettings, chat: ChatClient | None = None, embed: EmbedClient | None = None) -> PingResult:
    """LLM과 임베딩에 한 번씩 요청해 연결과 JSON 응답 여부를 본다. 예외는 결과에 담고 내지 않는다."""
    import json as _json
    import time

    chat = chat or ChatClient(settings.llm, settings)
    start = time.perf_counter()
    try:
        (c,) = chat.complete([("user", PING_PROMPT)], json=True, temperature=0.0)
    except LLMError as e:
        result = PingResult(False, False, f"error: {e}")
    else:
        try:
            parsed = _json.loads(c.text)
            is_json = isinstance(parsed, dict)
        except ValueError:
            is_json = False
        result = PingResult(
            True,
            is_json,
            f"{time.perf_counter() - start:.2f}s  model={settings.llm.model}  finish={c.finish_reason}  content={c.text[:120]!r}",
            reasoning_separated=c.reasoning_separated,
            think_in_content=c.think_stripped,
        )
    if settings.embed is None:
        return result
    embed = embed or EmbedClient(settings.embed, settings)
    start = time.perf_counter()
    try:
        (vec,) = embed.embed(["연결 확인 connection check"])
    except LLMError as e:
        result.embed_ok, result.embed_detail = False, f"error: {e}"
    else:
        result.embed_ok, result.embed_detail = True, f"{time.perf_counter() - start:.2f}s  model={settings.embed.model}  dim={len(vec)}"
    return result
