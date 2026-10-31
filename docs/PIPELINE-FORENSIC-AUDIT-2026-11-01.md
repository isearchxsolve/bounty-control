# Pipeline forensic audit — 2026-11-01

Audited checkout: `b5c6e0919f1975b858edf5c576c59ee5976492a3`.
Live evidence collection began 2026-10-31 21:38:57 UTC (2026-11-01 IST).
Scope: all five Actions workflows and the reachable discovery, admission, claim, worker,
release, publication, reconciliation, and heartbeat paths. Legacy local/fleet/email entry
points were inspected for deployment boundaries, but their external deployments were not verified.
No production code, remote state, workflow settings, or external messages were changed.

## Verdict and measured outcome

The control plane executes, but the inspected ledger does not demonstrate delivery.
The totals do not establish that preparation discarded valid opportunities. The user independently
classified the 103 refusal reasons as 46 news digests, 32 hackathon/prize announcements,
12 proposal/grant solicitations, six competing/already-paid items, four empty/no-code repositories,
one non-code request and two other items. That is evidence of unsuitable upstream supply being
correctly refused, rather than 103 lost engineering opportunities. This classification is the user's
review; this audit's original collection did not independently establish its ground truth.

The eight recorded execution failures (four missing deliverables, three missing terminal receipts,
one FAILED_VERIFIED) must be investigated separately from those refusals. F02 is a real repair
mechanism defect, but the evidence does not make it the cause of the historical zero-delivery count.
Supply quality is a first-priority repair lane alongside the ownership and evidence-integrity gates.

The live `bounty-control` branch contains **113 task records**:

| Recorded state | Tasks |
| --- | ---: |
| REJECTED_PREPARATION | 103 |
| FAILED_DELIVERABLE_MISSING | 4 |
| FAILED_MISSING_TERMINAL_RECEIPT | 3 |
| DISPATCHED | 2 |
| FAILED_VERIFIED | 1 |
| Any record with a PR URL | **0** |

The latest 200 runs at collection contain 43 successful delivery runs, seven failed delivery
runs, and one cancelled delivery run. This is a bounded run sample, not lifetime totals.
The ledger snapshot and run sample cover different populations; they are not a conversion denominator.
Sampled green delivery logs explicitly end in REJECTED_PREPARATION. Green workflow status therefore
cannot establish that a patch was delivered.

Scheduled discovery and heartbeat runs exist. The older statement that the schedule never fired
is no longer current. Conversely, the newest delivery in this sample predates the latest sovereign
changes: the snapshot does **not** prove those changes have passed an end-to-end delivery.

Evidence: `_probe/forensic-2026-11-01/{ledger.json,runs.json,collected-at.json,run-*.log}`.
The folder is ignored by Git and remains local. Collection helper: `_probe/forensic_snapshot.py`.

## Findings

P1 means a delivery, ownership, or evidence-integrity defect requiring priority repair.
P2 means an operational, diagnostic, or conditional correctness defect. “Reproduced” means
the real function was exercised with an offline transport fixture; it does not assert a live incident.

### F01 — P1 — The sovereign verdict is lost inside discovery

**Confirmed code path; historical live symptoms.** `queue_agent_rows()` stores the door's stamps,
but hydration builds a new context, calls `admit()`, applies `is_code_change_request()`, infers
repository intent, and calls competition again. It stores a newly constructed candidate rather than
carrying the original decision. Dispatch refreshes context and repeats admission and code classification.
Its call to `dispatch()` omits the original competition verdict, so `_sovereign_stamps()` supplies
a generic clear statement. The latest patch preserves fields on the queue and dispatch interfaces,
but the intervening path still replaces their meaning.

Locations: [actions_dispatch.py:1130](../scripts/actions_dispatch.py#L1130),
[actions_dispatch.py:1444](../scripts/actions_dispatch.py#L1444),
[actions_dispatch.py:1605](../scripts/actions_dispatch.py#L1605),
[actions_dispatch.py:720](../scripts/actions_dispatch.py#L720).

This violates law 85: regexes, keyword sets, repository exceptions, and inferred intent still decide
whether the agent's selected work is worth doing. Preserve an explicit, source-cited decision artifact;
let code check identity, literal evidence, freshness, capacity, and newly changed facts. Give a model
the factual gate failures to resolve instead of adding more classification rules.

### F02 — P1 — A refused row cannot be repaired during the same search

**Reproduced.** `iterate.bank()` adds every checked identity to `banked_keys`, including refusals
and unpriced rows. Later rounds skip that identity before verification, regardless of changed content.
The per-round lists are then cleared. A repaired quote for the same issue is never checked, and even
the old refusal can disappear from the final result. The tailer independently deduplicates by issue.

Location: [cline_entry_door.py:946](../scripts/cline_entry_door.py#L946), particularly banking and
the remaining-row filter; [cline_entry_door.py:137](../scripts/cline_entry_door.py#L137).
Probe result: two submitted versions, one verify call, zero admissions, zero final refusals.
Only admitted unchanged evidence should be reusable; a changed submission needs a new verification.
Preserve the complete decision journal across rounds.

### F03 — P1 — Missing evidence is converted into approval

**Reproduced.** `sovereign_admission({}, {})` manufactures a nonempty sovereign proof;
`sovereign_competition({}, {})` claims the door found no competing claimant.
`claim()` accepts manual delivery inputs without requiring a matching admitted dispatch record,
and does not require an expected dispatch generation. `queue_agent_rows()` checks stamps for
non-None presence, not a true admission decision or internally consistent evidence.

Locations: [actions_delivery.py:427](../scripts/actions_delivery.py#L427),
[actions_delivery.py:458](../scripts/actions_delivery.py#L458),
[actions_dispatch.py:1160](../scripts/actions_dispatch.py#L1160).
Manual execution may be authorized, but it must be identified as such; it cannot truthfully assert
that a nonexistent entry-door decision occurred. Require a bound task/dispatch/evidence record or
an explicit manual provenance record. Missing evidence is a named failure.

### F04 — P1 — Pending dispatches are immediately redispatchable without consuming attempts

**Reproduced.** `retry_eligible()` accepts DISPATCHING and DISPATCHED. `dispatch.reserve()` permits
them again; attempts increment only when a worker claims. Two successive calls sent the same task
twice with attempt zero. Concurrent discovery/hydration can therefore generate duplicate events.
Engine concurrency serializes execution for the issue, but does not prevent duplicate queue entries
or later failed/redundant claims. A failed POST also leaves an ambiguous reservation.

Locations: [actions_dispatch.py:1002](../scripts/actions_dispatch.py#L1002),
[actions_dispatch.py:738](../scripts/actions_dispatch.py#L738),
[actions_github.py:283](../scripts/actions_github.py#L283).
Use a durable dispatch generation and acknowledgement deadline; reconcile the ambiguous event
before authorizing another generation. Bind the worker claim to that generation.

### F05 — P1 — The sweeper releases tasks without proving the worker stopped

**Reproduced.** A cancellation HTTP 403 followed by an in-progress owner still produces
FAILED_RUNNER_SHUTDOWN and `swept: true`. The code also releases after its short polling deadline
without requiring a completed run. `owned_update()` checks owner identity only, so the old worker
can continue updating the released record until another owner replaces it.

Locations: [actions_reconcile.py:33](../scripts/actions_reconcile.py#L33),
[actions_github.py:331](../scripts/actions_github.py#L331).
The age clock uses workflow creation time before job start time, so queue/setup time can also count
against a job-specific timeout. Keep cancellation requested as an intermediate state and require
confirmed termination before release. Fence writes/publication by generation and allowed state.

### F06 — P1 — Engineering refusals become permanent issue-level tombstones

**Confirmed code; 103 live tombstones.** REJECTED_* is never retryable. A new maintainer decision,
changed requirements, a corrected offer, or a fixed toolchain does not invalidate that verdict.
The entry door can rediscover the issue, but the durable task identity still rejects it.
Older rejected rows therefore survive later policy/prompt repairs.

Locations: [actions_dispatch.py:1002](../scripts/actions_dispatch.py#L1002),
[actions_dispatch.py:1586](../scripts/actions_dispatch.py#L1586),
[actions_delivery.py:368](../scripts/actions_delivery.py#L368).
Key a refusal to the evidence/policy revision it evaluated. Reconsider only when relevant facts
change or a model explicitly repairs the earlier decision; retain the old refusal as history.

### F07 — P2 — Publication failure evidence is masked by engineering success

**Reproduced; matching live failure state.** `terminal_result()` returns engineering-result.json
before inspecting publish-failure.json. If engineering verified and publication fails, `finish()`
can record FAILED_VERIFIED, losing the actual publication failure diagnosis. One ledger row has
FAILED_VERIFIED. This establishes the bad state exists, not that its exact historical trigger was reproduced live.

Locations: [actions_delivery.py:975](../scripts/actions_delivery.py#L975),
[actions_delivery.py:1006](../scripts/actions_delivery.py#L1006).
Resolve terminal outcome from the last attempted phase and retain all phase receipts. Successful
publication recovery must also retain failed claim/engagement details.

### F08 — P2 — Streaming banks locally but does not dispatch while the agent searches

**Confirmed code; live timing evidence.** The tailer writes admitted-stream.jsonl during search,
but `find_issues()` returns only after all rounds complete. `discover()` queues rows only after
that return. A row found early can wait nearly two 800-second rounds before dispatch begins.
The sampled run 41225683237 started the gateway at 17:55:58Z and queued at 18:17:08Z.

Locations: [agent_door.py:116](../scripts/agent_door.py#L116),
[actions_dispatch.py:1290](../scripts/actions_dispatch.py#L1290),
[cline_entry_door.py:946](../scripts/cline_entry_door.py#L946).
Connect the verified-row channel to the bounded dispatcher as rows arrive, with the same durable
claim and idempotency gates. Local streaming alone does not satisfy on-the-fly ingestion.

### F09 — P1 — Fresh door results can be reported queued but remain unselectable

**Reproduced.** `store_pending_item()` retains a recent checked status if GitHub's issue timestamp
has not changed. `queue_agent_rows()` nevertheless reports the ID queued. `queue_window()` selects
only pending rows. Probe: one reported queued ID, stored status checked, zero selectable rows.
This can hide a corrected door decision for six hours because the decision changed rather than the issue.

Locations: [actions_dispatch.py:1082](../scripts/actions_dispatch.py#L1082),
[actions_dispatch.py:891](../scripts/actions_dispatch.py#L891).
Store and compare the decision/evidence version separately from issue updated_at; report actual
queue disposition rather than counting every attempted write as queued.

### F10 — P1 — Door lanes and founder ingestion do not meet downstream contracts

**Reproduced.** The door emits `lane='bounty'`; configurable discovery lanes are founder, programs,
startup, normal. A partition such as programs/normal filters bounty rows out. All-lane mode avoids
this specific filter, so the default all-lane deployment is not automatically affected.
Founder-watch emits no sovereign stamps and is rejected by `queue_agent_rows()`; its default source
is also a Windows-local path absent from a clean Linux runner.

Locations: [cline_entry_door.py:545](../scripts/cline_entry_door.py#L545),
[actions_dispatch.py:1392](../scripts/actions_dispatch.py#L1392),
[cline_entry_door.py:1069](../scripts/cline_entry_door.py#L1069).
Separate the discovery/source lane from the verified admission type using an explicit shared schema.
Route founder-watch evidence through the agent and source checks before enqueueing it.

### F11 — P2 — Unpriced leads and agent diagnostics are not durable in scheduled discovery

**Confirmed workflow path.** The production wrapper returns admitted/refused rows but drops
`outcome['unpriced']` and does not invoke `write_unpriced_leads()`. The CLI does have a lead writer,
but discovery uses the wrapper. The workflow caches/uploads BOUNTY_STATE_DIR only; the agent workspace,
shortlist, and admitted stream live elsewhere under /tmp/bounty-agent. Runner termination loses them.

Locations: [agent_door.py:139](../scripts/agent_door.py#L139),
[cline_entry_door.py:1110](../scripts/cline_entry_door.py#L1110),
[bounty-discovery.yml](../.github/workflows/bounty-discovery.yml).
Persist the source decisions, unpriced lead queue, and replay cursor in the durable state path.

### F12 — P1 — Native-command validation accepts synthetic success

**Reproduced validator weakness; no claim of a complete malicious release.** A plan with
`['sh','-c','exit 0']` for builds/baseline/final tests passes `validate_plan_contract()`.
`require_commands()` requires successful argv receipts and rejects known zero-test text, but does
not establish what the command actually tested. The current denylist catches some spellings only.
Regression validation is a separate guard and was not bypassed end-to-end in this audit.

Locations: [actions_release.py:99](../scripts/actions_release.py#L99),
[actions_release.py:137](../scripts/actions_release.py#L137),
[delivery_supervisor.py:37](../scripts/delivery_supervisor.py#L37).
Do not extend a shell-command blacklist. Have an independent model inspect native manifests/CI
and cite the selected commands; bind those sources and observed test targets/counts to receipts.
Keep execution, exit-status, artifact, and source-integrity checks deterministic.

### F13 — P2 — Preparation instructions require both implementation and a pristine checkout

**Confirmed contradiction; present-run incidence unverified.** The intake prompt's numbered mandate
requires implementing the fix and preparing the PR, while the same phase must return a clean unchanged
upstream baseline. The host rejects any edits at the end of preparation. An agent following the numbered
implementation steps can therefore fail the phase contract before the engineering loop starts.

Location: [kaggle_engine_worker.py:2851](../scripts/kaggle_engine_worker.py#L2851), especially the mandate
and the clean-baseline check near the end. Define the phase's deliverable once: inspected clean baseline,
native plan, and reproduction specification. The subsequent engineering turn owns product edits.

### F14 — P2 — Publication rejects every base movement, including unrelated changes

**Confirmed conditional liveness failure.** Engineering's baseline relationship check allows safe
ancestry with no touched-file overlap, but publication requires exact equality with base_sha.
A high-velocity repository can invalidate hours of verified work through an unrelated commit.
The publisher raises instead of running a bounded rebase/reverification recovery.

Locations: [actions_delivery.py:286](../scripts/actions_delivery.py#L286),
[actions_delivery.py:914](../scripts/actions_delivery.py#L914).
Keep the current fail-safe gate, but send the new base and changed files to engineering for a bounded
rebase and independent revalidation; do not discard the verified patch or silently weaken the gate.

### F15 — P1 — A single reconciliation error stops recovery for the remaining ledger

**Confirmed structure; historical rate-limit incident exists.** Both sweeper and reconciliation
iterate records without a per-record failure boundary. A CAS conflict, malformed record, missing PR,
or transport exception can abort the rest. Discovery marks the entire reconcile step continue-on-error,
so the workflow may remain green while recovery is skipped. `records()` performs one content read per
task, and reconciliation enumerates it twice before PR-specific probes. Quota demand grows with history.

Locations: [actions_reconcile.py:33](../scripts/actions_reconcile.py#L33),
[actions_reconcile.py:130](../scripts/actions_reconcile.py#L130),
[actions_github.py:338](../scripts/actions_github.py#L338),
[bounty-discovery.yml:46](../.github/workflows/bounty-discovery.yml#L46).
Persist per-record errors/cursors, isolate independent records, and bound work to due active tasks.
Transport failure must leave a visible unresolved observation rather than ending all later recovery.

### F16 — P2 — Dispatch acknowledgement and fleet capacity use incomplete run windows

**Confirmed conditional defect.** Both acknowledgement reconciliation and headroom calculation read
only the latest 100 repository runs across all workflows. A queued delivery outside that window is
missed. A matching old run title can also satisfy acknowledgement for a newer dispatch because the
match is task identity only, without dispatch generation/time. Capacity is a snapshot rather than a
global reservation shared by concurrent dispatchers.

Locations: [actions_reconcile.py:139](../scripts/actions_reconcile.py#L139),
[actions_dispatch.py:1530](../scripts/actions_dispatch.py#L1530).
Use workflow-scoped complete observations plus dispatch-generation correlation. Reserve capacity
durably if four is intended as a fleet-wide maximum.

### F17 — P2 — Capacity cache skips probes but does not apply cached exclusions

**Confirmed code.** `capacity_exclusions()` skips a fresh remembered size without adding it to its
working cache. Its return value is derived only from that working cache. Fresh known oversized repos
therefore disappear from the pre-hydration exclusion set. The later dispatch capacity gate remains,
so the primary effect is repeated hydration/API waste, not a proven unsafe publication.

Location: [actions_dispatch.py:844](../scripts/actions_dispatch.py#L844).
Apply cached measured values as well as newly probed values, with their timestamps and provenance.

### F18 — P1 — Payment and claim completion are outside the durable lifecycle

**Confirmed scope gap.** Reconciliation ends at merge → DELIVERED. It does not verify claim acceptance,
maintainer reward, or payment. `post_claim()` returns false on failure, but its caller ignores the value;
there is no durable retry obligation for the claim. The PR conversion watcher is not invoked by any
of the five workflows. SMTP_DELIVERED in the separate inbound path denotes SMTP acceptance, not
recipient delivery or payment evidence.

Locations: [actions_delivery.py:874](../scripts/actions_delivery.py#L874),
[actions_delivery.py:945](../scripts/actions_delivery.py#L945),
[actions_reconcile.py:169](../scripts/actions_reconcile.py#L169),
[pr_conversion_watch.py](../scripts/pr_conversion_watch.py),
[deepseek_inbound_pipeline.py:366](../scripts/deepseek_inbound_pipeline.py#L366).
Record PR publication, claim submission/acceptance, merge, reward approval, and payment as distinct
observed events. An agent can determine the next legitimate action from platform receipts;
code should not infer payment from merge. No financial outcome was verified in this audit.

### F19 — P1 — CI omits the new critical path and has no PR trigger

**Confirmed workflow configuration.** actions-contracts runs on push and manual dispatch, despite
README claiming PR coverage. Its explicit module list omits test_agent_door, test_agent_queue,
test_cline_entry_door, test_sovereign_stamps, and test_sovereign_delivery. Its compile/F821 list also
omits agent_door and cline_entry_door. New tests can exist without being executed by scheduled CI.

Location: [actions-contracts.yml](../.github/workflows/actions-contracts.yml).
Add PR coverage and include the production door/queue/claim suites. More importantly, add a transport-
mocked end-to-end contract from a streamed row through durable claim and publication outcome; the current
interface tests pass while the cross-boundary defects above survive.

There is a second test-discovery trap: `test_cline_entry_door.py:339` calls `unittest.main()`
before later test classes are defined. Direct script execution runs 29 tests and exits before
the feedback-loop, streaming, sovereignty, and full-gate classes are loaded. Import-based discovery
or pytest is required to collect those later classes; simply adding the script to CI is insufficient.

### F20 — P2 — Health and refusal telemetry can report a quiet success while work is lost

**Confirmed code and sampled live logs.** Empty door results return before receipts.jsonl/census writes.
The census filters on a small subset of count names, omitting actual `refuse()` reasons such as
HARD_ISSUE_EVIDENCE_MISSING and REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN. Streaming decision printing occurs after
an early return when no row was admitted, hiding live refusal events until later aggregation.
The heartbeat measures run freshness/activity, not successful discovery or delivered output.

Locations: [actions_dispatch.py:1378](../scripts/actions_dispatch.py#L1378),
[actions_dispatch.py:1653](../scripts/actions_dispatch.py#L1653),
[cline_entry_door.py:974](../scripts/cline_entry_door.py#L974),
[discovery_heartbeat.py:84](../scripts/discovery_heartbeat.py#L84).
Run 41225683237 reported 10 admitted rows, zero qualified/dispatched, and 16,752 pending hydration rows.
This is observed attrition, not proof every admission was economically valid. Record every handoff's
input/output/reason counts and distinguish execution health from publication and payment outcomes.

## Additional operational boundaries

- **Competition unknown is not clear.** `competition_refusal()` converts transport errors into
  `{blocking:false, verdict:'unverified:...'}`. Reproduced with HTTP 503. Downstream competition checks
  still provide backstops, so this is an evidence-contract inconsistency rather than a demonstrated
  contested publication. Preserve an explicit unknown decision.
- **Quota/backoff:** GitHub retries can sleep up to 600 seconds per retry, independent of remaining
  job/door budget. The rate-limit helper uses ambient credentials rather than the instance token and
  reads core reset without first establishing that the core resource is exhausted. Search throttling
  can therefore consume an unrelated hourly reset wait. Carry one deadline and use the relevant
  resource's observed remaining/reset information.
- **Budget gaps:** the four-hour clock limits Cline turns; native verification loops use separate
  hour-long command timeouts. The job can still die mid-verification or artifact upload at its larger
  Actions timeout. Reserve explicit finalization time; terminate child process groups and write receipts.
- **Tailer concurrency:** verification runs synchronously in a daemon tailer, whose join is only ten
  seconds. Slow network verification may outlive the return path while shared lists/sets are read or
  cleared. File rewriting/truncation also has no byte-offset reset. These are inspected race risks,
  not timing-reproduced incidents in this audit.
- **Cache ownership:** discovery and manually invoked hydration share an immutable cache prefix but
  have separate concurrency groups. Latest-cache restore is not a mergeable authoritative queue;
  concurrent snapshots may lose local-only pending work even though per-task remote CAS protects claims.
  Hydration's schedule is currently disabled. Do not claim autonomous backlog draining is active.
- **Legacy boundary:** indexed_fleet_dispatcher/autonomous_icu_pipeline, Kaggle relay workers,
  mass-attack engines, and the email pipeline use additional local stores and D:\anonym defaults.
  None is invoked by these five workflows. Their live processes, credentials, relay availability,
  and cross-store deduplication remain unverified. Treat them as separate deployments until inventory
  proves otherwise; do not equate their proposal receipts with this ledger's verified PR delivery.

## Verification performed

- Read all five workflow definitions and traced their primary Python entry points and imported gates.
- Collected 200 live run summaries, all 113 visible ledger records, and five complete sampled logs.
- Ran 49 selected offline test modules: 48 passed initially; test_download_patch_submodule failed in
  sandboxed local-clone fixture setup. Its nine tests passed when rerun outside that sandbox.
  Thus all 49 selected modules passed across the initial run plus that rerun. No application defect
  is attributed to the sandbox failure.
- Ran the five door/queue/sovereignty suites through pytest to include classes skipped by direct
  script execution: **130 passed in 14.10 seconds**. These passing tests coexist with the ten
  defect probes; they do not establish an end-to-end live delivery.
- Deliberately excluded test_icu_pipeline_suite.py from local execution because it writes a hardcoded
  D:\anonym\scratch path. Other scratch/live test scripts were not bulk-imported; some have import-time
  external effects. This was not a complete safe execution of README's blanket unittest command.
- Ran ten offline probes against actual functions. All ten observed the behavior described above;
  synthetic-plan acceptance is a validator-level proof, not an end-to-end forged delivery.
- No new live task, PR, issue comment, email, or deployment was created for verification.

Reproduction helpers: `_probe/forensic_probes.py`, `_probe/forensic_contracts.py`.
Evidence: `_probe/forensic-2026-11-01/offline-probes.json`, `tests.json`, and per-module logs.
The test log for cline_entry_door also reports unclosed-file ResourceWarnings in fixtures despite
returning success; these are test hygiene issues, not delivery proof.

## Repair order and acceptance evidence

1. **Fence ownership and dispatch first (F04/F05).** Two overlapping dispatchers must produce one
   authorized generation. Rejected cancellation must leave ownership reserved. Old-generation
   workers must fail state updates and publication even if their process remains alive.
2. **Restore evidence integrity (F01/F03/F10).** One source-bound agent decision must survive the
   full handoff; missing proof must fail visibly. A source change must cause factual revalidation
   and model reconsideration, without a new regex rule deciding what is worthwhile.
3. **Make repair and intake lossless (F02/F06/F08/F09/F11).** Corrected rows must be rechecked;
   relevant changed facts must permit reconsideration; every streamed decision must survive runner
   loss and have a durable queue disposition. Test the partitioned and founder paths explicitly.
4. **Verify one real engineering delivery (F12–F14/F19).** Produce a source-cited native plan,
   unchanged healthy baseline, real failing reproduction, verified product change, independently
   validated bundle, and an upstream PR receipt. Test an unrelated base movement and a publication
   failure without hiding the patch or its diagnostics.
5. **Close the recovery and business loop (F07/F15–F18/F20).** Every failure must retain its phase
   and next obligation. One bad task must not stop the ledger sweep. Measure published PRs,
   accepted claims, merges, and observed payments separately; green workflow counts are insufficient.

No additional hardcoded classification lists are recommended. Judgement, interpretation, and repair
belong to a model with source-reading and execution tools. The deterministic layer should enforce
identity, provenance, literal evidence, state transitions, deadlines, ownership, and actual receipts.
