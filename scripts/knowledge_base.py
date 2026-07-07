#!/usr/bin/env python3
"""knowledge_base.py -- A4 knowledge accumulation library

Extract entities (PERSON/EVENT/DATA/QUOTE) and source URLs from published
articles, persist to output/state/knowledge_base.jsonl, and reduce repeated
research cost for subsequent articles.

CLI subcommands:
  add   <slug> --article <path>  extract entities from article and store
  query <keyword>                search knowledge base for keyword matches
  stats                          output library statistics

Exit code: 0 (pure utility script, always exit 0)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# project root & import claim_extractor
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_KB_PATH = _ROOT / "output" / "state" / "knowledge_base.jsonl"

sys.path.insert(0, str(_ROOT / "script-verifier"))

from claim_extractor import (  # noqa: E402
    extract_person_claims,
    extract_event_claims,
    extract_data_claims,
    extract_quote_claims,
)


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r'https?://[^\s)\]>]{5,300}')


def _extract_urls(text: str) -> list[str]:
    """Extract deduplicated URLs from article body."""
    urls = _URL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        u = u.rstrip('.,;:!?')
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


# ---------------------------------------------------------------------------
# sub-command: add
# ---------------------------------------------------------------------------

def _cmd_add(args: argparse.Namespace) -> None:
    """Extract entities + sources from article, append to knowledge_base.jsonl."""
    article_path = Path(args.article)
    if not article_path.exists():
        print(json.dumps({"error": "file not found: " + args.article}, ensure_ascii=False, indent=2))
        return

    # size guard: reject articles > 10 MB to prevent OOM / unbounded read on
    # CLI-supplied path (WC-EXT-M-003, audit-2026-07-08-041)
    _MAX_ARTICLE_BYTES = 10 * 1024 * 1024
    try:
        file_size = article_path.stat().st_size
    except OSError as exc:
        print(json.dumps({"error": f"cannot stat {args.article}: {exc}"}, ensure_ascii=False, indent=2))
        return
    if file_size > _MAX_ARTICLE_BYTES:
        print(json.dumps({
            "error": f"article too large ({file_size} bytes, max {_MAX_ARTICLE_BYTES})",
            "path": args.article,
        }, ensure_ascii=False, indent=2))
        return

    text = article_path.read_text(encoding="utf-8")

    # extract four entity types
    persons = extract_person_claims(text)
    events = extract_event_claims(text)
    data = extract_data_claims(text)
    quotes = extract_quote_claims(text)

    # deduplicated person names
    person_names = list(dict.fromkeys(c["text"] for c in persons))

    # deduplicated event summaries
    event_texts = list(dict.fromkeys(c["text"] for c in events))

    # deduplicated data claims (value + context snippet)
    data_items: list[dict] = []
    seen_data: set[str] = set()
    for c in data:
        key = c["text"]
        if key not in seen_data:
            seen_data.add(key)
            data_items.append({
                "value": c["text"],
                "context": c.get("context", "")[:80],
                "data_type": c.get("data_type", ""),
            })

    # extract source URLs
    sources = _extract_urls(text)

    # build knowledge base entry
    entry = {
        "slug": args.slug,
        "persons": person_names,
        "events": event_texts,
        "data": data_items,
        "quotes": [c["text"] for c in quotes],
        "sources": sources,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "article_path": str(article_path),
    }

    # ensure output directory exists
    _KB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # append to JSONL with exclusive lock (concurrent-safe)
    with open(_KB_PATH, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # output summary
    summary = {
        "action": "add",
        "slug": args.slug,
        "persons_count": len(person_names),
        "events_count": len(event_texts),
        "data_count": len(data_items),
        "quotes_count": len(quotes),
        "sources_count": len(sources),
        "stored_to": str(_KB_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# sub-command: query
# ---------------------------------------------------------------------------

def _load_kb() -> list[dict]:
    """Load all knowledge base entries from JSONL.

    Acquires LOCK_SH (shared lock) so concurrent readers proceed in parallel
    while a writer holding LOCK_EX blocks us until its append completes.
    Mirrors the locking protocol in _cmd_add to prevent torn-line reads.
    """
    if not _KB_PATH.exists():
        return []
    entries: list[dict] = []
    with open(_KB_PATH, "r", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return entries


def _cmd_query(args: argparse.Namespace) -> None:
    """Search knowledge base for entries matching keyword."""
    keyword = args.keyword.strip()
    if not keyword:
        print(json.dumps({"error": "keyword must not be empty"}, ensure_ascii=False, indent=2))
        return

    entries = _load_kb()
    results: list[dict] = []

    for entry in entries:
        matched_fields: list[str] = []

        # search slug
        if keyword.lower() in entry.get("slug", "").lower():
            matched_fields.append("slug")

        # search persons
        for p in entry.get("persons", []):
            if keyword in p:
                matched_fields.append("persons")
                break

        # search events
        for e in entry.get("events", []):
            if keyword in e:
                matched_fields.append("events")
                break

        # search data (value + context)
        for d in entry.get("data", []):
            val = d if isinstance(d, str) else d.get("value", "") + d.get("context", "")
            if keyword in val:
                matched_fields.append("data")
                break

        # search quotes
        for q in entry.get("quotes", []):
            if keyword in q:
                matched_fields.append("quotes")
                break

        # search sources
        for s in entry.get("sources", []):
            if keyword.lower() in s.lower():
                matched_fields.append("sources")
                break

        if matched_fields:
            results.append({
                "slug": entry.get("slug", ""),
                "matched_fields": matched_fields,
                "date": entry.get("date", ""),
            })

    output = {"keyword": keyword, "results": results, "total": len(results)}
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# sub-command: stats
# ---------------------------------------------------------------------------

def _cmd_stats(_args: argparse.Namespace) -> None:
    """Output knowledge base statistics."""
    entries = _load_kb()

    if not entries:
        print(json.dumps({
            "total_entries": 0,
            "unique_sources": 0,
            "top_persons": [],
            "message": "knowledge base is empty",
        }, ensure_ascii=False, indent=2))
        return

    # unique sources
    all_sources: set[str] = set()
    for entry in entries:
        for s in entry.get("sources", []):
            all_sources.add(s)

    # frequent persons
    person_counter: Counter[str] = Counter()
    for entry in entries:
        for p in entry.get("persons", []):
            person_counter[p] += 1

    top_persons = [
        {"name": name, "count": count}
        for name, count in person_counter.most_common(10)
    ]

    # entity totals
    total_persons = sum(len(e.get("persons", [])) for e in entries)
    total_events = sum(len(e.get("events", [])) for e in entries)
    total_data = sum(len(e.get("data", [])) for e in entries)
    total_quotes = sum(len(e.get("quotes", [])) for e in entries)

    stats = {
        "total_entries": len(entries),
        "unique_sources": len(all_sources),
        "entity_totals": {
            "persons": total_persons,
            "events": total_events,
            "data": total_data,
            "quotes": total_quotes,
        },
        "top_persons": top_persons,
        "date_range": {
            "earliest": min((e.get("date", "") for e in entries), default=""),
            "latest": max((e.get("date", "") for e in entries), default=""),
        },
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="A4 knowledge base -- extract entities and sources, persist and search, reduce repeated research cost",
    )
    subparsers = parser.add_subparsers(dest="command", help="sub-commands")

    # add
    p_add = subparsers.add_parser("add", help="extract entities from article and store")
    p_add.add_argument("slug", help="article identifier (e.g. gig-economy-2025)")
    p_add.add_argument("--article", required=True, help="path to article file")

    # query
    p_query = subparsers.add_parser("query", help="search knowledge base for keyword")
    p_query.add_argument("keyword", help="search keyword")

    # stats
    subparsers.add_parser("stats", help="output knowledge base statistics")

    args = parser.parse_args()

    if args.command == "add":
        _cmd_add(args)
    elif args.command == "query":
        _cmd_query(args)
    elif args.command == "stats":
        _cmd_stats(args)
    else:
        parser.print_help()

    sys.exit(0)


if __name__ == "__main__":
    main()
