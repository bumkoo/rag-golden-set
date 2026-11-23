"""DeepEval 생성기. deepeval 패키지는 이 패키지 안에서만 import한다.

확인한 버전: deepeval 4.3.4 (NOTES.md 참고). 파일을 도구가 직접 읽는 generate_goldens_from_docs는 쓰지 않는다.
이 패키지는 deepeval이 설치되어 있을 때만 import된다.
"""

import os

# 사용 통계(PostHog)와 .deepeval/ 폴더 생성, .env 자동 읽기를 끈다. deepeval import 전에 있어야 한다.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
