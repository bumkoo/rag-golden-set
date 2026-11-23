"""ragas 단계 요약에 쓰는 것: 지식 그래프 집계, 이름표, ragas 자체 진행 막대 끄기."""

from collections import Counter
from contextlib import contextmanager

from ragas.testset.graph import KnowledgeGraph, NodeType

from golden_set.generation.progress import Stages

# 요약 줄에 쓰는 이름. 표에 없는 이름은 그대로 찍는다.
TRANSFORM_LABELS = {
    "SummaryExtractor": "요약",
    "EmbeddingExtractor": "임베딩",
    "ThemesExtractor": "주제",
    "NERExtractor": "개체명",
    "CosineSimilarityBuilder": "유사도",
    "OverlapScoreBuilder": "개체명 겹침",
}
RELATION_LABELS = {"summary_similarity": "유사도", "entities_overlap": "개체명 겹침"}  # 관계 빌더가 붙이는 type
SYNTHESIZER_LABELS = {
    "single_hop_specific_query_synthesizer": "단일",
    "multi_hop_abstract_query_synthesizer": "넓은 주제",
    "multi_hop_specific_query_synthesizer": "특정 대상",
}


def relation_stats(kg: KnowledgeGraph) -> tuple[Counter, int]:
    """(종류별 선의 수, 선이 하나도 없는 청크 수). 선의 종류는 Relationship.type이다."""
    by_type: Counter = Counter()
    linked: set = set()
    for rel in kg.relationships:
        by_type[rel.type] += 1
        linked.add(rel.source.id)
        linked.add(rel.target.id)
    isolated = sum(1 for node in kg.nodes if node.type == NodeType.CHUNK and node.id not in linked)
    return by_type, isolated


def relation_summary(kg: KnowledgeGraph) -> str:
    by_type, isolated = relation_stats(kg)
    names = list(RELATION_LABELS) + sorted(t for t in by_type if t not in RELATION_LABELS)
    counts = ", ".join(f"{RELATION_LABELS.get(t, t)} {by_type.get(t, 0)}개" for t in names)
    return f"{counts}, 선 없는 청크 {isolated}개"


def kinds_summary(counts: Counter, labels: dict[str, str]) -> str:
    """종류별 개수를 "임베딩 74, 주제 74"처럼 쓴다. labels의 순서를 따르고 표에 없는 종류는 뒤에 붙인다."""
    names = [k for k in labels if k in counts] + sorted(k for k in counts if k not in labels)
    return ", ".join(f"{labels.get(k, k)} {counts[k]}" for k in names)


@contextmanager
def quiet_ragas_bars():
    """ragas가 직접 그리는 tqdm 막대(Applying ..., Generating ...)를 끈다. 진행은 우리 reporter가 보인다.

    ragas 0.4.4는 모든 막대를 ragas.utils.ProgressBarManager에서 ragas.utils.tqdm으로 만든다.
    그 이름이 없는 버전이면 아무것도 하지 않는다 (막대가 그대로 보일 뿐 동작은 같다).
    """
    import ragas.utils as ragas_utils

    original = getattr(ragas_utils, "tqdm", None)
    if original is None:
        yield
        return

    def silent(*args, **kwargs):
        kwargs["disable"] = True
        return original(*args, **kwargs)

    ragas_utils.tqdm = silent
    try:
        yield
    finally:
        ragas_utils.tqdm = original


class SampleStages:
    """시나리오 단계와 질문·정답 단계의 경계를 잡는다 (guards.SynthesisEvents 구현).

    ragas의 TestsetGenerator.generate는 시나리오를 전부 만든 뒤에 샘플을 만든다. 그래서 첫 샘플이 시작될 때
    시나리오 단계를 닫고 질문·정답 단계를 연다.
    """

    def __init__(self, stages: Stages, sample_stage: str, scenario_tail: str = ""):
        self.stages = stages
        self.sample_stage = sample_stage
        self.scenario_tail = scenario_tail
        self.scenarios: Counter = Counter()
        self.samples_open = False

    @property
    def total(self) -> int:
        return sum(self.scenarios.values())

    def scenarios_done(self, synthesizer_name: str, count: int) -> None:
        self.scenarios[synthesizer_name] += count

    def sample_started(self) -> None:
        if not self.samples_open:
            self.open_samples()

    def sample_finished(self) -> None:
        self.stages.advance()

    def open_samples(self) -> None:
        """시나리오 단계를 닫고 질문·정답 단계를 연다. 시나리오가 하나도 없을 때는 밖에서 부른다."""
        if self.samples_open:
            return
        self.samples_open = True
        kinds = kinds_summary(self.scenarios, SYNTHESIZER_LABELS)
        self.stages.finish(f"{self.total}개" + (f" ({kinds})" if kinds else ""), failed=self.stages.failed_items or None, tail=self.scenario_tail)
        self.stages.start(self.sample_stage, self.total)
