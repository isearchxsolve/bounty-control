#!/usr/bin/env python3
"""Fix F11: Integrate census writing into discovery loop."""
with open('D:/anonym/scripts/actions_dispatch.py') as f:
    content = f.read()

old = '''        summary = {"at": utcnow(), "mode": "LIVE" if live else "READ_ONLY", "counts": dict(counts),
                   "qualified_fresh": fresh_count, "qualified_unique": len(candidates), "dispatched": dispatched,
                   "pending_hydration": con.execute("SELECT count(*) FROM pending WHERE status='pending'").fetchone()[0]}
        with (folder / "receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\\n")
        print(json.dumps(summary), flush=True)
        return summary'''

new = '''        summary = {"at": utcnow(), "mode": "LIVE" if live else "READ_ONLY", "counts": dict(counts),
                   "qualified_fresh": fresh_count, "qualified_unique": len(candidates), "dispatched": dispatched,
                   "pending_hydration": con.execute("SELECT count(*) FROM pending WHERE status='pending'").fetchone()[0]}
        with (folder / "receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary) + "\\n")
        print(json.dumps(summary), flush=True)

        # F11: Refusal census - write census file with refusal counts by reason
        census = {
            "at": summary["at"],
            "mode": summary["mode"],
            "refusals": {k: v for k, v in counts.items() if k.startswith("admission_changed.") or k.startswith("CURRENT_") or k in ("QUERY_EXCLUDED_ASSIGNED", "QUERY_EXCLUDED_EXPERIMENT", "QUERY_EXCLUDED_VIDEO_DEMO", "QUERY_EXCLUDED_NOT_A_DEFECT")},
            "qualified": counts.get("qualified", 0),
            "dispatched": len(dispatched),
        }
        census_path = folder / "census.jsonl"
        with census_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(census) + "\\n")
        return summary'''

count = content.count(old)
content = content.replace(old, new)

with open('D:/anonym/scripts/actions_dispatch.py', 'w') as f:
    f.write(content)
print(f"Replaced {count} occurrence(s) of summary block")
print("F11 census integration added")