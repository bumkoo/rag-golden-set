"""ragas의 실제 프롬프트에 스키마가 맞는 답을 돌려주는 가짜 LLM. 서버 없이 RagasGenerator를 끝까지 돌릴 때 쓴다.

ragas 프롬프트는 출력 JSON 스키마와 입력 JSON을 본문에 싣는다. 스키마의 title로 어떤 요청인지 가린다.
"""

import json
import re

from conftest import choice, completion

PERSONA_NAMES = ["형사 전문 변호사", "법학과 학생", "사법경찰관"]
ENTITIES = ["청운 문파", "화산", "장문인", "신의", "백리"]

_SCHEMA = re.compile(r"JSON Schema:\s*\n(\{.*?\})\s*Do not use", re.S)
_INPUT = re.compile(r"Now perform the same with the following input\s*\ninput: (.*)\nOutput:", re.S)


def prompt_parts(prompt: str) -> tuple[dict, dict]:
    """(출력 스키마, 입력 JSON). 찾지 못하면 빈 dict."""
    schema = _SCHEMA.search(prompt)
    given = _INPUT.search(prompt)
    try:
        return json.loads(schema.group(1)) if schema else {}, json.loads(given.group(1)) if given else {}
    except ValueError:
        return {}, {}


class RagasResponder:
    """FakeOpenAI에 넣는 응답 함수. 요청을 종류별로 세어 둔다 (counts)."""

    def __init__(self, fail_summary_containing: str | None = None):
        self.counts: dict[str, int] = {}
        self.fail_summary_containing = fail_summary_containing
        self.personas = 0

    def __call__(self, kwargs) -> object:
        prompt = kwargs["messages"][0]["content"]
        schema, given = prompt_parts(prompt)
        title = schema.get("title", "?")
        fields = set(schema.get("properties", {}))
        self.counts[title] = self.counts.get(title, 0) + 1
        return completion(choice(json.dumps(self.answer(title, fields, given, prompt), ensure_ascii=False)))

    def answer(self, title: str, fields: set, given: dict, prompt: str) -> dict:
        if fields == {"text"}:  # 요약
            text = str(given.get("text", ""))
            if self.fail_summary_containing and self.fail_summary_containing in text:
                raise RuntimeError("summary failed on purpose")
            return {"text": "요약: " + text[:40]}
        if fields == {"output"}:  # 주제
            return {"output": ["규율", "신의", "문파"]}
        if fields == {"entities"}:  # 개체명. 청크마다 겹치는 것이 있어야 관계가 생긴다
            return {"entities": ENTITIES[:3]}
        if fields == {"name", "role_description"}:  # 질문자
            name = PERSONA_NAMES[self.personas % len(PERSONA_NAMES)]
            self.personas += 1
            return {"name": name, "role_description": f"{name}의 관점에서 문서를 읽는다."}
        if fields == {"mapping"}:  # 질문자 ↔ 주제
            personas = [p["name"] for p in given.get("personas", [])]
            themes = given.get("themes", [])
            flat = [t for item in themes for t in (item if isinstance(item, list) else [item])]
            return {"mapping": {p: flat for p in personas}}
        if fields == {"combinations"}:  # 멀티홉 주제 조합
            themes = [t for group in given.get("lists_of_concepts", []) for t in group]
            return {"combinations": [themes[:2] or ["규율", "신의"]]}
        if fields == {"query", "answer"}:  # 질문·정답
            return {"query": "강호의 규율은 무엇에서 나오는가?", "answer": "신의에서 나온다."}
        raise AssertionError(f"ragas_fake: unknown prompt {title} {sorted(fields)}\n{prompt[-600:]}")


def law_chunks(n: int, source: str = "docs/law.pdf") -> list:
    """서로 다른 본문을 가진 청크 n개 (chunks.jsonl에서 읽은 것과 같은 꼴)."""
    from golden_set.domain.chunk import Chunk

    return [
        Chunk(
            chunk_id=f"law.pdf:p{i}:0:abcd1234",
            text=f"제{i}조 강호의 규율은 무공이 아니라 신의에서 나온다. 청운 문파는 화산에 있고 장문인은 제자에게 그 뜻을 오래 가르쳤다. 비밀본문{i:03d}",
            source=source,
            page=i,
            file_type="pdf",
            loader="pymupdf",
            extra={"chunk_index": 0},
        )
        for i in range(1, n + 1)
    ]


def fake_ragas_factory(responder: RagasResponder | None = None, created: list | None = None):
    """get_generator 자리에 넣는 함수. 실제 RagasGenerator를 가짜 LLM·임베딩으로 만든다. 요청 집계는 리포트의 것을 쓴다."""
    from conftest import FakeOpenAI, fake_embed

    from golden_set.generation.llm import ChatClient, EmbedClient
    from golden_set.generation.ragas.generator import RagasGenerator

    def factory(name, settings, report=None, reporter=None, **options):
        fake = FakeOpenAI(responder or RagasResponder())
        chat = ChatClient(settings.llm, settings, log=report.llm, client=fake, aclient=fake.as_async)
        _, fake_vectors = fake_embed()
        embed = EmbedClient(settings.embed, settings, log=report.embed, client=fake_vectors, aclient=fake_vectors.as_async)
        generator = RagasGenerator(settings, report=report, chat=chat, embed=embed, reporter=reporter, **options)
        if created is not None:
            created.append(generator)
        return generator

    return factory
