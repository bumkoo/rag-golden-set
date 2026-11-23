# golden_set

pdf, pptx, docx, txt 문서(와 내용이 RTF인 doc)를 같은 형태의 `list[Document]`로 읽고 추출 품질을 숫자로 검증한 뒤,
Ragas와 DeepEval로 질문-정답 **골든 후보**를 만들어 같은 형식의 JSONL로 저장하고 검증하는 패키지다.
후보는 사람이 검수하기 전 단계의 결과물이다.

```text
문서 폴더 ──validate──▶ 로더 품질 리포트
문서 폴더 ──prepare───▶ chunks.jsonl (머리글·바닥글 제거, 청킹)
chunks.jsonl ──generate --generator ragas|deepeval──▶ candidates.jsonl
candidates.jsonl ──check──▶ 후보별 합격 여부, 생성기별 비교 요약
```

## 구조

코드는 네 개의 컨텍스트와 공통 도메인 모델로 나뉜다. 컨텍스트끼리는 서로를 import하지 않고 `domain`의 타입과 두 JSONL 파일로만 주고받는다.

```text
src/golden_set/
├── domain/        공통 언어: Chunk, GoldenCandidate, 언어 판별, chunks.jsonl·candidates.jsonl 읽기·쓰기
├── loading/       ① 파일 → 문서        loaders/, registry.py, validation.py
├── chunking/      ② 문서 → 청크        cleaning.py, chunker.py
├── generation/    ③ 청크 → 골든 후보   generator.py, matching.py, progress.py, llm/, ragas/, deepeval/
├── evaluation/    ④ 후보 → 판정        checks.py, summary.py, output.py
└── cli/           명령행               main.py, llm_options.py, commands/
```

| 패키지 | import해도 되는 것 |
|---|---|
| `domain` | 표준 라이브러리만 |
| `loading` | `domain`, langchain_core, 각 로더 라이브러리 |
| `chunking` | `domain`, langchain_core (로더가 낸 `Document`를 받는다) |
| `generation` | `domain`, openai(`llm/` 안에서만), ragas(`ragas/` 안에서만), deepeval(`deepeval/` 안에서만) |
| `evaluation` | `domain` |
| `cli` | 전부 |

이 표는 `tests/test_architecture.py`가 지킨다. `src/golden_set/` 아래 모든 import 문을 읽어 위반한 줄을 파일과 줄 번호로 보고한다.
무거운 패키지(openai, ragas, deepeval)는 필요할 때만 import하므로 `validate`, `prepare`, `check`는 `generate` extra 없이 돈다.
옛 경로와 새 경로의 대응표는 [NOTES.md](NOTES.md) 9장에 있다.

## 설치

```bash
uv venv && uv pip install -e ".[dev,compare,generate]"
```

- `compare`: 비교용 대안 로더(python-docx, pdfplumber, unstructured). 기본 로더만 쓸 때는 빼도 된다.
- `generate`: 후보 생성기(openai, ragas, rapidfuzz, deepeval). 로더만 쓸 때는 빼도 된다.
- `dev`: pytest와 픽스처 생성 도구. `generate`를 포함한다 (생성기 변환 테스트가 실제 도구 객체를 쓴다).

데비안 계열의 시스템 pip로는 `compare`의 langdetect 빌드가 실패할 수 있다. 가상환경(`uv venv` 또는 `python -m venv .venv`)에서 설치한다.

## 사용: 로더

```python
from golden_set import load_path, load_dir

docs = load_path("문서.pdf")                 # 기본 로더(pymupdf)
docs = load_path("문서.pdf", "pdfplumber")   # 이름으로 로더 지정
docs, failures = load_dir("문서폴더")         # 하위 폴더까지, 실패는 Failure(path, reason)로 수집
```

```bash
python -m golden_set.cli validate <폴더> [--out report.csv] [--samples N]
python -m golden_set.cli compare <파일> [--samples N]
```

종료 코드: 불합격(`fail`)이나 읽기 실패(`error`)가 하나라도 있으면 1, 폴더나 파일이 없으면 2, 그 외 0.
지원하지 않는 확장자(`unsupported`)는 표에 보고만 하고 종료 코드에는 넣지 않는다.

## 사용: 골든 후보 생성

### 1. 접속 정보 (환경 변수로만)

| 변수 | 내용 |
|---|---|
| `GOLDEN_LLM_BASE_URL` | 생성용 LLM(Qwen3.6)의 OpenAI 호환 주소, 예: `http://서버:8000/v1` |
| `GOLDEN_LLM_MODEL` | 서버에 올린 모델 이름 |
| `GOLDEN_LLM_API_KEY` | 키. vLLM, SGLang처럼 검사하지 않는 서버면 생략 가능 |
| `GOLDEN_EMBED_BASE_URL` | 임베딩 서버의 OpenAI 호환 주소 (Ragas에 필요, DeepEval은 쓰지 않음) |
| `GOLDEN_EMBED_MODEL` | 임베딩 모델 이름 (한국어·영어를 함께 다루는 모델, 예: BGE-M3) |
| `GOLDEN_EMBED_API_KEY` | 키. 생략 가능 |

주소와 키는 코드, 문서, 커밋에 적지 않는다. 모델을 바꿔도 환경 변수만 바꾸면 된다.

### 2. 명령 순서

서버에 닿는 PC에서 아래 순서대로 실행한다. `<문서 폴더>`와 `<작업 폴더>`는 저장소 밖에 둔다 (실제 문서와 산출물은 저장소에 넣지 않는다).

```bash
python -m golden_set.cli ping
```

```bash
python -m golden_set.cli prepare <문서 폴더> --out <작업 폴더>/chunks.jsonl
```

```bash
python -m golden_set.cli generate <작업 폴더>/chunks.jsonl --generator ragas --size 30 --out <작업 폴더>/ragas.candidates.jsonl
```

```bash
python -m golden_set.cli generate <작업 폴더>/chunks.jsonl --generator deepeval --size 30 --out <작업 폴더>/deepeval.candidates.jsonl
```

```bash
cat <작업 폴더>/ragas.candidates.jsonl <작업 폴더>/deepeval.candidates.jsonl > <작업 폴더>/candidates.jsonl
```

```bash
python -m golden_set.cli check <작업 폴더>/candidates.jsonl --chunks <작업 폴더>/chunks.jsonl --out <작업 폴더>/check.csv
```

픽스처 문서로 먼저 확인하려면 `python tests/make_fixtures.py`로 `tests/fixtures/`를 만들고 `<문서 폴더>` 자리에 넣는다.
실제 서버 호출 테스트는 다음과 같이 돈다 (환경 변수가 없으면 건너뛴다):

```bash
pytest tests/test_real_calls.py -v -s
```

### 3. 명령별 설명

**`ping`** — LLM과 임베딩에 한 번씩 요청해 연결, JSON 응답 여부, 추론 분리 여부(`reasoning_content` 필드가 따로 오는지, 본문에 `<think>`가 섞이는지)를 출력한다. 둘 다 정상이면 0.

**`prepare <폴더> --out chunks.jsonl`** — 로더로 읽고, 쪽 단위 파일(pdf, pptx)에서 전체 쪽의 60% 이상에 반복되는 첫 줄·끝 줄을 지운 뒤(쪽 번호처럼 숫자만 다른 줄은 같은 줄로 본다), 1,200자/겹침 150자 기본값으로 문단·문장 경계에서 자른다. 공백을 뺀 글자가 100자 미만인 청크는 버린다. 지운 문구와 횟수, 파일별 청크 수를 출력한다.
옵션: `--chunk-size`, `--overlap`, `--min-chars`, `--header-ratio`. 읽기 실패한 파일이 있으면 1, 청크가 하나도 없으면 2.

**`generate chunks.jsonl --generator ragas|deepeval --size N --out candidates.jsonl`** — 생성기 하나를 돌린다 (`--size` 기본 30).
- `ragas`: 청크를 그대로 지식 그래프의 노드로 넣고 `TestsetGenerator`로 만든다. 임베딩 서버가 필요하다. 근거 본문을 chunks.jsonl과 대조해 출처를 채운다.
- `deepeval`: 같은 파일의 이웃한 청크 1~3개(`--context-chunks`, 기본 3)를 context 하나로 묶어 `generate_goldens_from_contexts`로 만든다. 출처는 정확히 채운다.
- `--language auto|ko|en`: 질문 언어. `auto`는 청크의 한글 비율로 정한다. 두 도구 모두 프롬프트에 언어 지시를 넣는다.
- LLM 옵션: `--concurrency`(기본 4), `--timeout`(120초), `--max-tokens`(4096), `--temperature`(0.2), `--keep-thinking`(추론 끄기 옵션을 보내지 않음), `--reasoning-effort LEVEL`(`reasoning_effort` 값을 보냄), `--no-json-mode`(`response_format=json_object`를 붙이지 않음).
- Ollama는 추론 끄기 옵션(`chat_template_kwargs.enable_thinking=false`)을 무시한다. `--reasoning-effort none`을 줘야 추론이 꺼진다 (qwen3.5:9b에서 요청 하나가 41.6초 → 2.2초).
- 도는 동안 지금 어느 단계인지와 진행을 보여 주고, 단계가 끝날 때마다 한 줄 요약을 찍는다 (아래 "출력 예시: generate").
- `--log-file <경로>`: 단계 요약과 마지막 리포트를 그 파일에도 쓴다. 진행 줄, 본문 내용, 서버 주소, 키는 쓰지 않는다.
- 끝에 요청 수, 성공 수, 실패 수와 사유, 건너뛴 항목을 출력한다. 응답을 파싱하지 못한 항목은 멈추지 않고 건너뛴다. 후보가 0개면 1, 접속 정보나 입력 파일이 없으면 2.

**`check candidates.jsonl [--chunks chunks.jsonl] [--out report.csv]`** — LLM 없이 후보마다 합격 여부를 낸다. 항목: 필수 필드, 출처(chunk_id가 chunks.jsonl에 있는지), 질문 길이(공백 제외 10~300자), 언어 일치, 중복, 추론 찌꺼기(`<think>`, 코드 울타리, JSON 조각), 지시어 질문("위 글", "the passage" 등). 기준값은 `evaluation.checks.CheckThresholds`에 모여 있다.
끝에 생성기별 요약(후보 수, 합격률, 불합격 사유별 건수, 질문 유형 분포, 언어 분포, 파일별 후보 수)을 나란히 낸다. 이 표가 두 도구를 같은 잣대로 비교하는 표다.
`--chunks`를 생략하면 후보 파일 옆, 그다음 현재 폴더의 `chunks.jsonl`을 쓴다. 합격이 하나도 없으면 1.

정답이 근거 본문과 실제로 맞는지는 `check`로 알 수 없다. 다음 단계인 사람 검수에서 본다.

### 4. 출력 형식

`chunks.jsonl`: 한 줄에 청크 하나. `{"chunk_id", "text", "metadata"}`. metadata는 로더 메타데이터(source, file_type, loader, page)에 `chunk_id`, `chunk_index`를 더한 것이다.

`candidates.jsonl`: 한 줄에 후보 하나. 두 생성기의 출력이 같은 꼴이다.

| 필드 | 내용 |
|---|---|
| `id` | 생성기 이름 + 일련번호, 예: `ragas-0001` |
| `question`, `reference_answer` | 질문, 기대 정답 |
| `reference_contexts` | 정답의 근거가 된 본문 조각 목록 |
| `sources` | 근거 청크의 출처 목록. 항목마다 `chunk_id`, `source`(파일 경로), `page` |
| `question_type` | 도구가 붙인 질문 유형. ragas는 합성기 이름, deepeval은 적용한 진화 이름. 없으면 빈 값 |
| `language` | 질문의 언어, `ko` 또는 `en` |
| `generator`, `model`, `created_at` | 생성기, LLM 이름, 생성 시각(UTC) |

## 테스트

```bash
pytest
```

LLM 서버 없이 전부 돈다 (실제 문서 테스트와 실제 호출 테스트는 환경 변수가 없으면 건너뛴다). 생성 단계는 실제 ragas·deepeval에 가짜 LLM(`tests/ragas_fake.py`)을 물려 끝까지 돌린다. 픽스처 파일은 테스트가 직접 만든다. 같은 파일을 디스크에 깔아 보려면 `python tests/make_fixtures.py`를 실행한다 (`tests/fixtures/`, git에는 넣지 않는다).

실제 문서로 로더를 검증하려면 문서 폴더를 환경 변수로 준다. 검사 항목은 [NOTES.md](NOTES.md) 6장에 있다.

```bash
GOLDEN_SET_REAL_DOCS=<문서 폴더> pytest tests/test_real_docs.py -v
```

## 출력 예시: generate

ragas는 여섯 단계, deepeval은 두 단계로 돈다. 단계가 끝날 때마다 한 줄 요약이 남고, 마지막 리포트는 그 아래에 이전과 같은 꼴로 찍힌다.

```text
[1/6] 요약                  40/40  0초  LLM 40회  실패 0
[2/6] 임베딩·주제·개체명    120/120  임베딩 40, 주제 40, 개체명 40  0초  LLM 80회  임베딩 40회  실패 0
[3/6] 관계                  유사도 780개, 개체명 겹침 780개, 선 없는 청크 0개
[4/6] 질문자                3명: 형사 전문 변호사, 법학과 학생, 사법경찰관  LLM 3회
[5/6] 시나리오              30개 (단일 10, 넓은 주제 10, 특정 대상 10)  0초  LLM 40회
[6/6] 질문·정답             30/30  0초  LLM 30회  실패 0  출처 못 찾음 0
generator=ragas  requested=30  produced=30  skipped=0
llm    requests=193  ok=193  failed=0 (-)  think_stripped=0  reasoning_separated=0  truncated=0
embed  requests=40  ok=40  failed=0 (-)  think_stripped=0  reasoning_separated=0  truncated=0
```

| 단계 | 요약에 나오는 것 |
|---|---|
| 요약 | 요약을 만든 청크 수/전체, 걸린 시간, LLM 요청 수, 실패한 청크 수 |
| 임베딩·주제·개체명 | 끝난 작업 수/전체, 작업 종류별 완료 수, 걸린 시간, LLM·임베딩 요청 수, 실패 수 |
| 관계 | 종류별 선의 수(요약 유사도, 개체명 겹침), 선이 하나도 없는 청크 수. 선이 너무 많으면 무관한 청크가 묶인다는 신호다 |
| 질문자 | 만든 수와 각 질문자의 이름 |
| 시나리오 | 합성기별 시나리오 수(단일, 넓은 주제, 특정 대상), 걸린 시간. 프롬프트 번역에 쓴 LLM 요청 수가 여기에 들어간다 |
| 질문·정답 | 만든 후보 수/시나리오 수, 걸린 시간, 실패 수, 근거 본문을 청크와 맞추지 못한 후보 수 |
| (deepeval) context 구성 | 만든 context 수와 고른 수, context당 후보 수, 파일별 분포 |
| (deepeval) 질문 생성 | 끝난 context 수/전체, 만든 후보 수, 걸린 시간, 실패한 context 수 |

- 단계별 LLM 요청 수를 더하면 마지막 리포트의 `requests`와 같다.
- 터미널에서는 진행 줄 하나를 제자리에서 다시 그린다. 출력을 파일로 돌리면 10%마다 한 줄씩만 찍는다.
- 위는 가짜 LLM으로 돌린 것이다 (`python tests/make_stage_report.py`). 진행 줄과 로그 파일까지 포함한 전체는 [reports/generate_stages.txt](reports/generate_stages.txt).

## 출력 예시: prepare

`python tests/make_fixtures.py && python -m golden_set.cli prepare tests/fixtures --out chunks.jsonl` (broken.pdf 때문에 종료 코드 1)

```text
skip  tests/fixtures/broken.pdf  (pymupdf: EmptyFileError: Cannot open empty file: filename='tests/fixtures/broken.pdf'.)
skip  tests/fixtures/old.doc  (unsupported)
skip  tests/fixtures/sheet.xlsx  (unsupported)

removed from tests/fixtures/three_pages.pdf (3 pages):
  [tail] x2  'text for extraction.'  (pattern 'text for extraction.')

removed from tests/fixtures/with_header.pdf (5 pages):
  [head] x5  '문파 연대기  국가법령정보센터'  (pattern '문파 연대기 국가법령정보센터')
  [tail] x5  '- 1 -'  (pattern '- # -')

chunks  source
     0  tests/fixtures/ko_cp949.txt
     0  tests/fixtures/ko_utf8.txt
     0  tests/fixtures/sub/two_slides.pptx
     0  tests/fixtures/sub/with_blank.pdf
     0  tests/fixtures/three_pages.pdf
     0  tests/fixtures/two_paragraphs.docx
     5  tests/fixtures/with_header.pdf

docs=17  chunks=5  chars min/avg/max=242/258/277  errors=1
saved: chunks.jsonl
```

`three_pages.pdf`의 `text for extraction.`은 본문이 줄바꿈된 끝 줄이 3쪽 중 2쪽에서 우연히 같아 지워진 것이다. 이렇게 지워진 줄은 모두 출력되므로 사람이 확인할 수 있다. 짧은 픽스처는 100자 미만이라 청크가 0개다. 전체 출력은 [reports/prepare.txt](reports/prepare.txt).

## 출력 예시: validate

`python -m golden_set.cli validate tests/fixtures` (종료 코드 1)

```text
loader       status       doc_count  empty_ratio  avg_chars  broken_ratio  hangul_ratio  meta_ok  elapsed_sec  path  (reasons)
pymupdf      error                                                                                             tests/fixtures/broken.pdf  (pymupdf: EmptyFileError: Cannot open empty file: filename='tests/fixtures/broken.pdf'.)
stdlib       pass         1          0.000        96.0       0.0000        0.526         True     0.000        tests/fixtures/ko_cp949.txt
stdlib       pass         1          0.000        96.0       0.0000        0.526         True     0.000        tests/fixtures/ko_utf8.txt
-            unsupported                                                                                       tests/fixtures/old.doc  (unsupported)
-            unsupported                                                                                       tests/fixtures/sheet.xlsx  (unsupported)
python-pptx  pass         2          0.000        93.5       0.0000        0.630         True     0.078        tests/fixtures/sub/two_slides.pptx
pymupdf      fail         4          0.500        33.8       0.0000        0.396         True     0.005        tests/fixtures/sub/with_blank.pdf  (empty_ratio 50.0% > 30.0%; avg_chars 33.8 < 50)
pymupdf      pass         3          0.000        67.7       0.0000        0.406         True     0.001        tests/fixtures/three_pages.pdf
docx2txt     pass         1          0.000        73.0       0.0000        0.373         True     0.002        tests/fixtures/two_paragraphs.docx
pymupdf      pass         5          0.000        282.4      0.0000        0.449         True     0.002        tests/fixtures/with_header.pdf

pass=6  fail=1  error=1  unsupported=2
```

`--samples`와 CSV까지 포함한 전체 출력은 [reports/validate.txt](reports/validate.txt), 로더 비교는 [reports/compare.txt](reports/compare.txt),
pytest 실행 결과 전문은 [reports/pytest.txt](reports/pytest.txt)에 있다. 계획과 달라진 점, 확인한 도구 버전, 남은 문제는 [NOTES.md](NOTES.md)를 본다.
