"""Ragas 생성기. ragas 패키지는 이 패키지 안에서만 import한다.

확인한 버전: ragas 0.4.4 (NOTES.md 참고). 이 패키지는 ragas가 설치되어 있을 때만 import된다.
"""

import os

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")  # 사용 통계(t.explodinggradients.com) 전송을 끈다. ragas import 전에 있어야 한다
