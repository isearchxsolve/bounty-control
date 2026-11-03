# Pipeline master failure test plan

## Purpose and acceptance contract

Exercise discovery → source verification → admission → capacity → dispatch → durable
claim → engineering → release → publication → remote checks → review → reconciliation
→ merge/payment observation, including failure and recovery at their boundaries.

No finite suite proves **all possible failures**. This plan distinguishes executable
regressions from additional sandbox acceptance exercises. Passing the master runner means
the selected regression commands passed; it does not certify production or model quality.
Some historical tests encode older policy; a failure requires investigation against the
current architectural law, not automatically restoring the old policy.

The model chooses, interprets and repairs. Tests check factual evidence, ownership,
transport, deadlines, receipts and observable outcomes. Do not turn a failed judgement
example into a new production keyword rule.

Release invariants:

1. Unknown/unavailable observations never count as evidence of safety or success.
2. Every admitted task carries the same canonical identity and source-bound proof across handoffs.
3. Only the current owner and dispatch generation may work or publish; ambiguity must not cause a duplicate.
4. Failure before reservation produces no dispatch; failure after an external effect preserves evidence for reconciliation.
5. Retry and time budgets are bounded, with an explicit, observable outcome at exhaustion.
6. Verification applies to the actual changed source and intended base/head; missing receipts cannot pass.
7. A published PR is not verified delivery; a merge is not proof of payment.
8. Failure of one task does not silently erase the queue or suppress observations of other tasks.
9. A refused claim returns evidence to the agent; code must not silently rewrite the agent's answer into approval.

## One-command execution

```powershell
python scripts/run_pipeline_master.py
python scripts/run_pipeline_master.py --list
python scripts/run_pipeline_master.py --suite test_pipeline_failure_master.py
python scripts/run_pipeline_master.py --timeout 300 --output scratch/pipeline-master
```

`scripts/pipeline_master_suites.json` is the reviewed allowlist. It preserves all test
commands previously selected by `actions-contracts.yml`, plus the new fault matrix and
runner tests. Script-style suites remain scripts; unittest-only suites use discovery.
Do not replace it with wildcard discovery: several `test_*` files are live probes.

Each suite runs in a separate Python process with warnings treated as errors and a
default 180-second limit. A failed suite does not prevent later suites from running.
Each invocation writes a unique UTC directory containing per-suite logs and an atomic
`report.json`, updated after every suite. Exit 0 means every selected suite passed;
exit 1 means at least one FAIL, TIMEOUT or ERROR; invalid arguments exit 2. An interrupted
run leaves `complete: false`; never interpret a partial report as green. Counts are
**suite commands**, not individual assertions or a coverage percentage. Consult logs
for unittest skips and individual failures, including script suites' own reporting.

Credential-like environment variables are removed and GH configuration and fleet scratch
paths are isolated. This is **not** a network or OS security sandbox. The timeout terminates
the direct Python child; independently spawned descendants need OS job/process-group
containment for hostile-process testing. Tests that inspect repository files still read
the current checkout. Use an isolated checkout for reproducible release evidence.

CI runs the same manifest and uploads reports/logs even on failure. Earlier import,
compile, secret scanning and undefined-name checks remain separate gates. The workflow's
overall time limit may interrupt a pathological run; its partial report is a failed run.

## Automated regression map

The filenames below refer to `scripts/`. This is a map to relevant suites, not a claim
that every conceivable permutation within a category is already implemented.

| Stage / risk | Existing executable evidence | New master fault assertions |
|---|---|---|
| Deployment/import/workflow wiring | CI import/compile/lint; `test_actions_migration.py`, `test_engine_identity.py` | Runner rejects unknown/missing suites and invalid timeouts |
| Discovery schedule, starvation, breadth | `test_discovery_heartbeat.py`, `test_fresh_discovery_schedule.py`, `test_discovery_breadth.py`, `test_partition_regressions.py` | None added |
| Search pagination, query encoding, hydration | `test_query_encoding.py`, `test_hydrate_only_path.py`, `test_hydration_capacity.py`, `test_pipeline_repairs.py` | Malformed later page raises instead of returning empty supply |
| Model door, malformed output and repair feedback | `test_agent_door.py`, `test_cline_entry_door.py`, `test_agent_queue.py`, `test_pipeline_repairs.py` | Missing/ambiguous admission and competition stamps rejected |
| Literal funding/code/source evidence | `test_funding_evidence_required.py`, `test_admission_trust.py`, `test_sovereign_stamps.py` | Body/title/comment changes invalidate proof; cross-issue/repo proof refused |
| Freshness and repository availability | `test_repository_intent.py`, `test_competition_evidence.py`, `test_competition_linked.py` | Closed issue, archived/disabled repo, incomplete comments rejected; fetch timestamp alone does not invalidate proof |
| Capacity and queue fairness | `test_capacity_gate.py`, `test_queue_ordering.py`, `test_lane_partition.py`, `test_dispatch_velocity.py` | None added |
| API failure/deadline | `test_pipeline_repairs.py` | CLI absent, timeout, 401/403/404/422/500/502/503, truncated JSON, exhausted deadline, bounded throttle |
| Durable storage | `test_claim_lease.py`, `test_pipeline_repairs.py` | CAS conflict rereads fresh revision; 409/422 exhaustion; 403/500 fail explicitly |
| Dispatch/claim races | `test_e2e_door_to_claim.py`, `test_claim_lease.py` | Failed reservation sends no POST; lost POST response preserves reservation; duplicate blocked; fast claim survives late acknowledgement |
| Lease/cancellation/ownership | `test_claim_lease.py`, `test_cline_delivery_ownership.py`, `test_pipeline_repairs.py` | Real ownership methods exercised in dispatch race |
| Agent execution/preparation | `test_preparation_contract.py`, `test_preparation_terminal.py`, `test_preflight.py`, `test_cline_deliverable.py` | None added |
| Native verification and baseline | `test_engineering_evidence.py`, `test_baseline_relationship.py`, `test_base_branch.py`, `test_actions_migration.py` | None added |
| Patch, paths, immutable tests, submodules | `test_actions_migration.py`, `test_download_patch_submodule.py` | None added |
| Publication and remote CI | `test_sovereign_delivery.py`, `test_pipeline_repairs.py`, `test_e2e_walk.py` | None added |
| Review, retry, merge and payment | `test_pipeline_repairs.py`, `test_e2e_full_pipeline.py` | None added |
| Failure classification and visibility | `test_failure_taxonomy.py`, `test_failure_digest.py`, `test_refusal_census.py`, `test_heartbeat.py` | Runner distinguishes PASS/FAIL/TIMEOUT/ERROR, retains failure and continues |

`test_pipeline_failure_master.py` contains deterministic fault injection against production
methods. Its source-stamp matrix checks boolean identity (e.g. `1` must not masquerade as
`True`) and independent negative cases with a valid control. Transport and storage faults
are injected at subprocess/API boundaries. No external GitHub or model calls are needed.

Important limit: `test_e2e_full_pipeline.py` uses an in-memory store and transport, and
sets engineering/publication states directly. Its receipts prove handoff continuity,
not actual coding, git push or PR creation. The sandbox exercise below is required to
validate those operations together.

## Master sandbox acceptance case: MC-001

Use a disposable control repository, disposable target repository and synthetic funding
evidence. Never use a real bounty or payer for this exercise. Restrict credentials to
those repositories, and use controlled model/API responses where reproducibility matters.

Prepare an open issue with literal funding and source quotes, two comments, one small
defective function, a native test that fails for the defect, a valid base commit and an
empty durable ledger. Record repository names, issue ID, harness SHA, base/head SHA,
source revision, selected model/version, budgets and clock. Avoid logging credentials.

1. Discover the issue and verify its source quotes. Expect one admitted identity with
   a proof bound to the observed source bytes and explicit competition evidence.
2. Dispatch it. Expect one durable generation/reservation and one dispatch event.
3. Start two workers for that generation. Exactly one owns the task; the losing worker
   performs no engineering or publication. A replay of the winner must not consume
   another engineering attempt merely because it is replayed.
4. Execute the real agent on a disposable worktree. Capture the native failing baseline,
   actual diff, successful repaired test and required regression commands. Observe
   source and base/head provenance, not just the agent's statement of success.
5. Publish the actual diff to a fork branch and create one PR. Record the remote PR
   number and exact head. Crash immediately afterward, before local acknowledgement.
6. Restart reconciliation. It must observe the existing PR and avoid creating a second
   branch/PR or losing the task. Pending checks must remain pending.
7. Produce a failed check, then a successful rerun on the same head; also test a new head
   with stale green checks from the old head. Only evidence for the correct head qualifies.
8. Request a review change. Expect a durable obligation and a bounded repair run with
   ownership preserved. Approve after the fix and merge the PR.
9. Reconcile twice. Expect stable DELIVERED state, no redispatch, retained receipts and
   payment UNVERIFIED until independent payment evidence exists.
10. Repeat with each fault below using a fresh fixture or explicit checkpoint. Record
    before/after state, external side effects, recovery observation and assertion result.

## Additional fault catalogue: required sandbox coverage

These are **planned acceptance cases, not reported as executed by the offline runner**.
Some have unit-level coverage in the map above. Exercise the real process/storage/network
boundary before claiming coverage of that failure in deployment.

| IDs | Faults to inject separately | Required observable outcome |
|---|---|---|
| BOOT-01–06 | Missing gh/git/Python/Cline; invalid configuration; missing secret; revoked secret; wrong account; incompatible dependency | Named startup failure; no claim/publication; no credential disclosure |
| SRC-01–08 | Empty search; duplicate result; missing page; reordered pages; deleted issue; PR presented as issue; issue edited after admission; comment deleted after admission | No fabricated evidence; deduped identity; incomplete/stale source re-observed and sent back to agent |
| SRC-09–14 | Offer withdrawn; currency changed; amount changed; wrong source URL; Unicode lookalike quote; huge body with quoted/code-block offer | Literal provenance checked; interpretation delegated to model; no invented funding |
| MODEL-01–08 | No provider key; all providers throttled; provider 5xx; stream truncation; malformed tool call; malformed JSONL; empty result; tool timeout | Bounded execution and diagnostic feedback; no default approval |
| MODEL-09–14 | Duplicate row; row rewrite while read; output after deadline; contradictory evidence; instruction injection in source; model claims unexecuted tests passed | Revalidate factual claims and tool receipts; source text cannot bypass gates |
| NET-01–08 | DNS failure; TLS failure; connection reset; slow response; 429 with Retry-After; exhausted quota; 401/403; malformed successful response | Explicit transport failure or bounded retry; no false empty supply/success |
| STORE-01–08 | Conflict before write; repeated conflict; permission failure; truncated JSON; unreadable record; unavailable branch; truncated tree; one corrupt row among valid rows | Preserve durable history; no blind overwrite; corrupted task visible; healthy tasks continue where safe |
| RACE-01–08 | Two dispatchers; two claimants; delayed old generation; duplicate webhook; claim before POST ack; POST accepted but response lost; state write fails after POST; owner revoked during work | One effective owner; no duplicate publication; durable ambiguity resolved by observation |
| LEASE-01–07 | Expired lease/live run; expired lease/dead run; probe unavailable; malformed owner; clock skew; cancellation refused; cancellation accepted but still running | Unknown is not dead; only proven stale owner released; takeover/cancellation receipt retained |
| EXEC-01–10 | Missing dependency; install failure; native test fails; native test hangs; stdout flood; stderr flood; child crash; parent crash; OOM kill; disk full | No VERIFIED without complete evidence; bounded cleanup; exact failure available to agent/reconciler |
| PATCH-01–09 | Empty diff; wrong base; upstream head advances; merge conflict; rename/delete; binary change; path traversal; symlink escape; immutable test modified | Intended base/head and path contract enforced; unsafe/unverified patch blocked |
| PATCH-10–14 | Untracked companion file; submodule change; CRLF-only diff; newline/Unicode filename; diff changes after verification | Complete artifact with exact verified bytes; no stale verification accepted |
| PUB-01–08 | Push rejected; fork unavailable; protected branch; PR creation rejected; duplicate PR exists; PR accepted/response lost; crash after push; crash after PR creation | No false delivery; observe existing remote effect before retry; ownership checked before write |
| CI-01–09 | No checks; queued; running; failed; cancelled; timed out; held for approval; old failure superseded by rerun; green result on old SHA | Correct distinction between pending/held/failure/success; only current-head evidence used |
| REVIEW-01–07 | No review; changes requested; dismissed review; approval then new commit; closed without merge; merged; inaccessible PR | Durable obligation/terminal state as appropriate; no inferred approval or payment |
| REC-01–08 | Restart at each boundary; duplicate reconciliation; missed schedule; stale heartbeat; retry cap reached; capacity zero; one failing task; payment provider unavailable | Observable bounded progression or terminal reason; no silent orphan, duplicate work or false paid status |
| SEC-01–04 | Credential in exception; credential in model output; malicious issue text; malicious repository build command | Redacted evidence and isolated execution; no unauthorized external effect |

For every write boundary, test four timings: **before send**, **accepted remotely but
acknowledgement lost**, **acknowledged but local state not saved**, and **after local
state saved**. Repeat with restart and duplicate delivery. For budgets, counts and lease
times, test just below, exactly at and just above the boundary, plus absent/invalid input.
For concurrency, use a barrier to force overlap; sequential calls alone do not establish
race safety. For transient faults, test both recovery within budget and persistent failure.

Prioritize combinations with the largest effect: lost dispatch response + restart;
owner revocation + publication; source edit + queued claim; new head + old green CI;
disk full + receipt write; provider throttle + expiring deadline; CAS conflict + duplicate
event; cancellation ambiguity + expired lease. Run a seeded repeated schedule of these
combinations and retain the seed for reproduction.

## Evidence and release decision

For each sandbox case retain: case ID, harness/source SHA, seed, injected fault and exact
boundary, initial ledger, final ledger, task/generation/owner IDs, elapsed time and budget,
API call counts, PR/head receipts, redacted logs, assertion outcome and cleanup outcome.
Do not store raw credentials, private source unrelated to the fixture, or full environment dumps.

The release reviewer requires a complete green master report, successful MC-001 on the
actual target platform, and explicit disposition of unexecuted high-risk acceptance cases.
A green mock-based suite alone does not close process-kill, live concurrency, filesystem,
credential-permission, production model-quality or remote-publication risks.

## Recorded local validation — 2026-11-02

Windows / Python 3.11: the full 58-suite run completed with 56 passes and two failures.
The historical release test still expected warnings to override a successful native exit
code; it was updated to the current production contract while retaining failed-command,
missing-receipt and zero-test rejection. That suite and both new suites then passed in
a targeted three-suite rerun. The submodule fixture suite failed because Git's Windows
shell could not create shared memory (`CreateFileMapping`, Win32 error 5) inside the
sandbox; the same suite passed in an approved run outside the sandbox.

Thus all 58 selected suites have passing results across the full run and targeted reruns;
there was no subsequent single all-green full run. No production implementation was
changed for these tests. The original reports retain their original failure results.

Local evidence (under ignored `scratch/pipeline-master/`):

- `20261102T045822777585Z/report.json`: complete original 58-suite run.
- `20261102T050142852601Z/report.json`: corrected release suite and new suites, 3/3 pass.
- `20261102T050632350783Z/report.json`: Git fixture rerun outside sandbox, 1/1 pass.

The three new Python files compiled successfully, the workflow parsed successfully as
YAML, and the changed tracked files passed whitespace validation. MC-001 and the live
sandbox fault catalogue have not been executed. Platform skips remain visible in suite
logs, including the newline-filename case unsupported by the Windows filesystem.
