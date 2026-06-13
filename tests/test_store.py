import pytest

from citeseek.db import connect
from citeseek.models import Candidate, CandidateScores, PaperMeta, Passage
from citeseek.pipeline.store import upsert_paper
from citeseek.session import store
from citeseek.session.export import export_report


@pytest.fixture
def conn():
    return connect(":memory:")


def _candidate(conn, rank=1, title="Attention Is All You Need", year=2017):
    meta = PaperMeta(
        arxiv_id=f"1706.0{rank}",
        title=title,
        year=year,
        url=f"https://arxiv.org/abs/1706.0{rank}",
        sources=["arxiv"],
    )
    pid = upsert_paper(conn, meta)
    return Candidate(
        rank=rank,
        paper_id=pid,
        paper=meta,
        scores=CandidateScores(embed=0.9, final=0.9),
        confidence=0.85,
        verdict="supports",
        rationale="Introduces the idea.",
        passages=[Passage(quote="The dominant sequence transduction models...", score=0.92)],
    )


def test_session_node_candidate_roundtrip(conn):
    session = store.create_session(conn, "test session")
    node_id = store.create_node(conn, session.id, "transformers use attention")
    store.save_candidates(conn, node_id, [_candidate(conn)])
    store.set_node_status(conn, node_id, "done", queries=["q1", "q2"])

    node = store.get_node(conn, node_id)
    assert node is not None
    assert node.status == "done"
    assert node.queries == ["q1", "q2"]
    assert len(node.candidates) == 1
    cand = node.candidates[0]
    assert cand.paper.title == "Attention Is All You Need"
    assert cand.confidence == 0.85
    assert cand.read_status == "unread"
    assert cand.passages[0].score == 0.92


def test_tree_structure_and_counts(conn):
    session = store.create_session(conn)
    root = store.create_node(conn, session.id, "root claim")
    store.save_candidates(conn, root, [_candidate(conn, rank=1), _candidate(conn, rank=2, title="Other Paper")])
    child = store.create_node(conn, session.id, "child claim", parent_id=root, paper_id=1)

    tree = store.get_tree(conn, session.id)
    assert len(tree) == 2
    root_summary = next(n for n in tree if n.id == root)
    assert root_summary.candidate_count == 2
    assert root_summary.unread_count == 2
    child_summary = next(n for n in tree if n.id == child)
    assert child_summary.parent_id == root


def test_candidate_open_marks_read(conn):
    session = store.create_session(conn)
    node_id = store.create_node(conn, session.id, "claim")
    cand = _candidate(conn)
    store.save_candidates(conn, node_id, [cand])
    paper_id = store.set_candidate_status(conn, cand.id, "opened")
    assert paper_id == cand.paper_id
    node = store.get_node(conn, node_id)
    assert node.candidates[0].read_status == "opened"
    assert node.unread_count == 0


def test_export_report_walks_tree(conn):
    session = store.create_session(conn, "GAN provenance")
    root = store.create_node(conn, session.id, "GANs train two networks adversarially")
    store.save_candidates(conn, root, [_candidate(conn)])
    child = store.create_node(conn, session.id, "minimax objective", parent_id=root)
    store.save_candidates(conn, child, [_candidate(conn, rank=3, title="Some Older Paper", year=2004)])

    report = export_report(conn, session.id)
    assert "GAN provenance" in report
    assert "GANs train two networks adversarially" in report
    assert "Attention Is All You Need" in report
    assert "Some Older Paper" in report
    # child indented deeper than root
    assert "  - **Claim:** “minimax objective”" in report


def test_settings_roundtrip(conn):
    store.set_setting(conn, "llm.provider", "ollama")
    assert store.get_settings_map(conn)["llm.provider"] == "ollama"
