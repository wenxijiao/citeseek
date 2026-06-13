"""CiteSeek -> Von integration bridge.

Connects, as a standard MCP client, to BOTH:
  - citeseek-mcp        (this project's MCP server: claim -> evidence-ranked papers)
  - Von's vontology MCP (the Strong AI Lab Von system, launched unmodified via
                         its own `src/backend/mcp_server/mcp_stdio_server.py`)

For a given research claim it:
  1. asks CiteSeek for supporting/antecedent papers with passage evidence,
  2. writes the claim, the candidate papers, the evidence passages (as
     first-class concepts) and the provenance ("identified by CiteSeek") into
     Von's Vontology using Von's own MCP tools,
  3. reads the claim concept back out of Von (fetch_concept) to prove the
     knowledge persisted,
  4. saves a full timestamped transcript of every MCP call to
     integration/evidence/.

Knowledge model written into the Vontology (all concept-to-concept):

    research claim --supported by-->  scholarly work
    research claim --has evidence-->  evidence passage
    evidence passage --evidence from--> scholarly work
    research claim / scholarly work / evidence passage
                   --identified by--> CiteSeek (instance of citation support tool)

Von's codebase is never modified: the integration happens entirely over the
Model Context Protocol, which is Von's documented surface for external agents
(see Von-main/docs/engineering/workflow_mcp_capability_matrix.md). The only
prerequisites are data/config: VON_MCP_ALLOW_WRITES=1 in Von-main/.env (Von's
own documented opt-in for MCP writes) and the seeded #V#information_object
mid-level type (integration/seed_scholarly_ontology.py).

Usage:
    .venv/bin/python integration/von_citeseek_bridge.py "<research claim>" [--top 3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
VON = REPO / "Von-main"
EVIDENCE_DIR = REPO / "integration" / "evidence"

PARENT_TYPE = "#V#information_object"  # seeded mid-level type (see module docstring)

CITESEEK_SERVER = StdioServerParameters(
    command=str(REPO / ".venv" / "bin" / "citeseek-mcp"),
    cwd=str(REPO),
)
VON_SERVER = StdioServerParameters(
    command=str(VON / ".venv" / "bin" / "python"),
    args=[str(VON / "src" / "backend" / "mcp_server" / "mcp_stdio_server.py")],
    cwd=str(VON),
)

transcript: list[dict] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def call(session: ClientSession, server: str, tool: str, args: dict) -> str:
    """Call one MCP tool, record the exchange, return the text payload."""
    t0 = now()
    result = await session.call_tool(tool, args, read_timeout_seconds=timedelta(seconds=600))
    text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
    transcript.append(
        {"at": t0, "server": server, "tool": tool, "arguments": args, "result": text}
    )
    status = "ERR" if result.isError else "ok"
    print(f"[{t0}] {server}.{tool} -> {status} ({len(text)} chars)", file=sys.stderr)
    if result.isError:
        raise RuntimeError(f"{server}.{tool} failed: {text[:500]}")
    return text


def parse_candidates(markdown: str) -> list[dict]:
    """Parse citeseek-mcp's find_supporting_papers markdown into records."""
    cands: list[dict] = []
    cur: dict | None = None
    node = re.search(r"\(node `([^`]+)`, session `([^`]+)`\)", markdown)
    for line in markdown.splitlines():
        m = re.match(r"^(\d+)\. \*\*(.+?)\*\* \((\d{4}|\?)\)(.*)", line.strip())
        if m:
            cur = {
                "rank": int(m.group(1)),
                "title": m.group(2),
                "year": None if m.group(3) == "?" else int(m.group(3)),
                "confidence": None,
                "verdict": None,
                "ref": None,
                "url": None,
                "rationale": None,
                "quotes": [],
            }
            conf = re.search(r"confidence \*\*([\d.]+)\*\* \((\w+)\)", m.group(4))
            if conf:
                cur["confidence"] = float(conf.group(1))
                cur["verdict"] = conf.group(2)
            cands.append(cur)
            continue
        if cur is None:
            continue
        s = line.strip()
        m = re.match(r"^ref: `([^`]+)` \| paper_id: \d+ \| (.*?)\s*$", s)
        if m:
            cur["ref"] = m.group(1)
            cur["url"] = None if m.group(2) == "no url" else m.group(2)
        elif s.startswith("> "):
            cur["quotes"].append(s[2:].strip())
        elif s and cur["ref"] is not None and cur["rationale"] is None and not s.startswith("ref:"):
            cur["rationale"] = s
    return [
        {"node_id": node.group(1) if node else None,
         "session_id": node.group(2) if node else None,
         **c}
        for c in cands
    ]


def created_concept_id(payload: str) -> str | None:
    """Pull the created concept_id out of a create_concepts response."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    for r in data.get("results", []):
        cid = (r.get("concept") or {}).get("concept_id")
        if r.get("success") and isinstance(cid, str) and cid.startswith("#V#"):
            return cid
        cid = (r.get("error_details") or {}).get("existing_concept_id")
        if isinstance(cid, str) and cid.startswith("#V#"):
            return cid
    return None


async def ensure_concept(von: ClientSession, name: str, kind: str, parent: str,
                         description: str = "") -> str:
    """Create a concept through Von's MCP, or resolve it if it already exists."""
    res = await call(von, "von", "create_concepts", {
        "parent_id": parent,
        "concepts": [{"name": name, "kind": kind, "description": description}],
    })
    cid = created_concept_id(res)
    if cid:
        return cid
    res = await call(von, "von", "resolve_concept_by_name", {"name": name})
    try:
        cid = json.loads(res).get("resolved_concept_id")
    except (ValueError, TypeError):
        cid = None
    if not cid:
        raise RuntimeError(f"could not create or resolve concept {name!r}: {res[:300]}")
    return cid


async def relate(von: ClientSession, source: str, predicate: str, target: str) -> None:
    res = await call(von, "von", "add_relationship",
                     {"source_id": source, "predicate": predicate, "target": target})
    try:
        ok = json.loads(res).get("success", False)
    except (ValueError, TypeError):
        ok = False
    if not ok:
        raise RuntimeError(f"add_relationship {source} -{predicate}-> {target} failed: {res[:300]}")


async def run(claim: str, top: int) -> None:
    started = now()

    # ---- 1. CiteSeek: find supporting papers ------------------------------
    async with stdio_client(CITESEEK_SERVER) as (r, w):
        async with ClientSession(r, w) as cs:
            await cs.initialize()
            tools = [t.name for t in (await cs.list_tools()).tools]
            print(f"citeseek tools: {tools}", file=sys.stderr)
            md = await call(cs, "citeseek", "find_supporting_papers", {"claim": claim})
    candidates = parse_candidates(md)[:top]
    if not candidates:
        print("CiteSeek returned no candidates; aborting.", file=sys.stderr)
        print(md, file=sys.stderr)
        return
    print(f"parsed {len(candidates)} candidates", file=sys.stderr)

    # ---- 2. Von: ingest claim + papers + evidence + provenance ------------
    async with stdio_client(VON_SERVER) as (r, w):
        async with ClientSession(r, w) as von:
            await von.initialize()
            von_tools = (await von.list_tools()).tools
            print(f"von exposes {len(von_tools)} tools", file=sys.stderr)

            t_claim = await ensure_concept(
                von, "research claim", "type", PARENT_TYPE,
                "A claim selected from a research text, for citation support.")
            t_work = await ensure_concept(
                von, "scholarly work", "type", PARENT_TYPE,
                "A paper or other scholarly publication.")
            t_evidence = await ensure_concept(
                von, "evidence passage", "type", PARENT_TYPE,
                "A verbatim passage from a scholarly work, quoted as evidence "
                "that the work supports or anticipates a research claim.")
            t_tool = await ensure_concept(
                von, "citation support tool", "type", PARENT_TYPE,
                "Software that finds candidate antecedent papers for claims.")

            preds = {}
            for pname, pdesc in [
                ("supported by", "claim is plausibly supported/anticipated by a scholarly work"),
                ("has evidence", "claim is linked to an evidence passage"),
                ("evidence from", "evidence passage was quoted from a scholarly work"),
                ("identified by", "provenance: which tool produced this knowledge"),
            ]:
                preds[pname] = await ensure_concept(von, pname, "predicate", PARENT_TYPE, pdesc)

            citeseek_id = await ensure_concept(
                von, "CiteSeek", "instance", t_tool,
                "CiteSeek citation-evidence workbench (COMPSCI 792 project), "
                "queried over MCP by integration/von_citeseek_bridge.py.")

            claim_id = await ensure_concept(
                von, claim[:80], "instance", t_claim, f"Full claim text: {claim}")
            await relate(von, claim_id, preds["identified by"], citeseek_id)

            for c in candidates:
                paper_desc = (
                    f"{c['title']} ({c['year']}). CiteSeek rank {c['rank']}, "
                    f"ref {c['ref']}, url {c['url'] or 'n/a'}."
                )
                paper_id = await ensure_concept(
                    von, c["title"][:120], "instance", t_work, paper_desc)
                await relate(von, claim_id, preds["supported by"], paper_id)
                await relate(von, paper_id, preds["identified by"], citeseek_id)

                if c["quotes"] or c["confidence"] is not None:
                    ev_desc_parts = []
                    if c["confidence"] is not None:
                        ev_desc_parts.append(
                            f"CiteSeek confidence {c['confidence']:.2f} ({c['verdict']}).")
                    if c["rationale"]:
                        ev_desc_parts.append(f"Rationale: {c['rationale']}")
                    for q in c["quotes"][:1]:
                        ev_desc_parts.append(f"Quote: “{q}”")
                    ev_id = await ensure_concept(
                        von,
                        f"evidence for claim in: {c['title'][:80]}",
                        "instance", t_evidence, " ".join(ev_desc_parts))
                    await relate(von, claim_id, preds["has evidence"], ev_id)
                    await relate(von, ev_id, preds["evidence from"], paper_id)
                    await relate(von, ev_id, preds["identified by"], citeseek_id)

            # ---- 3. read back to prove persistence ------------------------
            readback = await call(von, "von", "fetch_concept", {
                "concept_id": claim_id,
                "include_relations_arg1": True,
                "include_text_relations_arg1": "snippets",
            })

    # ---- 4. evidence file --------------------------------------------------
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.replace(":", "").replace("-", "")
    out = EVIDENCE_DIR / f"run_{stamp}.md"
    lines = [
        "# CiteSeek -> Von integration run",
        "",
        f"- started: {started}",
        f"- finished: {now()}",
        f"- claim: {claim}",
        f"- claim concept in Von: `{claim_id}`",
        f"- candidates ingested: {len(candidates)}",
        f"- Von launched unmodified via: `{VON_SERVER.command} {' '.join(VON_SERVER.args)}`",
        "",
        "## Candidates (parsed from citeseek-mcp)",
        "```json",
        json.dumps(candidates, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Von read-back of the claim concept (fetch_concept)",
        "```json",
        readback,
        "```",
        "",
        "## Full MCP transcript",
    ]
    for i, t in enumerate(transcript, 1):
        lines += [
            f"### {i}. [{t['at']}] {t['server']}.{t['tool']}",
            "```json",
            json.dumps(t["arguments"], indent=2, ensure_ascii=False)[:2000],
            "```",
            "result:",
            "```",
            t["result"][:3000],
            "```",
            "",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nEvidence written to {out}")
    print(f"Claim concept in Von: {claim_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("claim")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    asyncio.run(run(args.claim, args.top))


if __name__ == "__main__":
    main()
