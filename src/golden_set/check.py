"""후보 검증. LLM을 부르지 않고 계산만으로 후보마다 합격 여부를 낸다. 기준값은 전부 CheckThresholds에 둔다.

정답이 근거 본문과 실제로 맞는지는 여기서 알 수 없다. 그것은 다음 단계인 사람 검수에서 본다.
"""

import csv
import re
import unicodedata
from collections import Counter, defaultdict
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


# ---- 요약 ----


@dataclass
class GeneratorSummary:
    """생성기 하나의 요약. 두 생성기를 같은 잣대로 비교하는 표의 한 줄이다."""

    generator: str
    count: int
    passed: int
    reasons: Counter
    question_types: Counter
    languages: Counter
    files: Counter

    @property
    def pass_rate(self) -> float:
        return self.passed / self.count if self.count else 0.0


def summarize(results: list[CheckResult]) -> list[GeneratorSummary]:
    by_gen: dict[str, list[CheckResult]] = defaultdict(list)
    for r in results:
        by_gen[r.generator].append(r)
    out: list[GeneratorSummary] = []
    for gen, rs in sorted(by_gen.items()):
        reasons = Counter(reason.split(":")[0] for r in rs for reason in r.reasons)
        files = Counter(f for r in rs for f in (r.sources or ["(no source)"]))
        out.append(
            GeneratorSummary(
                generator=gen,
                count=len(rs),
                passed=sum(r.passed for r in rs),
                reasons=reasons,
                question_types=Counter(r.question_type or "(none)" for r in rs),
                languages=Counter(r.language or "(none)" for r in rs),
                files=files,
            )
        )
    return out


def format_summary(summaries: list[GeneratorSummary]) -> str:
    """생성기별 요약을 사람이 읽는 표로 만든다."""
    if not summaries:
        return "no candidates"
    lines = ["generator  candidates  passed  pass_rate"]
    for s in summaries:
        lines.append(f"{s.generator:<9}  {s.count:>10}  {s.passed:>6}  {s.pass_rate:>8.1%}")

    def block(title: str, pick) -> None:
        lines.append(f"\n{title}")
        keys = sorted({k for s in summaries for k in pick(s)})
        width = max([len(k) for k in keys] + [4])
        lines.append("  " + " " * width + "  " + "  ".join(f"{s.generator:>9}" for s in summaries))
        for k in keys:
            lines.append("  " + k.ljust(width) + "  " + "  ".join(f"{pick(s).get(k, 0):>9}" for s in summaries))

    block("fail reasons", lambda s: s.reasons)
    block("question types", lambda s: s.question_types)
    block("languages", lambda s: s.languages)
    block("candidates per file", lambda s: s.files)
    return "\n".join(lines)


# ---- 출력 ----

CSV_COLUMNS = ["id", "generator", "status", "question_chars", "question_language", "context_language", "source_count", "question_type", "language", "sources", "reasons", "question"]


def row_values(r: CheckResult) -> dict[str, str]:
    return {
        "id": r.id,
        "generator": r.generator,
        "status": "pass" if r.passed else "fail",
        "question_chars": str(r.question_chars),
        "question_language": r.question_language,
        "context_language": r.context_language,
        "source_count": str(r.source_count),
        "question_type": r.question_type,
        "language": r.language,
        "sources": ";".join(r.sources),
        "reasons": "; ".join(r.reasons),
        "question": r.question,
    }


def print_table(results: list[CheckResult]) -> None:
    columns = ["id", "generator", "status", "question_chars", "question_language", "context_language", "source_count"]
    table = [row_values(r) for r in results]
    widths = {c: max(len(c), *(len(v[c]) for v in table)) if table else len(c) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns) + "  (reasons)")
    for v in table:
        print("  ".join(v[c].ljust(widths[c]) for c in columns) + (f"  ({v['reasons']})" if v["reasons"] else ""))


def write_csv(results: list[CheckResult], out: str) -> None:
    """Excel에서 한글이 깨지지 않게 utf-8-sig로 쓴다."""
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(row_values(r) for r in results)
