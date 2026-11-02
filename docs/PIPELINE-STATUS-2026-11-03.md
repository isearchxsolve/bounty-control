# Pipeline status — 2026-11-03

Status snapshot. The live acceptance campaign is **in flight** as this is written;
its result is not yet known and is not claimed here.

## Correction to the prior record

Earlier statements in this thread said no pull request had ever landed from this
pipeline. I then "corrected" that after finding a merged PR, and the correction
was itself wrong in the other direction. Both need settling, because the fact and
the meaning are different things.

**The fact:** `isearchxsolve/oss-hunter-livefire#7` did merge, on
2026-11-02T16:43:05Z.

- Title: `fix: #5 - [LIVE-INTEGRATION r332cf3a31d9b] Correct day-to-second conversion`
- Verified published head: `6a29f8ea5a4f00eac62a15d384c14de01990923b`
- Merge commit: `cd228b06bc11fcbb64d2d3f5699c6bfb6fbf29e4`
- Campaign: `r332cf3a31d9b`

**The meaning: it is a dummy.** The pipeline provisioned issue #5 itself, wrote
the defective `days_to_seconds` function itself, declared the expected failure
itself, fixed it, and merged it into a repository it controls. Every side of that
transaction is the pipeline grading its own homework. It proves the plumbing
connects end to end. It proves nothing about delivering against a stranger's
issue in a stranger's repository.

So the original statement was right in substance and imprecise in wording. The
accurate form: **no real pull request has landed.** One synthetic one has, in the
sandbox target, and it should be counted as a plumbing test rather than a
delivery.

Merged PRs by `isearchxsolve`, all time: **2**, both synthetic.

| PR | Repository | Merged | Nature |
|---|---|---|---|
| #7 | `isearchxsolve/oss-hunter-livefire` | 2026-11-02T16:43:05Z | Dummy: pipeline-authored issue and defect, sandbox target |
| #6 | `isearchxsolve/bounty-proof` | 2026-10-29T15:17:41Z | Fixture repository |

## Shipped this session

Three commits on `main`, each green in CI.

| Commit | What it does |
|---|---|
| `ed9aa29` | Four failure-reading defects |
| `cd7ef9e` | Injection seam; `preflight` driven offline |
| `33222a7` | `store=` seam; `dispatch` driven offline |

### The four defects

1. **A true red proof was rejected for its phrasing** (run `41496156712`). The
   gate required the agent's declared assertion as a literal substring. The agent
   declared `days_to_seconds(1) == 86400`; unittest printed
   `AssertionError: 3600 != 86400`. Base genuinely red, five tests failed, gate
   said no. Now corroborates on distinctive tokens; an invented assertion still
   fails.
2. **A terminal GitHub error named no endpoint** (run `41488848364`). A bare
   `gh: Not Found (HTTP 404)` cannot distinguish a deleted branch from a wrong
   repo, a missing ref, or an absent PR. Terminal errors now carry
   `[endpoint: METHOD path]`.
3. **A provider quota exhaustion looked like a pipeline bug.** The door died on a
   429 while the assertion reported only `Real scout failed`. `admit` now reports
   the retained scout tail.
4. **A commit SHA was accepted as a dispatch ref.** `control_branch` is written
   only by `preflight()`, so the fallback could resolve to a SHA, which the
   dispatch API answers with HTTP 422 `No ref found` — a transport-shaped error
   for a wrong-ref mistake.

### The seams

`LiveRun` now accepts optional `api=`, `command=` and `store=` injections, all
defaulting to the live path. Production behaviour is unchanged.

Measured line coverage of `live_pipeline_integration.py` (692 statements):

| Phase | Before | After |
|---|---:|---:|
| Whole file | 14.3% | **23.0%** |
| `preflight` | 0.0% | **100.0%** |
| `dispatch` | 0.0% | **100.0%** |

`dispatch` matters most: it is where duplicate-publication risk lives. The new
suite pins that a waiting task gets exactly one generation, that a replay creates
none, that a replay which does dispatch again is refused, and that a `FAILED`
record is replaced rather than resumed.

## Verification

- Full master gate: **63/63 suites passed, 0 failed** (local and CI).
- CI on `ed9aa29`: run [41515355188](https://github.com/isearchxsolve/bounty-control/actions/runs/41515355188), success.
- CI on `cd7ef9e`: run [41516032532](https://github.com/isearchxsolve/bounty-control/actions/runs/41516032532), success.
- CI on `33222a7`: run [41517315372](https://github.com/isearchxsolve/bounty-control/actions/runs/41517315372), success.
  Runner log confirms `PASS test_live_dispatch_offline.py` and `63/63 suites passed; 0 failed`.

## In flight — result unknown

**Live acceptance campaign: run [41517665373](https://github.com/isearchxsolve/bounty-control/actions/runs/41517665373)**, dispatched 2026-11-02T20:16:11Z on `33222a7`. Job limit 100 minutes. Status `in_progress` at the time of writing; logs are not published until the run completes.

It exercises `intake → provision → faults → negative_claim → observe_negative →
admit → dispatch → wait → artifact_faults → merge`. Acceptance requires all 20
cases in `REQUIRED_CASES` to be `PASS`; anything less sets
`end_to_end_passed: false` with a named reason.

Also in flight: scheduled `Bounty discovery and reconciliation`, run
[41516582049](https://github.com/isearchxsolve/bounty-control/actions/runs/41516582049)
on `aaf4805`. This is the lane that would show whether the hydration drain
restored in `65e6750` is actually moving the backlog that was stranded on
2026-10-31.

## Open pull requests

20 open by `isearchxsolve`. They are not equivalent:

- **1 potentially real payer target**: `sriahead/aheed-online-store#1382`,
  `Production is down: Neon production project over quota (HTTP 402)`, opened
  2026-11-01.
- **6 arguably real engineering targets**: `fyne-io/fyne#6637`,
  `Tarsnap/kivaloo#402`, `paraloom-labs/paraloom-core#1233` and `#1234`,
  `geekinasuit/obolus#131`, `bl4ckb4ll/blackball#182`.
- **13 junk or non-code**: `muaddibco/RealWorldProblems` experiment rows,
  `NEXAITECHAU/gh-disc-*` recursive mirror repos, a `ClawPowers-Skills` digest.

## What remains

**Driver phases still at 0.0%** (535 of 692 statements missed):

| Phase | Stmts | Blocker |
|---|---:|---|
| `admit` | 64 | needs model gateway + durable queue + provider router fake |
| `intake` | 62 | needs discovery/hydration workflow artifacts on disk |
| `observe` | 47 | needs Actions run + jobs + reconcile fake |
| `provision` | 36 | needs git tree/commit/ref writes |
| `faults` | 33 (+10 sub-cases) | needs a real CAS-conflicting store |
| `artifact_faults` | 33 | needs a corruptible release bundle |
| `merge` | 27 | needs PR merge + reconciliation |
| `negative_claim` | 27 | needs a workflow dispatch fake |
| `cleanup`, `run`, `main`, `source_rejections`, `observe_negative`, `recent_runs`, `audit`, `wait` | 148 | mostly orchestration |

`admit` and `observe` are the two worth the effort. The rest are orchestration or
need a live boundary to mean anything.

**Acceptance work never executed:**

- MC-001 sandbox acceptance case: never run.
- The live fault catalogue (BOOT, SRC, MODEL, NET, STORE, RACE, LEASE, EXEC,
  PATCH, PUB, CI, REVIEW, REC, SEC): planned, not executed.
- OOM/disk-full injection, arbitrary provider-wide outages, cross-account review
  and payment settlement: outside exercised coverage.

**The gap that matters:** one dummy merge is not a working business. The pipeline
has delivered once, into a repository it controls, against an issue and a defect
it wrote itself. Whether it can deliver into a stranger's repository against a
stranger's issue remains unproven, and the `aheed-online-store#1382` PR is the
closest thing to a test of that.

## Standing caveat

A green contract suite is not evidence of live delivery. 63/63 proves the gates
and the ledger behave correctly in isolation. It does not prove a PR lands, and
this document does not claim it does.
