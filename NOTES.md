# NOTES

코드만 봐서는 알 수 없는 것을 적는다: 도구를 고른 근거, 모호한 요구사항을 어떻게 읽었는지, 확인한 한계, 남은 문제.
쓰는 방법은 [README.md](README.md)와 [docs/CLI_GUIDE.md](docs/CLI_GUIDE.md)에 있다. 작업 과정의 기록(단계별 커밋, 납품물 점검표)은 git 이력에 있다.

## 1. 도구와 버전

| 용도 | 패키지 (확인한 버전) | 쓰는 것 | 비고 |
|---|---|---|---|
| txt | 표준 라이브러리 | `bytes.decode` | |
| docx 기본 | docx2txt 0.9 | `docx2txt.process` | 머리글·바닥글도 읽는다 |
| docx 대안 | python-docx 1.2.0 | `Document(path).iter_inner_content()` | 본문만 읽는다 |
| pdf 기본 | PyMuPDF 2.1 | `import pymupdf` | AGPL 또는 상용 라이선스. 배포물에 넣게 되면 확인이 필요하다 |
| pdf 대안 | pdfplumber 0.11.11 | `pdfplumber.open` | |
| pptx 기본 | python-pptx 1.0.2 | `Presentation` | |
| pptx 대안 | unstructured 0.27.37 | `partition_pptx` | Python 3.14 미만만 지원 |
| doc (RTF) | 직접 쓴 파서 | `loading/loaders/doc.py` | 2장 |
| 문서 타입 | langchain-core 1.8.4 | `Document`, `LLMResult`, `PromptValue` | |
| 생성 | ragas 0.4.4 | `TestsetGenerator`, `apply_transforms`, `generate_personas_from_kg` 등 | `<0.5`로 묶었다 |
| 생성 | deepeval 4.3.4 | `Synthesizer.a_generate_goldens_from_contexts` 등 | `<4.4`로 묶었다 |
| LLM 호출 | openai | `OpenAI`, `AsyncOpenAI` | 하한 1.109. 3.3.0에서도 돈다 |
| ragas 의존 | rapidfuzz 3.14.6 | `OverlapScoreBuilder`가 import | ragas 기본 의존성에 없어 `generate` extra에 넣었다 |

- **langchain의 로더 클래스는 쓰지 않고 각 라이브러리를 직접 부른다.** 필요한 것은 `Document` 타입뿐이고, 직접 불러야 빈 쪽 보존과 메타데이터 규약을 통제할 수 있다.
- **ragas와 deepeval에 상한을 둔 이유**: 코드가 두 도구의 내부 구조(변환 실행 계획, 합성기 메서드, tqdm 막대를 만드는 자리, `_progress` 인자)에 기댄다.
- **의존성 배치**: 기본 로더와 langchain-core는 필수, 대안 로더는 `compare`, 생성 도구는 `generate`, pytest와 픽스처 도구는 `dev` extra다. 로더와 생성기는 라이브러리를 쓸 때 import하므로 extra가 없어도 나머지 명령은 돈다.
- **unstructured는 import할 때 사용 통계를 밖으로 보낸다.** 로더가 import 직전에 `DO_NOT_TRACK=1`, `UNSTRUCTURED_DISABLE_NOTICE=1`을 `setdefault`로 넣는다.

## 2. 로딩

### 지표 (`loading/validation.py`)

- `empty_ratio`: **모든 공백 문자를 뺀** 글자 수가 20 미만이면 빈 문서다. pdf는 줄바꿈과 띄어쓰기가 많아 양끝만 자르면 글자 몇 개뿐인 쪽이 통과한다.
- `avg_chars`: 공백을 포함한 길이의 평균이다.
- `broken_ratio`: U+FFFD와 제어문자(유니코드 범주 `Cc`)의 비율. `\n`, `\r`, 탭은 뺀다. 분모는 공백을 포함한 전체 글자 수다.
- `hangul_ratio`: 완성형 음절(U+AC00~U+D7A3) 수 ÷ 공백을 뺀 글자 수. 낱자모는 세지 않는다.
- 경계값 30%, 0.5%, 50자는 합격이다. 문서가 0개면 비율은 0으로 두고 `doc_count`만 사유로 낸다.
- `meta_ok`: 필수 키가 있고 값이 비어 있지 않아야 한다. pdf와 pptx는 `page`가 1 이상의 정수여야 한다.
- txt, docx, doc은 파일 전체가 문서 하나라서 사실상 "본문이 20자 미만이면 불합격"이다.
- **기준값은 출발점이다.** 문서 종류가 늘면 `Thresholds`를 고친다. 제목만 있는 슬라이드가 많은 pptx는 `empty_ratio` 30%와 `avg_chars` 50에 걸릴 수 있다.

### 명령의 동작

- `unsupported`는 표에 보고만 하고 종료 코드에 넣지 않는다. 폴더에 `.xlsx` 하나가 있다고 매번 1이 나오면 종료 코드를 쓸 수 없다.
- `compare`의 종료 코드는 기본 로더의 결과만 본다. 대안 패키지가 없는 환경에서 항상 1이 되는 것을 피했다.
- `--samples N`은 파일마다 앞에서 N개 문서의 본문 앞 300자다.
- 화면 표는 `path`를 맨 뒤에 둔다. 한글 경로는 글자 폭 때문에 열 정렬이 깨진다. CSV는 Excel에서 한글이 깨지지 않게 `utf-8-sig`다.
- **CLI 출력은 항상 utf-8이다.** Windows의 기본 코드페이지를 따르지 않는다. cp949에 없는 글자가 본문에 있어도 죽지 않게 하려는 것이다.
- `load_dir`와 `validate`는 점으로 시작하는 파일과 폴더를 건너뛴다.

### 로더

- 읽기 실패는 `LoadError`, 지원하지 않는 형식은 그 하위의 `UnsupportedError`다.
- 암호가 걸린 pdf는 `LoadError("password-protected pdf")`다.
- python-pptx 로더는 그룹 안의 도형과 표도 읽는다. 표는 행마다 한 줄, 칸은 탭으로 나눈다. 발표자 노트는 본문 뒤에 둔다.
- **unstructured 로더에서는 발표자 노트가 본문 앞에 온다.** unstructured가 그 순서로 내보내고 구분할 표시를 주지 않는다. 텍스트가 없는 슬라이드는 `PageBreak` 수로 세어 빈 슬라이드로 남긴다.
- txt는 utf-8(BOM 허용)과 cp949를 읽는다. UTF-16은 BOM이 있을 때만 읽고, BOM이 없으면 추측하지 않는다. UTF-32 LE는 utf-16으로 읽혀 글자 사이에 NUL이 끼고 `broken_ratio` 불합격으로 드러난다.

### `.doc`는 내용이 RTF일 때만 읽는다

법제처에서 내려받은 `.doc`는 확장자만 `.doc`이고 내용은 RTF였다. `RtfDocLoader`가 `.doc`와 `.rtf`를 맡고, 첫머리가 `{\rtf`일 때만 읽는다. 바이너리(OLE) `.doc`와 빈 파일은 `unsupported`다.

- RTF 파서는 표준 라이브러리만으로 직접 썼다. `striprtf`는 이 파일들의 `\bin` 이진 그림 블록을 넘기지 못해 빈 문자열을 돌려준다. `\bin`을 미리 떼어 주면 읽으므로 실제 문서 테스트에서 대조용으로 쓴다 (`dev` extra).
- 머리글과 바닥글 그룹은 버린다. 각주는 내용을 남기고 앞뒤에 줄바꿈을 넣는다.
- `\u` 서로게이트 쌍은 한 글자로 합치고, 짝이 없으면 U+FFFD로 바꾼다.
- 쪽 개념이 없어 파일 전체가 문서 하나다.

### 실제 문서 검증 (`tests/test_real_docs.py`)

문서는 저장소에 넣지 않고 `GOLDEN_SET_REAL_DOCS=<폴더>`로 준다. 형법, 민법, 상법 파일로 다음을 통과했다.

| 형식 | 검사 | 무엇과 대조하나 |
|---|---|---|
| pdf | 쪽 수와 쪽 번호, 빈 쪽 없음 | PyMuPDF의 쪽 수 |
| pdf | 쪽마다 글자 구성이 같고, 머리글을 지운 본문 전체가 글자 순서까지 같음 | pymupdf 대 pdfplumber |
| pdf | 같은 법령의 doc과 본문이 글자 단위로 같음 | pdf 대 RTF (형식도 파서도 다름) |
| pdf, doc | 조문 번호가 제1조부터 끝까지 빠짐없음 | 법령의 구조 |
| doc | 제어어, 중괄호, 그림 데이터가 본문에 없음. 독립 구현과 결과가 같음 | 우리 파서 대 striprtf |
| pptx | 슬라이드마다 글자 구성이 원본 XML과 같음. 텍스트 상자의 글이 통째로 남음 | zip 안의 `<a:t>`, python-pptx의 도형 |

조문 번호와 머리글 검사는 법제처 법령 형식에만 맞는다. 이 검증으로도 확인되지 않는 것:

- **pptx의 읽는 순서.** 로더는 도형을 파일에 저장된 순서로 읽는다. 받은 pptx는 118장 중 114장에서 저장 순서와 화면 위치 순서가 달랐다. 어느 쪽이 사람이 읽는 순서인지는 `--samples`로 본다.
- 표의 행과 열 뒤섞임, 다단의 문장 순서도 숫자로 잡지 않는다.
- 받은 형법 pptx는 2013년 개정까지의 옛 판본이라 pdf와 내용이 다르다. 골든셋 원본으로 함께 쓰면 같은 조문에 답이 둘 생긴다.

## 3. 청킹

- **머리글 제거**: 쪽의 첫(끝) 비어 있지 않은 줄 하나씩을 본다. 숫자만 다른 줄은 같은 줄로 본다. 전체 쪽의 60% 이상에서 반복되면 지운다 (`--header-ratio`). 쪽이 3개 미만인 파일은 건드리지 않는다. 2쪽은 100%냐 50%냐 둘뿐이라 본문이 지워질 위험이 크다.
- **오탐이 있다.** 본문의 끝 줄이 쪽마다 우연히 같으면 지워진다. 지운 줄은 모두 출력되므로 사람이 확인한다. 두 줄짜리 머리글은 윗줄만 지워진다.
- **첫 쪽에만 있는 줄은 남는다.** 형법 pdf 1쪽의 "법무부(형사법제과) 02-..." 줄이 청크에 남아, 조문과 전화번호를 한 질문에 묶은 후보가 나왔다.
- **자르기**: 빈 줄로 나뉜 문단이 크기 이하면 문단째로, 넘으면 `.!?。！？` 뒤 공백이나 줄바꿈에서 나눈다. 숫자 바로 뒤의 마침표("1. ")는 번호로 보고 자르지 않는다. 문장 하나가 크기를 넘으면 글자 수로 나눈다.
- **겹침 150자**: 앞 청크의 마지막 단위(문장·문단)들을 150자를 넘지 않는 만큼 다시 넣는다. 단위 하나가 150자보다 길면 겹침이 0이다.
- 청크는 쪽 경계를 넘지 않는다. 공백을 뺀 글자가 100자 미만인 청크는 버린다.
- **`chunk_id`**는 `파일이름:p쪽:순번:경로해시8자리`다 (예: `a.pdf:p3:1:6e7263cd`). 사람이 읽을 수 있고, 다른 폴더의 같은 이름 파일과 구분된다. 경로가 바뀌면 id도 바뀌므로 `check`에는 후보를 만들 때 쓴 chunks.jsonl을 줘야 한다.

## 4. 생성

### LLM 연결 (`generation/llm/`)

- 두 생성기는 `ChatClient`를 통해서만 LLM을 부른다. `<think>` 분리, 요청·실패 집계, 제한 시간, 동시 요청 수 제한(세마포어)이 한곳에서 된다. 두 도구의 동시성 모델이 달라 도구 설정만으로는 보장되지 않는다.
- 추론 끄기는 두 가지다. `chat_template_kwargs.enable_thinking=false`(vLLM, SGLang 방식, 기본으로 보냄)와 `--reasoning-effort none`(Ollama 방식, 옵션).
  **Ollama는 앞의 것을 무시한다.** qwen3.5:9b에서 같은 요약 요청이 41.6초(추론 7,000자)에서 2.2초로 줄었다.
- 서버가 추론을 `reasoning_content` 필드로 따로 주면 그대로 두고, 본문에 `<think>`가 섞여 오면 뗀다. 떼고 나서 본문이 비면 실패로 센다.
- JSON을 기대하는 요청에는 `response_format={"type": "json_object"}`를 붙인다. 서버가 거부하면 `--no-json-mode`.
- 실패 사유는 두 층이다. 요청 단위(연결 오류, 빈 응답, 잘림)는 `CallLog`, 항목 단위(샘플, context, 변환)는 `GenerateReport.skipped`다. ragas의 JSON 파싱 실패는 ragas 안에서 일어나 요청은 성공으로 보이고 항목 단위로만 잡힌다.

### Ragas (`generation/ragas/`)

- **LLM은 `BaseRagasLLM`을 직접 구현했다.** ragas가 권하는 `llm_factory`는 instructor로 JSON을 받는데, 재시도와 제한 시간이 우리 설정과 따로 돈다. `finish_reason == "length"`면 끝나지 않은 응답으로 본다.
- **JSON 파싱은 ragas가 한다.** 첫 `{`나 `[`부터 짝이 맞는 곳까지 자르므로 `<think>` 안에 중괄호가 있으면 깨진다. `ChatClient`가 먼저 떼어 넘긴다. 깨진 JSON은 ragas가 최대 3회 고쳐 달라고 다시 묻는다.
- **청크는 `NodeType.CHUNK` 노드로 넣는다.** `generate_with_chunks`와 같은 구성이지만 그 메서드는 쓰지 않는다. 변환에서 노드 하나가 실패하면 전체가 예외로 끝나고, `raise_exceptions=False`는 실패한 샘플을 `NaN`으로 바꿔 다음 줄에서 터지기 때문이다. 변환은 `GuardedTransform`, 합성기는 `GuardedSynthesizer`로 감싸 실패를 리포트에 적고 계속 간다.
- 변환 구성: 요약 → (요약 임베딩, 주제, 개체명) → (요약 유사도, 개체명 겹침). 뒷단계는 앞단계 속성이 있는 노드만 본다. `CustomNodeFilter`는 뺐다. 미리 나눈 청크에는 아무것도 하지 않는다.
- **요약 추출이 실패한 청크는 임베딩·유사도에서, 개체명 추출이 실패한 청크는 단일홉 후보에서 빠진다.** 전부 실패하면 `GenerateError`다.
- **질문 언어**: 질문 생성 프롬프트에 근거 본문과 같은 언어로 쓰라는 지시(`llm_context`)를 넣고, `ko`일 때 합성기 프롬프트의 예시를 LLM으로 번역한다 (`adapt_prompts`, `--no-adapt-prompts`로 끔). 요약·주제·개체명·질문자 프롬프트는 영어다. 실제 실행에서 질문자 이름은 영어로, 질문과 정답은 한국어로 나왔다.
- **근거 본문 대조**: 멀티홉은 `<1-hop>\n\n` 같은 표시가 앞에 붙는다. 표시를 떼고 청크 본문과 정확히, 그다음 공백만 무시하고 대조한다. 못 찾으면 `sources`를 비워 두고 `check`가 잡는다.
- 합성기는 지식 그래프에 군집이 있는 것만 쓴다. 청크가 적으면 단일홉만 남을 수 있다. 결과 수는 요청과 다를 수 있어 `--size`로 자른다.

### DeepEval (`generation/deepeval/`)

- **`generate_goldens_from_contexts`만 쓴다.** `generate_goldens_from_docs`는 파일을 도구가 직접 읽는다. context는 같은 파일의 이웃한 청크를 겹치지 않게 묶은 것이라 출처가 정확하다. context가 모자라면 context당 후보 수를 올린다 (상한 5).
- **context마다 따로 호출한다.** 한 번에 넘기면 context 하나의 실패가 전체를 멈춘다.
- **모델 클래스**: schema를 받아 pydantic 인스턴스를 돌려준다. 파싱 실패는 `LLMError`로 낸다. `TypeError`면 deepeval이 "schema를 못 받는 모델"로 보고 다른 경로로 간다.
- **자유 텍스트 스키마**: 진화와 기대 정답 프롬프트는 자유 텍스트를 요구하면서 `Response(response: str)` 스키마로 들어온다. 문자열 필드 하나뿐인 스키마는 JSON 모드를 끄고 본문을 그 필드에 담는다.
- **`FiltrationConfig(critic_model=우리 모델)`을 꼭 넘긴다.** 비우면 OpenAI 기본 모델을 만들려 한다.
- **호출 수**: 기본값으로 후보 30개면 대략 150~250회다.
- **질문 언어**: `StylingConfig`에 언어 지시를 넣었다. 진화 프롬프트에는 언어 지시가 없어 언어가 바뀔 수 있고, 마지막 형식 맞춤 재작성이 되돌리지만 보장은 아니다. `check`가 잡는다.
- 비동기 경로만 쓴다. 동기 모드는 모델이 요청보다 많은 입력을 내면 `IndexError`가 난다.
- deepeval의 실제 서버 실행은 아직 해 보지 않았다. 가짜 LLM 테스트로만 확인했다.

### 단계 로그 (`generation/progress.py`, `generation/ragas/stages.py`)

- **ragas의 단계를 나눈 방법**: 변환 세 개는 `apply_transforms`를 하나씩 부른다. 질문자는 `generate_personas_from_kg`로 먼저 만들어 `TestsetGenerator(persona_list=...)`에 넘긴다. 시나리오와 질문·정답은 `generate()` 한 번 안에서 도는데, 감싼 합성기가 첫 샘플이 시작될 때 시나리오 단계를 닫고 다음 단계를 연다. ragas는 시나리오를 전부 만든 뒤에 샘플을 만든다.
- **프롬프트 번역의 요청 수**는 시나리오 단계에 넣고 요약 줄에 따로 적는다. 그래서 단계별 합이 마지막 리포트의 `requests`와 맞는다.
- **ragas 자체 막대 끄기**: ragas 0.4.4는 모든 tqdm 막대를 `ragas.utils.tqdm`으로 만든다. 생성하는 동안만 그 이름을 `disable=True`를 붙이는 함수로 바꾼다. ragas가 구조를 바꾸면 막대가 다시 보일 뿐 동작은 같다.
- **deepeval의 rich 막대**: deepeval은 진행을 적을 `rich.progress.Progress` 객체를 인자로 받는다. 하나를 만들어 넘기지 않으면 호출마다 만들어 동시 표시 오류가 난다. `Progress(disable=True)`로 화면에는 그리지 않는다.
- 화면 출력은 stdout 한 곳으로 보내고 쓸 때마다 flush한다. 파일로 돌려도 순서가 맞는다.
- 요약 줄의 "실패 n"은 건너뛴 항목 수다. 재시도로 살아난 요청 실패는 "LLM 74회(요청 실패 1)"처럼 요청 수 옆에 적는다.
- 질문·정답 단계의 분모는 시나리오 수다. 합성기별로 올림해서 나누므로 요청보다 많을 수 있다.

### 실제 실행 기록

로컬 Ollama(qwen3.5:9b, bge-m3, RTX 2070 SUPER 8GB), 형법 pdf 1개, 청크 74개, 후보 30개. 약 15분 걸렸다.

```text
[1/6] 요약                  74/74  4분 18초  LLM 74회  실패 0
[2/6] 임베딩·주제·개체명    222/222  임베딩 74, 주제 74, 개체명 74  5분 48초  LLM 148회  임베딩 74회  실패 0
[3/6] 관계                  유사도 431개, 개체명 겹침 328개, 선 없는 청크 0개
[4/6] 질문자                3명: International Criminal Law Advisor, Korean Criminal Law Analyst, Criminal Defense Consultant  LLM 3회
[5/6] 시나리오              30개 (단일 10, 넓은 주제 10, 특정 대상 10)  2분 09초  LLM 48회(요청 실패 1)  (프롬프트 번역 LLM 8회 포함)
[6/6] 질문·정답             30/30  2분 14초  LLM 30회  실패 0  출처 못 찾음 0
generator=ragas  requested=30  produced=30  skipped=0
llm    requests=303  ok=302  failed=1 (APIConnectionError x1)  think_stripped=0  reasoning_separated=0  truncated=0
embed  requests=74  ok=74  failed=0 (-)  think_stripped=0  reasoning_separated=0  truncated=0
```

- 30개 모두 `check`에 합격했다. 정답의 정확성은 사람이 검수해야 한다.
- 청크 74개에 유사도 선 431개, 개체명 겹침 선 328개다. 청크 하나에 평균 20개쯤 이어져 있어 무관한 청크가 묶일 수 있다 (8장의 제안).

## 5. 문서 내용이 밖으로 나가는 경로

문서 본문은 `GOLDEN_LLM_BASE_URL`과 `GOLDEN_EMBED_BASE_URL`로만 간다. openai 클라이언트는 이 두 주소로만 만든다.

| 경로 | 무엇이 나가나 | 처리 |
|---|---|---|
| ragas 사용 통계 (`t.explodinggradients.com`) | 이벤트 종류, 버전, 익명 id, 모델 이름. 본문 없음 | `generation/ragas/__init__.py`가 import 전에 `RAGAS_DO_NOT_TRACK=true` |
| deepeval 사용 통계 (PostHog) | 생성 방식, 후보 수, 익명 id. 본문 없음 | `generation/deepeval/__init__.py`가 `DEEPEVAL_TELEMETRY_OPT_OUT=YES`. `.deepeval/` 폴더도 만들지 않는다 |
| deepeval `.env` 자동 읽기 | 현재 폴더의 `.env`를 환경 변수로 올린다 | `DEEPEVAL_DISABLE_DOTENV=1` |
| deepeval pytest 플러그인 | pytest 시작 때 telemetry 모듈을 import한다 | `pyproject.toml`의 `addopts = "-p no:deepeval"` |
| 두 도구의 OpenAI 기본 모델 | 모델 인자를 비우면 `OPENAI_API_KEY`로 OpenAI를 부른다 | 항상 우리 어댑터를 넘긴다 |
| tiktoken 인코딩 내려받기 | 인코딩 파일 요청만. 본문 없음 | **끄지 않았다.** 캐시가 없는 PC에서 첫 실행 때 한 번 받는다. 막힌 환경이면 `TIKTOKEN_CACHE_DIR`에 미리 받아 둔다 |
| unstructured 사용 통계 | - | 1장 |

`--log-file`에는 단계 요약과 마지막 리포트만 쓴다. 본문, 서버 주소, 키는 들어가지 않는다 (테스트가 확인한다).

## 6. 평가와 내보내기

### check (`evaluation/checks.py`)

- **중복**: 공백과 문장부호를 빼고 소문자로 맞춘 질문이 같으면 **같은 생성기 안에서** 두 번째부터 불합격이다. 두 생성기의 결과를 한 파일에 합쳐 비교하므로 생성기 사이의 같은 질문은 중복이 아니다. 어순만 다른 같은 질문은 잡지 못한다.
- **출처**: `sources`가 비어 있거나 chunk_id 하나라도 chunks.jsonl에 없으면 불합격이다.
- **언어 일치**: 질문과 근거 본문 각각에서 글자(한글 음절 + 로마자) 중 한글 음절이 30% 이상이면 ko다. 영어 용어가 섞인 한국어 질문은 ko다.
- **추론 찌꺼기**: `<think>`, 코드 울타리, `{"키":` 꼴의 JSON 조각, `"query":` 같은 도구 스키마 키. 질문과 정답 양쪽을 본다.
- **지시어 질문**: 문구 목록을 소문자 질문에서 찾는다. 문구 앞은 글자가 아니어야 한다 ("장문인이 문서에"의 "이 문서"는 아니다). "the passage of time"처럼 다른 뜻으로 쓰인 경우도 걸린다.
- **종료 코드**: 합격이 하나도 없으면 1이다. 불합격이 섞여 있는 것은 정상이라 넣지 않았다 (`validate`와 다르다).
- `GoldenCandidate.language`는 **질문**의 언어다. `created_at`은 도구가 만든 시각이 아니라 우리 형식으로 옮긴 시각이다.

### export (`exporting/`)

- awx1은 `{"id", "query", "expected_response"}` 세 키뿐이다. `id`는 1부터 매기는 정수라 우리 후보 id와 출처는 빠진다. 순서가 candidates.jsonl과 같아 n번째 항목이 n번째 후보다.
- 후보를 거르지 않는다. `check` 불합격을 자동으로 빼지 않는다. 사람이 고른 후보는 `4-check/reviewed.candidates.jsonl`에 두고, 있으면 `export --project`가 그것만 내보낸다. 검수본은 후보 파일을 복사해 줄을 지워서 만든다.
- 형식이 늘면 `exporting/`에 어댑터 모듈을 하나 더하고 `EXPORTERS`에 등록한다.

## 7. 구조

컨텍스트 경계와 의존 규칙은 README의 "구조"에 있고 `tests/test_architecture.py`가 지킨다.

- **`domain.Chunk`**: 청킹의 출력부터 저장, 생성, 평가까지 이 타입으로 주고받는다. LangChain의 `Document`는 로더 출력을 다루는 곳(`loading`, `chunking`의 입력, `cli validate`)과 `generation/ragas/`의 어댑터에만 남는다. `Chunk.metadata`가 chunks.jsonl의 metadata를 같은 키 순서로 돌려준다. 정수가 아닌 `page` 값은 `extra`에 그대로 둔다.
- **규칙의 예외**: rich는 `generation/deepeval/` 안에서만 쓴다 (4장). langchain_core는 `loading/`, `chunking/`, `generation/ragas/`, `cli/`에서만 쓴다. 상대 import는 금지다 (검사기가 전체 경로를 봐야 한다).
- **`cli/llm_options.py`**: LLM 옵션을 `ping`과 `generate`가 같이 쓴다. 한 명령 모듈에 두면 다른 명령이 그 모듈을 import하게 된다.
- **인자 정의는 `cli/main.py`에 한데 뒀다.** 명령 순서와 `--help` 출력을 한곳에서 본다. 명령 모듈에는 `cmd_<이름>`만 있다.
- **사용 통계를 끄는 환경 변수**는 `generation/ragas/__init__.py`, `generation/deepeval/__init__.py`에 있다. 도구 import 전에 실행되는 것을 보장할 자리가 패키지의 `__init__`뿐이다.
- **프로젝트 폴더 (`cli/project.py`)**: `--project`를 주면 산출물이 `1-validate/` ~ `5-export/`에 놓인다. 생성기별 폴더가 아니라 단계별 폴더로 나눈 것은 청크처럼 두 생성기가 같이 쓰는 파일의 자리가 분명해지기 때문이다. 폴더 구조는 명령행의 약속이라 `cli`에 뒀고, 컨텍스트들은 여전히 경로를 인자로 받는다. 같은 단계를 다시 돌리면 덮어쓴다. `check`와 `export`는 `3-generate/`의 `*.candidates.jsonl`을 전부 읽으므로 생성기 결과를 손으로 합치지 않는다.
- **`tests/examples/`**는 픽스처와 가짜 LLM으로 돌린 출력 예시다. 테스트가 읽지 않는다. `generate_stages.txt`는 `python tests/make_stage_report.py`로 다시 만든다.

구조를 바꾸기 전의 경로로 import하던 코드는 다음과 같이 고친다. 옛 경로를 이어 주는 모듈은 없다.

| 옛 경로 | 새 경로 |
|---|---|
| `candidates` | `domain.candidate`, 읽기·쓰기는 `domain.store` |
| `prepare.chunk` | `chunking.chunker`. `make_chunk_id`는 `domain.chunk`, 읽기·쓰기는 `domain.store` |
| `prepare.clean` | `chunking.cleaning` |
| `loaders`, `registry`, `validate` | `loading.loaders`, `loading.registry`, `loading.validation` |
| `generators.base` | `generation.generator`, `generation.matching`. `detect_language`는 `domain.language` |
| `generators.ragas_gen` | `generation.ragas.{adapters,guards,transforms,generator}` |
| `generators.deepeval_gen` | `generation.deepeval.{adapters,contexts,generator}` |
| `llm` | `generation.llm.{settings,client,ping}` |
| `check` | `evaluation.{checks,summary,output}` |
| `cli` | `cli.main`, `cli.commands.*` (`from golden_set.cli import main`은 그대로) |

## 8. 남은 문제와 구현하지 않은 제안

**남은 문제**

- `elapsed_sec`에 첫 사용 때의 import 시간이 들어간다. 파일 하나로 `compare`를 돌린 속도 비교는 이 점을 감안한다.
- 픽스처 pdf는 PyMuPDF로 만든 단순한 문서라 두 pdf 로더의 결과가 거의 같다. 로더 간 차이(표, 다단, 내장 글꼴)는 실제 문서에서만 드러난다.
- 머리글 제거의 오탐과 첫 쪽 발행 정보 줄 (3장).
- ragas의 영어 프롬프트 때문에 개체명이 영어로 나오면 질문에 영어 용어가 섞일 수 있다.
- tiktoken 인코딩 내려받기는 끄지 않았다 (5장).

**구현하지 않은 제안**

- **개체명 걸러 내기**: 전화번호·부서명 같은 개체명을 관계 계산에서 빼거나, 관계 단계 요약에서 선이 가장 많은 개체명 몇 개를 같이 보여 준다.
- **관계 문턱값 조정**: 개체명 겹침 선이 청크 수에 비해 지나치게 많으면 `OverlapScoreBuilder`의 `threshold=0.01`이 느슨하다는 뜻이다. 옵션으로 여는 것은 생성 방식 변경이라 하지 않았다.
- **스캔 pdf 표시**: 지금은 `empty_ratio` 불합격으로만 드러난다. 쪽에 이미지는 있는데 글자가 없으면 `scanned`로 따로 표시하면 원인을 바로 안다. OCR은 하지 않는다.
- **`load_dir` 병렬 처리**: 파일 단위라 `ProcessPoolExecutor`로 바꾸기 쉽다. 분량이 문제가 될 때 한다.
- **로더 옵션**: pdfplumber의 `layout=True`, PyMuPDF의 `sort=True`는 다단 문서의 순서에 영향을 준다. 순서 문제가 보이면 옵션을 다르게 준 로더를 하나 더 등록해 `compare`로 비교한다.
- **단계별 요청 실패 사유**: 요약 줄에는 수만 나오고 사유는 마지막 리포트에 모여 있다.
- **openai 패키지 상한**: 넣지 않았다.
