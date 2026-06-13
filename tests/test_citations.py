"""Offline tests for backward snowballing and the new ranking signals."""

from citeseek.models import Candidate, CandidateScores, PaperMeta
from citeseek.pipeline.citations import meta_key
from citeseek.pipeline.rank import finalize_scores


def _meta(**kw) -> PaperMeta:
    return PaperMeta(title=kw.pop("title", "t"), **kw)


def test_meta_key_prefers_arxiv_and_folds_arxiv_doi():
    assert meta_key(_meta(arxiv_id="1706.03762")) == "arxiv:1706.03762"
    # the arXiv-assigned DOI is the same identity as the bare arXiv id
    assert meta_key(_meta(doi="10.48550/arxiv.1706.03762")) == "arxiv:1706.03762"
    assert meta_key(_meta(doi="10.1038/nature16961")) == "doi:10.1038/nature16961"
    assert meta_key(_meta(title="Attention Is All You Need")).startswith("title:")


def test_meta_key_same_paper_different_records_agree():
    a = _meta(arxiv_id="1512.03385", title="Deep Residual Learning")
    b = _meta(doi="10.48550/arxiv.1512.03385", title="Deep residual learning")
    assert meta_key(a) == meta_key(b)


def _cand(title: str, year: int, embed: float = 0.5, cite: float | None = None) -> Candidate:
    return Candidate(
        rank=1,
        paper_id=0,
        paper=PaperMeta(title=title, year=year),
        scores=CandidateScores(embed=embed, cite_freq=cite),
    )


def test_survey_titles_are_penalised():
    origin = _cand("Generative Adversarial Nets", 2014)
    survey = _cand("Generative adversarial networks: introduction and outlook", 2014)
    ranked = finalize_scores([survey, origin], use_year_prior=False)
    assert ranked[0].paper.title == "Generative Adversarial Nets"
    assert ranked[1].scores.survey_penalty is not None


def test_cite_freq_bonus_lifts_shared_antecedent():
    plain = _cand("Some follow-up work", 2020, embed=0.55)
    antecedent = _cand("The original paper", 2015, embed=0.50, cite=0.24)
    ranked = finalize_scores([plain, antecedent], use_year_prior=False)
    assert ranked[0].paper.title == "The original paper"
