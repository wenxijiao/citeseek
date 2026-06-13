import json

import httpx
import pytest

from citeseek.sources.arxiv import ArxivSource
from citeseek.sources.openalex import OpenAlexSource, deinvert_abstract
from citeseek.sources.semantic_scholar import SemanticScholarSource

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You\n Need</title>
    <summary>The dominant sequence transduction models...</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
  </entry>
</feed>"""

S2_JSON = {
    "data": [
        {
            "paperId": "abc123",
            "title": "Attention Is All You Need",
            "abstract": "The dominant sequence transduction models...",
            "year": 2017,
            "venue": "NeurIPS",
            "citationCount": 100000,
            "url": "https://www.semanticscholar.org/paper/abc123",
            "externalIds": {"ArXiv": "1706.03762", "DOI": "10.5555/3295222.3295349"},
            "authors": [{"name": "Ashish Vaswani"}],
        }
    ]
}

OPENALEX_JSON = {
    "results": [
        {
            "ids": {"openalex": "https://openalex.org/W2741809807"},
            "doi": "https://doi.org/10.48550/arxiv.1706.03762",
            "title": "Attention Is All You Need",
            "publication_year": 2017,
            "cited_by_count": 90000,
            "open_access": {"is_oa": True},
            "primary_location": {
                "landing_page_url": "https://arxiv.org/abs/1706.03762",
                "source": {"display_name": "arXiv (Cornell University)"},
            },
            "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
            "abstract_inverted_index": {"The": [0], "dominant": [1], "models": [2]},
        }
    ]
}


def _client(payload, content_type: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, text=body, headers={"Content-Type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_arxiv_parsing():
    async with _client(ARXIV_ATOM, "application/atom+xml") as client:
        papers = await ArxivSource(client).search("attention")
    assert len(papers) == 1
    p = papers[0]
    assert p.arxiv_id == "1706.03762"
    assert p.title == "Attention Is All You Need"
    assert p.year == 2017
    assert p.open_access
    assert p.authors == ["Ashish Vaswani", "Noam Shazeer"]


@pytest.mark.asyncio
async def test_s2_parsing():
    async with _client(S2_JSON, "application/json") as client:
        papers = await SemanticScholarSource(client).search("attention")
    p = papers[0]
    assert p.arxiv_id == "1706.03762"
    assert p.doi == "10.5555/3295222.3295349"
    assert p.s2_id == "abc123"
    assert p.citation_count == 100000
    assert p.open_access


@pytest.mark.asyncio
async def test_openalex_parsing():
    async with _client(OPENALEX_JSON, "application/json") as client:
        papers = await OpenAlexSource(client).search("attention")
    p = papers[0]
    assert p.arxiv_id == "1706.03762"
    assert p.openalex_id == "W2741809807"
    assert p.abstract == "The dominant models"
    assert p.year == 2017


def test_deinvert_abstract():
    assert deinvert_abstract({"world": [1], "hello": [0]}) == "hello world"
    assert deinvert_abstract(None) is None
