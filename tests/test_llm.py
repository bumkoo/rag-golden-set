"""llm.py: 환경 변수 읽기, 추론 블록 제거, 요청 집계, ping. 서버 없이 가짜 클라이언트로 검사한다."""

import asyncio

import pytest
from conftest import FakeOpenAI, choice, completion, embedding_response, fake_chat, fake_embed

from golden_set.generation.llm import (
    EMBED_ENV,
    LLM_ENV,
    CallLog,
    ChatClient,
    ConfigError,
    EmbedClient,
    Endpoint,
    LLMError,
    LLMSettings,
    settings_from_env,
    strip_think,
)
from golden_set.generation.llm.ping import ping

ENV = {
    "GOLDEN_LLM_BASE_URL": "http://llm.test/v1",
    "GOLDEN_LLM_MODEL": "qwen",
    "GOLDEN_LLM_API_KEY": "k",
    "GOLDEN_EMBED_BASE_URL": "http://emb.test/v1",
    "GOLDEN_EMBED_MODEL": "bge",
}


# ---- 환경 변수 ----


def test_settings_from_env_reads_both_endpoints() -> None:
    s = settings_from_env(need_embed=True, env=ENV, concurrency=2)
    assert s.llm == Endpoint("http://llm.test/v1", "qwen", "k")
    assert s.embed == Endpoint("http://emb.test/v1", "bge", "EMPTY")  # 키가 없으면 자리채움 값
    assert (s.concurrency, s.timeout, s.disable_thinking, s.json_mode) == (2, 120.0, True, True)


def test_settings_missing_llm_is_config_error() -> None:
    with pytest.raises(ConfigError, match=LLM_ENV[0]):
        settings_from_env(env={})
    with pytest.raises(ConfigError, match="GOLDEN_LLM_MODEL"):
        settings_from_env(env={"GOLDEN_LLM_BASE_URL": "http://x"})


def test_settings_embed_optional_unless_needed() -> None:
    env = {k: v for k, v in ENV.items() if k.startswith("GOLDEN_LLM")}
    assert settings_from_env(env=env).embed is None
    with pytest.raises(ConfigError, match=EMBED_ENV[0]):
        settings_from_env(need_embed=True, env=env)


# ---- 추론 블록 ----


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', ('{"a": 1}', False)),
        ('<think>생각 중 {"x": [1]}</think>\n{"a": 1}', ('{"a": 1}', True)),
        ("앞<think>a</think>중간<think>b</think>뒤", ("앞중간뒤", True)),
        ('생각만 보임</think>\n{"a": 1}', ('{"a": 1}', True)),  # 여는 태그가 잘린 경우
        ('{"a": 1}<think>잘린 추론', ('{"a": 1}', True)),  # 닫히지 않은 경우
        ("<think>끝까지 추론만", ("", True)),
    ],
)
def test_strip_think(text: str, expected: tuple[str, bool]) -> None:
    assert strip_think(text) == expected


# ---- ChatClient ----


def test_request_kwargs_default_disable_thinking_and_json_mode() -> None:
    c, fake = fake_chat('{"ok": true}')
    (out,) = c.complete([("user", "hi")], json=True, temperature=0.0)
    assert out.text == '{"ok": true}' and out.finish_reason == "stop"
    kw = fake.calls[0]
    assert kw["model"] == "qwen-test" and kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert kw["temperature"] == 0.0 and kw["max_tokens"] == 4096 and "n" not in kw


def test_request_kwargs_options_off() -> None:
    c, fake = fake_chat("x", disable_thinking=False, json_mode=False, temperature=0.7, max_tokens=99)
    c.complete([{"role": "user", "content": "hi"}], json=True, n=2)
    kw = fake.calls[0]
    assert "extra_body" not in kw and "response_format" not in kw
    assert kw["temperature"] == 0.7 and kw["max_tokens"] == 99 and kw["n"] == 2


def test_reasoning_effort_is_sent_only_when_set() -> None:
    """Ollama는 chat_template_kwargs를 무시한다. reasoning_effort를 줘야 추론이 꺼진다."""
    c, fake = fake_chat("x", "y", reasoning_effort="none")
    c.complete([("user", "hi")])
    assert fake.calls[0]["reasoning_effort"] == "none"
    assert fake.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    default, fake2 = fake_chat("x")
    default.complete([("user", "hi")])
    assert "reasoning_effort" not in fake2.calls[0]


def test_langchain_messages_are_converted() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    c, fake = fake_chat("x")
    c.complete([SystemMessage(content="s"), HumanMessage(content="h")])
    assert fake.calls[0]["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "h"}]


def test_think_block_is_stripped_and_counted() -> None:
    ep = Endpoint("http://llm.test/v1", "qwen")
    fake = FakeOpenAI(completion(choice('<think>음</think>{"a": 1}'), choice('{"b": 2}', reasoning="따로 온 추론")))
    c = ChatClient(ep, client=fake)
    (a, b) = c.complete([("user", "hi")], n=2)
    assert (a.text, a.think_stripped, a.reasoning_separated) == ('{"a": 1}', True, False)
    assert (b.text, b.think_stripped, b.reasoning_separated) == ('{"b": 2}', False, True)
    assert (c.log.requests, c.log.successes, c.log.think_stripped, c.log.reasoning_separated) == (1, 1, 1, 1)


def test_empty_content_is_a_failure() -> None:
    ep = Endpoint("http://llm.test/v1", "qwen")
    c = ChatClient(ep, client=FakeOpenAI(completion(choice("<think>끝까지 추론만")), completion(choice(None))))
    with pytest.raises(LLMError, match="only reasoning"):
        c.complete([("user", "hi")])
    with pytest.raises(LLMError, match="empty content"):
        c.complete([("user", "hi")])
    assert c.log.requests == 2 and c.log.successes == 0 and len(c.log.failures) == 2


def test_transport_error_is_wrapped_and_logged() -> None:
    ep = Endpoint("http://llm.test/v1", "qwen")
    c = ChatClient(ep, client=FakeOpenAI(TimeoutError("read timed out"), completion(choice("ok", finish="length"))))
    with pytest.raises(LLMError, match="TimeoutError"):
        c.complete([("user", "hi")])
    (out,) = c.complete([("user", "hi")])
    assert out.finish_reason == "length" and c.log.truncated == 1
    assert "TimeoutError" in c.log.summary() and "failed=1" in c.log.summary()


def test_async_complete_uses_async_client() -> None:
    c, fake = fake_chat('{"a": 1}')
    (out,) = asyncio.run(c.acomplete([("user", "hi")], json=True))
    assert out.text == '{"a": 1}' and c.log.successes == 1 and fake.calls[0]["response_format"]


def test_call_log_can_be_shared() -> None:
    log = CallLog()
    c, _ = fake_chat("a")
    c.log = log
    c.complete([("user", "hi")])
    assert log.requests == 1


# ---- 임베딩 ----


def test_embed_orders_by_index_and_checks_count() -> None:
    fake = FakeOpenAI(embedding_response([1.0, 0.0], [0.0, 1.0]), embedding_response([1.0]))
    e = EmbedClient(Endpoint("http://emb.test/v1", "bge"), client=fake)
    assert e.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert fake.calls[0] == {"model": "bge", "input": ["a", "b"]}
    with pytest.raises(LLMError, match="expected 2 embeddings"):
        e.embed(["a", "b"])
    assert e.log.requests == 2 and len(e.log.failures) == 1
    e2, _ = fake_embed(dim=3)
    assert asyncio.run(e2.aembed(["x", "y"])) == [[1.0, 0.0, 0.0]] * 2


# ---- ping ----


def test_ping_reports_json_and_embedding() -> None:
    chat, _ = fake_chat('<think>x</think>{"ok": true, "lang": "ko"}')
    embed, _ = fake_embed(dim=8)
    settings = LLMSettings(llm=chat.endpoint, embed=embed.endpoint)
    r = ping(settings, chat, embed)
    assert r.ok and r.llm_json and r.think_in_content and not r.reasoning_separated
    assert r.embed_ok and "dim=8" in r.embed_detail


def test_ping_not_json_or_errors_is_not_ok() -> None:
    chat, _ = fake_chat("안녕하세요")
    r = ping(LLMSettings(llm=chat.endpoint), chat)
    assert r.llm_ok and not r.llm_json and not r.ok and r.embed_ok is None
    chat, _ = fake_chat(ConnectionError("refused"))
    r = ping(LLMSettings(llm=chat.endpoint), chat)
    assert not r.llm_ok and "ConnectionError" in r.llm_detail


def test_cli_ping_and_generate_without_env_exit_2(monkeypatch, tmp_path) -> None:
    from golden_set.cli import main

    for name in LLM_ENV + EMBED_ENV:
        monkeypatch.delenv(name, raising=False)
    assert main(["ping"]) == 2
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text("", encoding="utf-8")
    assert main(["generate", str(chunks), "--generator", "ragas"]) == 2
