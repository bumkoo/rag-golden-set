"""deepeval의 모델 인터페이스를 우리 클라이언트로 구현한다."""

from deepeval.models import DeepEvalBaseLLM

from golden_set.generation.generator import GenerateReport
from golden_set.generation.llm.client import ChatClient, LLMError
from golden_set.generation.matching import extract_json


class ChatDeepEvalModel(DeepEvalBaseLLM):
    """DeepEvalBaseLLM을 ChatClient로 구현한다.

    schema가 오면 JSON 모드로 요청해 그 pydantic 모델 인스턴스를 돌려준다. 파싱이 안 되면 LLMError를 낸다
    (TypeError가 아니어야 한다: deepeval은 TypeError를 "schema를 못 받는 모델"로 해석해 다른 경로로 간다).
    """

    def __init__(self, client: ChatClient, report: GenerateReport | None = None):
        self.client = client
        self.report = report
        self.parse_failures: list[str] = []
        super().__init__(model=client.model)

    def load_model(self, *args, **kwargs):
        return self.client

    def get_model_name(self, *args, **kwargs) -> str:
        return self.client.model

    @staticmethod
    def text_field(schema) -> str | None:
        """문자열 필드 하나뿐인 스키마(예: Response.response)면 그 필드 이름. deepeval은 이런 스키마로 자유 텍스트를 받는다."""
        fields = getattr(schema, "model_fields", {})
        if len(fields) == 1:
            (name, info), = fields.items()
            if info.annotation is str:
                return name
        return None

    def _to_schema(self, text: str, schema):
        field = self.text_field(schema)
        try:
            return schema.model_validate(extract_json(text))
        except Exception as e:  # ValueError(JSON 없음)나 pydantic ValidationError
            if field is not None:  # 프롬프트가 자유 텍스트를 요구한 경우다. 본문을 그대로 담는다
                return schema(**{field: text})
            reason = f"{schema.__name__}: {type(e).__name__}: {str(e).splitlines()[0][:120]}"
            self.parse_failures.append(reason)
            self.client.log.fail(f"json parse ({reason})")
            raise LLMError(f"response did not match {reason}") from e

    def _json_mode(self, schema) -> bool:
        """JSON 키를 지정한 프롬프트에만 JSON 모드를 쓴다. 자유 텍스트 스키마(Response)는 서버가 JSON을 강제하면 안 된다."""
        return schema is not None and self.text_field(schema) is None

    def generate(self, prompt: str, schema=None, **kwargs):
        (c,) = self.client.complete([("user", prompt)], json=self._json_mode(schema))
        return c.text if schema is None else self._to_schema(c.text, schema)

    async def a_generate(self, prompt: str, schema=None, **kwargs):
        (c,) = await self.client.acomplete([("user", prompt)], json=self._json_mode(schema))
        return c.text if schema is None else self._to_schema(c.text, schema)
