import pytest
from test_learning import fixture

from rlmgraph.document_learning import (
    DocumentExtraction,
    DocumentFact,
    DocumentInput,
    DocumentLearning,
    DocumentReview,
    FactVerdict,
)
from rlmgraph.project_world_memory import ProjectWorldMemory


def candidate(**updates):
    return DocumentFact(topic="Luma tiles", statement="Luma tiles require a two-unit gap.",
        excerpt="Luma tiles require a two-unit gap.", applies_when="Laying out Luma tiles",
        limitations="Only the fictional Luma layout system", collection="Luma layout").model_copy(update=updates)


class Reader:
    def __init__(self, candidates=None, verdicts=None):
        self.candidates = candidates if candidates is not None else [candidate()]
        self.verdicts = verdicts if verdicts is not None else [FactVerdict(candidate=0, verdict="SUPPORTED", reason="The source states this rule and its scope.")]
        self.calls = 0

    def extract_document_facts(self, document, collections):
        self.calls += 1
        return DocumentExtraction(candidates=self.candidates)

    def review_document_facts(self, document, extraction, existing):
        self.calls += 1
        return DocumentReview(verdicts=self.verdicts)


def source(**updates):
    return DocumentInput(title="Luma manual", source_ref="fixture:luma-v1",
        text="In the fictional Luma layout system: Luma tiles require a two-unit gap.").model_copy(update=updates)


def test_document_is_reviewed_saved_indexed_and_idempotent(tmp_path):
    _, store, project, library = fixture(tmp_path)
    reader = Reader()
    pipeline = DocumentLearning(store, reader)
    receipt = pipeline.ingest(project, source(), "owner")
    assert receipt["saved_count"] == 1
    lesson = library.list(project)[0]
    assert lesson["status"] == "SOURCE_SUPPORTED"
    assert lesson["source_span"]["start"] >= 0
    assert lesson["world_index"]["terms"]
    assert lesson["collection_name"] == "luma layout"
    assert ProjectWorldMemory(store).search("Luma gap", project)["memories"][0]["id"] == lesson["id"]
    assert pipeline.ingest(project, source(), "owner")["reused"] is True
    assert reader.calls == 2
    assert pipeline.history(project)[0]["document_id"] == receipt["document_id"]
    second = pipeline.ingest(project, source(source_ref="fixture:luma-v2"), "owner")
    assert second["saved_count"] == 0
    assert second["decisions"][0]["outcome"] == "DUPLICATE"
    assert len(library.list(project)) == 1


@pytest.mark.parametrize("verdict", ["UNSUPPORTED", "CONFLICT"])
def test_negative_review_never_enters_retrieval(tmp_path, verdict):
    _, store, project, library = fixture(tmp_path)
    reader = Reader(verdicts=[FactVerdict(candidate=0, verdict=verdict, reason="Conditions are not supported.")])
    receipt = DocumentLearning(store, reader).ingest(project, source(), "owner")
    assert receipt["saved_count"] == 0
    assert library.list(project) == []
    assert receipt["decisions"][0]["outcome"] == verdict


def test_missing_quote_and_incomplete_review_fail_closed(tmp_path):
    _, store, project, library = fixture(tmp_path)
    pipeline = DocumentLearning(store, Reader([candidate(excerpt="Invented source text")]))
    assert pipeline.ingest(project, source(), "owner")["decisions"][0]["outcome"] == "REJECTED"
    with pytest.raises(ValueError, match="exactly once"):
        DocumentLearning(store, Reader(verdicts=[])).ingest(project, source(source_ref="new"), "owner")
    assert library.list(project) == []


def test_review_failure_saves_nothing_and_collections_reuse(tmp_path):
    _, store, project, library = fixture(tmp_path)
    reader = Reader()
    def fail(*args):
        raise TimeoutError("review timeout")
    reader.review_document_facts = fail
    with pytest.raises(TimeoutError):
        DocumentLearning(store, reader).ingest(project, source(), "owner")
    assert library.list(project) == []
    assert DocumentLearning(store, None).history(project) == []
    DocumentLearning(store, Reader()).ingest(project, source(), "owner")
    second_text = "Luma tiles use square corners."
    DocumentLearning(store, Reader([candidate(statement=second_text, excerpt=second_text)])).ingest(
        project, source(text=second_text), "owner")
    assert len({lesson["collection_id"] for lesson in library.list(project)}) == 1
    # Windows refuses this rename if a learning connection was left open.
    destination = tmp_path / "closed-learning-store.sqlite3"
    library.path.rename(destination)
    assert destination.exists()
