"""프로젝트 폴더: 산출물을 작업 단계별 하위 폴더에 둔다.

    <프로젝트>/
    ├── 1-validate/   validate.csv
    ├── 2-prepare/    chunks.jsonl
    ├── 3-generate/   <생성기>.candidates.jsonl, <생성기>.log
    ├── 4-check/      check.csv, (사람이 만든) reviewed.candidates.jsonl
    └── 5-export/     golden.<형식>.json

명령에 --project를 주면 입력과 출력 경로가 이 구조로 정해진다. --out처럼 경로를 직접 준 옵션이 우선한다.
"""

from dataclasses import dataclass
from pathlib import Path

CANDIDATES_SUFFIX = ".candidates.jsonl"
REVIEWED_NAME = "reviewed" + CANDIDATES_SUFFIX


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def validate_csv(self) -> Path:
        return self.root / "1-validate" / "validate.csv"

    @property
    def chunks(self) -> Path:
        return self.root / "2-prepare" / "chunks.jsonl"

    @property
    def generate_dir(self) -> Path:
        return self.root / "3-generate"

    def candidates(self, generator: str) -> Path:
        return self.generate_dir / f"{generator}{CANDIDATES_SUFFIX}"

    def generate_log(self, generator: str) -> Path:
        return self.generate_dir / f"{generator}.log"

    @property
    def check_csv(self) -> Path:
        return self.root / "4-check" / "check.csv"

    @property
    def reviewed(self) -> Path:
        """사람이 검수해서 남긴 후보. 있으면 export가 이것을 내보낸다."""
        return self.root / "4-check" / REVIEWED_NAME

    def export_file(self, fmt: str) -> Path:
        return self.root / "5-export" / f"golden.{fmt}.json"

    def generated(self) -> list[Path]:
        """3-generate/에 있는 후보 파일들. 이름순이다."""
        return sorted(self.generate_dir.glob(f"*{CANDIDATES_SUFFIX}"))


def project_of(args) -> ProjectPaths | None:
    value = getattr(args, "project", None)
    return ProjectPaths(Path(value)) if value else None


def for_writing(path: Path) -> str:
    """쓸 파일의 폴더를 만들고 경로를 문자열로 돌려준다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def read_all_candidates(paths: list[Path]) -> list:
    """후보 파일 여러 개를 차례로 읽어 하나로 잇는다."""
    from golden_set.domain.store import read_candidates

    out: list = []
    for p in paths:
        out.extend(read_candidates(str(p)))
    return out
