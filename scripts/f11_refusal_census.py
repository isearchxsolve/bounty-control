"""F11 Refusal Census - builds the 60-issue hand-labeling sample for F9.

Scans discovery runs and the pending queue to:
1. Catalog all refusal reasons with counts (the census)
2. Extract a diverse 60-issue sample for hand-labeling into:
   - needs_code_change
   - not_code_change_external  
   - not_code_change_process
   - unclear
3. Output a labeling-ready CSV and JSON sample

Usage:
    python f11_refusal_census.py --census        # Print refusal statistics
    python f11_refusal_census.py --sample 60     # Produce labeling sample
    python f11_refusal_census.py --both          # Both
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRATCH_ROOT = Path(os.environ.get("F11_SCRATCH_ROOT", "D:/anonym/scratch"))
DISCOVERY_DB = SCRATCH_ROOT / "actions-discovery" / "discovery.sqlite3"


def load_discovery_db(db_path: Path = DISCOVERY_DB) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"WARNING: discovery db not found at {db_path}", file=sys.stderr)
        return None
    return sqlite3.connect(str(db_path))


def census_refusals(con: sqlite3.Connection) -> dict:
    """Catalog refusal reasons from the pending queue statuses."""
    if con is None:
        return {}
    statuses = con.execute(
        "SELECT status, COUNT(*) FROM pending GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    return {status: count for status, count in statuses}


def census_labels(con: sqlite3.Connection) -> Counter:
    """Count label frequency across pending issues."""
    counter = Counter()
    rows = con.execute("SELECT payload FROM pending").fetchall()
    for (payload,) in rows:
        try:
            item = json.loads(payload)
            for lbl in item.get("labels", []):
                name = lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
                counter[name] += 1
        except Exception:
            pass
    return counter


def extract_sample(con: sqlite3.Connection, n: int = 60) -> list[dict]:
    """Extract a diverse n-issue sample for hand-labeling.

    Stratifies by:
    - status (pending, checked, rejected_repository_intent)
    - label categories (bug, bounty, enhancement, external, no labels, etc.)
    - whether issue has code references (file paths in body)
    """
    if con is None:
        return []

    rows = con.execute("SELECT payload FROM pending").fetchall()
    issues = []
    for (payload,) in rows:
        try:
            item = json.loads(payload)
        except Exception:
            continue

        labels = []
        for lbl in item.get("labels", []):
            if isinstance(lbl, dict):
                labels.append(lbl.get("name", ""))
            elif isinstance(lbl, str):
                labels.append(lbl)

        body = item.get("body", "") or ""
        title = item.get("title", "") or ""

        import re
        # Heuristic: does the body contain file path references?
        has_code_ref = bool(
            re.search(r"\.(py|js|ts|go|rs|java|cpp|c|h|rb|php|cs|swift|kt)\b", body)
            or re.search(r"(src/|lib/|pkg/|cmd/|app/)", body)
        )

        issues.append({
            "task_id": item.get("url", "").split("/")[-1] or str(item.get("number", "")),
            "repo": item.get("repository_url", "").replace("https://api.github.com/repos/", ""),
            "number": item.get("number"),
            "title": title,
            "body_preview": body[:200],
            "labels": labels,
            "has_code_reference": has_code_ref,
            "state": item.get("state", "unknown"),
            "created_at": item.get("created_at", ""),
            "html_url": item.get("html_url", ""),
        })

    # Stratified sampling
    def category(iss):
        labels_set = set(l.lower() for l in iss["labels"])
        if "bug" in labels_set:
            return "bug"
        if "bounty" in labels_set or any("$" in l for l in labels_set):
            return "bounty"
        if "enhancement" in labels_set:
            return "enhancement"
        if "external" in labels_set:
            return "external"
        if not labels_set:
            return "no_labels"
        return "other"

    by_category = defaultdict(list)
    for iss in issues:
        by_category[category(iss)].append(iss)

    sample = []
    per_category = max(1, n // max(len(by_category), 1))
    for cat, cat_issues in by_category.items():
        take = min(per_category, len(cat_issues))
        sample.extend(cat_issues[:take])

    if len(sample) < n:
        sampled_ids = {iss["task_id"] for iss in sample}
        remaining = [iss for iss in issues if iss["task_id"] not in sampled_ids]
        sample.extend(remaining[: n - len(sample)])

    return sample[:n]


def write_labeling_csv(sample: list[dict], output_path: Path):
    """Write a CSV ready for hand-labeling."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "task_id", "repo", "number", "title", "labels",
            "has_code_reference", "html_url",
            "HAND_LABEL: needs_code_change / not_code_change_external / not_code_change_process / unclear",
            "HAND_LABEL: one-line justification",
        ])
        for iss in sample:
            writer.writerow([
                iss["task_id"], iss["repo"], iss["number"], iss["title"],
                "; ".join(iss["labels"]),
                iss["has_code_reference"], iss["html_url"],
                "",  # hand-label column
                "",  # justification column
            ])


def write_labeling_json(sample: list[dict], output_path: Path):
    """Write a JSON sample with empty label fields for hand-labeling."""
    labeled = []
    for iss in sample:
        labeled.append({
            **iss,
            "hand_label": None,  # needs_code_change / not_code_change_external / not_code_change_process / unclear
            "hand_label_justification": None,
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(labeled, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="F11 Refusal Census for F9 gate")
    parser.add_argument("--census", action="store_true", help="Print refusal statistics")
    parser.add_argument("--sample", type=int, default=60, help="Produce labeling sample of N issues")
    parser.add_argument("--both", action="store_true", help="Both census and sample")
    parser.add_argument("--output-dir", default="D:/anonym/scripts/f11_sample", help="Output directory")
    args = parser.parse_args()

    con = load_discovery_db()
    do_census = args.census or args.both
    do_sample = args.sample is not None or args.both

    if do_census and con:
        print("=== F11 REFUSAL CENSUS ===\n")
        stats = census_refusals(con)
        print("Pending queue statuses:")
        for status, count in stats.items():
            print(f"  {status}: {count}")
        print()

        labels = census_labels(con)
        print("Top 20 labels:")
        for label, count in labels.most_common(20):
            safe_label = label.encode('ascii', 'replace').decode('ascii')
            print(f"  {safe_label}: {count}")
        print()

    if do_sample and con:
        print(f"=== F11 LABELING SAMPLE ({args.sample} issues) ===\n")
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        sample = extract_sample(con, args.sample)
        print(f"Extracted {len(sample)} issues for hand-labeling\n")

        for iss in sample:
            safe_labels = [l.encode('ascii', 'replace').decode('ascii') for l in iss['labels']]
            safe_title = iss['title'].encode('ascii', 'replace').decode('ascii')
            print(f"  {iss['repo']}#{iss['number']}: labels={safe_labels} | code_ref={iss['has_code_reference']} | {safe_title[:50]}")

        csv_path = out_dir / f"f11_labeling_sample_{args.sample}.csv"
        json_path = out_dir / f"f11_labeling_sample_{args.sample}.json"
        write_labeling_csv(sample, csv_path)
        write_labeling_json(sample, json_path)
        print(f"\nWrote labeling CSV: {csv_path}")
        print(f"Wrote labeling JSON: {json_path}")
        print("\nHand-label each issue with one of:")
        print("  needs_code_change        - issue requests a code change (should be admitted)")
        print("  not_code_change_external - external deliverable/docs/contest (should be refused)")
        print("  not_code_change_process  - process/meta issue (should be refused)")
        print("  unclear                  - cannot determine (fail-open: admit)")

    if con:
        con.close()


if __name__ == "__main__":
    main()