"""ragas의 LLM·임베딩 인터페이스를 우리 클라이언트로 구현한다."""

from langchain_core.outputs import Generation, LLMResult
from langchain_core.prompt_values import PromptValue
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import BaseRagasLLM
from ragas.run_config import RunConfig

from golden_set.generation.llm.client import ChatClient, EmbedClient


class ChatRagasLLM(BaseRagasLLM):
    """ragas의 BaseRagasLLM을 ChatClient로 구현한다. 응답은 LLMResult로 돌려준다."""

    def __init__(self, client: ChatClient, run_config: RunConfig | None = None):
        super().__init__()
        self.client = client
        if run_config is not None:
            self.set_run_config(run_config)

    @staticmethod
    def _result(completions) -> LLMResult:
        return LLMResult(generations=[[Generation(text=c.text, generation_info={"finish_reason": c.finish_reason}) for c in completions]])

    def generate_text(self, prompt: PromptValue, n: int = 1, temperature: float = 0.01, stop=None, callbacks=None) -> LLMResult:
        return self._result(self.client.complete(prompt.to_messages(), json=True, temperature=temperature, n=n))

    async def agenerate_text(self, prompt: PromptValue, n: int = 1, temperature: float | None = 0.01, stop=None, callbacks=None) -> LLMResult:
        return self._result(await self.client.acomplete(prompt.to_messages(), json=True, temperature=temperature, n=n))

    def is_finished(self, response: LLMResult) -> bool:
        """max_tokens에 잘린 응답(finish_reason=length)은 끝나지 않은 것으로 본다."""
        for gens in response.generations:
            for g in gens:
                if (g.generation_info or {}).get("finish_reason") == "length":
                    return False
        return True


class ChatRagasEmbedding(BaseRagasEmbedding):
    """ragas의 BaseRagasEmbedding을 EmbedClient로 구현한다."""

    is_async = True  # EmbeddingExtractor가 이 속성을 보고 aembed_text를 쓴다

    def __init__(self, client: EmbedClient):
        super().__init__()
        self.client = client

    def embed_text(self, text: str, **kwargs) -> list[float]:
        return self.client.embed([text])[0]

    async def aembed_text(self, text: str, **kwargs) -> list[float]:
        return (await self.client.aembed([text]))[0]
