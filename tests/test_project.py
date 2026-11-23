"""--project: 산출물이 단계별 폴더에 놓이고, 다음 단계가 앞 단계의 파일을 알아서 찾는다."""

import json
from pathlib import Path

import pytest
from ragas_fake import fake_ragas_factory

from golden_set.cli import main
from golden_set.cli.project import ProjectPaths
from golden_set.domain.candidate import GoldenCandidate, Source, make_id
from golden_set.domain.store import read_candidates, read_chunks, write_candidates


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    for name in ("a", "b"):
        (root / f"{name}.txt").write_text(" ".join(f"{name} 문서의 {n}번째 문장은 강호의 규율을 길게 이야기한다." for n in range(60)), encoding="utf-8")
    return root


def test_project_paths_layout(tmp_path: Path) -> None:
    p = ProjectPaths(tmp_path / "형법")
    rel = [str(x.relative_to(p.root)) for x in (p.validate_csv, p.chunks, p.candidates("ragas"), p.generate_log("ragas"), p.check_csv, p.reviewed, p.export_file("awx1"))]
    assert rel == [
        "1-validate/validate.csv",
        "2-prepare/chunks.jsonl",
        "3-generate/ragas.candidates.jsonl",
        "3-generate/ragas.log",
        "4-check/check.csv",
        "4-check/reviewed.candidates.jsonl",
        "5-export/golden.awx1.json",
    ]
    assert p.generated() == []


def test_whole_flow_with_project(tmp_path: Path, docs: Path, capsys, monkeypatch) -> None:
    import golden_set.generation as generation

    monkeypatch.setenv("GOLDEN_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("GOLDEN_LLM_MODEL", "qwen-test")
    monkeypatch.setenv("GOLDEN_EMBED_BASE_URL", "http://emb.test/v1")
    monkeypatch.setenv("GOLDEN_EMBED_MODEL", "bge-test")
    monkeypatch.setattr(generation, "get_generator", fake_ragas_factory())
    project = tmp_path / "out" / "강호"
    p = ProjectPaths(project)
    flag = ["--project", str(project)]

    assert main(["validate", str(docs), *flag]) == 0 and p.validate_csv.is_file()
    assert main(["prepare", str(docs), *flag, "--chunk-size", "300", "--overlap", "0"]) == 0
    chunks = read_chunks(str(p.chunks))
    assert len(chunks) > 4

    assert main(["generate", *flag, "--generator", "ragas", "--size", "6", "--no-adapt-prompts"]) == 0
    assert len(read_candidates(str(p.candidates("ragas")))) == 6
    assert "[6/6]" in p.generate_log("ragas").read_text(encoding="utf-8")  # 로그 파일도 같이 생긴다

    # 다른 생성기의 결과가 나중에 추가된다. 서로 덮어쓰지 않는다
    first = chunks[0]
    extra = GoldenCandidate(make_id("deepeval", 1), "첫 문장은 무엇을 이야기하는가?", "강호의 규율이다.", [first.text], [Source(first.chunk_id, first.source, first.page)], "t", "ko", "deepeval", "m")
    write_candidates([extra], str(p.candidates("deepeval")))
    assert [x.name for x in p.generated()] == ["deepeval.candidates.jsonl", "ragas.candidates.jsonl"]
    capsys.readouterr()

    assert main(["check", *flag]) == 0  # 3-generate/의 후보를 모두 읽고 2-prepare/의 청크와 대조한다
    printed = capsys.readouterr().out
    assert "deepeval-0001" in printed and "ragas-0006" in printed and f"saved: {p.check_csv}" in printed
    assert "sources:" not in printed  # 출처가 모두 chunks.jsonl에 있다

    assert main(["export", *flag, "--format", "awx1"]) == 0  # 검수본이 없으면 전부 내보낸다
    assert len(json.loads(p.export_file("awx1").read_text(encoding="utf-8"))) == 7
    assert "from: " in capsys.readouterr().out

    write_candidates([extra], str(p.reviewed))  # 사람이 검수해서 하나만 남겼다
    assert main(["export", *flag, "--format", "awx1"]) == 0
    assert json.loads(p.export_file("awx1").read_text(encoding="utf-8")) == [{"id": 1, "query": extra.question, "expected_response": extra.reference_answer}]
    assert f"from: {p.reviewed}" in capsys.readouterr().out


def test_explicit_paths_win_over_project(tmp_path: Path, docs: Path) -> None:
    project, elsewhere = tmp_path / "proj", tmp_path / "elsewhere.jsonl"
    assert main(["prepare", str(docs), "--project", str(project), "--out", str(elsewhere), "--chunk-size", "300", "--overlap", "0"]) == 0
    assert elsewhere.is_file() and not ProjectPaths(project).chunks.exists()


def test_missing_inputs_are_errors(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("GOLDEN_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("GOLDEN_LLM_MODEL", "qwen-test")
    empty = ["--project", str(tmp_path / "empty")]
    assert main(["generate", "--generator", "deepeval"]) == 2  # 청크 경로도 프로젝트도 없다
    assert main(["generate", *empty, "--generator", "deepeval"]) == 2  # 2-prepare/chunks.jsonl이 없다
    assert main(["check"]) == 2
    assert main(["check", *empty]) == 2
    assert main(["export", "--format", "awx1"]) == 2
    assert main(["export", *empty, "--format", "awx1"]) == 2
    src = tmp_path / "c.jsonl"
    src.write_text("", encoding="utf-8")
    assert main(["export", str(src), "--format", "awx1"]) == 2  # 쓸 곳이 없다
    assert capsys.readouterr().err.count("error:") == 7
