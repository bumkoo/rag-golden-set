"""지식 그래프 변환 구성: 요약 → 임베딩·주제·개체명 → 관계."""

from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import BaseRagasLLM
from ragas.testset.graph import Node, NodeType
from ragas.testset.transforms import Parallel
from ragas.testset.transforms.extractors import EmbeddingExtractor
from ragas.testset.transforms.extractors.llm_based import NERExtractor, SummaryExtractor, ThemesExtractor
from ragas.testset.transforms.relationship_builders import CosineSimilarityBuilder, OverlapScoreBuilder

from golden_set.generation.generator import GenerateReport
from golden_set.generation.ragas.guards import GuardedTransform


def _chunk_with(prop: str):
    def ok(node: Node) -> bool:
        return node.type == NodeType.CHUNK and node.get_property(prop) is not None

    return ok


def build_transforms(llm: BaseRagasLLM, embedding: BaseRagasEmbedding, report: GenerateReport) -> list:
    """ragas의 default_transforms_for_prechunked와 같은 구성에 실패 보호를 더한 것.

    차이: 각 변환을 GuardedTransform으로 감싸고, 뒷단계는 앞단계 속성이 있는 노드만 본다.
    CustomNodeFilter는 미리 나눈 청크에는 부모 요약이 없어 아무것도 하지 않으므로(ragas 0.4.4 filters.py) 뺐다.
    """
    chunk = _chunk_with("page_content")
    return [
        GuardedTransform(SummaryExtractor(llm=llm, filter_nodes=chunk), report),
        GuardedTransform(
            Parallel(
                EmbeddingExtractor(embedding_model=embedding, property_name="summary_embedding", embed_property_name="summary", filter_nodes=_chunk_with("summary")),
                ThemesExtractor(llm=llm, filter_nodes=chunk),
                NERExtractor(llm=llm, filter_nodes=chunk),
            ),
            report,
        ),
        GuardedTransform(
            Parallel(
                CosineSimilarityBuilder(property_name="summary_embedding", new_property_name="summary_similarity", threshold=0.7, filter_nodes=_chunk_with("summary_embedding")),
                OverlapScoreBuilder(threshold=0.01, filter_nodes=_chunk_with("entities")),
            ),
            report,
        ),
    ]
