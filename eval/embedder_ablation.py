"""Embedding-model ablation: bge-small-en-v1.5 vs allenai-specter.

Fully offline w.r.t. scholarly APIs (uses eval/cache). Compares the two
embedders on the no-judge configurations so the difference is attributable
to the embedding model alone. SPECTER is citation-informed and tuned for
scientific papers (Cohan et al., 2020); bge-small is the small general
retrieval model the product ships with.

Usage:  .venv/bin/python eval/embedder_ablation.py
Output: eval/results-embedder.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_eval import KS, _is_gold, score_ranking  # noqa: E402

from citeseek.models import PaperMeta  # noqa: E402
from citeseek.pipeline.citations import SeedCitationIndex  # noqa: E402
from citeseek.pipeline.dedup import dedupe  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CACHE = EVAL_DIR / "cache"

MODELS = {
    "bge-small-en-v1.5": ("BAAI/bge-small-en-v1.5",
                          "Represent this sentence for searching relevant passages: "),
    "allenai-specter": ("sentence-transformers/allenai-specter", ""),
}


def load(name: str) -> list[PaperMeta]:
    f = CACHE / name
    if not f.exists():
        return []
    return [PaperMeta.model_validate(m) for m in json.loads(f.read_text())]


def main() -> None:
    from sentence_transformers import SentenceTransformer

    items = [
        json.loads(line)
        for line in (EVAL_DIR / "benchmark.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows = {}
    for label, (model_name, prefix) in MODELS.items():
        model = SentenceTransformer(model_name, cache_folder="var/models")
        for config in ("llmq+embed", "llmq+cite+embed+freq"):
            scores_acc = []
            for it in items:
                base = load(f"{it['id']}-llmq.json")
                if config.startswith("llmq+cite"):
                    cf = CACHE / f"{it['id']}-cite.json"
                    data = json.loads(cf.read_text()) if cf.exists() else {"refs": [], "freq": {}}
                    refs = [PaperMeta.model_validate(m) for m in data["refs"]]
                    metas = dedupe(base + refs)
                    index = SeedCitationIndex(refs, data["freq"])
                else:
                    metas, index = base, None
                if not metas:
                    scores_acc.append(score_ranking([], it["gold"]))
                    continue
                qv = model.encode([prefix + it["claim"]], normalize_embeddings=True)[0]
                dv = model.encode(
                    [f"{m.title}. {m.abstract or ''}".strip() for m in metas],
                    normalize_embeddings=True, show_progress_bar=False, batch_size=32,
                )
                s = dv @ qv
                if index is not None:
                    s = s + 0.3 * np.array(
                        [min(index.count_for(m), 10) / 10 for m in metas]
                    )
                ranked = [metas[i] for i in np.argsort(-s)]
                scores_acc.append(score_ranking(ranked, it["gold"]))
            avg = lambda key: sum(r[key] for r in scores_acc) / len(scores_acc)  # noqa: E731
            rows[f"{config} [{label}]"] = (
                [avg(f"recall@{k}") for k in KS]
                + [avg(f"hit@{k}") for k in KS]
                + [avg("mrr")]
            )
            print(f"{label:>20} {config:<24} "
                  f"R@5={rows[f'{config} [{label}]'][0]:.3f} "
                  f"Hit@5={rows[f'{config} [{label}]'][3]:.3f} "
                  f"MRR={rows[f'{config} [{label}]'][6]:.3f}", flush=True)

    lines = [
        "# Embedding-model ablation (no LLM judge)",
        "",
        "| config [embedder] | " + " | ".join(f"R@{k}" for k in KS)
        + " | " + " | ".join(f"Hit@{k}" for k in KS) + " | MRR |",
        "|---|" + "---|" * 7,
    ]
    for name, vals in rows.items():
        lines.append("| " + name + " | " + " | ".join(f"{v:.3f}" for v in vals) + " |")
    out = EVAL_DIR / "results-embedder.md"
    out.write_text("\n".join(lines) + "\n")
    print("written to", out)


if __name__ == "__main__":
    main()
