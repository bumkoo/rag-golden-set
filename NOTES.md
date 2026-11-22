# NOTES

개발계획서(2026-11-23)와 달라진 점, 도구 선택 근거, 모호한 요구사항의 해석, 남은 문제를 적는다.

## 1. 도구 확인 결과

구현 전에 설치된 패키지의 메타데이터와 실제 동작으로 확인했다 (Python 3.13).

| 형식 | 역할 | 패키지 (확인한 버전) | import / 진입점 | 지원 Python | 계획 대비 |
|---|---|---|---|---|---|
| txt | 기본 | 표준 라이브러리 | `bytes.decode` | - | 그대로 |
| docx | 기본 | docx2txt 0.9 | `docx2txt.process(path)` | 명시 없음 | 그대로 |
| docx | 대안 | python-docx 1.2.0 | `docx.Document(path).iter_inner_content()` | >=3.9 | 그대로 |
| pdf | 기본 | PyMuPDF 2.1 | `import pymupdf` | >=3.11 | 그대로 |
| pdf | 대안 | pdfplumber 0.11.11 | `pdfplumber.open(path)` | >=3.8 | 그대로 |
| pptx | 기본 | python-pptx 1.0.2 | `from pptx import Presentation` | >=3.8 | 그대로 |
| pptx | 대안 | unstructured 0.27.37 (`unstructured[pptx]`) | `unstructured.partition.pptx.partition_pptx` | >=3.11,<3.14 | 그대로, 아래 주의 |
| 공통 | Document | langchain-core 1.8.4 | `langchain_core.documents.Document` | >=3.11 | 그대로 |

도구는 하나도 바꾸지 않았다. 다만 다음을 정했다.

- **langchain의 로더 클래스(`langchain_community`의 `PyMuPDFLoader` 등)는 쓰지 않고 각 라이브러리를 직접 호출한다.**
  필요한 것은 `Document` 타입뿐이고, 직접 호출해야 빈 페이지 보존과 메타데이터 규약을 우리가 통제할 수 있다.
  의존성도 `langchain-core` 하나로 줄어든다.
- **PyMuPDF는 `import pymupdf`를 쓴다.** 예전 이름 `fitz`는 호환용으로만 남아 있다 (`pymupdf>=1.24.3`부터 새 이름).
- **unstructured는 Python 3.14 미만만 지원한다.** 그래서 `compare` extra에 `python_version < '3.14'` 조건을 붙였다.
  3.14에서는 pptx 대안 로더가 `error` 줄로 보고되고 나머지는 그대로 돈다.
- **unstructured는 import할 때 사용 통계(scarf)를 외부로 보낸다.** 문서 작업용 도구라 로더가 import 직전에
  `DO_NOT_TRACK=1`과 `UNSTRUCTURED_DISABLE_NOTICE=1`을 `setdefault`로 넣어 끈다. 이미 값이 있으면 건드리지 않는다.
- **PyMuPDF는 AGPL(또는 상용) 라이선스다.** 내부 검증 도구로 쓰는 데는 문제가 없지만, 이 코드를 배포물에 넣게 되면 확인이 필요하다.

의존성 배치: 기본 로더 4종과 `langchain-core`는 필수 의존성, 대안 로더 3종은 `compare` extra, pytest와 픽스처 생성용 python-docx는 `dev` extra다.
로더는 라이브러리를 `load()` 안에서 import하므로 대안 패키지가 없어도 패키지 자체는 import된다 (그 로더만 `LoadError`).

## 2. 계획과 달라진 점

| 항목 | 계획 | 구현 | 이유 |
|---|---|---|---|
| 패키지 위치 | `golden_set/` 폴더 아래 | 저장소 루트가 곧 프로젝트 루트 (`pyproject.toml`, `src/`, `tests/`) | 저장소 `rag-golden-set`이 이 패키지 하나만 담는다. 폴더를 한 겹 더 두면 설치와 실행 경로만 길어진다 |
| `validate_docs` 시그니처 | `(path, loader_name, docs)` | `(path, loader_name, docs, thresholds=None, elapsed_sec=None)` | 3장이 기준값을 "인자로 바꿀 수 있게" 하라고 했고, 4장의 `elapsed_sec`는 Document만으로는 계산할 수 없어 호출자가 재서 넘겨야 한다. 앞의 세 인자는 계획과 같다 |
| 예외 | `LoadError` | `LoadError`와 그 하위 `UnsupportedError` | "unsupported"와 읽기 실패를 문자열 비교 없이 구분하려고 추가했다. `LoadError`로 잡으면 둘 다 잡힌다 |
| registry 공개 함수 | `get_loader`, `load_path`, `load_dir` | 추가로 `loaders_for(path)`, `list_files(root)` | `compare`가 형식의 모든 로더를, `validate`가 파일별 시간을 재려고 파일 목록을 필요로 한다 |
| `tests/fixtures/` | 형식별 샘플 파일 | git에 넣지 않음. `python tests/make_fixtures.py`로 생성 | 5장의 "저장소에 바이너리 샘플을 넣지 않는다"를 따랐다. 테스트는 `tmp_path`에 직접 만든다 |
| 테스트 파일 | 3개 | `test_cli.py`, `conftest.py`, `make_fixtures.py` 추가 | 5장이 cli 테스트를 요구한다 |
| 납품물 위치 | 지정 없음 | `reports/pytest.txt`, `reports/validate.txt`, `reports/compare.txt` | |

## 3. 모호한 요구사항과 선택한 해석

**지표 계산 (validate.py)**

- `empty_ratio`의 "공백 제거 후": 양끝만이 아니라 **모든 공백 문자를 뺀** 글자 수가 20 미만이면 빈 문서다. pdf 추출 결과는 줄바꿈과 띄어쓰기가 많아서, 양끝만 자르면 글자 몇 개와 공백뿐인 페이지가 통과한다.
- `avg_chars`: 공백을 **포함한** `len(page_content)`의 평균이다. 표가 `empty_ratio`에만 "공백 제거 후"라고 적었기 때문이다.
- `broken_ratio`: 분모는 공백을 포함한 전체 글자 수다. 제어문자는 유니코드 범주 `Cc`이고, 제외하는 "개행"에 `\r`도 넣었다 (Windows 줄바꿈이 오류로 잡히지 않게). 폼피드(`\f`)는 제외하지 않았다.
- `hangul_ratio`: U+AC00~U+D7A3(완성형 음절) 수 ÷ **공백을 뺀** 글자 수다. 낱자모(ㄱ, ㅏ)는 음절이 아니므로 세지 않는다. 분모에서 공백을 뺀 것은 줄바꿈이 많은 pdf와 적은 txt의 값을 비교할 수 있게 하려는 것이다.
- 경계값: 표의 "이하"와 "이상"을 그대로 따라 30%, 0.5%, 50자는 **합격**이다.
- 문서가 0개면 비율 지표는 0으로 두고 `doc_count`만 실패 사유로 낸다.
- `meta_ok`: 필수 키가 있고 값이 비어 있지 않아야 한다. pdf와 pptx는 `page`가 1 이상의 정수여야 한다. 형식은 `path`의 확장자로 판단한다.
- "그 외 0%"는 txt와 docx다. 이 둘은 파일 전체가 문서 하나라서 사실상 "본문이 20자 미만이면 불합격"이 된다.

**CLI**

- 종료 코드: `fail`(기준 미달)이나 `error`(읽기 실패)가 있으면 1이다. **`unsupported`는 표에 보고만 하고 종료 코드에 넣지 않는다.** 1장이 구형식을 "지원 안 함으로 보고한다"고 했고, 폴더에 `.xlsx`가 하나 있다고 매번 1이 나오면 종료 코드를 쓸 수 없다. 폴더나 파일이 없으면 2다.
- `compare`의 종료 코드는 **기본 로더**의 결과만 본다. 대안 로더는 비교 대상일 뿐이고, 대안 패키지를 설치하지 않은 환경에서 항상 1이 되는 것을 피했다.
- `--samples N`: 파일마다 **앞에서 N개 문서**의 본문 앞 300자를 출력한다 ("300자를 N개"를 이렇게 읽었다). `compare`에서는 로더마다 N개다.
- CSV 열: `path, file_type, loader, status, doc_count, empty_ratio, avg_chars, broken_ratio, hangul_ratio, meta_ok, elapsed_sec, reasons`. `status`는 `pass / fail / error / unsupported`이고, 읽지 못한 파일은 지표 칸이 비어 있다. Excel에서 한글이 깨지지 않게 `utf-8-sig`로 쓴다.
- 화면 표는 `path`를 맨 뒤에 둔다. 한글 경로는 글자 폭 때문에 열 정렬이 깨지기 때문이다.

**로더**

- `load_dir`와 `validate`는 점으로 시작하는 파일과 폴더(`.DS_Store`, `.git`)를 건너뛴다. 그 외에는 확장자가 무엇이든 `unsupported`로 기록한다.
- 암호가 걸린 pdf는 `LoadError("password-protected pdf")`다.
- python-pptx 로더는 텍스트 상자뿐 아니라 그룹 안의 도형과 표도 읽는다. 표는 행마다 한 줄, 칸은 탭으로 나눈다.
- **unstructured 로더에서는 발표자 노트가 본문 앞에 온다.** unstructured가 노트를 슬라이드 본문보다 먼저 내보내고 본문과 구분할 표시를 주지 않는다. "노트는 본문 뒤"는 기본 로더(python-pptx)에서만 지킨다.
- unstructured는 텍스트가 없는 슬라이드에 요소를 내지 않는다. 슬라이드 사이의 `PageBreak` 수로 슬라이드 수를 세어 빈 슬라이드를 남긴다.
- docx2txt는 머리글과 바닥글도 읽고, python-docx 로더는 본문만 읽는다. 두 로더의 `avg_chars`가 다르면 이 차이일 수 있다.

## 4. 범위 밖이라 구현하지 않은 제안

- **스캔 pdf 전용 표시**: 지금은 `empty_ratio` 불합격으로만 드러난다. 페이지에 이미지는 있는데 글자가 없으면 `scanned`로 따로 표시하면 원인을 바로 알 수 있다. OCR은 하지 않는다.
- **`load_dir` 병렬 처리** (미결 사항): 실제 분량을 알기 전에는 넣지 않았다. 파일 단위라 `ProcessPoolExecutor`로 쉽게 바꿀 수 있다.
- **로더 옵션**: pdfplumber의 `layout=True`, PyMuPDF의 `sort=True`는 다단 문서의 순서에 영향을 준다. 실제 문서의 `--samples` 출력에서 순서 문제가 보이면 옵션을 다르게 준 로더를 하나 더 등록해 `compare`로 비교하면 된다.
- **`compare`의 `--out`**: 계획이 `validate`에만 지정해서 넣지 않았다.

## 5. 남은 문제

- **`elapsed_sec`에 첫 사용 때의 import 시간이 들어간다.** 로더가 라이브러리를 `load()` 안에서 import하기 때문에, 프로세스에서 그 로더를 처음 쓰는 파일은 느리게 찍힌다 (픽스처에서 unstructured 1.6초의 대부분, pymupdf 0.07초의 대부분). 파일이 많은 폴더에서는 평균에 묻히지만, 파일 하나로 `compare`를 돌린 속도 비교는 이 점을 감안해야 한다.
- **합격 기준값은 미확정이다** (미결 사항). 실제 문서로 `validate`를 한 번 돌린 뒤 `Thresholds`의 기본값을 고친다. 특히 pptx는 제목만 있는 슬라이드가 많으면 `empty_ratio` 30%와 `avg_chars` 50에 걸릴 수 있다.
- **픽스처 pdf는 PyMuPDF로 만든 단순한 문서다.** 두 pdf 로더의 결과가 거의 같게 나온다. 로더 간 실제 차이(표, 다단, 내장 글꼴)는 실제 문서에서만 드러난다.
- 표의 행과 열 뒤섞임, 다단의 문장 순서는 계획대로 숫자로 잡지 않는다. `--samples`로 사람이 본다.

## 6. 실제 문서 검증 뒤에 바뀐 것 (형법, 민법, 상법 파일)

**`.doc` 지원 범위를 바꿨다.** 계획 1장은 구형식 `.doc`를 "지원 안 함"으로 두었지만, 받은 `.doc` 파일(법제처 내려받기)은
확장자만 `.doc`이고 내용은 RTF였다. 이 자료를 파싱 검증과 골든셋에 쓰기로 해서 다음과 같이 했다.

- `loaders/doc.py`의 `RtfDocLoader`(name `rtf`)가 `.doc`와 `.rtf`를 맡는다. 파일 첫머리가 `{\rtf`일 때만 읽는다.
- 진짜 바이너리(OLE) `.doc`와 빈 파일은 전과 같이 `"unsupported"`로 보고한다. 변환은 여전히 하지 않는다.
- RTF 파서는 직접 썼다 (표준 라이브러리만 사용). `striprtf`는 이 파일들에 든 `\bin` 이진 그림 블록을 넘기지 못해 빈 문자열을 돌려준다.
  `\bin` 블록을 미리 떼어 주면 `striprtf`도 읽으므로, 실제 문서 테스트에서 두 구현의 결과를 대조하는 데 쓴다 (`dev` extra).
- 머리글과 바닥글 그룹은 본문이 아니라서 버린다. `file_type`은 `doc`이고 쪽 개념이 없어 파일 전체가 Document 하나다.

**실제 문서 테스트를 추가했다** (`tests/test_real_docs.py`, 도우미 `tests/lawtext.py`).
문서는 저장소에 넣지 않고 `GOLDEN_SET_REAL_DOCS=<폴더>`로 준다. 없으면 건너뛴다. 결과는 `reports/real_docs.txt`.

| 형식 | 검사 | 무엇과 대조하나 |
|---|---|---|
| pdf | 쪽 수와 쪽 번호, 빈 쪽 없음 | PyMuPDF의 쪽 수 |
| pdf | 쪽마다 두 로더의 글자 구성이 같음 | pymupdf 대 pdfplumber |
| pdf | 머리글을 지운 본문 전체가 글자 순서까지 같음 | pymupdf 대 pdfplumber |
| pdf | 조문 번호가 제1조부터 끝까지 빠짐없음 | 법령의 구조 |
| pdf | 같은 법령의 doc과 본문이 글자 단위로 같음 | pdf 대 RTF (형식도 파서도 다름) |
| doc | 제어어, 중괄호, 그림 데이터가 본문에 없음 | - |
| doc | 독립 구현과 결과가 같음 | 우리 파서 대 striprtf |
| doc | 조문 번호가 빠짐없음 | 법령의 구조 |
| pptx | 슬라이드마다 글자 구성이 원본 XML과 같음 (로더 2종) | zip 안의 `<a:t>` |
| pptx | 텍스트 상자 하나의 글이 통째로 남아 있음 | python-pptx의 도형 |

조문 번호와 머리글 검사는 법제처 법령 형식에만 맞는다. 다른 종류의 문서를 넣으면 이 검사들은 실패하거나 의미가 없다.

**이 검증으로도 확인되지 않는 것**

- **pptx의 읽는 순서.** 글자는 하나도 빠지지 않았지만, 로더는 도형을 파일에 저장된 순서로 읽는다. 받은 pptx는 118장 중 114장에서
  저장 순서와 화면 위치 순서가 달랐다. 어느 쪽이 사람이 읽는 순서인지는 기계로 판정하지 못했다 (`--samples`로 확인).
- **pdf 머리글.** 쪽마다 "법제처 N 국가법령정보센터"와 법령 이름이 본문에 들어간다. 로더는 원문 그대로 두는 것이 맞으므로 지우지 않았다.
  골든셋을 만들기 전 단계에서 지워야 한다 (`tests/lawtext.py`의 `law_body` 참고).
- 받은 pptx는 2013년 개정까지 반영된 옛 판본이라 pdf(2026년 개정)와 내용이 다르다. 골든셋 원본으로 함께 쓰면 같은 조문에 답이 둘 생긴다.
