"""픽스처 폴더를 디스크에 만든다: python tests/make_fixtures.py [폴더=tests/fixtures]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import build_fixture_dir  # noqa: E402

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "fixtures"
    print(build_fixture_dir(target))
