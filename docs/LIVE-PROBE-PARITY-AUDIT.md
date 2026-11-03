# Live probe parity audit — in progress

Execution plan: [Live probe master suite plan](LIVE-PROBE-MASTER-PLAN.md).

The objective is to map the existing master test contract to real, independently
observable pipeline probes. A count of cases is not evidence of parity. No test is
credited as live solely because a similarly named case exists.

The manifest currently names 68 offline suites. A static inventory found 977 named
test methods; dynamic tests and script-level checks may add more. The live driver
declares 32 required cases. The case-by-case mapping is **not complete**.

| Area | Current real evidence | Remaining audit/work |
|---|---|---|
| Entry and queue | `pipeline()` calls production discovery; source checks, hydration and replay use actual GitHub and SQLite data. | Map each original admission, funding, competition, queue, capacity and recovery probe to a live result. |
| Ownership and transport | `faults()` tests actual remote state, conflicts, claim races, ownership, retry cap and HTTP failures on an isolated branch; `negative_claim()` exercises an Actions rejection. | Compare each original lease, claim, transport, authentication and dispatch failure probe. |
| Engineering and release | Actual delivery uses the production Actions workflow and native verification. `artifact_faults()` tests corrupt copies of an actual release receipt and bundle. | Map every preparation, toolchain, execution and release case. Release probes requiring a genuine positive control remain pending until one exists. |
| Fleet failures | `failures()` reads durable records and completed Actions runs. | Verify cause attribution, duplicate handling, historical versus active status, and expected fault-injection runs against the original contract. |
| Continuation | The live driver restores a prior real campaign and validates source-bound admissions before reuse. | Audit every checkpoint, generation, ownership and attempt-limit case against actual live continuation evidence. |
| External conditions | The driver explicitly lists provider-wide outage, runner resource exhaustion, reviewer actions and payment settlement among conditions not exercised. | Determine which can be safely probed live; otherwise report them blocked with their prerequisite, never as passed. |

The machine-readable static inventory is `scratch/probe-parity-inventory.json` in
the current workspace. Its entries are marked `NOT_AUDITED`: it is a work list, not
a coverage report. Populate mappings only from code and actual run receipts.

## Batch 1: Core Dispatch, Ownership, Release, and Fault Suites (15 / 68 suites audited)

Audit date: 2026-11-03  
Audited suites: 15 / 68  
Audited test cases: 248 / 977

| Suite | Cases | Area | Parity Assessment | Real Wiring / Live Equivalent | Failure Point & Fault Mechanism | Evidence & Receipts |
|---|---|---|---|---|---|---|
| `test_live_pipeline_resume.py` | 7 | Continuation and Recovery | **VERIFIED_LIVE** | live_pipeline_resume.py:restore_files() and live_pipeline_integration.py:delivery_harness( | State corruption or generation mismatch during checkpoint restoration (--resume-run) — Exercised directly during resume  | Runs 41615904730 -> 41618838277 RESUMED_CHECKPOINT receipts; cohort state and attempt hist |
| `test_live_pipeline_scope.py` | 12 | Driver and Orchestration | **VERIFIED_LIVE** | scripts/live_pipeline_integration.py (record deduplication, discovery_cadence, dispatch_in | Repeat verdict runaway loops, discovery cron throttle starvation, doubled dispatch of in-flight discovery — Exercised di | Runs 41615904730 and 41618838277 collapse repeat ACTIONS_TERMINAL events; discovery cadenc |
| `test_actions_migration.py` | 42 | Release and Baseline Integrity | **PARTIAL** | actions_release.py (validate_bundle, protect_baseline_tests, regression_proof, safe_path)  | Release bundle tampering, baseline test mutation, path traversal, or bypassed plan validation — artifact_faults() inject | LIVE_RELEASE_* cases in live_pipeline_integration.py; unit tests pin strict path security  |
| `test_cline_delivery_ownership.py` | 35 | Ownership and Delivery Execution | **VERIFIED_LIVE** | actions_delivery.py:engineer(), actions_release.py:guard_untouched_baseline() executed by  | Unowned execution, baseline mutation during provisioning, lockfile rewrite false-positives, regression contract loss — L | Runs 41601570698, 41581930854, and live faults() PASS receipts |
| `test_preparation_terminal.py` | 14 | Preparation Failure Taxonomy | **VERIFIED_LIVE** | actions_delivery.py:engineer() preparation phase and delivery_errors.py | Preparation budget exhaustion, unresolvable contract violations, runner preemption during preparation — Captured in engi | Task state records in fleet-state/ and retained engineer-failure.json artifacts across fai |
| `test_engineering_evidence.py` | 15 | Admission and Funding | **PURE_UNIT** | bounty_admission.py:engineering_evidence(), engineering_signal(), admit() | Sanitization stripping repository permalinks; weak or missing technical vocabulary signals — Unit assertion matrix testi | Offline suite passes in CI (15/15 in 3.28s); pipeline manifests via LIVE_SOURCE_REJECTIONS |
| `test_baseline_relationship.py` | 12 | Baseline Integrity | **VERIFIED_LIVE** | actions_delivery.py and live_pipeline_integration.py:preflight() using git rev-parse and G | Base SHA mismatch, detached HEAD, stale target commit, or shallow clone boundary violation — Verified natively on target | TARGET_PREFLIGHT and ENVIRONMENT cases in run.json; engine2.yml step 'Run actions/checkout |
| `test_cline_deliverable.py` | 12 | Deliverable Validation | **PARTIAL** | actions_delivery.py:worker.verify_deliverable() and release bundle construction | Empty patch, non-product-code deliverable, missing report markdown, uncommitted diff changes — Release gate checks produ | actions_delivery.py line 804: No issue-linked product change; no-op/docs/lockfile-only rel |
| `test_failure_taxonomy.py` | 19 | Failure Classification | **VERIFIED_LIVE** | live_pipeline_integration.py:failures(), surface_entries(), group_causes() | Unexplained errors, misclassified refusals vs failures, missing terminal receipts — failures() reads all fleet-state/*.j | failures.json and failures.md generated in run 41618838277; LIVE_FAILURE_SURFACE: PASS |
| `test_claim_lease.py` | 14 | Ownership and Transport | **VERIFIED_LIVE** | actions_github.py:StateStore.claim(), actions_reconcile.py:sweep_stale_runs() against GitH | Concurrent claim races, stale generation writes, dead owner detection, lease duration calculations — faults() runs LIVE_ | Live run 41618838277 events: LIVE_CONCURRENT_CLAIM: PASS, LIVE_CLAIM_REPLAY: PASS, LIVE_RE |
| `test_lane_partition.py` | 12 | Lane Architecture | **VERIFIED_LIVE** | sovereign_discovery.py:discover(['startup', 'founder', 'normal', 'programs']) in live_pipe | Cross-lane contamination, priority inversion, starvation of non-founder lanes — Production discovery executed across all | entry-scout run artifacts partitioned by lane; LIVE_INTAKE: PASS across all 4 lanes in run |
| `test_capacity_gate.py` | 18 | Queue and Capacity | **VERIFIED_LIVE** | sovereign_discovery.py:discover() and actions_dispatch.py:hydrate() | Over-dispatching repositories beyond concurrent limit, queue starvation, capacity calculation drift — Production hydrati | Census in run 41618838277 showing capacity_wait: 21, CAPACITY_EXCLUDED: 11; drain run 4153 |
| `test_preparation_contract.py` | 14 | Preparation and Native Plan | **PARTIAL** | actions_delivery.py:validate_plan_contract() and delivery_errors.py | Invalid plan commands, shell metacharacters bypassing execution, empty test/linter lists, unapproved plan schema — Calle | Run 41572134967 and engine2 delivery logs showing plan contract validation; actions_delive |
| `test_preflight.py` | 7 | Environment and Toolchain Verification | **VERIFIED_LIVE** | live_pipeline_integration.py:preflight() and engine2.yml bootstrap steps | Missing gh CLI, missing or incompatible Cline CLI, Python version mismatch, missing repository permissions — Preflight c | ENVIRONMENT: PASS event in every live campaign; workflow step 'Install the same Cline CLI  |
| `test_pipeline_failure_master.py` | 15 | Fault Injection and Taxonomy | **VERIFIED_LIVE** | live_pipeline_integration.py:faults() executing real API calls and StateStore mutations | Storage CAS conflicts, truncated JSON state, GitHub 401/404, boolean stamp spoofing — Live injection of 409 CAS conflict | Run 41618838277 events: LIVE_STATE_ROUNDTRIP: PASS, LIVE_CAS_CONFLICT: PASS, LIVE_TRUNCATE |
