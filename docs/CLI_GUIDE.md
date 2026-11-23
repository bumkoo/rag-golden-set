# CLI 사용 안내: 문서 폴더에서 골든셋 파일까지

문서 폴더 하나를 받아 골든 후보를 만들고 내보내기까지, 명령을 어떤 순서로 쓰는지 정리한 문서다.
명령별 옵션의 자세한 뜻은 [README.md](../README.md)의 "명령별 설명"에 있다.

## 1. 한눈에 보기

작업 하나를 **프로젝트 폴더** 하나로 묶는다. 모든 명령에 `--project <폴더>`를 주면 산출물이 단계별 하위 폴더에 놓이고, 다음 명령은 앞 단계의 파일을 알아서 찾는다.

```text
<프로젝트>/                      예: data-out/형법/
├── 1-validate/   validate.csv                               ① validate
├── 2-prepare/    chunks.jsonl                               ② prepare
├── 3-generate/   ragas.candidates.jsonl     ragas.log       ④ generate --generator ragas
│                 deepeval.candidates.jsonl  deepeval.log    ④ generate --generator deepeval (필요할 때)
├── 4-check/      check.csv                                  ⑤ check
│                 reviewed.candidates.jsonl                  (사람이 검수해서 남긴 후보, 선택)
└── 5-export/     golden.awx1.json                           ⑥ export
```

| 순서 | 명령 | 읽는 것 | 쓰는 것 | LLM 서버 |
|---|---|---|---|---|
| ① | `validate <문서 폴더>` | 문서 폴더 | `1-validate/validate.csv` | 필요 없음 |
| ② | `prepare <문서 폴더>` | 문서 폴더 | `2-prepare/chunks.jsonl` | 필요 없음 |
| ③ | `ping` | 없음 | 화면의 연결 결과 | 필요 |
| ④ | `generate --generator <이름>` | `2-prepare/chunks.jsonl` | `3-generate/<이름>.candidates.jsonl`, `<이름>.log` | 필요 |
| ⑤ | `check` | `3-generate/`의 후보 파일 전부 | `4-check/check.csv` | 필요 없음 |
| ⑥ | `export --format awx1` | 검수본이 있으면 그것, 없으면 `3-generate/`의 후보 전부 | `5-export/golden.awx1.json` | 필요 없음 |

- 중간 파일이 남아 있으면 그 단계부터 다시 돌릴 수 있다. 같은 단계를 다시 돌리면 그 단계의 파일을 덮어쓴다.
- 생성기는 따로 돌린다. deepeval만 먼저 돌리고 나중에 ragas를 추가해도 서로 덮어쓰지 않는다.
- `validate`와 `prepare`는 문서 폴더를 받고 하위 폴더까지 읽는다. 파일 하나만 처리하려면 5장을 본다.
- 지원 형식: pdf, pptx, docx, txt, 내용이 RTF인 doc. 그 밖의 파일은 `unsupported`로 표시하고 건너뛴다.

## 2. 준비

### 설치

```bash
uv venv && uv pip install -e ".[dev,compare,generate]"
```

아래 명령의 `python`은 이 가상환경의 것이다 (`.venv/bin/python` 또는 `source .venv/bin/activate` 뒤의 `python`).

### 폴더 정하기

```bash
DOCS=<문서 폴더>            # 읽을 문서가 있는 곳, 예: data/
PROJ=<프로젝트 폴더>        # 산출물을 둘 곳, 예: data-out/형법
```

프로젝트 폴더와 그 아래 단계 폴더는 명령이 만든다. 실제 문서와 산출물은 저장소에 커밋하지 않는다. 저장소 안의 `data/`와 `data-out/`은 .gitignore에 들어 있어 여기에 둬도 된다.

### 접속 정보 (③ ping, ④ generate에만 필요)

```bash
export GOLDEN_LLM_BASE_URL=http://<서버>:<포트>/v1
export GOLDEN_LLM_MODEL=<모델 이름>
export GOLDEN_EMBED_BASE_URL=http://<서버>:<포트>/v1    # ragas 생성기에만 필요
export GOLDEN_EMBED_MODEL=<임베딩 모델 이름>
# 키를 검사하는 서버일 때만: GOLDEN_LLM_API_KEY, GOLDEN_EMBED_API_KEY
```

로컬 Ollama 예:

```bash
export GOLDEN_LLM_BASE_URL=http://localhost:11434/v1 GOLDEN_LLM_MODEL=qwen3.5:9b
export GOLDEN_EMBED_BASE_URL=http://localhost:11434/v1 GOLDEN_EMBED_MODEL=bge-m3
```

> Ollama를 쓸 때는 `ping`과 `generate`에 `--reasoning-effort none`을 붙인다. 붙이지 않으면 요청마다 추론을 해서 수십 배 느리다.

## 3. 단계별 명령

### ① validate: 문서를 읽을 수 있는지 확인

```bash
python -m golden_set.cli validate "$DOCS" --project "$PROJ"
```

- 파일마다 한 줄씩 `pass`, `fail`, `error`, `unsupported`가 나온다.
- `fail`은 읽었지만 품질 기준 미달(빈 쪽이 많음, 글자가 깨짐 등), `error`는 읽지 못한 것이다.
- 본문을 눈으로 확인하려면 `--samples 2`를 붙인다 (파일마다 앞 300자를 2개씩 출력).
- 파일 하나를 여러 로더로 비교하려면: `python -m golden_set.cli compare <파일> --samples 1`

### ② prepare: 청크 만들기

```bash
python -m golden_set.cli prepare "$DOCS" --project "$PROJ"
```

- 쪽마다 반복되는 머리글·바닥글을 지우고 1,200자 단위로 자른다.
- 지운 문구와 파일별 청크 수를 출력한다. 본문이 지워지지 않았는지 여기서 확인한다.
- 자주 쓰는 옵션: `--chunk-size 1200`, `--overlap 150`, `--min-chars 100`.
- `prepare`를 다시 돌리면 청크가 바뀐다. 그 뒤에는 `generate`부터 다시 돌린다.

### ③ ping: 서버 연결 확인

```bash
python -m golden_set.cli ping
```

- `llm ok json=yes`와 `embed ok`가 나오면 된다.
- 응답 시간이 수십 초면 추론이 켜져 있는 것이다. Ollama면 `--reasoning-effort none`을 붙여 다시 본다.

### ④ generate: 골든 후보 만들기

```bash
python -m golden_set.cli generate --project "$PROJ" --generator deepeval --size 30
```

- `--generator`는 `ragas` 또는 `deepeval`이다. `--size`는 만들 후보 수(기본 30).
- 도는 동안 단계 이름과 진행이 보이고, 단계가 끝날 때마다 한 줄 요약이 남는다. 같은 요약이 `3-generate/<이름>.log`에도 남는다.
- 서버가 느리면 `--timeout 300`처럼 제한 시간을 늘린다 (기본 120초).

다른 생성기의 후보도 필요하면 한 번 더 돌린다. 파일이 따로 생기고, 다음 단계가 둘 다 읽는다.

```bash
python -m golden_set.cli generate --project "$PROJ" --generator ragas --size 30
```

### ⑤ check: 후보 검증

```bash
python -m golden_set.cli check --project "$PROJ"
```

- `3-generate/`의 후보를 모두 읽어 후보마다 `pass`/`fail`과 사유(질문 길이, 출처 없음, 중복, 언어 불일치 등)를 낸다.
- 생성기를 둘 다 돌렸으면 끝의 요약 표에 두 생성기가 나란히 나온다.
- 형식만 본다. 정답이 근거 본문과 맞는지는 사람이 검수한다.

### 검수 (사람이 하는 단계, 선택)

내보낼 후보를 고르려면 검수본을 만든다. 후보 파일을 합쳐 복사한 뒤, 뺄 후보의 줄을 지운다 (한 줄이 후보 하나다).

```bash
cat "$PROJ"/3-generate/*.candidates.jsonl > "$PROJ/4-check/reviewed.candidates.jsonl"
# 편집기로 reviewed.candidates.jsonl을 열어 뺄 후보의 줄을 지운다. check.csv의 fail 줄을 참고한다
```

검수본이 없으면 다음 단계는 생성된 후보를 전부 내보낸다.

### ⑥ export: 바깥 형식으로 내보내기

```bash
python -m golden_set.cli export --project "$PROJ" --format awx1
```

- `awx1`: `[{"id": 1, "query": "...", "expected_response": "..."}]` 꼴의 JSON 배열.
- 무엇을 읽었는지 `from: ...` 줄로 알려 준다. `4-check/reviewed.candidates.jsonl`이 있으면 그것만 내보낸다.

## 4. 폴더 하나를 처음부터 끝까지

아래를 그대로 붙여 넣으면 폴더 하나가 순서대로 처리된다. 접속 정보는 2장대로 먼저 넣는다.

```bash
DOCS=<문서 폴더>
PROJ=<프로젝트 폴더>
LLM_OPTS=""                  # Ollama면: LLM_OPTS="--reasoning-effort none --timeout 300"

python -m golden_set.cli validate "$DOCS" --project "$PROJ"
python -m golden_set.cli prepare  "$DOCS" --project "$PROJ" || echo "prepare: 읽지 못한 파일이 있다 (위 skip 줄 확인)"
python -m golden_set.cli ping $LLM_OPTS || { echo "서버 연결 실패"; exit 1; }
python -m golden_set.cli generate --project "$PROJ" --generator ragas --size 30 $LLM_OPTS
python -m golden_set.cli check    --project "$PROJ"
python -m golden_set.cli export   --project "$PROJ" --format awx1
```

`set -e`는 쓰지 않는다. `validate`와 `prepare`는 파일 하나만 불합격이어도 종료 코드 1을 내는데, 나머지 파일로 계속 진행할 수 있기 때문이다 (6장의 종료 코드 표).

## 5. 파일마다 따로 처리하기

`prepare`는 폴더만 받는다. 파일 하나만, 또는 파일마다 결과를 따로 받으려면 파일을 폴더 하나에 담아 넘긴다.

### 파일 하나만

```bash
mkdir -p "$PROJ/input"
cp "<문서 폴더>/형법.pdf" "$PROJ/input/"
python -m golden_set.cli prepare "$PROJ/input" --project "$PROJ"
```

그다음은 3장의 ③부터 같다.

### 폴더의 파일을 하나씩 차례로

파일마다 프로젝트를 따로 만들어 순서대로 돌린다. 한 파일이 실패해도 다음 파일로 넘어간다.

```bash
DOCS=<문서 폴더>
OUT=<결과 폴더>              # 이 아래에 파일 이름으로 프로젝트가 생긴다
LLM_OPTS=""                  # Ollama면: LLM_OPTS="--reasoning-effort none --timeout 300"

for f in "$DOCS"/*; do
  [ -f "$f" ] || continue
  proj="$OUT/$(basename "${f%.*}")"
  mkdir -p "$proj/input" && cp "$f" "$proj/input/"
  echo "=== $proj"

  python -m golden_set.cli prepare "$proj/input" --project "$proj" \
    || { echo "건너뜀 (prepare 실패): $f"; continue; }
  python -m golden_set.cli generate --project "$proj" --generator ragas --size 30 $LLM_OPTS \
    || { echo "건너뜀 (generate 실패): $f"; continue; }
  python -m golden_set.cli check  --project "$proj"
  python -m golden_set.cli export --project "$proj" --format awx1
done
```

지원하지 않는 형식의 파일은 `prepare`가 청크를 만들지 못해 "건너뜀"으로 넘어간다.

### 폴더 여러 개를 차례로

```bash
for DOCS in <폴더1> <폴더2> <폴더3>; do
  PROJ=<결과 폴더>/$(basename "$DOCS")
  # 여기에 4장의 validate ~ export 명령을 넣는다
done
```

### 폴더 전체를 한 번에 돌릴 때와의 차이

| | 폴더 전체를 프로젝트 하나로 (4장) | 파일마다 프로젝트 하나 (5장) |
|---|---|---|
| 후보 수 | 폴더 전체에서 `--size`개 | 파일마다 `--size`개 |
| 여러 파일에 걸친 질문 | ragas가 만들 수 있다 | 만들어지지 않는다 |
| 내보낸 파일 | 하나 | 파일마다 하나 |
| 한 파일이 문제일 때 | 그 파일만 건너뛰고 나머지로 진행 | 그 파일만 건너뜀 |

## 6. 경로를 직접 주고 싶을 때

`--project` 없이도 쓸 수 있고, 섞어 써도 된다. 경로를 직접 준 옵션이 우선한다.

```bash
python -m golden_set.cli prepare  <문서 폴더> --out <경로>/chunks.jsonl
python -m golden_set.cli generate <경로>/chunks.jsonl --generator ragas --out <경로>/candidates.jsonl --log-file <경로>/generate.log
python -m golden_set.cli check    <경로>/candidates.jsonl --chunks <경로>/chunks.jsonl --out <경로>/check.csv
python -m golden_set.cli export   <경로>/candidates.jsonl --format awx1 --out <경로>/golden.awx1.json
```

예: 같은 생성기의 이전 결과를 남기고 다시 돌리려면 `--out "$PROJ/3-generate/ragas-2차.candidates.jsonl"`처럼 이름을 직접 준다. 이름이 `.candidates.jsonl`로 끝나면 `check`와 `export`가 같이 읽는다.

## 7. 종료 코드와 자주 겪는 문제

| 명령 | 0 | 1 | 2 |
|---|---|---|---|
| `validate` | 전부 합격 | 불합격이나 읽기 실패가 있음 | 폴더가 없음 |
| `prepare` | 저장함 | 저장했지만 읽기 실패한 파일이 있음 | 폴더가 없거나 청크가 0개 |
| `ping` | LLM과 임베딩 정상 | 연결이나 JSON 응답 실패 | 접속 정보 없음 |
| `generate` | 후보를 만듦 | 후보가 0개 | 접속 정보나 입력 파일 없음 |
| `check` | 합격한 후보가 있음 | 합격이 하나도 없음 | 입력 파일 없음 |
| `export` | 저장함 | 후보가 없음 | 파일을 읽거나 쓰지 못함 |

| 증상 | 확인할 것 |
|---|---|
| `error: missing GOLDEN_LLM_BASE_URL, ...` | 2장의 접속 정보를 같은 셸에서 export했는지 |
| `ragas needs an embedding model` | `GOLDEN_EMBED_*` 두 변수. deepeval은 임베딩 없이 돈다 |
| `error: no candidates in .../3-generate` | `generate`를 먼저 돌렸는지, `--project` 경로가 같은지 |
| 요청 하나가 수십 초 걸린다 | `ping`의 응답 시간. Ollama면 `--reasoning-effort none` |
| `generate`의 요약 줄에 "실패"가 많다 | `--timeout`을 늘리거나 `--concurrency`를 줄인다 (기본 4) |
| `check`에서 `sources: chunk_id not in chunks.jsonl` | 후보를 만든 뒤에 `prepare`를 다시 돌리지 않았는지. 돌렸다면 `generate`부터 다시 한다 |
| `prepare`가 본문 줄을 지웠다 | 출력의 `removed from ...` 목록. `--header-ratio`를 올린다 (기본 0.6) |
