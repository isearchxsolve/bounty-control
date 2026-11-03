# Live probe master suite: audit, wiring, execution and repair plan

Date: 2026-11-03  
Repository: `isearchxsolve/bounty-control`  
Status: inventory and initial gap review complete; detailed parity audit incomplete.

## 1. Intended outcome

Preserve the original master suite's verification contract and connect its applicable
pipeline failure probes to the real environment. One campaign should execute all
independent probes, collect their evidence, and return a consolidated failure report.
Repair shared causes in a batch, then resume the campaign from the last valid
checkpoint to verify the repairs and expose the remaining failures.

The user's premise is the design requirement: an early pipeline failure must not
prevent unrelated failure probes from running. Repeatedly stopping at the first
failure and discovering the next defect after every patch is not an acceptable
master-suite design.

This plan does not claim that one execution proves the absence of every unknown
defect. It requires complete accounting of the defined probes, including explicit
results for probes whose real prerequisites are unavailable.

## 2. Baseline and current evidence

| Item | Verified position when this plan was prepared |
|---|---|
| Offline master | `scripts/pipeline_master_suites.json` lists 68 suites. |
| Static inventory | 977 named test methods were inventoried. Dynamic tests and script-level checks may add more. |
| Live master | `scripts/live_pipeline_integration.py` declares 32 required cases. |
| Parity | Not established. Suite counts, method counts and live case counts measure different things. |
| Existing audit | [Live probe parity audit](LIVE-PROBE-PARITY-AUDIT.md). |
| Current inventory | `scratch/probe-parity-inventory.json`; entries are `NOT_AUDITED`, not coverage claims. |
| Live execution | Real intake, admission, queue, ownership, dispatch and fault checks have produced receipts. |
| Acceptance | No full green live E2E result has been demonstrated in this work. |

The latest inspected campaign, [41618838277](https://github.com/isearchxsolve/bounty-control/actions/runs/41618838277),
completed its test phase with failure. Its final published receipt reported intake
PASS, delivery execution FAIL, and publication/release/reconciliation cases PENDING.
These are historical observations, not a claim about the current deployment.

Known repairs already made include checkpoint continuation, preservation of queued
admissions across interruption, live progress receipts, full-lane hydration, native
process monitoring, failure-surface execution, hydration heartbeat recovery and
more complete regression-failure feedback. Passing contract CI for these changes
does not certify live parity or successful delivery.

## 3. Non-negotiable contract

- Keep existing assertions and required release gates. Expand coverage without
  replacing a failing check with a weaker one.
- Drive the full production entry door without an issue filter for a full campaign.
  Scoped diagnostics may supplement it but cannot stand in for full E2E.
- Use actual original issues for delivery. A sandbox fixture cannot establish that
  an original issue was delivered.
- Fault inputs may use isolated real test resources and corrupt copies of genuine
  artifacts. Label them as fault probes; never represent them as production success.
- Preserve task identity, admission proof, dispatch history, claim ownership, source
  hashes, attempt counters, native command results and release provenance.
- No fabricated receipts, bypassed checks, silent counter resets, or duplicate work
  to make the report green.
- Resume after repair from the last valid checkpoint. Repeat an earlier stage only
  when its evidence is missing, incomplete or invalidated by current facts.
- Preserve the distinction between publication, maintainer merge and payment.
  Upstream maintainers control their merges; payment requires its own evidence.
- Follow [AGENTS.md](../AGENTS.md): the model interprets and repairs; code performs
  plumbing and factual validation. Give the agent missing tools and gate feedback
  instead of adding an endless series of issue-specific rules.

## 4. Phase A: complete the parity audit

Read the actual assertions and setup in every original suite. Do not map tests by
filename or similar wording alone. Include dynamic cases and script-level checks
that the static method inventory does not capture.

For each distinct assertion or failure scenario, record:

| Field | Required content |
|---|---|
| Original probe | Suite, class/method or script check, source location and assertion. |
| Failure point | Production component, boundary and triggering condition. |
| Current test dependency | Mock, fake, local process, filesystem, network or real service. |
| Real wiring | Actual production entry point, API/client/workflow and resource. |
| Fault mechanism | How the real condition will be induced or observed. |
| Prerequisites | State, credentials, artifact, capacity or external actor required. |
| Expected result | Observable refusal, failure, recovery or successful operation. |
| Evidence | Run, job, artifact, command receipt, source/hash or state revision. |
| Parity assessment | Implemented but unverified, verified live, partial, missing, or blocked. |
| Gap/action | Concrete implementation needed, or exact blocking prerequisite. |

Several assertions may share one live probe if that probe independently proves all
of them; preserve the links and explain the equivalence. Tests of internal pure
functions may appropriately remain local. Document that rationale explicitly and
identify the corresponding observable pipeline behavior rather than silently
dropping those tests from the audit.

Audit areas include discovery and scheduler recovery; funding, scope and competition
evidence; queue and capacity; dispatch transport; claims, leases and ownership;
preparation and native-plan contracts; model routing and tool execution; baseline
integrity; engineering and regression proof; release artifacts; publication and
remote CI; reconciliation and replay; checkpoint recovery; and failure reporting.

**Exit gate:** every original assertion/scenario has a reviewed disposition and
every claimed live equivalent has a concrete implementation/evidence reference.
An unmapped or silently excluded case prevents a claim of full parity.

## 5. Phase B: implement the real wiring

Use the existing master driver and workflow as the entry point. Add the missing
adapters/probes identified by the audit, preserving their assertions.

1. Use the production clients, queue, ledger, claim logic, model gateway, native
   execution, release validator and publisher where those are the components tested.
2. Give each probe a stable identity and a declared prerequisite list so independent
   checks can continue after another check fails.
3. Exercise state corruption, conflicts, stale ownership and related negative cases
   on isolated real resources with retained evidence and controlled cleanup.
4. Exercise artifact rejection against copies of a genuine validated release bundle.
   A genuine positive control must pass before rejection tests can be credited.
5. Plan provider failures, process termination and resource faults in isolated real
   executions. Do not disrupt unrelated production deliveries to manufacture a fault.
6. Provide model/tool feedback with the actual failed command, expected assertion,
   output, exit code, worktree/context and retained prior contract.
7. Publish progress and probe results during execution, including failure causes and
   evidence links suitable for review without exposing credentials.

**Exit gate:** each applicable mapped probe has real wiring, a reproducible trigger,
an observable assertion and a retained evidence path. Unsupported conditions remain
explicit gaps; they are not counted as completed live coverage.

## 6. Phase C: one consolidated live probe campaign

Run the existing full, unfiltered master campaign. Execute every independent probe
despite failures elsewhere. Observe the actual production delivery through its
dependent stages. Keep campaign state and attempt budgets durable.

The consolidated report must distinguish:

| Outcome | Meaning |
|---|---|
| PASS | The defined assertion was exercised and supported by actual evidence. |
| FAIL | The assertion was exercised and failed; retain the precise cause/evidence. |
| BLOCKED | A named prerequisite is unavailable; identify it and the dependent cases. |
| PENDING | A real operation or external decision is still outstanding. |
| NOT_RUN | No execution evidence exists; explain why. |

BLOCKED is the required reporting design, not a claim that every existing code path
already emits that token. The current driver also uses PENDING/NOT_RUN/INCOMPLETE.
Audit and wire the reporting gaps while preserving their meaning.

A production delivery failure must not prevent independent transport, state,
ownership, queue, scheduler and existing-artifact probes from running. Where a
downstream probe genuinely requires a release, successful publication or maintainer
action, name that dependency instead of inventing a substitute success.

The report must include source/driver revisions, continuation history, all probe
outcomes, original task/run identities, active failures, historical failures,
refusals, expected fault injections, blocked dependencies and retained artifacts.
Separate repeat sightings from unique root causes; do not count every old failed
Actions run as a new active defect.

**Exit gate:** all defined probes are accounted for in one report, with no silent
skips. The report can be complete while the pipeline is red. A full green acceptance
claim requires every required live case to pass.

## 7. Phase D: consolidated repairs

Freeze the campaign report as the repair baseline. Group failures by shared cause
before changing code. Assign each repair its affected probe IDs and expected result.

Batch related fixes, run their focused checks and the required contract CI, and
retain an explanation of how the change addresses the observed evidence. Customer
code defects, model decisions, tool/environment faults, orchestration defects and
external blockers need different repairs; do not treat every failure as a prompt issue.

An improved diagnostic is a feedback repair, not proof that the underlying customer
defect is fixed. A fresh scheduled run is recovery evidence, not proof that the
scheduler will always fire. Record those practical limits.

**Exit gate:** a reviewable repair set addresses each actionable cause in the report;
unresolved causes and external blockers remain visible. CI success is necessary but
does not replace a live verification result.

## 8. Phase E: resume and verify

Restore the latest completed campaign's genuine artifacts and journal on the repaired
revision. Revalidate source evidence and checkpoint integrity. Continue from the
failed stage, preserving earlier valid results and their original revisions.

Re-exercise probes whose behavior is affected by the repairs and continue downstream.
Capture newly reachable failures in the next consolidated report. Do not repeat
unrestricted discovery if a valid later checkpoint exists. Do not spend exhausted
attempt budgets or exceed fleet capacity merely to rerun a report.

The expected progression is a finite list of observed causes and explicitly blocked
checks, with batches of verified repairs. Further iterations may be necessary when
previously blocked stages become executable; they must be evidence-driven rather
than an untracked sequence of narrow patches.

## 9. Acceptance criteria

- Parity audit complete, including dynamic and script-level assertions.
- Applicable live probes wired and all original verification requirements preserved.
- One report accounts for every probe and distinguishes failures from blockers.
- Real entry, admission, persistence, dispatch, claim, preparation, engineering,
  native verification, regression proof, release, publication, CI and reconciliation
  have the required actual receipts.
- Recovery/replay preserves identity, ownership, artifact integrity and bounded attempts.
- Required live cases all pass for a full green claim; pending/blocked/unexecuted
  cases cannot be converted to success.
- External maintainer or payment outcomes are reported according to real evidence.

## 10. Execution commands

Run from `D:\bc` using authenticated GitHub CLI. The workflow uses the repository's
configured GitHub and model secrets; never put credential values in commands or docs.

Start a full campaign only when no valid campaign checkpoint is available:

```powershell
gh workflow run pipeline-live-integration.yml --repo isearchxsolve/bounty-control --ref main -f merge_fixture=false
```

Resume after repair, replacing the example ID with the latest appropriate completed
or cancelled master run whose artifact is retained:

```powershell
gh workflow run pipeline-live-integration.yml --repo isearchxsolve/bounty-control --ref main -f merge_fixture=false -f resume_run=41618838277
```

Leave `issue_number` empty for the full production entry door. `merge_fixture=false`
keeps the campaign's original-issue path from requesting a sandbox merge; upstream
merges remain the maintainer's action.

```powershell
gh run list --repo isearchxsolve/bounty-control --workflow pipeline-live-integration.yml --limit 5
gh run watch RUN_ID --repo isearchxsolve/bounty-control
gh run view RUN_ID --repo isearchxsolve/bounty-control --log-failed
gh run download RUN_ID --repo isearchxsolve/bounty-control --name live-integration-RUN_ID --dir scratch/review-RUN_ID
```

The Actions workflow currently has a 240-minute job limit. That is a ceiling, not
an ETA. Detailed job logs are not always available through GitHub CLI until the job
finishes; use the published progress receipts while it runs.

## 11. Estimates and progress reporting

The stated audit-only estimate is **2–4 hours of focused active work**, provisional
until representative case mapping confirms the effort. This does not include real
wiring, deployment, model execution, downstream repair, or external maintainer time.
Estimate wiring and live validation after the audit identifies their concrete scope.

The audit does not continue automatically in the background when the assistant's
turn ends. GitHub Actions can continue independently, but that does not mean a model
is continuously auditing or repairing it. Progress updates must distinguish actual
active work, an independently running workflow, and a waiting/blocking condition.

Track progress by mapped scenarios, remaining gaps, wired probes, completed live
outcomes and unresolved root causes. Update this plan and the parity matrix from
evidence; do not use an elapsed countdown or a passing offline suite as a substitute.
