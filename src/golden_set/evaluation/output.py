"""후보별 검증 결과의 표 출력과 CSV 쓰기."""

import csv

from golden_set.evaluation.checks import CheckResult

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
