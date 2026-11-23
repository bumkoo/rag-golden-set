"""LLM과 임베딩 클라이언트. OpenAI 호환 API로 접속한다.

두 생성기(Ragas, DeepEval)는 이 모듈의 ChatClient를 통해서만 LLM을 부른다. 그래서 추론(<think>) 분리,
요청·성공·실패 수 집계, 제한 시간이 한곳에서 처리된다.
"""

import re
import threading
from dataclasses import dataclass, field

from golden_set.generation.llm.settings import Endpoint, LLMSettings


class LLMError(Exception):
    """요청이 실패했거나 응답이 비었을 때. 원인 메시지를 담는다."""


# ---- 응답 정리 ----

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str) -> tuple[str, bool]:
    """본문에 섞인 추론 블록을 뗀다. (남은 본문, 뗐는지) 를 돌려준다.

    닫는 태그만 있으면(서버가 여는 태그를 잘라 보낸 경우) 그 앞까지 버린다.
    여는 태그만 있으면(추론 중에 잘린 경우) 그 뒤는 전부 추론이라 버린다.
    """
    if "<think>" not in text and "</think>" not in text:
        return text, False
    cleaned = _THINK_BLOCK.sub("", text)
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>", 1)[0]
    return cleaned.strip(), True


@dataclass
class Completion:
    """응답 하나. finish_reason이 "length"면 max_tokens에 잘린 것이다."""

    text: str
    finish_reason: str | None = None
    reasoning_separated: bool = False  # 서버가 reasoning_content 필드로 추론을 따로 보냈다
    think_stripped: bool = False  # 본문에 섞인 <think> 블록을 우리가 뗐다


@dataclass
class CallLog:
    """요청 집계. 생성이 끝나면 리포트에 찍는다."""

    requests: int = 0
    successes: int = 0
    failures: list[str] = field(default_factory=list)
    think_stripped: int = 0
    reasoning_separated: int = 0
    truncated: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def ok(self, completions: list[Completion]) -> None:
        with self._lock:
            self.requests += 1
            self.successes += 1
            self.think_stripped += sum(c.think_stripped for c in completions)
            self.reasoning_separated += sum(c.reasoning_separated for c in completions)
            self.truncated += sum(c.finish_reason == "length" for c in completions)

    def fail(self, reason: str) -> None:
        with self._lock:
            self.requests += 1
            self.failures.append(reason[:300])

    def summary(self) -> str:
        from collections import Counter

        reasons = Counter(r.split(":")[0] for r in self.failures)
        why = ", ".join(f"{k} x{v}" for k, v in reasons.most_common()) or "-"
        return (
            f"requests={self.requests}  ok={self.successes}  failed={len(self.failures)} ({why})  "
            f"think_stripped={self.think_stripped}  reasoning_separated={self.reasoning_separated}  truncated={self.truncated}"
        )


# ---- 클라이언트 ----


def _message_dicts(messages: list) -> list[dict]:
    """langchain 메시지 객체나 (role, content) 쌍, dict를 OpenAI 메시지 dict로 맞춘다."""
    out: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
        elif isinstance(m, tuple):
            out.append({"role": m[0], "content": m[1]})
        else:  # langchain_core BaseMessage
            role = {"human": "user", "ai": "assistant", "system": "system"}.get(getattr(m, "type", ""), "user")
            out.append({"role": role, "content": m.content if isinstance(m.content, str) else str(m.content)})
    return out


class _Limiter:
    """동시 요청 수 제한. 동기 호출은 스레드 세마포어, 비동기 호출은 이벤트 루프마다 asyncio 세마포어를 쓴다."""

    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self._sync = threading.BoundedSemaphore(self.limit)
        self._async: dict[int, object] = {}

    def sync(self):
        return self._sync

    def asyncio(self):
        import asyncio

        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._async:
            self._async = {loop_id: asyncio.Semaphore(self.limit)}  # 루프가 바뀌면 이전 것은 버린다
        return self._async[loop_id]


class ChatClient:
    """채팅 완성 요청. openai 패키지의 클라이언트를 감싼다. 테스트에서는 client 인자로 가짜를 넣는다.

    동시 요청 수(settings.concurrency)는 여기서도 제한한다. 도구 쪽 동시성 설정과 무관하게 서버에는 이 수 이상 동시에 가지 않는다.
    """

    def __init__(self, endpoint: Endpoint, settings: LLMSettings | None = None, log: CallLog | None = None, client=None, aclient=None):
        self.endpoint = endpoint
        self.settings = settings or LLMSettings(llm=endpoint)
        self.log = log if log is not None else CallLog()
        self._client = client
        self._aclient = aclient
        self._limiter = _Limiter(self.settings.concurrency)

    @property
    def model(self) -> str:
        return self.endpoint.model

    def _sync(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.endpoint.base_url, api_key=self.endpoint.api_key, timeout=self.settings.timeout, max_retries=1)
        return self._client

    def _async(self):
        if self._aclient is None:
            from openai import AsyncOpenAI

            self._aclient = AsyncOpenAI(base_url=self.endpoint.base_url, api_key=self.endpoint.api_key, timeout=self.settings.timeout, max_retries=1)
        return self._aclient

    def request_kwargs(self, messages: list, json: bool, temperature: float | None, n: int) -> dict:
        kwargs: dict = {
            "model": self.endpoint.model,
            "messages": _message_dicts(messages),
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if n != 1:
            kwargs["n"] = n
        if json and self.settings.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.settings.disable_thinking:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        if self.settings.reasoning_effort:
            kwargs["reasoning_effort"] = self.settings.reasoning_effort
        return kwargs

    def _parse(self, response) -> list[Completion]:
        completions: list[Completion] = []
        for choice in response.choices:
            message = choice.message
            extra = getattr(message, "model_extra", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning") or getattr(message, "reasoning_content", None)
            text, stripped = strip_think(message.content or "")
            if not text.strip():
                raise LLMError("empty content" + (" (only reasoning returned)" if reasoning or stripped else ""))
            completions.append(Completion(text, choice.finish_reason, bool(reasoning), stripped))
        if not completions:
            raise LLMError("no choices")
        return completions

    def complete(self, messages: list, json: bool = False, temperature: float | None = None, n: int = 1) -> list[Completion]:
        """요청 하나. 실패하면 LLMError를 내고 CallLog에 사유를 남긴다."""
        try:
            with self._limiter.sync():
                response = self._sync().chat.completions.create(**self.request_kwargs(messages, json, temperature, n))
            completions = self._parse(response)
        except LLMError as e:
            self.log.fail(str(e))
            raise
        except Exception as e:
            self.log.fail(f"{type(e).__name__}: {e}")
            raise LLMError(f"{type(e).__name__}: {e}") from e
        self.log.ok(completions)
        return completions

    async def acomplete(self, messages: list, json: bool = False, temperature: float | None = None, n: int = 1) -> list[Completion]:
        """complete의 비동기판."""
        try:
            async with self._limiter.asyncio():
                response = await self._async().chat.completions.create(**self.request_kwargs(messages, json, temperature, n))
            completions = self._parse(response)
        except LLMError as e:
            self.log.fail(str(e))
            raise
        except Exception as e:
            self.log.fail(f"{type(e).__name__}: {e}")
            raise LLMError(f"{type(e).__name__}: {e}") from e
        self.log.ok(completions)
        return completions


class EmbedClient:
    """임베딩 요청. ChatClient와 같은 방식으로 감싼다."""

    def __init__(self, endpoint: Endpoint, settings: LLMSettings | None = None, log: CallLog | None = None, client=None, aclient=None):
        self.endpoint = endpoint
        self.settings = settings or LLMSettings(llm=endpoint, embed=endpoint)
        self.log = log if log is not None else CallLog()
        self._client = client
        self._aclient = aclient

    @property
    def model(self) -> str:
        return self.endpoint.model

    def _sync(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.endpoint.base_url, api_key=self.endpoint.api_key, timeout=self.settings.timeout, max_retries=1)
        return self._client

    def _async(self):
        if self._aclient is None:
            from openai import AsyncOpenAI

            self._aclient = AsyncOpenAI(base_url=self.endpoint.base_url, api_key=self.endpoint.api_key, timeout=self.settings.timeout, max_retries=1)
        return self._aclient

    @staticmethod
    def _vectors(response, n: int) -> list[list[float]]:
        vectors = [list(d.embedding) for d in sorted(response.data, key=lambda d: d.index)]
        if len(vectors) != n or any(not v for v in vectors):
            raise LLMError(f"expected {n} embeddings, got {len(vectors)}")
        return vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self._vectors(self._sync().embeddings.create(model=self.endpoint.model, input=texts), len(texts))
        except LLMError as e:
            self.log.fail(str(e))
            raise
        except Exception as e:
            self.log.fail(f"{type(e).__name__}: {e}")
            raise LLMError(f"{type(e).__name__}: {e}") from e
        self.log.ok([])
        return vectors

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._async().embeddings.create(model=self.endpoint.model, input=texts)
            vectors = self._vectors(response, len(texts))
        except LLMError as e:
            self.log.fail(str(e))
            raise
        except Exception as e:
            self.log.fail(f"{type(e).__name__}: {e}")
            raise LLMError(f"{type(e).__name__}: {e}") from e
        self.log.ok([])
        return vectors
