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

## 7. 검토 뒤에 고친 것

검토에서 나온 5건을 고쳤다. 건마다 실패하는 테스트를 먼저 쓰고 고친 뒤 따로 커밋했다. 새 기능은 넣지 않았다.

| 건 | 증상 | 고친 내용 |
|---|---|---|
| 1 | 출력 인코딩이 cp949일 때 본문에 cp949에 없는 글자(U+00A0 등)가 있으면 `--samples`에서 `UnicodeEncodeError` | `cli.main()` 첫머리의 `force_utf8_output()`이 stdout과 stderr를 utf-8, `errors="replace"`로 재설정한다. `reconfigure`가 없는 스트림은 건너뛴다 |
| 2 | RTF의 `\u-10179?\u-8704?`가 서로게이트 두 개로 따로 남아 utf-8 인코딩이 안 됨 | `rtf_to_text`가 끝에서 상위+하위 쌍을 한 글자로 합치고, 짝이 없는 서로게이트는 U+FFFD로 바꾼다 |
| 3 | BOM이 붙은 utf-8 txt의 본문 첫 글자로 U+FEFF가 남음 | txt 로더의 첫 시도 인코딩을 `utf-8-sig`로 바꿨다. BOM이 없으면 utf-8과 똑같이 읽는다 |
| 4 | UTF-16 txt(메모장의 "유니코드")가 `LoadError` | 파일이 `FF FE`나 `FE FF`로 시작하면 utf-16으로 읽는다. BOM이 없는 UTF-16은 추측하지 않는다 |
| 5 | RTF 각주가 구분 없이 본문에 붙음 | `footnote` 그룹의 내용은 남기고 앞뒤에 줄바꿈을 넣는다 |

**수정 때문에 달라진 동작과 선택**

- **(1) CLI 출력은 이제 항상 utf-8이다.** `PYTHONIOENCODING`이나 Windows의 기본 코드페이지를 따르지 않는다.
  Windows에서 `> result.txt`로 돌린 파일도 cp949가 아니라 utf-8로 저장된다 (BOM 없음). 지시가 utf-8 재설정이었고,
  cp949를 유지하면서 `errors="replace"`만 주면 죽지는 않아도 본문의 한자와 기호가 `?`로 바뀌어 눈으로 확인하는 용도에 맞지 않는다.
  `--out`의 CSV는 전과 같이 `utf-8-sig`다.
- **(2) 기존 테스트 하나의 기대값을 바꿨다.** `test_rtf_unicode_fallback_chars_are_skipped`의 마지막 줄은 음수 `\u` 값이
  16비트로 되돌려지는지 보려고 `\u-10179`(상위 서로게이트 하나)를 썼는데, 이 입력은 이제 U+FFFD가 된다.
  같은 목적을 서로게이트가 아닌 `\u-21504`(= U+AC00 "가")로 검사하도록 바꿨고, 짝 없는 서로게이트는 새 테스트가 맡는다.
- **(2) 쌍으로 인정하는 범위.** 출력에서 상위 서로게이트 바로 뒤에 하위 서로게이트가 붙어 있을 때만 합친다.
  둘 사이에 글자가 하나라도 있거나 순서가 뒤집히면 각각 U+FFFD가 된다.
- **(4) UTF-16 BOM이 있는데 utf-16으로 풀리지 않으면** (홀수 바이트 등) cp949로 넘어가지 않고 바로 `LoadError`다.
  `FF`는 cp949와 utf-8 어느 쪽에서도 첫 바이트가 될 수 없어서, 이 검사가 기존에 읽히던 파일을 바꾸지는 않는다.
- **(5) 각주가 건너뛰는 그룹(머리글, 바닥글 등) 안에 있으면** 내용도 줄바꿈도 내보내지 않는다.

**남은 문제 (고치지 않음)**

- UTF-32 LE의 BOM(`FF FE 00 00`)도 `FF FE`로 시작해서 utf-16으로 읽힌다. 오류는 나지 않고 글자 사이에 NUL이 끼어
  `broken_ratio` 불합격으로 드러난다. UTF-32 txt는 지시 범위 밖이라 그대로 두었다.

실제 문서 테스트(`tests/test_real_docs.py`)는 수정 뒤에도 19개 통과, 1개 건너뜀으로 전과 같다.

## 8. 골든 후보 생성 모듈 (개발계획서 2026-11-23, 0~5단계)

### 8.1 0단계와 1단계의 상태

- **0단계(기준 브랜치).** 원격에는 `claude/focused-curie-v3j91w`(커밋 `721bf3c`) 하나만 있고 그것이 원격 HEAD다. main/master는 없다.
  병합할 대상이 없어 병합은 하지 않았다. `721bf3c`에서 pytest 85개 통과(12개 건너뜀)를 확인한 뒤, 거기서 갈라진 작업 브랜치
  `claude/vibrant-lamport-egera2`에서 이후 단계를 진행했다.
- **1단계(새 문서 검증)는 하지 않았다.** `/data`가 없었다. 작업 중에도 올라오지 않았다. 머리글 제거와 청크 크기의 기본값은 픽스처로만 검증됐다.
  `/data`가 생기면 `python -m golden_set.cli validate /data --samples 2`와 `prepare /data --out /data-out/chunks.jsonl`을 돌리고
  불합격 파일의 원인을 로더·기준값·문서 문제로 나눠 적는 일이 남아 있다.
- 서버 호출(3~5단계의 실제 호출 부분)도 하지 못했다. 작업 환경에 `GOLDEN_LLM_*` 환경 변수가 없었다. 실제 호출 명령은 README.md "명령 순서"에 있다.

### 8.2 확인한 도구 버전

구현 전에 설치된 패키지의 소스를 읽고 실제 객체로 동작을 확인했다 (Python 3.13). `pyproject.toml`의 `generate` extra에 이 버전 이상으로 하한을 걸었다.

| 패키지 | 확인한 버전 | 쓴 것 | 비고 |
|---|---|---|---|
| ragas | 0.4.4 | `TestsetGenerator.generate`, `default_query_distribution`, `apply_transforms`, `BaseRagasLLM`, `BaseRagasEmbedding`, `RunConfig`, `SingleTurnSample`, `TestsetSample` | `generate_with_chunks`가 있지만 아래 이유로 노드 구성만 같은 방식으로 직접 했다 |
| deepeval | 4.3.4 | `Synthesizer.a_generate_goldens_from_contexts`, `DeepEvalBaseLLM`, `Golden`, `StylingConfig`, `FiltrationConfig`, `EvolutionConfig` | pytest 플러그인을 자동 등록한다. `-p no:deepeval`로 끈다 |
| openai | 1.109.1 | `OpenAI`, `AsyncOpenAI` (`base_url`, `extra_body`, `response_format`) | deepeval이 2.x를 막는다 |
| rapidfuzz | 3.14.6 | ragas `OverlapScoreBuilder`가 import | ragas 기본 의존성에 없어 `generate` extra에 넣었다 |
| instructor | 1.3.2 | 쓰지 않음 | ragas `llm_factory`가 쓰는데 너무 오래된 판이라 (아래) 피했다 |
| langchain-core | 1.8.4 | `Document`, `LLMResult`, `PromptValue` | 로더와 같음 |

### 8.3 Ragas: 확인한 것과 선택

- **LLM은 `BaseRagasLLM`을 직접 구현했다** (`ChatRagasLLM`). ragas가 권하는 `llm_factory(model, client=OpenAI(...))`는 instructor로 JSON을 받는데,
  설치된 instructor 1.3.2는 `llm_factory`가 참조하는 `Provider` 멤버가 없어 openai 외 provider에서 깨지고, 재시도·제한 시간이 우리 설정과
  따로 돈다. 직접 구현하면 `<think>` 분리, 요청·실패 집계, 동시 요청 수 제한이 `llm.py` 한곳에서 된다. 응답은 `LLMResult`로 돌려주고,
  `finish_reason == "length"`면 `is_finished`가 False를 돌려 ragas가 `LLMDidNotFinishException`을 낸다.
- **JSON 파싱은 ragas가 한다** (`RagasOutputParser` → `extract_json`은 첫 `{`/`[`부터 짝이 맞는 곳까지 자른다). 그래서 `<think>` 블록 안에 중괄호가 있으면
  파싱이 깨진다. `ChatClient`가 먼저 블록을 떼어 넘기므로 괜찮다 (테스트 `test_think_tags_are_stripped_before_ragas_parses`). 깨진 JSON은 ragas가
  `FixOutputFormat` 프롬프트로 최대 3회 고쳐 달라고 다시 묻고, 그래도 안 되면 `RagasOutputParserException`을 낸다 (테스트로 확인).
- **임베딩은 `BaseRagasEmbedding`(새 인터페이스)을 구현했다.** `EmbeddingExtractor`는 `is_async` 속성이 True면 `aembed_text`를 쓴다.
- **청크는 `NodeType.CHUNK` 노드로 넣는다.** `generate_with_chunks`가 하는 것과 같은 구성이다. 그 메서드를 직접 쓰지 않은 이유는 두 가지다.
  (1) 변환 단계의 실패를 잡을 자리가 없다. `apply_transforms`는 노드 하나의 추출이 실패하면 모든 작업이 끝난 뒤 첫 예외를 던진다.
  (2) `raise_exceptions=False`는 실패한 샘플을 `NaN`으로 바꿔 그다음 줄에서 터진다 (`TestsetSample(eval_sample=nan)`).
  그래서 변환마다 `GuardedTransform`, 합성기마다 `GuardedSynthesizer`로 감싸 실패를 리포트에 적고 계속 간다.
  변환 구성은 `default_transforms_for_prechunked`와 같다: 요약 → (요약 임베딩, 주제, 개체명) → (요약 유사도, 개체명 겹침). 뒷단계 변환은 앞단계
  속성이 있는 노드만 보도록 `filter_nodes`를 걸었다. 실패한 노드는 그 속성이 비어 자연히 빠진다.
  `CustomNodeFilter`는 뺐다: 미리 나눈 청크에는 부모 문서 요약이 없어 "Skipping filtering"만 하고 LLM도 부르지 않는다 (filters.py 64~78행).
- **질문 언어.** 두 가지를 적용했다. (1) `llm_context`: 질문 생성 프롬프트(`QueryCondition.llm_context`)에 들어가는 지시다. 근거 본문과 같은
  언어로 쓰라고 넣는다 (`LANGUAGE_INSTRUCTION`). (2) `adapt_prompts(language, llm)`: 합성기 프롬프트의 예시(few-shot)를 LLM으로 번역한다.
  `ko`일 때만 돌리고 `--no-adapt-prompts`로 끈다. 번역이 실패하면 영어 예시 그대로 두고 리포트에 적는다.
  확인된 한계: 요약·주제·개체명 추출과 페르소나 생성 프롬프트는 영어다. 페르소나가 영어로 나와도 질문은 llm_context 지시를 따를 것으로 보지만
  실제로 돌려 봐야 안다.
- **근거 본문 대조.** 단일홉은 노드의 `page_content` 그대로, 멀티홉은 `<1-hop>\n\n` 같은 표시가 앞에 붙는다. 표시를 떼고 청크 본문과 정확히,
  그다음 공백만 무시하고 대조한다. 못 찾으면 `sources`를 비워 두고 리포트에 적는다 (check의 `sources` 항목에 걸린다).
- **그 외.** `RunConfig(max_workers=동시 요청 수, timeout, max_retries=3)`를 변환과 생성 양쪽에 넘긴다. 안 넘기면 ragas Executor는 동시성 제한이 없다.
  합성기는 지식 그래프에 군집이 있는 것만 쓴다 (`default_query_distribution(llm, kg)`); 청크가 적으면 단일홉만 남을 수 있고 하나도 없으면
  `GenerateError`. 결과 수는 `testset_size`와 다를 수 있어 `size`로 자른다.

### 8.4 DeepEval: 확인한 것과 선택

- **`generate_goldens_from_contexts`만 쓴다.** `generate_goldens_from_docs`는 파일을 도구가 직접 읽으므로 쓰지 않는다. context는 같은 파일의
  이웃한 청크를 겹치지 않게 `--context-chunks`(기본 3)개씩 묶은 것이다. 파일을 돌아가며 고르고, context가 모자라면 context당 후보 수를
  올린다 (상한 5). 출처는 우리가 만든 context라 정확하다 (`Golden.context`는 넘긴 문자열 목록 그대로다).
- **한 context가 실패하면 전체가 중단된다.** 동기·비동기 모두 context 단위 try/except가 없다 (`asyncio.gather` 기본값). 그래서 context마다
  `a_generate_goldens_from_contexts([context])`를 따로 부르고 우리 쪽에서 실패를 잡는다. 진행 표시(rich `Progress`)는 호출마다 만들면 "동시 표시
  하나만" 오류가 나므로 하나를 만들어 `_progress`, `_pbar_id`로 넘긴다.
- **모델 클래스 (`ChatDeepEvalModel`).** deepeval은 사용자 모델을 먼저 `generate(prompt, schema=...)`로 부르고, `TypeError`가 나면 "schema를 못 받는
  모델"로 보고 `generate(prompt)` 뒤 자체 JSON 파싱으로 간다. 우리는 schema를 받아 pydantic 인스턴스를 돌려준다. 파싱 실패는 `LLMError`로
  내서 (TypeError가 아니어야 한다) 그 context만 실패한다. 응답 JSON은 첫 `{`부터 `json.JSONDecoder.raw_decode`로 꺼낸다 (앞뒤 설명 문장, ```json 울타리 허용).
- **자유 텍스트 스키마.** 진화(evolution)와 기대 정답 프롬프트는 "Rewritten Input:", "Generated Response:"처럼 자유 텍스트를 요구하면서도
  `Response(response: str)` 스키마로 들어온다. 이때 JSON 모드를 켜면 서버가 임의의 JSON을 강제해 검증이 깨진다. 문자열 필드 하나뿐인
  스키마는 JSON 모드를 끄고, JSON이 아니면 본문을 그 필드에 그대로 담는다 (`text_field`).
- **LLM 호출 수.** context마다 입력 생성 1회 + 입력마다 (품질 평가 1~3회 + 재작성 0~3회 + 진화 1회 + 형식 맞춤 1회 + 기대 정답 1회).
  기본값으로 후보 30개면 대략 150~250회다. `FiltrationConfig(critic_model=우리 모델)`을 꼭 넘긴다: 비우면 `initialize_model(None)`이
  OpenAI 기본 모델(`gpt-5.4`, `OPENAI_API_KEY`)을 만들려 한다. Synthesizer 생성자는 기본으로 `critic_model=self.model`을 넣지만 config를
  직접 만들 때는 아니다.
- **질문 언어.** 템플릿은 언어를 지정하지 않고 영어 예시만 있다. `StylingConfig.input_format`과 `expected_output_format`에 언어 지시를 넣었다.
  `input_format`을 주면 마지막에 형식 맞춤 재작성 호출이 한 번 더 돌아 진화 과정에서 영어로 샌 질문을 바로잡는다.
- **진화.** deepeval 기본값(`num_evolutions=1`, 7종 균등)을 그대로 쓴다. `question_type`에는 적용된 진화 이름을 `+`로 이어 적는다.
  `Multi-context` 진화는 질문을 15단어 이하로 줄이라고 한다.
- **동기 모드의 결함.** `async_mode=False`에서 모델이 `max_goldens_per_context`보다 많은 입력을 내면 `IndexError`가 난다 (비동기 경로는 자른다).
  우리는 비동기 경로만 쓴다.

### 8.5 Qwen3.6 연결에서 확인한 것과 못 한 것

서버가 없어 실제 응답은 보지 못했다. 그래서 다음을 코드로 준비하고 `ping`이 실제 응답에서 확인할 수 있게 했다.

- 모든 요청에 `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`를 보낸다 (vLLM, SGLang이 Qwen3 계열의 추론을 끄는 방식).
  `--keep-thinking`으로 끈다. 다른 서버가 이 인자를 거부하면 `--keep-thinking`을 쓴다.
- 서버가 추론을 `reasoning_content` 필드로 분리해 주면 그대로 두고 센다 (`reasoning_separated`). 본문에 `<think>...</think>`가 섞여 오면
  떼고 센다 (`think_stripped`). 떼고 나서 본문이 비면(추론만 왔거나 추론 중에 잘림) 실패로 센다.
- JSON을 기대하는 요청에는 `response_format={"type": "json_object"}`를 붙인다. 서버가 거부하면 `--no-json-mode`.
- `ping`은 LLM에 JSON 한 줄을 요구해 연결, JSON 응답 여부, `reasoning_content` 유무, 본문 `<think>` 유무, 임베딩 차원을 출력한다.
  서버에 닿지 않는 주소로는 `APIConnectionError`를 깔끔하게 보고하고 1로 끝나는 것을 확인했다.
- 못 확인한 것: Qwen3.6이 ragas·deepeval 프롬프트에 맞는 JSON을 얼마나 안정적으로 내는지, `max_tokens=4096`이 충분한지, 한국어 질문이 실제로
  나오는지. 실패율이 높으면 계획서 8장의 순서(추론 끄기 → 온도 낮추기 → 서버의 JSON 강제)를 `--keep-thinking`/`--temperature`/`--no-json-mode`로 시험한다.

### 8.6 문서 내용이 밖으로 나가는 경로 점검

| 경로 | 무엇이 나가나 | 처리 |
|---|---|---|
| ragas 사용 통계 (`ragas/_analytics.py`, `requests.post`를 `t.explodinggradients.com`에) | 이벤트 종류, ragas 버전, 익명 id, 모델 이름, 요청 수. 본문은 없음 | `ragas_gen.py`가 import 전에 `RAGAS_DO_NOT_TRACK=true`를 `setdefault`로 넣는다 |
| deepeval 사용 통계 (`deepeval/telemetry`, PostHog `us.i.posthog.com`) | 생성 방식, 후보 수, 진화 이름, 익명 id. 본문은 없음 | `deepeval_gen.py`가 import 전에 `DEEPEVAL_TELEMETRY_OPT_OUT=YES`. 꺼지면 `.deepeval/` 폴더와 `~/.deepeval/.deepeval_telemetry.txt`도 만들지 않는다 |
| deepeval `.env` 자동 읽기 | 현재 폴더의 `.env`를 환경 변수로 올린다 | `DEEPEVAL_DISABLE_DOTENV=1` |
| deepeval PyPI 버전 확인 | 켜져 있을 때만 | 기본 꺼짐 (`DEEPEVAL_UPDATE_WARNING_OPT_IN`이 있을 때만 돈다). 그대로 둔다 |
| deepeval pytest 플러그인 | pytest 시작 때 telemetry 모듈을 import하고 `.deepeval/`을 만든다 | `pyproject.toml`의 `addopts = "-p no:deepeval"` |
| 두 도구의 OpenAI 기본 모델 호출 | `llm`/`model`/`critic_model`을 비우면 `gpt-4o-mini`, `gpt-5.4`를 `OPENAI_API_KEY`로 부른다 | 항상 우리 어댑터를 넘긴다. 테스트가 `FiltrationConfig(critic_model=...)` 지정을 확인한다 |
| tiktoken 인코딩 내려받기 (ragas LLM 추출기가 토큰 수를 세는 데 쓴다) | 인코딩 파일 요청만 (`openaipublic.blob.core.windows.net`). 본문은 없음 | 끄지 않았다. 캐시가 없는 PC에서 첫 실행 때 한 번 받는다. 막힌 환경이면 `TIKTOKEN_CACHE_DIR`에 미리 받아 둔다 |
| unstructured 사용 통계 (로더, 기존) | - | 1장 참고. `DO_NOT_TRACK=1` |

문서 본문은 `GOLDEN_LLM_BASE_URL`과 `GOLDEN_EMBED_BASE_URL`로만 간다. openai 클라이언트는 이 두 주소로만 만든다.

### 8.7 계획과 달라진 점

| 항목 | 계획 | 구현 | 이유 |
|---|---|---|---|
| 0단계 병합 | 기본 브랜치에 병합 | 병합 없음 (8.1) | 병합할 대상이 없다 |
| `GoldenCandidate.language` | ko 또는 en | **질문**의 언어 (한글 비율 30% 기준) | 검수자가 읽을 질문 기준으로 나누는 것이 쓸모 있다. 근거 본문과의 불일치는 check가 잡는다 |
| `chunk_id` | 파일 경로 + 쪽 + 순번으로 만든 고정 값 | `파일이름:p쪽:순번:경로해시8자리`, 예 `a.pdf:p3:1:6e7263cd` | 사람이 읽을 수 있으면서 다른 폴더의 같은 이름 파일과 구분된다 |
| `check` 명령 | `check candidates.jsonl [--out]` | `--chunks chunks.jsonl` 추가. 생략하면 후보 파일 옆, 현재 폴더에서 찾고 없으면 2 | 출처 항목이 chunk_id를 chunks.jsonl과 대조해야 한다 |
| 머리글 제거 대상 | 쪽 단위 파일 | 쪽이 3개 이상인 파일만 (`CleanSettings.min_pages`) | 2쪽은 100%냐 50%냐 둘뿐이라 본문이 지워질 위험이 크다 |
| ragas 변환 | `TestsetGenerator`에 청크를 넘김 | 노드 구성은 같되 변환과 합성기를 감싸 실패를 건너뜀 (8.3) | ragas는 한 항목 실패가 전체를 멈춘다 |
| ragas `CustomNodeFilter` | (기본 변환에 포함) | 뺌 | 미리 나눈 청크에는 아무것도 하지 않는다 |
| deepeval 호출 | context 목록을 한 번에 | context마다 따로 호출 (8.4) | 한 context 실패가 전체를 멈춘다 |
| 동시 요청 수 | 도구 설정 | 도구 설정과 함께 `ChatClient`가 세마포어로 직접 제한 | 두 도구의 동시성 모델이 달라 한곳에서 보장한다 |
| `generate` 종료 코드 | 지정 없음 | 후보 0개면 1, 접속 정보·입력 파일 문제면 2 | validate와 같은 규칙 |
| `prepare` 종료 코드 | 지정 없음 | 읽기 실패 파일이 있으면 1(청크는 저장), 청크 0개나 폴더 없음은 2 | |
| 픽스처 | 그대로 | `with_header.pdf`(머리글·쪽 번호가 반복되는 5쪽) 추가, `make_pdf`의 글상자를 쪽 전체로 키움 | prepare의 머리글 제거 예시와 실제 호출 테스트에 쓸 문서가 필요했다 |
| 기존 cli 테스트 | 9개 파일, `pass=5` | 10개 파일, `pass=6`으로 기대값 수정 | 위 픽스처 추가 때문이다. 로더 테스트 85개는 그대로 통과한다 (reports/pytest.txt) |
| 테스트 파일 | 명시 없음 | `test_prepare.py`, `test_candidates.py`, `test_llm.py`, `test_generators.py`, `test_ragas_gen.py`, `test_deepeval_gen.py`, `test_check.py`, `test_real_calls.py` | 5장의 표 순서를 따랐다 |

### 8.8 모호한 요구사항과 선택한 해석

- **"쪽의 첫 줄이나 끝 줄"**: 첫(끝) 비어 있지 않은 줄 하나씩이다. 두 줄짜리 머리글은 윗줄만 지워진다. 한 쪽에 줄이 하나뿐이면 첫 줄로만 센다.
  "60% 이상"은 쪽 수 대비 등장 쪽 수이며 60%는 합격(지운다)이다. 비율은 `--header-ratio`.
- **"문단과 문장 경계에서 자른다"**: 빈 줄로 나뉜 문단이 size 이하면 문단째로, 넘으면 `.!?。！？` 뒤 공백이나 줄바꿈에서 나눈다.
  숫자 바로 뒤의 마침표("1. ", "Section 11.")는 번호로 보고 자르지 않는다. 문장 하나가 size를 넘으면 글자 수로 억지로 나눈다.
- **"겹침 150자"**: 다음 청크 앞에 앞 청크의 마지막 **단위(문장·문단)들**을 150자를 넘지 않는 만큼 다시 넣는다. 단위 하나가 150자보다 길면 겹침이 0이다.
  청크는 쪽(Document) 경계를 넘지 않는다. 쪽에 걸친 문장은 두 청크에 나뉜다.
- **"공백 제거 후 100자 미만인 청크는 버린다"**: 모든 공백 문자를 뺀 글자 수다. 그래서 짧은 픽스처(txt 96자)는 청크가 0개다.
- **"같은 파일의 이웃한 청크 1~3개"**: 파일 안 순서대로 N개씩 겹치지 않게 묶는다 (N은 `--context-chunks`, 기본 3). 마지막 묶음은 짧을 수 있다.
- **"후보 수"**: `--size N`은 상한이다. 두 도구 모두 정확히 N개를 내지 않으므로 N개로 자른다. deepeval은 N을 채우기 위해 필요한 context 수를
  계산하고, 모자라면 context당 후보 수를 올린다 (상한 5).
- **check "중복"**: 공백과 문장부호(유니코드 P 범주)를 빼고 소문자로 맞춘 질문이 같으면, **같은 생성기 안에서** 두 번째부터 불합격이다.
  두 생성기의 결과를 한 파일에 합쳐 비교하므로 생성기 사이의 같은 질문은 중복으로 보지 않는다.
- **check "출처"**: `sources`가 비어 있거나 chunk_id 하나라도 chunks.jsonl에 없으면 불합격이다.
- **check "언어 일치"**: 질문과 근거 본문(전체를 이어서) 각각의 글자(한글 음절 + 로마자) 중 한글 음절 비율이 30% 이상이면 ko, 아니면 en.
  영어 용어가 섞인 한국어 질문은 ko다. 기준은 `CheckThresholds.ko_hangul_ratio`.
- **check "추론 찌꺼기"**: `<think>`/`</think>`, 코드 울타리(```), `{"키":` 꼴의 JSON 조각, `"query":` 같은 도구 스키마 키. 질문과 정답 양쪽을 본다.
  문장 속 따옴표나 중괄호만으로는 걸리지 않는다.
- **check "지시어 질문"**: 문구 목록(`CheckThresholds.deictic_phrases`)을 소문자 질문에서 찾는다. 문구 앞은 글자가 아니어야 한다
  ("장문인이 문서에"의 "이 문서"는 아니다). "the passage of time"처럼 다른 뜻으로 쓰인 경우도 걸리는 한계가 있다. 검수자가 본다.
- **check 종료 코드**: 합격이 하나도 없으면 1, 그 외 0. 불합격이 섞여 있는 것은 정상이라 종료 코드에 넣지 않았다 (validate와 다르다).
- **`GenerateReport`의 "실패 사유"**: 두 층으로 적는다. LLM 요청 단위(연결 오류, 빈 응답, 잘림, JSON 파싱 실패)는 `CallLog`, 항목 단위(샘플·context·변환 실패)는 `skipped`다.
  ragas의 JSON 파싱 실패는 ragas 안에서 일어나 요청 단위로는 성공으로 보이고 항목 단위로만 잡힌다.

### 8.9 남은 문제

- **실제 서버로 한 번도 돌리지 않았다.** 8.5의 확인 항목과 README "명령 순서"를 서버에 닿는 PC에서 먼저 돌려야 한다. `reports/generate.txt`, `reports/check.txt`는 그때 만든다.
- **머리글 제거의 오탐.** 본문이 줄바꿈된 끝 줄이 쪽마다 우연히 같으면 지워진다 (픽스처 `three_pages.pdf`의 `text for extraction.`이 그 예다).
  지운 줄은 모두 출력되므로 사람이 확인하고 `--header-ratio`를 올리거나 쪽 수가 적은 파일은 건너뛸 수 있다. 두 줄짜리 머리글은 한 줄만 지워진다.
- **ragas 변환 단계의 실패는 품질 저하로 이어진다.** 요약 추출이 실패한 청크는 임베딩·유사도에서 빠지고, 개체명 추출이 실패한 청크는 단일홉 후보에서 빠진다.
  전부 실패하면 `GenerateError`. 리포트의 `transform ...` 줄 수로 알 수 있다.
- **ragas의 영어 프롬프트.** 요약·주제·개체명·페르소나는 영어 프롬프트로 만든다. 질문 언어는 `llm_context`와 `adapt_prompts`로 맞추지만, 개체명이 영어로 번역되어
  나오면 질문에 영어 용어가 섞일 수 있다. check의 언어 항목(한글 30%)은 이 정도는 ko로 본다.
- **deepeval 진화가 언어를 바꿀 수 있다.** 진화 프롬프트에는 언어 지시가 없다. 마지막 형식 맞춤 재작성이 되돌리지만 보장은 아니다. check가 잡는다.
- **tiktoken 인코딩 내려받기**는 끄지 않았다 (8.6).
- **`created_at`**은 후보를 만든 시각이 아니라 변환한 시각이다 (도구가 생성 시각을 주지 않는다). 한 번의 generate 안에서는 몇 초 차이다.
- **중복 검사는 글자 단위**다. 어순만 다른 같은 질문은 잡지 못한다. 범위 밖(LLM 없이 계산만)이라 그대로 두었다.

### 8.10 검토 때 볼 항목 자가 점검

| 항목 | 결과 | 근거 |
|---|---|---|
| 두 생성기가 `Generator` 프로토콜을 지키고 같은 `GoldenCandidate`를 내는가 | 예 | `test_generators_satisfy_protocol`, `test_generate_skips_failed_context_and_reports`(deepeval, `isinstance(gen, Generator)`). 두 변환 함수가 같은 `GoldenCandidate`를 만든다 |
| 후보마다 `sources`가 채워지고 실제 청크를 가리키는가 | 예 (ragas는 대조 실패 시 빈 값, check가 잡음) | `test_fields_are_transferred_and_sources_matched`, `test_fields_transferred_and_sources_exact`, check `sources` 항목 |
| DeepEval이 우리 로더와 전처리를 거친 청크를 쓰는가 | 예 | `generate_goldens_from_contexts`만 호출. 파일 경로는 `source_files` 표시용으로만 넘긴다 |
| LLM 응답이 깨져도 전체가 멈추지 않고 실패 수가 보고되는가 | 예 (항목 단위). 단, ragas 변환 단계 전부 실패나 deepeval 입력 생성 실패는 그 항목 전체가 빠진다 | `test_generate_continues_past_failed_samples_and_reports_them`, `test_guarded_transform_skips_failing_node_and_reports`, `test_generate_skips_failed_context_and_reports` |
| 연결 정보가 환경 변수에만 있고 저장소에 키나 주소가 없는가 | 예 | `settings_from_env`만 읽는다. 저장소의 주소는 테스트의 가짜 호스트(`llm.test`, `emb.test`)와 README의 자리표시만 |
| 문서 내용이 지정한 서버 밖으로 나가는 경로가 없는가 | 예 (8.6). tiktoken 인코딩 내려받기는 본문 없이 밖으로 나간다 | 8.6 표 |
| 기본 pytest가 LLM 서버 없이 전부 도는가 | 예: 210 통과, 15 건너뜀 (실제 문서 12, 실제 호출 3) | `reports/pytest.txt` |
| 4장의 검증 항목이 표와 일치하고 기준이 한곳에 있는가 | 예 | `CHECK_NAMES` 7개, `test_all_check_names_are_exercised_and_reason_prefixes_match`, `CheckThresholds` |

### 8.11 납품물

| 납품물 | 상태 |
|---|---|
| 소스 코드와 테스트, 갱신한 README.md, .gitignore, pyproject.toml | 있음 |
| reports/pytest.txt | 있음 (210 통과, 15 건너뜀) |
| reports/prepare.txt | 있음 (픽스처 폴더) |
| reports/generate.txt, reports/check.txt | **없음**. 서버에 닿지 않았다. README "명령 순서"로 만든다 |
| reports/validate_real.txt | **없음**. `/data`가 없었다 |
| NOTES.md 새 장 | 이 장 |
