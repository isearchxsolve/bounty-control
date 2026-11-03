# Live probe parity audit — in progress

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
