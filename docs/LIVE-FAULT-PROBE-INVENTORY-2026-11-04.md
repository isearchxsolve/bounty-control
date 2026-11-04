# Existing fault-line probe inventory

Verified 2026-11-04 against checkout `28d227b` and the retained independent probe
artifact from Actions run `41683203688` (source `96c8813`). This is an inventory
of existing work; no delivery or probe workflow was dispatched for this review.

## Assessment

Substantial independent fault probing is already implemented. The repository has
real provider bindings, isolated resources, execution receipts, and a standalone
Actions workflow. Remaining work concerns uncovered conditions, still-mocked
modules and result/resume semantics. It does not require rebuilding this foundation
or making probes depend on delivery campaigns.

## Implemented boundaries

| Boundary | Existing implementation | What executes for real |
|---|---|---|
| Transport/process faults | `scripts/live_transport_bindings.py`; original `TransportFailureMatrix` | Actual production GitHub client and CLI, loopback HTTP sockets, injected error statuses, malformed JSON/pagination, missing CLI, timeout, deadline and bounded waits. |
| Durable state and dispatch | `scripts/live_durable_bindings.py`; original `DurableStateFaults` | Real remote StateStore reads/writes on isolated branches, competing writes creating CAS conflicts, bounded error propagation, real sandbox repository dispatch and lost-ack fault injection. |
| Leases/ownership | `scripts/live_lease_bindings.py`; original `test_claim_lease.py` | Actual Actions observations and isolated remote claim state; live-owner refusal, unavailable-owner observation, completed-owner takeover and retry bounds. Cancellation fixture remains blocked. |
| Source-bound evidence | Original `EvidenceFailureMatrix` live provider | Real issue context, with controlled evidence mutations passed to the actual provenance gate. |
| Release validation | `scripts/live_release_bindings.py`; `ReleaseFailureMatrix` | Actual GitHub source clone, local Git changes, baseline/native commands, red-to-green regression, real bundle creation/clone and production validation. Positive control plus seven rejection probes. These are labelled probe artifacts. |
| Door-to-claim seam | `scripts/test_e2e_door_to_claim_live.py` | Real issue/source bytes, GitHub queries, sandbox repository dispatch, remote isolated state, evidence and claim gates. Twelve test methods currently exist. |
| State/concurrency matrix | `scripts/test_pipeline_state_live.py` | Eleven remote storage/claim cases, including concurrent claims, stale generations/owners, replay, attempt bounds and corrupted JSON. |
| Native job lifetime | Original `scripts/test_cline_process.py` | Eight actual OS-process tests, including output, cancellation, deadline and descendant lifetime. |
| Master process reporting | Original `scripts/test_pipeline_master_runner.py` live provider | Actual child success, failure, timeout and launch errors, plus continued execution/reporting after a child fails. |

These are different fidelity levels: remote-service probes, real local fault
resources, native gates and local invariant checks. An injected local HTTP error
verifies the production client's behaviour; it is not a claim of a real GitHub
outage. Cases and subtests can overlap, so their counts are not unique fault counts.

## Runner and retained results

- Original regression manifest: **68 suite entries**.
- Independent live runner: **41 selectors referring to 38 distinct modules**,
  plus explicitly loaded original failure-matrix classes.
- Five provider switches activate the evidence, lease, runner, transport and durable
  bindings. Independent release setup is also wired.
- Workflow: `.github/workflows/pipeline-live-probes.yml`.
- Last observed independent Actions result:
  [41683203688](https://github.com/isearchxsolve/bounty-control/actions/runs/41683203688),
  2026-11-03 17:19:58 UTC, source `96c8813`.
- Artifact: **620 recorded method identities**, **781 PASS receipts**, **2 BLOCKED**,
  `complete=true`, `passed=true`, `full_e2e_passed=false`.

Selected groups in that actual artifact:

| Original/probe group | Recorded method identities | Receipts |
|---|---:|---|
| `test_pipeline_failure_master` | 17 | 66 PASS including subtests |
| `test_pipeline_master_runner` | 3 | 9 PASS including subtests |
| `test_claim_lease` | 14 | 13 PASS, 1 BLOCKED |
| `test_e2e_door_to_claim_live` | 12 | 12 PASS |
| `test_cline_process` | 8 | 8 PASS |
| `test_pipeline_state_live` | 11 | 11 PASS |
| `test_pipeline_transport_live` | 2 | 4 PASS including subtests |

The blocked receipts name the owned overdue cancellation fixture and a separate
static check requiring `ruff`. Existing source-bound proof, real wire, state,
release and process work should be retained and extended from these receipts.

## Specific limits established by the review

1. Runner membership alone does not prove live conversion. Some added modules,
   including `test_e2e_full_pipeline.py`, still contain canned transports and direct
   simulated engineering/publication state writes. They must be identified as such.
2. The release fixture is a real independently built root-level Python example.
   That does not establish coverage of every monorepo working-directory or
   malformed-command condition found overnight.
3. The runner excludes BLOCKED from aggregate success and treats it as completed
   on resume. Its subtest/source-provenance handling also needs correction, as
   documented in the overnight RCA.
4. The latest retained independent run predates the overnight delivery changes.
   Its receipts are evidence for their recorded revision and inputs, not automatic
   certification of checkout `28d227b`.
5. Earlier documents use 183, 610 and 620 at different snapshots and sometimes
   call selectors suites. Preserve run/revision-specific counts; a percentage of
   selected test methods is not a demonstrated live fault-coverage percentage.

The appropriate next step is to extend these existing probes to the demonstrated
gaps, retain their original assertions and run the affected conditions against the
repaired revision. Independent probing is already an implemented capability.

Local evidence: `scratch/rca-20261104/coverage/latest-probe/20261103T172007667138Z/report.json`.
Related analysis: [Overnight RCA](PIPELINE-ROOT-CAUSE-ANALYSIS-2026-11-04.md).
