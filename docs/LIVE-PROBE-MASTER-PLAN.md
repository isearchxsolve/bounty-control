# Live probe master suite: replace mocks with real pipeline connections

Date: 2026-11-03  
Repository: `isearchxsolve/bounty-control`  
Status: live assertion parity has not been independently established by this plan review.

## 1. Intended outcome

### Governing premise: campaigns observe behavioral contracts; system faults are objective

**A live campaign observes composite behavioral contracts, but system faults are objective to the system itself.**

- **Live runs and campaigns** detect whether the end-to-end composite behavior holds across components in the wild (discovery, admission, dispatch, engineering, publication, reconciliation).
- **System faults are objective invariants:** Rejection of a corrupt release bundle, CAS write collisions, token expirations, attempt-bound exhaustion, or missing admission stamps are intrinsic, deterministic properties of the system's gates and contracts. They are not subject to or downstream of an ambient live campaign run.
- **Independent fault probes:** Fault detection therefore does not wait for a delivery campaign to produce an edge case by chance. Keep the original master suite and its assertions. Replace mocked dependencies with real pipeline connections, supply each probe's own inputs and fault condition directly, and execute the defined probes together to collect failures in one report.

A release probe must not wait for discovery, admission and engineering to succeed.
A publication, reconciliation or recovery probe must not wait for an unrelated
customer delivery. Give each probe its required real resource, state, artifact or
process directly. Use the production implementation at the boundary being tested.
Provision those inputs independently as part of probe setup; do not make obtaining
them another delivery campaign. A local dependency needed to execute one probe
does not become a dependency between otherwise independent probes.

| Probe boundary | Independently supplied setup |
|---|---|
| Discovery/admission | Actual source access and probe-specific evidence inputs. |
| State, dispatch and ownership | Isolated real store/queue resources and explicit fault states. |
| Engineering and native execution | A real worktree, executable commands and the probe's failure trigger. |
| Release validation | A release input produced through the real probe setup/builder, followed by controlled mutations and the actual validator. |
| Publication, checks and reconciliation | Owned real probe repository/PR/check resources with the state required by that assertion. |
| Cancellation/recovery | A dedicated real process or Actions run owned by the probe. |

Probe inputs and fault states are labelled test resources. They are not claims that
an original customer issue was admitted, engineered, published or delivered. A
positive control must run the actual operation or gate; it cannot be a handwritten
success flag. Preserve evidence identifying the resource, injected fault, actual
operation, assertion and observed result.

The execution order is: **wire the existing probes -> provision their own inputs ->
run all independent probes -> consolidate failures -> batch repairs -> rerun affected
probes using valid retained evidence.** One probe's failure must not suppress others.
The continuous entry-to-delivery journey checks composition separately; it is not a
prerequisite for fault detection or a substitute for the independent probes.

An unavailable probe prerequisite is an explicit provisioning gap/BLOCKED result.
Missing wiring is unfinished implementation. Neither justifies waiting for a chain
of delivery campaigns. This premise governs the remaining sections wherever older
campaign wording could imply such a dependency.

### Latest agreed premise: convert the original suite directly

The requested implementation is **the existing master suite with its mocked
dependencies replaced by live pipeline providers**. Preserve its test identities,
assertions, expected failure semantics and release gates. Reuse the interfaces the
tests already call. A parallel collection of new live tests is supplementary and
does not complete this conversion.

For each original suite:

1. Replace the mock provider with the actual client, store, process or workflow
   operation through the same interface.
2. Bind fixture identities and inputs to the corresponding real resources. Keep
   fault resources isolated and visibly labelled; retain their evidence.
3. Run the original assertions, collect all independent outcomes, and repair the
   observed causes. Resume affected checks after repair with valid evidence retained.

Where a mock directly substitutes an entire operation being probed, replace that operation too.
For example, `test_e2e_full_pipeline.py` currently simulates engineering and
publication by writing `VERIFIED` and `PUBLISHED_PENDING_CHECKS` itself. Live mode
must invoke real engineering/publication and observe their results before those
same assertions can establish E2E success. Merely giving those writes a remote
store would leave the simulated work in place. That composition test must not gate
the independent fault probes at engineering, release or publication boundaries.

Negative probes may induce faults on actual isolated HTTP, process or storage
boundaries. They must execute the production client/gate and identify the injected
condition. A local injected HTTP 500 proves client behaviour under that fault;
it is not evidence that GitHub itself suffered an outage. Mocked subprocess results,
invented successful artifacts and manually asserted delivery states cannot count
as live pipeline evidence.

Missing real prerequisites are explicit BLOCKED results. They do not become PASS,
and unavailable observations must not satisfy a test through an unrelated error.
For example, cancellation requires an owned real cancellable Actions fixture;
an unrelated production run is not an acceptable substitute.

**Current implementation evidence (2026-11-03):**

- The original three `EvidenceFailureMatrix` test bodies are unchanged and pass
  with a real GitHub issue-context provider.
- The original `test_claim_lease.py` providers now have live bindings to isolated
  real GitHub state and actual Actions observations. Its four admission tests pass;
  cancellation has a named fixture blocker. A completed-owner provider fix was
  checked by rerunning that original case successfully.
- The original three `test_pipeline_master_runner.py` tests now have live process
  providers. Real success, nonzero exit, timeout, launch failure and continuation
  checks pass. Their original assertions remain in place.
- All six original `TransportFailureMatrix` methods passed with actual CLI/HTTP
  fault boundaries: HTTP error statuses, malformed JSON/pagination, missing CLI,
  timeout, expired deadline and bounded throttling. Actual HTTP request and wait
  counts are retained in the execution output. These are injected transport faults.
- The previously published 24-check live run is supplementary subset evidence,
  not proof that the entire original master suite has been converted.

No full-suite completion ETA is currently verified. The next deliverables are
converted original providers and their actual assertion results, not another audit
waiting period or replacement test framework. Full conversion remains unfinished.

Implementation update (2026-11-03): `scripts/run_pipeline_live_probes.py` now
executes the original `EvidenceFailureMatrix` methods with the context provider
switched to GitHub, plus real transport, isolated remote-state/claim probes, and
the existing native process tests. The original evidence test assertions are
unchanged. Run with `python scripts/run_pipeline_live_probes.py`; use `--test`
with an exact wired test/class name for a focused post-repair check. Results are
retained under `scratch/live-probes/`. The E2E workflow runs these independent
checks before delivery and retains their failures while delivery continues.
This is implemented partial wiring, not a declaration that all original suites
or failure permutations have been converted. Unconverted assertions retain their
original offline coverage and must not be credited as live.

Scope clarification: keep the existing test scenarios, assertions and gates; replace
their mocked dependencies with real pipeline connections. Use the existing runner
and reporting wherever possible. No new test framework or separate campaign design
is required. The sections below describe checks on this conversion, not a sequence
of prerequisite projects that must finish before wiring begins.

The implementation sequence is concrete:

1. Read an existing test's assertions and mocked boundary.
2. Connect that boundary to the actual pipeline implementation and real resource;
   reproduce the failure condition without mocking the component under test.
3. Execute the unchanged assertion and retain the actual result and evidence.
4. Repeat for the remaining applicable probes, recording the mapping as work proceeds.
5. Run the connected suite together, collecting independent failures without stopping
   at the first one. Batch pipeline repairs, then resume affected checks from valid
   checkpoints.

The next implementation deliverable is a working conversion with a live receipt and
unchanged assertions, not another planning document. A mock-induced failure may need
an actual fault trigger; record that specific work instead of claiming every mock can
be replaced by changing a URL. Wiring checks can run during development; the
consolidated campaign remains the basis for the pipeline repair batch.

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

## 4. Assertion mapping during wiring

Read the actual assertions and setup as each suite is wired. Do not map tests by
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

**Completion gate, not a prerequisite to starting wiring:** every original assertion/scenario has a reviewed disposition and
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
4. Supply release probes with independently provisioned real probe artifacts and
   exercise the actual builder/validator. A real positive control must pass before
   rejection tests can be credited. Do not wait for a customer delivery to supply it.
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

Run the connected original master probes together, with their independently
provisioned inputs. Execute every independent probe despite failures elsewhere.
Retain setup, fault and assertion evidence for each probe. A continuous production
delivery may be observed separately; its progress does not gate the fault suite.
Keep probe state and any actual task attempt budgets durable.

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
ownership, queue, scheduler, release, publication or reconciliation probes from
running. Provision each probe's own real inputs. If a required resource or permission
cannot be supplied, identify that specific gap. Do not use an unsuccessful customer
campaign as the explanation for leaving an independently executable probe unrun.

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

The expected progression is a consolidated list of observed causes and explicit
probe setup gaps, followed by batches of verified repairs. Retry affected probes
directly. Do not require upstream delivery stages to be repaired before probing
another boundary whose own inputs can be supplied independently.

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

The earlier 2-4 hour audit estimate is withdrawn: it was not supported by measured
conversion work. There is no separate audit waiting period before wiring starts.
Report progress as actual boundaries connected, assertions executed live, remaining
mock dependencies, and named blockers. Do not turn suite-level production activity
into a claim that every assertion in that suite has been exercised live.

A defensible completion estimate requires inspecting the remaining mock boundaries
and measuring a representative conversion. Until then, no full-suite ETA is verified.
Separate implementation time from the measured duration of the live suite itself.

The audit does not continue automatically in the background when the assistant's
turn ends. GitHub Actions can continue independently, but that does not mean a model
is continuously auditing or repairing it. Progress updates must distinguish actual
active work, an independently running workflow, and a waiting/blocking condition.

Track progress by mapped scenarios, remaining gaps, wired probes, completed live
outcomes and unresolved root causes. Update this plan and the parity matrix from
evidence; do not use an elapsed countdown or a passing offline suite as a substitute.
