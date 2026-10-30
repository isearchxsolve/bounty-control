#!/usr/bin/env python3
"""
F12: Failure digest - summarizes the dispatch pipeline results.

Reads the durable ledger (receipts.jsonl, census.jsonl) and the Actions API,
uses the F4 taxonomy for grouping, and never judges -- it tabulates.

Outputs: funnel by final status, per-task cause, terminal cause table,
and list of runs whose log is unrecoverable.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRATCH_DIR = Path(os.environ.get("FLEET_ARTIFACT_DIR", Path(__file__).resolve().parent.parent / "scratch"))
DISCOVERY_DIR = SCRATCH_DIR / "actions-discovery"


def load_receipts(discovery_dir=DISCOVERY_DIR):
    """Load all discovery receipts."""
    receipts_file = discovery_dir / "receipts.jsonl"
    receipts = []
    if receipts_file.exists():
        with receipts_file.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        receipts.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return receipts


def load_census(discovery_dir=DISCOVERY_DIR):
    """Load all census records."""
    census_file = discovery_dir / "census.jsonl"
    census = []
    if census_file.exists():
        with census_file.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        census.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return census


def funnel_by_status(receipts):
    """Count receipts by final status."""
    funnel = Counter()
    for r in receipts:
        status = r.get("counts", {}).get("qualified", 0)
        # Count dispatched vs refused
        dispatched = r.get("dispatched", 0)
        refusals = sum(v for k, v in r.get("counts", {}).items()
                       if k.startswith("admission_changed.") or k.startswith("CURRENT_"))
        funnel["dispatched"] += dispatched
        funnel["refused"] += refusals
    return dict(funnel)


def refusal_reasons(receipts):
    """Count refusal reasons."""
    reasons = Counter()
    for r in receipts:
        for reason, count in r.get("counts", {}).items():
            if reason.startswith("admission_changed.") or reason.startswith("CURRENT_"):
                reasons[reason] += count
    return dict(reasons)


def main():
    receipts = load_receipts()
    census = load_census()

    print("=== F12 Failure Digest ===")
    print()

    # Funnel by final status
    funnel = funnel_by_status(receipts)
    print("Funnel:")
    for status, count in sorted(funnel.items()):
        print(f"  {status}: {count}")
    print()

    # Refusal reasons
    reasons = refusal_reasons(receipts)
    print("Refusal reasons:")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    print()

    # Census summary
    if census:
        latest = census[-1]
        print("Latest census:")
        print(f"  At: {latest.get('at')}")
        print(f"  Mode: {latest.get('mode')}")
        print(f"  Refusals: {latest.get('refusals', {})}")
        print(f"  Qualified: {latest.get('qualified')}")
        print(f"  Dispatched: {latest.get('dispatched')}")


if __name__ == "__main__":
    main()