"""Per-claim failure attribution, before and after citation expansion.

Fully offline: uses the candidate caches under eval/cache/. For each claim,
classifies the outcome of the llmq pipeline and of the llmq+cite+freq
pipeline into:

    hit@5           gold in the top 5 (success)
    rank_miss       gold retrieved but ranked outside the top 5
    retrieval_miss  gold never entered the candidate pool

Output: eval/failure_analysis.md (a table for the report's Discussion).

Usage:  .venv/bin/python eval/failure_analysis.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_eval import (  # noqa: E402
    _is_gold,
    rank_embed,
    rank_embed_freq,
)

from citeseek.models import PaperMeta  # noqa: E402
from citeseek.pipeline.dedup import dedupe  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CACHE = EVAL_DIR / "cache"


def load(name: str) -> list[PaperMeta]:
    f = CACHE / name
    if not f.exists():
        return []
    return [PaperMeta.model_validate(m) for m in json.loads(f.read_text())]


def classify(ranked: list[PaperMeta], gold: list[str]) -> tuple[str, int | None]:
    hits = [i for i, m in enumerate(ranked) if _is_gold(m, gold)]
    if not hits:
        return "retrieval_miss", None
    rank = hits[0] + 1
    return ("hit@5" if rank <= 5 else "rank_miss"), rank


def main() -> None:
    items = [
        json.loads(line)
        for line in (EVAL_DIR / "benchmark.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows = []
    for it in items:
        base = load(f"{it['id']}-llmq.json")
        before_cls, before_rank = classify(
            rank_embed(it["claim"], base) if base else [], it["gold"]
        )
        cite_file = CACHE / f"{it['id']}-cite.json"
        if cite_file.exists() and base:
            from citeseek.pipeline.citations import SeedCitationIndex

            data = json.loads(cite_file.read_text())
            refs = [PaperMeta.model_validate(m) for m in data["refs"]]
            combined = dedupe(base + refs)
            after_cls, after_rank = classify(
                rank_embed_freq(
                    it["claim"], combined, SeedCitationIndex(refs, data["freq"])
                ),
                it["gold"],
            )
        else:
            after_cls, after_rank = before_cls, before_rank
        rows.append((it["id"], before_cls, before_rank, after_cls, after_rank))
        print(f"{it['id']:>14}  {before_cls:<15} rank={before_rank or '-':<4} -> "
              f"{after_cls:<15} rank={after_rank or '-'}")

    def fmt_rank(r):
        return str(r) if r else "—"

    counts = {}
    for _, b, _, a, _ in rows:
        counts[(b, a)] = counts.get((b, a), 0) + 1

    lines = [
        "# Failure attribution (llmq+embed vs llmq+cite+embed+freq)",
        "",
        "Classification per claim: where does the pipeline lose the gold paper —",
        "never retrieved (`retrieval_miss`), retrieved but ranked below 5",
        "(`rank_miss`), or in the top five (`hit@5`). Ranking here is the",
        "no-judge configuration, so the table isolates retrieval and the",
        "citation-frequency signal from LLM behaviour.",
        "",
        "| claim | before: outcome | before: rank | after: outcome | after: rank |",
        "|---|---|---|---|---|",
    ]
    for cid, b, br, a, ar in rows:
        lines.append(f"| {cid} | {b} | {fmt_rank(br)} | {a} | {fmt_rank(ar)} |")
    lines += [
        "",
        "## Transition summary",
        "",
        "| before → after | claims |",
        "|---|---|",
    ]
    for (b, a), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {b} → {a} | {n} |")
    out = EVAL_DIR / "failure_analysis.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
