#!/usr/bin/env python3
"""
citation_gap.py — Find important references you might be missing.

Given a .bib file and a set of seed papers (by DOI, arXiv ID, or S2 paper ID),
this tool:
  1. Fetches the reference lists of each seed paper from Semantic Scholar
  2. Ranks papers by how many seed papers cite them (citation overlap)
  3. Diffs the result against your .bib file
  4. Outputs a ranked list of "probably missing" references

Usage:
    python citation_gap.py refs.bib \
        --seeds "2106.09685" "1706.03762" "2005.14165" \
        --top 30

Seed papers can be specified as:
    - arXiv IDs:  2106.09685
    - DOIs:       10.1038/s41586-021-03819-2
    - S2 IDs:     649def34f8be52c8b66281af98ae884c09aef38b

Optional: pass --llm-filter to use Claude to judge relevance of candidates
against your paper's topic (requires ANTHROPIC_API_KEY env var).

Dependencies:
    pip install bibtexparser requests rich

Optional:
    pip install anthropic   (for --llm-filter)
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import bibtexparser
import requests
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

# Rich output goes to stderr so you can pipe stdout cleanly:
#   python citation_gap.py refs.bib --seeds ... > missing.txt
console = Console(stderr=True)

# ─── Semantic Scholar API ────────────────────────────────────────────────────

S2_API = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "externalIds,title,authors,year,citationCount,url"
S2_REF_FIELDS = "externalIds,title,authors,year,citationCount,url"

# Respect rate limits: unauthenticated public API is shared among all users.
# Be conservative — S2 will 429 aggressively otherwise.
REQUEST_DELAY = 1.0  # seconds between requests
MAX_RETRIES = 5


def s2_headers(api_key: Optional[str] = None) -> dict:
    h = {"Accept": "application/json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


def s2_get(url: str, params: dict, api_key: Optional[str] = None) -> requests.Response:
    """GET with retry + exponential backoff on 429 (rate limit)."""
    for attempt in range(MAX_RETRIES):
        resp = requests.get(url, headers=s2_headers(api_key), params=params)
        if resp.status_code == 429:
            # Respect Retry-After header if present, else exponential backoff
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                wait = float(retry_after)
            else:
                wait = REQUEST_DELAY * (2 ** attempt)
            console.print(
                f"  [yellow]Rate limited (429), waiting {wait:.1f}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})...[/yellow]"
            )
            time.sleep(wait)
            continue
        return resp
    # Final attempt — let it raise if still failing
    return requests.get(url, headers=s2_headers(api_key), params=params)


def resolve_paper_id(identifier: str, api_key: Optional[str] = None) -> dict:
    """Resolve a DOI, arXiv ID, or S2 ID to a Semantic Scholar paper object."""
    # Heuristic to determine ID type
    if "/" in identifier and not identifier.startswith("http"):
        # Likely a DOI
        query_id = f"DOI:{identifier}"
    elif re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", identifier):
        # arXiv ID (new format)
        query_id = f"ArXiv:{identifier}"
    elif re.match(r"^[a-f0-9]{40}$", identifier):
        # S2 paper ID (SHA hash)
        query_id = identifier
    else:
        # Try as-is (could be old arXiv like hep-th/9905111)
        if re.match(r"^[a-z-]+/\d+$", identifier):
            query_id = f"ArXiv:{identifier}"
        else:
            query_id = identifier

    url = f"{S2_API}/paper/{query_id}"
    resp = s2_get(url, params={"fields": S2_FIELDS}, api_key=api_key)
    if resp.status_code == 404:
        console.print(f"[red]Paper not found:[/red] {identifier}")
        return None
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return resp.json()


def get_references(paper_id: str, api_key: Optional[str] = None) -> list[dict]:
    """Get all references of a paper via pagination."""
    refs = []
    offset = 0
    limit = 500
    while True:
        url = f"{S2_API}/paper/{paper_id}/references"
        params = {"fields": S2_REF_FIELDS, "offset": offset, "limit": limit}
        resp = s2_get(url, params=params, api_key=api_key)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("data", [])
        for item in batch:
            cited = item.get("citedPaper")
            if cited and cited.get("paperId"):
                refs.append(cited)
        if len(batch) < limit or data.get("next") is None:
            break
        offset += limit
        time.sleep(REQUEST_DELAY)
    return refs


# ─── BibTeX parsing ─────────────────────────────────────────────────────────

def parse_bib(bib_path: str) -> list[dict]:
    """Parse a .bib file and extract identifiers we can match against."""
    path = Path(bib_path)
    if not path.exists():
        console.print(f"[red]File not found:[/red] {bib_path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        raw = f.read()

    # Support both bibtexparser v1 and v2
    try:
        # v2 API
        bib_db = bibtexparser.parse(raw)
        entries = []
        for entry in bib_db.entries:
            info = {
                "key": entry.key,
                "title": entry.fields_dict.get("title", None),
                "doi": entry.fields_dict.get("doi", None),
                "eprint": entry.fields_dict.get("eprint", None),
                "year": entry.fields_dict.get("year", None),
                "author": entry.fields_dict.get("author", None),
            }
            for k, v in info.items():
                if v is not None and hasattr(v, "value"):
                    info[k] = v.value
            entries.append(info)
    except AttributeError:
        # v1 API
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.loads(raw, parser=parser)
        entries = []
        for entry in bib_db.entries:
            entries.append({
                "key": entry.get("ID", ""),
                "title": entry.get("title", None),
                "doi": entry.get("doi", None),
                "eprint": entry.get("eprint", None),
                "year": entry.get("year", None),
                "author": entry.get("author", None),
            })
    return entries


def normalize_title(title: str) -> str:
    """Lowercase, strip braces, punctuation, whitespace for fuzzy matching."""
    t = title.lower()
    t = re.sub(r"[{}\\\$]", "", t)
    t = re.sub(r"[^a-z0-9 ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_bib_fingerprints(entries: list[dict]) -> dict:
    """Build a lookup dict: normalized_title -> bib_key, plus DOI/arXiv sets."""
    fingerprints = {
        "titles": {},
        "dois": set(),
        "arxiv_ids": set(),
    }
    for e in entries:
        if e["title"]:
            nt = normalize_title(e["title"])
            fingerprints["titles"][nt] = e["key"]
        if e["doi"]:
            fingerprints["dois"].add(e["doi"].lower().strip())
        if e["eprint"]:
            # Strip version suffix for matching
            aid = re.sub(r"v\d+$", "", e["eprint"].strip())
            fingerprints["arxiv_ids"].add(aid)
    return fingerprints


def paper_in_bib(paper: dict, fingerprints: dict) -> Optional[str]:
    """Check if an S2 paper is already in the bib. Returns bib key or None."""
    ext = paper.get("externalIds") or {}

    # Match by DOI
    doi = ext.get("DOI")
    if doi and doi.lower().strip() in fingerprints["dois"]:
        return f"doi:{doi}"

    # Match by arXiv ID
    arxiv = ext.get("ArXiv")
    if arxiv:
        aid = re.sub(r"v\d+$", "", arxiv.strip())
        if aid in fingerprints["arxiv_ids"]:
            return f"arxiv:{arxiv}"

    # Match by title (fuzzy)
    title = paper.get("title")
    if title:
        nt = normalize_title(title)
        if nt in fingerprints["titles"]:
            return fingerprints["titles"][nt]

    return None


# ─── LLM relevance filter (optional) ────────────────────────────────────────

def llm_filter_candidates(candidates: list[dict], bib_titles: list[str],
                          seed_titles: list[str]) -> list[dict]:
    """Use Claude to score relevance of candidate papers."""
    try:
        import anthropic
    except ImportError:
        console.print("[yellow]anthropic package not installed, skipping LLM filter[/yellow]")
        return candidates

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[yellow]ANTHROPIC_API_KEY not set, skipping LLM filter[/yellow]")
        return candidates

    client = anthropic.Anthropic(api_key=api_key)

    # Build context about the paper
    bib_context = "\n".join(f"- {t}" for t in bib_titles[:40])
    seed_context = "\n".join(f"- {t}" for t in seed_titles)

    candidate_list = []
    for i, c in enumerate(candidates):
        authors = ", ".join(a["name"] for a in (c.get("authors") or [])[:3])
        candidate_list.append(
            f'{i}. "{c.get("title", "?")}" ({authors}, {c.get("year", "?")})'
            f' [cited by {c["_overlap_count"]}/{c["_total_seeds"]} seeds,'
            f' {c.get("citationCount", 0)} total citations]'
        )
    candidates_str = "\n".join(candidate_list)

    prompt = f"""You are helping a researcher check if they are missing important citations.

Here are some representative titles already in their bibliography:
{bib_context}

Their seed/anchor papers are:
{seed_context}

Below are candidate papers that appear frequently in the seed papers' reference lists 
but are NOT in the researcher's bibliography. For each candidate, judge whether it is 
likely an important missing citation (score 1-5, where 5 = almost certainly should be cited,
1 = probably not relevant to this specific line of work).

Candidates:
{candidates_str}

Respond with ONLY a JSON array of objects: [{{"index": 0, "score": 4, "reason": "..."}}, ...]
No other text."""

    with console.status("[bold cyan]Running LLM relevance filter..."):
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    text = resp.content[0].text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        scores = json.loads(text)
    except json.JSONDecodeError:
        console.print("[yellow]Could not parse LLM response, skipping filter[/yellow]")
        return candidates

    score_map = {s["index"]: s for s in scores if "index" in s}
    for i, c in enumerate(candidates):
        if i in score_map:
            c["_llm_score"] = score_map[i].get("score", 3)
            c["_llm_reason"] = score_map[i].get("reason", "")
        else:
            c["_llm_score"] = 3  # neutral default

    # Re-sort: primary by LLM score desc, secondary by overlap count desc
    candidates.sort(key=lambda c: (c.get("_llm_score", 3), c["_overlap_count"]), reverse=True)
    return candidates


# ─── Main logic ──────────────────────────────────────────────────────────────

def run(bib_path: str, seed_ids: list[str], top_n: int = 30,
        use_llm: bool = False, s2_api_key: Optional[str] = None):

    # 1. Parse .bib
    console.rule("[bold]1. Parsing bibliography")
    bib_entries = parse_bib(bib_path)
    fingerprints = build_bib_fingerprints(bib_entries)
    bib_titles = [e["title"] for e in bib_entries if e["title"]]
    console.print(f"Found [green]{len(bib_entries)}[/green] entries in {bib_path}")

    # 2. Resolve seed papers
    console.rule("[bold]2. Resolving seed papers")
    seeds = []
    for sid in seed_ids:
        paper = resolve_paper_id(sid, s2_api_key)
        if paper:
            seeds.append(paper)
            authors = ", ".join(a["name"] for a in (paper.get("authors") or [])[:3])
            console.print(
                f"  [green]✓[/green] {paper.get('title', '?')} "
                f"({authors}, {paper.get('year', '?')})"
            )

    if not seeds:
        console.print("[red]No seed papers could be resolved. Exiting.[/red]")
        sys.exit(1)

    # 3. Fetch references for each seed
    console.rule("[bold]3. Fetching reference lists")
    seed_refs: dict[str, list[dict]] = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for s in seeds:
            pid = s["paperId"]
            short_title = (s.get("title") or "?")[:60]
            task = progress.add_task(f"Fetching refs: {short_title}...", total=None)
            refs = get_references(pid, s2_api_key)
            seed_refs[pid] = refs
            progress.update(task, description=f"[green]✓[/green] {short_title} → {len(refs)} refs")
            progress.stop_task(task)
            time.sleep(REQUEST_DELAY)

    # 4. Compute overlap: count how many seeds cite each paper
    console.rule("[bold]4. Computing citation overlap")
    # paper_id -> {paper_data, citing_seeds: set}
    ref_registry: dict[str, dict] = {}
    for seed_pid, refs in seed_refs.items():
        for ref in refs:
            rid = ref["paperId"]
            if rid not in ref_registry:
                ref_registry[rid] = {"paper": ref, "citing_seeds": set()}
            ref_registry[rid]["citing_seeds"].add(seed_pid)

    total_seeds = len(seeds)
    console.print(f"Total unique references across all seeds: [green]{len(ref_registry)}[/green]")

    # 5. Filter out papers already in .bib, rank by overlap
    console.rule("[bold]5. Diffing against your bibliography")
    already_cited = 0
    candidates = []
    for rid, info in ref_registry.items():
        paper = info["paper"]
        overlap = len(info["citing_seeds"])
        match = paper_in_bib(paper, fingerprints)
        if match:
            already_cited += 1
            continue
        paper["_overlap_count"] = overlap
        paper["_total_seeds"] = total_seeds
        candidates.append(paper)

    # Sort by overlap desc, then citation count desc
    candidates.sort(key=lambda p: (p["_overlap_count"], p.get("citationCount", 0)), reverse=True)
    candidates = candidates[:top_n]

    console.print(
        f"Matched [green]{already_cited}[/green] references already in your .bib, "
        f"[yellow]{len(ref_registry) - already_cited}[/yellow] not found"
    )

    # 6. Optional LLM filter
    if use_llm and candidates:
        console.rule("[bold]6. LLM relevance scoring")
        seed_titles = [s.get("title", "?") for s in seeds]
        candidates = llm_filter_candidates(candidates, bib_titles, seed_titles)

    # 7. Display results
    console.rule("[bold green]Results: potentially missing references")
    if not candidates:
        console.print("[green]No missing references found — you seem well covered![/green]")
        return

    table = Table(
        box=box.ROUNDED,
        show_lines=True,
        title=f"Top {min(top_n, len(candidates))} potentially missing references",
        title_style="bold",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Overlap", justify="center", width=8)
    table.add_column("Title", min_width=30, max_width=60)
    table.add_column("Authors", max_width=25)
    table.add_column("Year", justify="center", width=5)
    table.add_column("Cites", justify="right", width=6)
    if use_llm:
        table.add_column("LLM", justify="center", width=4)
        table.add_column("Reason", max_width=30)
    table.add_column("IDs", max_width=25)

    for i, c in enumerate(candidates, 1):
        authors = ", ".join(a["name"] for a in (c.get("authors") or [])[:2])
        if len(c.get("authors") or []) > 2:
            authors += " et al."

        ext = c.get("externalIds") or {}
        ids = []
        if ext.get("ArXiv"):
            ids.append(f"arXiv:{ext['ArXiv']}")
        if ext.get("DOI"):
            ids.append(f"doi:{ext['DOI']}")

        overlap_str = f"[bold]{c['_overlap_count']}[/bold]/{c['_total_seeds']}"

        row = [
            str(i),
            overlap_str,
            c.get("title", "?"),
            authors,
            str(c.get("year", "?")),
            str(c.get("citationCount", "?")),
        ]
        if use_llm:
            score = c.get("_llm_score", "?")
            color = "green" if score >= 4 else "yellow" if score >= 3 else "dim"
            row.append(f"[{color}]{score}/5[/{color}]")
            row.append(c.get("_llm_reason", ""))
        row.append("\n".join(ids) if ids else "—")

        table.add_row(*row)

    console.print(table)

    # Also output a .bib-friendly summary to stdout for piping
    console.rule("[dim]Machine-readable summary (pipe with > missing.txt)")
    for i, c in enumerate(candidates, 1):
        ext = c.get("externalIds") or {}
        arxiv = ext.get("ArXiv", "")
        doi = ext.get("DOI", "")
        authors = ", ".join(a["name"] for a in (c.get("authors") or [])[:3])
        print(
            f"{i}. [{c['_overlap_count']}/{c['_total_seeds']}] "
            f"{c.get('title', '?')} | {authors} ({c.get('year', '?')}) "
            f"| arXiv:{arxiv} doi:{doi} | citations:{c.get('citationCount', '?')}"
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Find important references you might be missing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with arXiv IDs as seeds
  python citation_gap.py my_paper.bib --seeds 2106.09685 1706.03762

  # With DOIs
  python citation_gap.py refs.bib --seeds "10.1038/s41586-021-03819-2" "10.1103/PhysRevLett.69.2863"

  # With LLM relevance filter
  python citation_gap.py refs.bib --seeds 2106.09685 1706.03762 --llm-filter

  # Show more results
  python citation_gap.py refs.bib --seeds 2106.09685 1706.03762 --top 50
        """,
    )
    parser.add_argument("bibfile", help="Path to your .bib file")
    parser.add_argument(
        "--seeds", nargs="+", required=True,
        help="Seed paper identifiers (arXiv IDs, DOIs, or S2 paper IDs)"
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Number of top candidates to show (default: 30)"
    )
    parser.add_argument(
        "--llm-filter", action="store_true",
        help="Use Claude to score relevance of candidates (requires ANTHROPIC_API_KEY)"
    )
    parser.add_argument(
        "--s2-key", default=None,
        help="Semantic Scholar API key (optional, for higher rate limits)"
    )

    args = parser.parse_args()
    run(
        bib_path=args.bibfile,
        seed_ids=args.seeds,
        top_n=args.top,
        use_llm=args.llm_filter,
        s2_api_key=args.s2_key,
    )


if __name__ == "__main__":
    main()
