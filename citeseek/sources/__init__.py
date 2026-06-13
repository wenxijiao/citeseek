from .arxiv import ArxivSource
from .base import SourceClient
from .openalex import OpenAlexSource
from .semantic_scholar import SemanticScholarSource

ALL_SOURCES: list[type[SourceClient]] = [ArxivSource, SemanticScholarSource, OpenAlexSource]

__all__ = ["SourceClient", "ArxivSource", "SemanticScholarSource", "OpenAlexSource", "ALL_SOURCES"]
