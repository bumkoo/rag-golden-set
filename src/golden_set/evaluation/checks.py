"""후보 검증. LLM을 부르지 않고 계산만으로 후보마다 합격 여부를 낸다. 기준값은 전부 CheckThresholds에 둔다.

정답이 근거 본문과 실제로 맞는지는 여기서 알 수 없다. 그것은 다음 단계인 사람 검수에서 본다.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from golden_set.domain.candidate import GoldenCandidate
from golden_set.domain.language import KO_HANGUL_RATIO, detect_language

CHECK_NAMES = ("required", "sources", "question_length", "language", "duplicate", "residue", "deictic")


@dataclass(frozen=True)
class CheckThresholds:
    """합격 기준값. 출발점이며 한곳에만 둔다."""

    min_question_chars: int = 10  # 공백 제외
    max_question_chars: int = 300  # 공백 제외
    ko_hangul_ratio: float = KO_HANGUL_RATIO  # 언어 판별: 글자 중 한글 음절 비율
    # 추론 출력이나 형식 찌꺼기: <think> 태그, 코드 울타리, JSON 조각
    residue_patterns: tuple[str, ...] = (r"</?think>", r"```", r"\{\s*\"[^\"]+\"\s*:", r"\"(query|answer|input|response|question|data|rewritten_input)\"\s*:")
    # 지문 없이는 성립하지 않는 질문. 소문자로 바꾼 질문에서 찾는다
    deictic_phrases: tuple[str, ...] = (
        "위 글",
        "위 문서",
        "위 내용",
        "위 지문",
        "위 본문",
        "이 글",
        "이 문서",
        "이 지문",
        "이 본문",
        "본문에 따르면",
        "본문에서",
        "지문에서",
        "주어진 글",
        "주어진 문서",
        "제시된 글",
        "제시된 문서",
        "the passage",
        "the context",
        "this passage",
        "this context",
        "this document",
        "the document",
        "the text above",
        "the given text",
        "the provided text",
        "according to the text",
    )


@dataclass
class CheckResult:
    """후보 하나의 검증 결과."""

    id: str
    generator: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    question_chars: int = 0  # 공백 제외
    question_language: str = ""
    context_language: str = ""
    source_count: int = 0
    question_type: str = ""
    language: str = ""
    sources: list[str] = field(default_factory=list)  # 출처 파일 이름
    question: str = ""


def _visible(text: str) -> str:
    return "".join(text.split())


def duplicate_key(question: str) -> str:
    """공백과 문장부호를 무시하고 소문자로 맞춘 비교용 열쇠."""
    return "".join(c for c in question.lower() if not c.isspace() and not unicodedata.category(c).startswith("P"))


def check_one(c: GoldenCandidate, chunk_ids: set[str], th: CheckThresholds) -> CheckResult:
    """후보 하나를 중복 항목을 빼고 검사한다. 중복은 check_candidates가 묶음 전체를 보고 판단한다."""
    question = c.question or ""
    answer = c.reference_answer or ""
    contexts = [x for x in (c.reference_contexts or []) if x and x.strip()]
    r = CheckResult(
        id=c.id,
        generator=c.generator,
        passed=True,
        question_chars=len(_visible(question)),
        question_language=detect_language(question, th.ko_hangul_ratio) if question.strip() else "",
        context_language=detect_language(" ".join(contexts), th.ko_hangul_ratio) if contexts else "",
        source_count=len(c.sources),
        question_type=c.question_type,
        language=c.language,
        sources=sorted({Path(s.source).name for s in c.sources}),
        question=question,
    )
    reasons = r.reasons
    if not question.strip() or not answer.strip() or not contexts:
        reasons.append("required: " + ", ".join(n for n, ok in (("question", question.strip()), ("answer", answer.strip()), ("contexts", contexts)) if not ok) + " empty")
    if not c.sources:
        reasons.append("sources: empty")
    else:
        unknown = [s.chunk_id for s in c.sources if s.chunk_id not in chunk_ids]
        if unknown:
            reasons.append(f"sources: {len(unknown)} chunk_id not in chunks.jsonl")
    if question.strip() and not (th.min_question_chars <= r.question_chars <= th.max_question_chars):
        reasons.append(f"question_length: {r.question_chars} not in {th.min_question_chars}..{th.max_question_chars}")
    if r.question_language and r.context_language and r.question_language != r.context_language:
        reasons.append(f"language: question {r.question_language} != context {r.context_language}")
    for text, where in ((question, "question"), (answer, "answer")):
        hit = next((p for p in th.residue_patterns if re.search(p, text)), None)
        if hit:
            reasons.append(f"residue: {where} matches {hit!r}")
            break
    lowered = question.lower()
    # 문구 앞이 글자가 아니어야 한다: "장문인이 문서에"의 "이 문서"는 지시어가 아니다. 뒤에는 조사가 붙을 수 있어 보지 않는다
    phrase = next((p for p in th.deictic_phrases if re.search(r"(?<!\w)" + re.escape(p), lowered)), None)
    if phrase:
        reasons.append(f"deictic: {phrase!r}")
    r.passed = not reasons
    return r


def check_candidates(candidates: list[GoldenCandidate], chunk_ids: set[str], thresholds: CheckThresholds | None = None) -> list[CheckResult]:
    """후보 전체를 검사한다. 같은 생성기 안에서 같은 질문은 두 번째부터 중복이다."""
    th = thresholds or CheckThresholds()
    results = [check_one(c, chunk_ids, th) for c in candidates]
    seen: set[tuple[str, str]] = set()
    for c, r in zip(candidates, results):
        key = (c.generator, duplicate_key(c.question or ""))
        if key[1]:
            if key in seen:
                r.reasons.append("duplicate: same question seen earlier")
                r.passed = False
            seen.add(key)
    return results
