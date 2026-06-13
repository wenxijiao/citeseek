from citeseek.models import PaperMeta
from citeseek.pipeline.dedup import dedupe
from citeseek.sources.base import normalize_arxiv_id, normalize_doi, normalize_title


def test_normalize_arxiv_id():
    assert normalize_arxiv_id("2104.08691v2") == "2104.08691"
    assert normalize_arxiv_id("arXiv:1706.03762") == "1706.03762"
    assert normalize_arxiv_id("https://arxiv.org/abs/1706.03762v5") == "1706.03762"
    assert normalize_arxiv_id("http://arxiv.org/pdf/1409.0473.pdf") == "1409.0473"


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1162/NECO_a_00142") == "10.1162/neco_a_00142"
    assert normalize_doi("doi:10.1000/X") == "10.1000/x"
    assert normalize_doi(None) is None


def test_normalize_title_strips_latex_and_punct():
    assert normalize_title("Attention Is All You Need!") == "attention is all you need"
    assert normalize_title(r"$\alpha$-divergence {Methods}") == normalize_title(
        "alpha-divergence Methods"
    )


def _meta(**kw) -> PaperMeta:
    base = dict(title="Attention Is All You Need", year=2017, sources=["arxiv"])
    base.update(kw)
    return PaperMeta(**base)


def test_dedupe_merges_same_arxiv_id():
    a = _meta(arxiv_id="1706.03762", abstract=None)
    b = _meta(arxiv_id="1706.03762", abstract="The dominant sequence...", sources=["s2"])
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0].abstract == "The dominant sequence..."
    assert out[0].sources == ["arxiv", "s2"]


def test_dedupe_fuzzy_title_merge_across_namespaces():
    a = _meta(arxiv_id="1706.03762")
    b = _meta(doi="10.5555/3295222", title="Attention is all you need.", sources=["openalex"])
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0].arxiv_id == "1706.03762"
    assert out[0].doi == "10.5555/3295222"


def test_dedupe_keeps_distinct_papers():
    a = _meta(arxiv_id="1706.03762")
    b = _meta(arxiv_id="1409.0473", title="Neural Machine Translation by Jointly Learning to Align and Translate", year=2014)
    c = _meta(doi="10.1/abc", title="A Completely Different Paper", year=2017)
    out = dedupe([a, b, c])
    assert len(out) == 3


def test_dedupe_year_gate_blocks_fuzzy_merge():
    a = _meta(arxiv_id="1706.03762", year=2017)
    b = _meta(doi="10.1/xyz", title="Attention Is All You Need", year=2023)
    out = dedupe([a, b])
    assert len(out) == 2
