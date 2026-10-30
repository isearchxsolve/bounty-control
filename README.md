# bounty-control

Control plane for a bounty delivery pipeline: discover funded issues, decide admission,
prepare a patch, publish a pull request, and reconcile what happened to it afterwards.

This repository is the CI home of the pipeline. The engine is deliberately small and
dependency-free (Python standard library only) so that every job starts in seconds.

## What runs here

| workflow | schedule | purpose |
| --- | --- | --- |
| `bounty-discovery.yml` | every 15 min | poll funding platforms, admit only issues that pass the gates, dispatch preparation |
| `discovery-heartbeat.yml` | hourly | prove discovery is alive and log what it saw |
| `bounty-hydration.yml` | schedule | refresh metadata for admitted candidates |
| `engine2.yml` | schedule | prepare the patch for one admitted candidate |
| `actions-contracts.yml` | on push / PR | 432 contract tests pinning the behaviour below |

## Design rules the tests pin

1. **Admission before effort.** An issue is admitted only when funding is real, the repository
   accepts outside contributions, and the ask matches a class we can actually deliver.
2. **Receipts, not claims.** Every delivery records the exact artifact it produced. A send that
   cannot be opened afterwards is reported as not done.
3. **Claims are explicit.** A bounty platform pays on a claim command from a trusted bot, never
   on a merge alone. `claim_line()` emits `/claim #<n>` only when the thread really carries one.
4. **Incident classes get a test.** Every checkout break, every mis-sent proposal and every silent
   failure is followed by a regression test named after the incident, not a comment.

## Running the suite

```bash
python -m unittest discover -s scripts -p "test_*.py"
```

Individual modules are runnable directly, which is how CI invokes them:

```bash
python scripts/test_claim_command.py
```

## Status

Honest current state lives in `docs/`:

- `FUNNEL-YIELD-FORENSIC-2026-10-30.md` - measured yield, closure timing, and the payment mechanism
- `FUNNEL-REPAIR-PLAN-2026-10-30.md` - repair lanes R1-R11 with acceptance criteria
- `FUNNEL-TODO-2026-10-30.md` - the open list, including what is blocked on a human
