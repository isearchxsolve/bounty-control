# Repair receipt — four failure-reading defects and the live driver seam

Date: 2026-11-03
Revisions: `ed9aa29`, `cd7ef9e` (both on `main`, both green in CI)

## Scope

Two commits. The first repairs four defects that each made a real failure
unreadable or rejected a true proof. The second opens an injection seam in the
live driver and proves it on one phase.

Neither commit changes the live acceptance verdict. `end_to_end_passed` remains
`false` because the selected original issue is access-blocked, and the driver's
delivery phases remain unexercised offline. This receipt records what was fixed,
what was measured, and what is still open. It does not claim delivery coverage.

## Defect 1 — a true red proof was rejected for its phrasing

Source: run `41496156712`.

The red-proof gate in `actions_release.regression_proof()` required the agent's
declared assertion to appear in the failing run's output as a literal substring.
The agent declared:

```
expected_failure: "days_to_seconds(1) == 86400"
```

unittest printed:

```
AssertionError: 3600 != 86400
```

The base genuinely failed, five tests were red, and the gate rejected a correct
red-to-green proof because the sentence the agent wrote was the source
expression rather than the assertion message.

A gate that demands one phrasing of a true statement rejects true statements,
which is worse than not checking at all.

**Change.** `failure_corroborated(expected, output)` replaces the substring test.
The claim is corroborated when either the literal text appears, or every
distinctive token of it appears in the run's own output. Distinctive tokens are
identifiers and numbers of two or more digits; a claim must carry at least two
of them, so a single shared word corroborates nothing.

**What it still refuses.** An invented assertion fails, because a token the run
never printed is not corroborated. A partially matching claim fails, because
every distinctive token must appear. An empty or punctuation-only claim fails.

**Limit.** This checks corroboration of a *declared* failure against observed
output. It does not establish that the declared failure is the right defect to
have fixed; that judgement stays with the agent and the reviewer.

## Defect 2 — a terminal GitHub error named no endpoint

Source: run `41488848364`.

Publish failed with a bare `gh: Not Found (HTTP 404)`. That message cannot
distinguish a deleted branch from a wrong repository, a missing ref, or an
absent pull request — four different repairs, one indistinguishable symptom.

**Change.** Terminal `GitHubError` messages now carry the endpoint:
`[endpoint: METHOD path]`. The endpoint is not secret and is the one fact needed
to act on the failure. Throttle handling is unchanged; only the terminal raise
carries the addition.

## Defect 3 — a provider quota exhaustion looked like a pipeline bug

Source: run 2026-11-02, `admit` phase.

The door died on `TokenHarbor router HTTP 429: You've used this period's free
allowance`. The assertion reported only `Real scout failed`, so the one fact
that explained the run — an exhausted provider quota, not a code defect — was
discarded and the failure read as a pipeline fault.

**Change.** When the scout writes no queue row, `admit` now reads the retained
`scout-result.json` and raises with its `tail` (bounded to 900 characters), or
states plainly that no result file was retained and where to look instead.

**Limit.** This improves the failure message. It does not retry, refill, or
route around an exhausted quota.

## Defect 4 — a commit SHA was accepted as a dispatch ref

Source: negative-case run 2026-11-02.

`control_branch` is written only by `preflight()`. The `negative_claim` phase
does not call `preflight()`, so its fallback could resolve to a commit SHA. The
dispatch API answers a SHA with HTTP 422 `No ref found`, which reads as a
transport fault rather than the wrong-ref mistake it is.

**Change.** `negative_claim` now asserts the resolved ref is a non-empty string
that is not a 40-character lowercase hex SHA, and names the problem in the
failure message.

## The seam — `LiveRun` injection

`live_pipeline_integration.py` had no seam. Every phase called `GitHub()`
directly and shelled out through `subprocess`. The only way to execute a phase
was against a real repository.

`LiveRun.__init__` now accepts optional `api=` and `command=` injections. Both
default to the existing live path, so a real campaign is unchanged.

**Measured effect on `live_pipeline_integration.py`** (689 statements):

| Measure | Before | After |
|---|---:|---:|
| Line coverage | 14.3% | **17.3%** |
| Statements missed | 588 | 570 |
| `LiveRun.preflight` | 0.0% | **100.0%** |

`test_live_phase_offline.py` drives the real `preflight()` body offline against
a fake endpoint table and a fake command runner. Cases: healthy sandbox;
archived sandbox; non-sandbox target; target owned by another account; inactive
delivery workflow; collaborator-only PR policy with no push permission (the
recorded `fiztoz/uptime-phoenix#198` blocker); deployment change mid-campaign;
local head read through the command seam; and two guards that the seam defaults
to the live path and that a journal from another target is refused.

The fake raises on any endpoint it does not model, so a phase that invents a
request fails loudly instead of passing quietly.

## What is still not covered

Every remaining driver phase is at 0.0% line coverage:

| Phase | Statements | Coverage |
|---|---:|---:|
| `admit` | 64 | 0.0% |
| `intake` | 62 | 0.0% |
| `observe` | 47 | 0.0% |
| `provision` | 36 | 0.0% |
| `artifact_faults` | 33 | 0.0% |
| `faults` (10 sub-cases) | 33 | 0.0% |
| `dispatch` | 32 | 0.0% |
| `cleanup` | 28 | 0.0% |
| `merge` | 27 | 0.0% |
| `negative_claim` | 27 | 0.0% |
| `run` | 26 | 0.0% |
| `main` | 23 | 0.0% |
| `source_rejections` | 19 | 0.0% |
| `observe_negative` | 18 | 0.0% |
| `recent_runs` | 8 | 0.0% |
| `audit`, `wait`, `ScopedStore.*` | 15 | 0.0% |

The seam makes these reachable. It does not make them tested. Each needs its own
fake, and the fake has to model the endpoints that phase actually calls — the
`admit` phase in particular reaches a model gateway, a durable queue and a
provider router, so its fake is substantially larger than `preflight`'s.

## Verification

- `scripts/test_live_defect_regressions.py` — 9 tests, pins all four defects at
  the gate level. Was untracked and absent from the allowlist, so CI would never
  have run it; now listed.
- `scripts/test_live_phase_offline.py` — 12 tests, drives `preflight` offline.
- Full master gate: **62/62 suites passed, 0 failed** (local and CI).
- Contract CI on `ed9aa29`: run
  [41515355188](https://github.com/isearchxsolve/bounty-control/actions/runs/41515355188), success.
- Contract CI on `cd7ef9e`: run
  [41516032532](https://github.com/isearchxsolve/bounty-control/actions/runs/41516032532), success.
  Runner log confirms `PASS test_live_phase_offline.py` and `62/62 suites passed; 0 failed`.

## Standing caveat

A green contract suite is not evidence of live delivery. The four defects above
were all cases where the pipeline *was* working or *had* produced a true result
and the reporting layer obscured it. Fixing the reporting does not produce a
merged pull request, and no pull request has yet landed from this pipeline.

The next phase worth taking is `dispatch`: 32 statements, and it is where the
duplicate-publication risk lives.
