# Live Probe Wiring Execution Plan & Measured Progress

Date: 2026-11-03  
Repository: `isearchxsolve/bounty-control`  
Reference: [Live Probe Master Plan](LIVE-PROBE-MASTER-PLAN.md)  
Status: In Progress — Active Cluster Conversion

---

## Governing execution premise: campaigns observe behavioral contracts; system faults are objective

**Live runs like campaigns detect composite behavioral contracts; however, a system's faults are objective to the system itself, not subject to or downstream of a live run.**

- **Campaigns vs. Fault Probes:** An end-to-end delivery campaign verifies that composed subsystems interact correctly across the whole lifecycle. Conversely, system faults—rejection of corrupt release bundles, CAS write collisions, token expirations, unproven evidence stamps, or lease revocation—are objective invariants of the system's code and contracts.
- **Independent Provisioning:** Fault detection does not wait for an ambient live campaign to produce a failure. Replace mocked boundaries directly, keep original assertions, and supply each probe's own real inputs and fault triggers independently. Provision release, publication, ownership, and cancellation resources directly; another customer campaign succeeding is never their prerequisite.

Run all independently executable probes, retain all outcomes in one report, batch
repairs, and recheck affected probes directly. A continuous E2E delivery journey
checks composition separately. A missing probe resource is a setup gap; unconverted
mock wiring is unfinished implementation. Neither is a reason to serialize the
other fault probes behind it.

The [master plan's governing premise](LIVE-PROBE-MASTER-PLAN.md#governing-premise-independent-live-fault-probes)
applies throughout. Earlier cluster dependencies and projected clock times below
are superseded; no full conversion ETA has been verified.

## 1. Overview & Operational Law

In accordance with [Baba Law 85 (Stop Hardcoding Intelligence)](ARCHITECTURAL-LAW-PLUG-IN-INTELLIGENCE.md) and [Baba Law 86 (Resume After Repair)](../AGENTS.md):
- Keep existing test assertions, gates, and contracts intact.
- Swap mock boundaries (`FakeStore`, `FakeAPI`, synthetic subprocesses, stubbed dicts) with real pipeline connections (real `StateStore` on isolated integration branches, real `GitHub` API, real target issues and files).
- Run suites together in single-shot executions to surface all failure points at once.
- Fix failures in batches and rerun affected probes directly with valid retained evidence.
- Use `--resume-run` for an actual delivery continuation only; fault probes do not wait for it.

---

## 2. Cluster Breakdown & Measured Execution Schedule

The 42 mocked suites (715 test cases) are organized into 3 functional clusters for direct boundary replacement:

| Cluster | Key Suites Included | Cases | Mock Boundary Swapped | Target Completion | Status |
|---|---|---|---|---|---|
| **Cluster 1: Delivery & Release Execution** | `test_cline_delivery_ownership.py`, `test_actions_migration.py`, `test_cline_deliverable.py`, `test_non_code_deliverable.py` | 89 | Subprocess execution, baseline protection, release bundle validation, verification command checks | Not verified | Independent; requires only its own wiring/setup |
| **Cluster 2: Admission Door & Competition** | `test_cline_entry_door.py`, `test_competition_evidence.py`, `test_capacity_gate.py`, `test_claim_lease.py`, `test_claim_command.py` | 178 | `FakeAPI`, `FakeStore`, `FakeCompetitionAPI` -> real GitHub GraphQL competition queries and remote StateStore CAS | Not verified | Independent; requires only its own wiring/setup |
| **Cluster 3: Discovery & Dispatch** | `test_discovery_heartbeat.py`, `test_dispatcher_horizon.py`, `test_fresh_discovery_schedule.py`, `test_discovery_repairs.py`, `test_queue_ordering.py` | 110 | Workflow dispatch mocks, cron locks, SQLite queue windowing -> real GitHub Actions scheduling and queues | Not verified | Independent; requires only its own wiring/setup |
| **Consolidated Single-Shot Live Run** | Connected original master probes | Defined original assertions; conversion incomplete | Independent real boundary probes | Not verified | Does not depend on a delivery campaign |

---

## 3. Timing and execution independence

No measured full-suite conversion rate or completion ETA is verified. The earlier
3-5 minute conversion claim and 45-60 minute completion projection are withdrawn.
Network execution measurements for individual probes do not establish conversion
time for the remaining original assertions.

Clusters organize work; they do not create execution dependencies. Report actual
converted providers, original assertions executed, results, and specific setup gaps.

---

## 4. Live Conversion Receipts (Executed Today)

### Receipt 1: [`test_pipeline_transport_live.py`](../scripts/test_pipeline_transport_live.py)
- **Status:** **PASS** (2/2 tests passed in 13.78s)
- **Real boundary:** Real GitHub HTTP 401 (invalid authentication token) and HTTP 404 (absent repository probe) without transport fakes.

### Receipt 2: [`test_pipeline_state_live.py`](../scripts/test_pipeline_state_live.py)
- **Status:** **13 / 14 passed** in 282.76s
- **Isolated Branch:** `live-probes/1c9be01ca01b43c5b2cf38c98f44766f`
- **Real boundary:** Remote `StateStore` roundtrips, CAS conflicts (409/422), attempt limits, stale generation rejection, owner revocation, truncated JSON state recovery, and source mutation rejection.
- **Defect Surfaced:** Transient `TLS handshake timeout` during `ensure()` on the branch ref, demonstrating need for retry on network timeouts in `GitHub.api()`.

### Receipt 3: [`test_e2e_door_to_claim_live.py`](../scripts/test_e2e_door_to_claim_live.py)
- **Status:** **5 / 6 passed** in 167.22s
- **Real boundary:** Real target issue [`isearchxsolve/oss-hunter-livefire#10`](https://github.com/isearchxsolve/oss-hunter-livefire/issues/10), real file SHA and bytes on `duration.py`, real GraphQL competition checks, and real StateStore on GitHub.
- **Defect Surfaced:** `ValueError: Dispatch state disappeared` at `actions_dispatch.py:798` during `store.mutate(identity, acknowledge)`.

---

### Receipt 4: 
un_pipeline_live_probes.py (Full Master Live Battery)
- **Status:** **50 / 52 passed, 2 blocked** in 341.83s
- **Receipt Artifact:** [scratch/live-probes/20261103T115608463575Z/report.json](../scratch/live-probes/20261103T115608463575Z/report.json)
- **Real boundaries:**
  - Real GitHub issue mutations and evidence verification (EvidenceFailureMatrix on mgillr/acfa-rs#93).
  - Real local HTTP fault server (TransportFailureMatrix validating HTTP 401, 403, 404, 422, 500, 502, 503, malformed JSON, timeouts, and bounded throttling without mock bypass).
  - Real remote StateStore roundtrips, bounded attempts, CAS write rejections, and lease handoffs on isolated branch live-probes/4df20818ba4943709a69fcc9b3d88d17.
  - Real native job execution, exit code capturing, and log cursor streaming (	est_cline_process.py).
  - Real lease derivation and sweeper verification against actual Actions run metadata (	est_claim_lease.py).
  - Real environment preflight classification checks (	est_preflight.py, 	est_pipeline_master_runner.py).
- **Blocked Cases (Gate Integrity):**
  - 	est_cline_process.NativeJobTests.test_timeout_stops_native_descendant: BLOCKED on Windows host due to POSIX process-group requirement (os.killpg).
  - 	est_claim_lease.SweeperTests.test_5_a_run_past_its_job_window_is_cancelled_and_released: BLOCKED because cancellation requires an owned overdue Actions fixture; unrelated runs are never canceled per Baba 85/86 release gate rules.

## 5. Live Surfaced Defects & Batch Repair Tracker

| Defect ID | Component | Root Cause | Impact | Fix Applied / Planned |
|---|---|---|---|---|
| **DEF-01** | `actions_dispatch.py:1220` | `StateStore()` constructed without passing `api`, spawning unpatched `GitHub()` instance and bypassing mocks in tests. | Caused hydration tests to hang on unpatched GitHub calls. | Fixed: `store = StateStore(api)` reuses the configured API client. |
| **DEF-02** | `actions_dispatch.py:798` | `acknowledge()` in `dispatch()` raised a bare `Dispatch state disappeared` when `previous` was None. | First dispatch of a newly admitted issue failed during state acknowledgment, and the message could not be told apart from a real loss of durable state. | Fixed by naming the fact, not by inventing one: the error now carries task, dispatch, repo and states that another actor removed the record. A default record was **rejected**: a synthesized DISPATCHED row is a receipt with no admission behind it. |
| **DEF-03** | `actions_github.py:56` | `THROTTLE` regex only caught 403/429 rate limits, so a local socket problem was a verdict on first failure. | `net/http: TLS handshake timeout` failed a probe outright; the same call succeeded seconds later. | Fixed: `TRANSIENT` has its own budget (3 tries, 2s/4s backoff), never consumes throttle attempts, and prints a `TRANSIENT` line so a slow run is not read as a failure. |
| **DEF-04** | `scripts/test_dispatch_transport_live_receipts.py:25` | Suite read `DISPATCH_REGRESSION_FIXTURES`, which nothing in the repository produced; the loopback relay compared the door token against `''`. | Five assertions could not run at all (`KeyError`, then HTTP 401). | Fixed: `build_dispatch_regression_fixtures.py` reads the four real repositories, the real audit issue and the real `package-lock.json`, and reproduces the staging failure through the production `_git_checked` path. The suite sets its own loopback token, and falls back to `scripts/fixtures/dispatch_regression.json`. 5/5 pass, 23s live / 0.4s recorded. |
| **DEF-05** | `scripts/test_fleet_retry_policy.py:14` | Called `kaggle_engine_worker.task_retry_decision`, which no longer exists (the decision moved to `fleet_recovery_policy.recovery_decision`), and `worker.startup_health`. | Nine assertions died with `AttributeError`; the suite could not report on the policy it names. | Fixed: same ten assertions run against the function that decides; health now probes `_cline_proxy_is_healthy`. 10/10 pass. |
| **DEF-06** | `scripts/test_fleet_recovery_live_receipts.py:25` | Same missing-producer class: reads `FLEET_RECOVERY_SNAPSHOT` (`claims`/`results`/`queue`) although no script or workflow writes it. | Thirteen setup errors; the suite cannot run. | Open. The snapshot must come from a real ledger. The deployed relay answers `404 not found` for `/admin/export` and `403 bad token` for `/fleet/health` with the vault admin token, so the local export endpoint in `fleet_local_relay.py` is not what that edge serves. Needs either the edge's read credential or a locally replayed real ledger. |
