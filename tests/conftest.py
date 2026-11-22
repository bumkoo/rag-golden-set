"""픽스처 파일은 테스트가 직접 만든다. 저장소에 바이너리 샘플을 넣지 않는다."""

from pathlib import Path

import pytest

KO_TEXT = "강호에 떠도는 소문은 언제나 사실보다 빠르다. 객잔의 등불 아래에서 두 사람은 말없이 차를 마셨다.\nThe rumor travels faster than the truth."


@pytest.fixture
def txt_utf8(tmp_path: Path) -> Path:
    p = tmp_path / "ko_utf8.txt"
    p.write_text(KO_TEXT, encoding="utf-8")
    return p


@pytest.fixture
def txt_cp949(tmp_path: Path) -> Path:
    p = tmp_path / "ko_cp949.txt"
    p.write_text(KO_TEXT, encoding="cp949")
    return p
