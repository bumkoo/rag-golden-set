"""생성기별 요약. 두 생성기를 같은 잣대로 비교하는 표를 만든다."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from golden_set.evaluation.checks import CheckResult


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
