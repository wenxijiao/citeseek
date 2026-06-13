from citeseek.fetch.html_parser import parse_latexml_html
from citeseek.models import ParsedDoc
from citeseek.pipeline.chunking import chunk_document

LATEXML_HTML = """
<html><body><article class="ltx_document">
<h1 class="ltx_title ltx_title_document">Test Paper Title</h1>
<div class="ltx_abstract"><h6 class="ltx_title">Abstract</h6>
<p class="ltx_p">This is the abstract text of the paper.</p></div>
<section><h2 class="ltx_title ltx_title_section">1 Introduction</h2>
<div class="ltx_para"><p class="ltx_p">First intro paragraph with some content here.</p></div>
<div class="ltx_para"><p class="ltx_p">Second intro paragraph with math <math alttext="x^2"><mi>x</mi></math> inline.</p></div>
</section>
<section><h2 class="ltx_title ltx_title_bibliography">References</h2>
<div class="ltx_para"><p class="ltx_p">Some reference entry that should be skipped.</p></div>
</section>
</article></body></html>
"""


def test_parse_latexml_document_order_and_anchors():
    doc = parse_latexml_html(LATEXML_HTML)
    assert doc.title == "Test Paper Title"
    assert "Abstract" in doc.sections and " 1 Introduction" in [s for s in doc.sections] or any(
        "Introduction" in s for s in doc.sections
    )
    assert 'data-p="0"' in doc.reader_html
    assert "abstract text" in doc.plain_text
    # math replaced by alttext
    assert "x^2" in doc.plain_text
    # references skipped
    assert "reference entry" not in doc.plain_text


def test_paragraphs_anchor_sequence():
    doc = parse_latexml_html(LATEXML_HTML)
    assert doc.plain_text.split("\n\n")[0].startswith("This is the abstract")
    assert doc.reader_html.count("<p data-p=") == 3


def test_chunk_document_sections_and_anchors():
    doc = parse_latexml_html(LATEXML_HTML)
    chunks = chunk_document(doc)
    assert chunks, "expected at least one chunk"
    assert chunks[0].para_start == 0
    # every chunk text carries its section prefix when present
    for chunk in chunks:
        if chunk.section:
            assert chunk.text.startswith("§")


def test_chunk_merging_respects_target_size():
    paras = "\n".join(
        f'<p data-p="{i}" data-section="S">{"word " * 60}</p>' for i in range(10)
    )
    doc = ParsedDoc(reader_html=paras, plain_text="x", sections=["S"])
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert all(len(c.text.split()) * 1.3 < 600 for c in chunks)
    # overlap: next chunk starts at or before previous end + 1
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.para_start <= prev.para_end + 1
