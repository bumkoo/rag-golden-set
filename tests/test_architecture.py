"""의존 규칙: 컨텍스트 경계와 외부 도구의 위치를 import 문으로 검사한다 (NOTES.md 9장).

src/golden_set/ 아래 모든 파일의 import 문을 ast로 읽는다. 함수 안에서 하는 import도 본다.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "golden_set"
ROOT_PACKAGE = "golden_set"

CONTEXTS = ("loading", "chunking", "generation", "evaluation")

# 패키지 → import해도 되는 golden_set 내부 패키지. 자기 자신은 언제나 된다.
INTERNAL_ALLOWED: dict[str, set[str]] = {
    "domain": set(),
    "loading": {"domain"},
    "chunking": {"domain"},
    "generation": {"domain"},
    "evaluation": {"domain"},
    "cli": {"domain", "loading", "chunking", "generation", "evaluation"},
    "": {"loading"},  # golden_set/__init__.py: load_path, load_dir 재수출
}

# 패키지 → import해도 되는 외부 패키지(최상위 이름). None은 제한 없음.
LOADER_LIBRARIES = {"pymupdf", "pdfplumber", "docx", "docx2txt", "pptx", "unstructured"}
EXTERNAL_ALLOWED: dict[str, set[str] | None] = {
    "domain": {"langchain_core"},  # 3단계(도메인에서 LangChain 떼기) 뒤에는 표준 라이브러리만
    "loading": {"langchain_core"} | LOADER_LIBRARIES,
    "chunking": {"langchain_core"},
    "generation": {"langchain_core", "openai", "ragas", "deepeval", "rich"},  # rich: deepeval이 진행을 적을 Progress 객체를 받는다
    "evaluation": set(),
    "cli": None,
    "": set(),
}

# 외부 도구 → 그 도구를 import해도 되는 유일한 위치(golden_set 아래 경로의 앞부분).
TOOL_HOME: dict[str, str] = {
    "openai": "generation/llm/",
    "ragas": "generation/ragas/",
    "deepeval": "generation/deepeval/",
    "rich": "generation/deepeval/",
}


def imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    """(줄 번호, 모듈 이름) 목록. 상대 import는 이름 앞에 점을 붙여 돌려준다."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, "." * node.level + (node.module or "")))
    return found


def violations_in(relative_path: str, source: str) -> list[str]:
    """파일 하나의 위반 목록. relative_path는 golden_set 아래 경로(예: "generation/ragas/guards.py")다."""
    relative_path = relative_path.replace("\\", "/")
    package = relative_path.split("/")[0] if "/" in relative_path else ""
    out: list[str] = []

    def bad(line: int, message: str) -> None:
        out.append(f"{relative_path}:{line}: {message}")

    if package not in INTERNAL_ALLOWED:
        return [f"{relative_path}:1: package {package!r} is not in the dependency table"]
    for line, module in imported_modules(ast.parse(source)):
        if module.startswith("."):
            bad(line, f"relative import {module!r} (write the full golden_set path so the rule can be checked)")
            continue
        top = module.split(".")[0]
        if top == ROOT_PACKAGE:
            parts = module.split(".")
            target = parts[1] if len(parts) > 1 else ""
            if target and target != package and target not in INTERNAL_ALLOWED[package]:
                bad(line, f"{package or ROOT_PACKAGE} must not import golden_set.{target}")
            continue
        if top in sys.stdlib_module_names:
            continue
        allowed = EXTERNAL_ALLOWED[package]
        if allowed is not None and top not in allowed:
            bad(line, f"{package or ROOT_PACKAGE} must not import external package {top!r}")
            continue
        home = TOOL_HOME.get(top)
        if home is not None and not relative_path.startswith(home):
            bad(line, f"{top!r} may be imported only under {home}")
    return out


def all_violations(root: Path = SRC) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        out.extend(violations_in(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
    return out


# ---- 실제 소스 ----


def test_source_follows_dependency_rules() -> None:
    found = all_violations()
    assert not found, "dependency rule violations:\n" + "\n".join(found)


def test_every_top_level_package_is_in_the_table() -> None:
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    assert packages == set(INTERNAL_ALLOWED) - {""}


# ---- 검사기가 위반을 실제로 잡는지 ----


def test_checker_catches_context_importing_another_context() -> None:
    for importer in CONTEXTS:
        for target in CONTEXTS:
            source = f"from golden_set.{target}.x import y\n"
            found = violations_in(f"{importer}/m.py", source)
            assert bool(found) == (importer != target), (importer, target, found)
    assert violations_in("evaluation/checks.py", "import os\n\nfrom golden_set.generation.matching import ChunkIndex\n") == [
        "evaluation/checks.py:3: evaluation must not import golden_set.generation"
    ]


def test_checker_catches_imports_inside_functions_and_relative_imports() -> None:
    source = "def f():\n    from golden_set.loading.registry import load_dir\n    return load_dir\n"
    assert violations_in("chunking/chunker.py", source) == ["chunking/chunker.py:2: chunking must not import golden_set.loading"]
    assert "relative import" in violations_in("chunking/chunker.py", "from ..loading import registry\n")[0]


def test_checker_catches_domain_importing_other_packages() -> None:
    assert violations_in("domain/chunk.py", "import hashlib\nfrom dataclasses import dataclass\n") == []
    assert violations_in("domain/store.py", "import openai\n") == ["domain/store.py:1: domain must not import external package 'openai'"]
    assert violations_in("domain/chunk.py", "from golden_set.chunking.chunker import chunk_text\n") == ["domain/chunk.py:1: domain must not import golden_set.chunking"]
    assert violations_in("evaluation/checks.py", "import rapidfuzz\n") == ["evaluation/checks.py:1: evaluation must not import external package 'rapidfuzz'"]


def test_checker_keeps_each_tool_in_its_own_package() -> None:
    assert violations_in("generation/ragas/transforms.py", "from ragas.testset.graph import Node\n") == []
    assert violations_in("generation/deepeval/adapters.py", "from deepeval.models import DeepEvalBaseLLM\n") == []
    assert violations_in("generation/llm/client.py", "def f():\n    from openai import OpenAI\n") == []
    assert violations_in("generation/generator.py", "import ragas\n") == ["generation/generator.py:1: 'ragas' may be imported only under generation/ragas/"]
    assert violations_in("generation/ragas/generator.py", "import deepeval\n") == ["generation/ragas/generator.py:1: 'deepeval' may be imported only under generation/deepeval/"]
    assert violations_in("generation/deepeval/generator.py", "from openai import OpenAI\n") == ["generation/deepeval/generator.py:1: 'openai' may be imported only under generation/llm/"]
    assert violations_in("loading/registry.py", "import ragas\n") == ["loading/registry.py:1: loading must not import external package 'ragas'"]
    assert violations_in("cli/commands/generate.py", "import ragas\n") == ["cli/commands/generate.py:1: 'ragas' may be imported only under generation/ragas/"]


def test_checker_reports_unknown_package() -> None:
    assert violations_in("reporting/x.py", "import os\n") == ["reporting/x.py:1: package 'reporting' is not in the dependency table"]


# ---- generate extra 없이 도는 명령 ----

BLOCK_HEAVY = """
import sys

class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"openai", "ragas", "deepeval"}:
            raise ImportError("blocked for the test: " + name)
        return None

sys.meta_path.insert(0, Block())
from golden_set.cli import main
sys.exit(main(sys.argv[1:]))
"""


def run_without_generate_extra(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GOLDEN_")}  # 접속 정보가 있으면 generate가 더 나아간다
    return subprocess.run([sys.executable, "-c", BLOCK_HEAVY, *args], capture_output=True, text=True, encoding="utf-8", env=env)


def test_validate_prepare_check_run_without_generate_extra(tmp_path: Path) -> None:
    """openai, ragas, deepeval을 import할 수 없는 환경에서도 로더·청킹·평가 명령은 돈다."""
    from golden_set.domain.candidate import GoldenCandidate, Source, make_id
    from golden_set.domain.store import read_chunks, write_candidates

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text(" ".join(f"{n}번째 문장은 길게 이어진다." for n in range(100)), encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"

    assert run_without_generate_extra("validate", str(docs)).returncode == 0
    prepared = run_without_generate_extra("prepare", str(docs), "--out", str(chunks), "--chunk-size", "300", "--overlap", "0")
    assert prepared.returncode == 0, prepared.stderr

    first = read_chunks(str(chunks))[0]
    candidate = GoldenCandidate(
        id=make_id("ragas", 1),
        question="첫 번째 문장은 어떻게 이어지는가?",
        reference_answer="길게 이어진다.",
        reference_contexts=[first.page_content],
        sources=[Source(chunk_id=first.metadata["chunk_id"], source=first.metadata["source"], page=None)],
        question_type="",
        language="ko",
        generator="ragas",
        model="m",
    )
    write_candidates([candidate], str(tmp_path / "candidates.jsonl"))
    checked = run_without_generate_extra("check", str(tmp_path / "candidates.jsonl"))
    assert checked.returncode == 0, checked.stderr
    assert "ragas-0001" in checked.stdout

    blocked = run_without_generate_extra("generate", str(chunks), "--generator", "ragas")
    assert blocked.returncode == 2  # 접속 정보가 없어 생성기를 만들기 전에 끝난다
