import pytest
from pydantic import BaseModel

from citeseek.llm.openai_compat import OpenAICompatClient, _strip_fences
from citeseek.llm.registry import DEFAULT_MODELS, PROVIDERS, get_llm
from citeseek.llm.base import LLMError
from citeseek.models import Candidate, CandidateScores, PaperMeta
from citeseek.pipeline.rank import finalize_scores


def test_strip_fences():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_registry_rejects_unknown_provider():
    with pytest.raises(LLMError):
        get_llm(provider="not-a-provider")


def test_registry_covers_all_providers():
    assert set(DEFAULT_MODELS) == set(PROVIDERS)


class Out(BaseModel):
    answer: int


@pytest.mark.asyncio
async def test_complete_json_repairs_invalid_json(monkeypatch):
    client = OpenAICompatClient.__new__(OpenAICompatClient)
    client.provider = "test"
    client.model = "test"
    responses = iter(["not json at all", '{"answer": 42}'])

    async def fake_chat(system, user, max_tokens, json_mode):
        return next(responses)

    client._chat = fake_chat
    result = await client.complete_json("sys", "user", Out)
    assert result.answer == 42


def _cand(embed, llm=None, year=None):
    return Candidate(
        rank=0,
        paper_id=1,
        paper=PaperMeta(title="t", year=year),
        scores=CandidateScores(embed=embed, llm=llm),
        confidence=llm,
    )


def test_finalize_scores_blends_and_sorts():
    a = _cand(0.9, llm=0.2)   # high embed, judge says weak
    b = _cand(0.6, llm=0.95)  # judge says strong support
    out = finalize_scores([a, b], use_year_prior=False)
    assert out[0] is b
    assert out[0].rank == 1


def test_finalize_year_prior_favors_older():
    new = _cand(0.7, year=2024)
    old = _cand(0.7, year=2004)
    out = finalize_scores([new, old], before_year=2024)
    assert out[0] is old
    assert old.scores.year_prior and old.scores.year_prior > 0
