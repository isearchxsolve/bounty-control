# Overnight pipeline failures: root cause analysis

Investigation date: 2026-11-04. Snapshot: approximately 07:30 IST / 02:00 UTC.
Window: 2026-11-03 18:00 IST onward. Checkout reviewed: `580cb9f`.
This investigation read live Actions, artifacts, PRs and durable state. It did not
change production code, dispatch deliveries or reset attempt counters.

## Finding

A small set of shared execution/recovery defects is being multiplied by automatic
repair dispatch, while green tests do not establish that the deployed revision
exercised the real failing boundaries. Model-produced command/regression mistakes
also occur. These are interacting causes, not one universal customer-code defect.

The strongest observed chain is:

1. A runtime/contract mismatch breaks independent release verification.
2. Recovery preserves the inputs, sometimes including the offending build output.
3. Reconciliation spends another bounded attempt before that shared cause is fixed.
4. Contract CI passes against different conditions, including remaining mocks.
5. Another narrow repair changes execution behaviour or acceptance, without a new
   live probe result for that repaired revision.

## What the volume actually measures

The captured window contains 142 workflow runs. Customer delivery accounts for
49 invocations across 21 distinct repository/issues: 41 failed, 8 succeeded.
Lux alone accounts for 22 invocations: 18 failed, 4 succeeded.

There were also 32 sandbox/probe delivery invocations, 17 failed and 15 cancelled.
These require separate classification; they cannot all be counted as customer
failures or assumed to be expected negatives merely from their conclusion.

The latest failure-surface report counted 249 failure sightings, grouped into 45
normalized diagnostic groups, with 204 repeat sightings and 102 refusals. Those
groups are reporting fingerprints, not an independently proven census of root
causes. Historical errors, repeated observations and active faults coexist.
[Failure surface 41753928785](https://github.com/isearchxsolve/bounty-control/actions/runs/41753928785).

There were 31 code commits in the same window. The 28 captured contract-CI runs
contained 25 successes and 3 failures. Neither commit count nor CI success measures
live customer delivery success.

## Confirmed causal examples

| Evidence | Actual fault | Why it matters |
|---|---|---|
| Lux #102, runs 41744257863 and 41753372348 | Host tried to decode a Rust compiler cache binary as UTF-8 source. | Both failed on the same `dep-lib-itoa` file on harness `d5d4038`. |
| Latest #102 recovery | Restored 249 files, including 222 under `lux/priv/rust/target/`, including that exact binary. | The checkpoint carried the failure input into the next attempt. |
| Lux #54, run 41753446013 | 1,332 tests, formatting and Credo passed under `cd lux`; host ran the companion regression from repository root. | The real failure was missing `Mix.Project`, not a demonstrated failure of the proposed customer fix. |
| Earlier #54, run 41744466406 | Companion path omitted the `lux/` prefix. | Path coordinates disagreed between model artifact and repository gate. |
| Lux #86, run 41744567836 | Regression named production `.ex` files and `mix credo` instead of actual added companion tests. | The same terminal message as #54 concealed a different cause: an invalid model-produced regression contract, correctly rejected. |
| Dispo #19, run 41660230924 | `regression.json` supplied `argv` as one shell string. The execution helper called `list(argv)`, producing characters and trying to execute `T`. | Runtime schema validation did not reject the malformed contract before execution. |

Sources: [#102 first](https://github.com/isearchxsolve/bounty-control/actions/runs/41744257863),
[#102 recovery](https://github.com/isearchxsolve/bounty-control/actions/runs/41753372348),
[#54 latest](https://github.com/isearchxsolve/bounty-control/actions/runs/41753446013),
[#54 earlier](https://github.com/isearchxsolve/bounty-control/actions/runs/41744466406),
[#86](https://github.com/isearchxsolve/bounty-control/actions/runs/41744567836),
[Dispo](https://github.com/isearchxsolve/bounty-control/actions/runs/41660230924).

These examples support a shared contract problem: working directory, argv shape,
environment, companion-test paths and recoverable source files do not have one
consistently enforced representation across preparation, engineering and release.

The generic release feedback compounds it: `actions_delivery.py` tells the model
to change `expected_failure` to the actual error whenever the defect assertion did
not match. For a missing project/runtime error, that advice points at changing the
assertion instead of fixing execution context. The hint is confirmed in code and
the #54 diagnostic; successful concealment of such an error was not established.

## Why the failures repeat

Reconciliation repair dispatch bypasses the normal discovery capacity gate. In
[discovery run 41743861212](https://github.com/isearchxsolve/bounty-control/actions/runs/41743861212),
it dispatched six Lux repairs. All six engineering jobs overlapped from
00:10:31 to 00:30:02 UTC, while normal intake uses a global capacity of four.
Actions concurrency is per issue, so different issues do not serialize each other.
This increases load and the number of simultaneous failures. It does not prove
concurrency caused the particular binary/cwd defects.

Lux #102's repeated deterministic host failure consumed attempt three before the
relevant cache repair `ebf3a38` arrived. Attempts remain bounded: #54 and #102 both
have `attempt=3`, `dispatch_attempt=3`. The observed stream is not evidence of
unlimited counter resets for those identities.

Recovery does work in part: #54 restored eight actual source/test files and resumed
plan validation, then advanced to a different gate. Some retries on the same harness
also produced real PRs. A blanket requirement to change the harness SHA before any
retry would therefore be wrong. The missing decision is whether the recorded cause
or its prerequisites have actually changed enough to justify another attempt.

## Why testing did not prevent this

The latest independent probe run was
[41683203688](https://github.com/isearchxsolve/bounty-control/actions/runs/41683203688),
on `96c8813`, at 22:50 IST on November 3. Its report says `tests_run=620`,
`passed=true`, two BLOCKED receipts, and `full_e2e_passed=false`.

That runner imports original suites whose dependencies are still mocked. In
`test_e2e_full_pipeline.py`, canned checks/reviews and direct writes of `VERIFIED`
and publication states still produced passing methods. Importing such a suite into
the live runner does not replace those boundaries. Other probes do use real GitHub,
HTTP, processes and native gates; the result is mixed assurance.

There was no later independent probe run in the captured workflow history after
the overnight toolchain/model/gate changes. Push CI runs the offline manifest with
credentials removed. Automatic delivery is not gated on a probe receipt for its
deployed revision.

Additional confirmed reporting/resume weaknesses:

- BLOCKED results are excluded from the live runner's aggregate success calculation
  and treated as already completed on resume.
- A passing subtest can cause its entire parent method, including a failed sibling,
  to be filtered out on resume because subtest suffixes are stripped.
- Stored source hashes are overwritten rather than compared before reusing PASS.
- Reconciliation appends repeated failed-check observations to history. Kendraio
  #169 has eight failure entries at attempt one.
- Recovered AWAITING_REVIEW rows retain old failure diagnostics. Those strings do
  not prove the latest generation is still failing.

These are assurance/reporting defects. They are not each independently established
as the direct cause of a particular overnight customer-code failure.

## Repair churn and the latest fix

Acceptance also changed during the repair loop: `e86babb` made publisher whitespace
validation nonfatal while engineering still rejects it. `ebf3a38` introduced path
inference/suffix matching where explicit companion paths had been required. Such
changes need contract review and appropriate live evidence; a greener outcome
alone cannot establish that the original fault was repaired.

The cache/path fix `ebf3a38` and cwd fix `580cb9f` were committed after the sampled
Lux failures. Those old failures do not prove either new fix failed in production.

However, the newest cwd change has a locally reproduced composition defect:
`engineer()` selects `cwd=lux`, while `regression_proof()` prepends `cd lux` for a
non-bash argv. The combined path tries `lux/lux`.

Using the actual production `regression_proof()` on a temporary real Git repository:

- Root-cwd positive control: actual red exit 1, green exit 0.
- Current engineer's subproject-cwd convention: actual failure
  `cd: lux: No such file or directory`.

The trace is retained in
[`monorepo-reproduction.txt`](../scratch/rca-20261104/monorepo-reproduction.txt).
Contract CI for `580cb9f` nevertheless passed:
[41757771987](https://github.com/isearchxsolve/bounty-control/actions/runs/41757771987).
This is a verified local regression, not a claim of a post-fix production incident.
The same change also turns argv into unquoted shell text; its broader impact was
not tested in this investigation.

### Resolution in commit `179e37f`

The composition defect and shell-text quoting were addressed in commit [`179e37f`](https://github.com/isearchxsolve/bounty-control/commit/179e37f):
1. **Single-Hop Root Execution**: `actions_delivery.py` retains `cwd=root`, removing the subproject cwd override.
2. **Encapsulated Subproject Transition**: `regression_proof` detects monorepo subprojects (`project_dir != root_resolved`) and executes `bash -lc "cd {rel_p} && {shlex.join(command)}"`, matching the root-cwd positive control.
3. **Safe Shell Quoting**: Replaced raw string joining with `shlex.join(command)` to guarantee tokenization and quote preservation.
4. **Verified Positive Control**: The root-cwd execution passes red-to-green cleanly without double-cd errors.

### Resolution in commit `32b0a08` (Baba Law 85 Enforcement)

The final brittle static gate crashes that aborted verified green repairs in runs [`41759254523`](https://github.com/isearchxsolve/bounty-control/actions/runs/41759254523) and [`41759293637`](https://github.com/isearchxsolve/bounty-control/actions/runs/41759293637) were resolved in commit [`32b0a08`](https://github.com/isearchxsolve/bounty-control/commit/32b0a08):
1. **Monorepo Subproject Source Resolution**: If Cline cites a manifest relative to a subproject (e.g. `mix.exs` vs `lux/mix.exs`), [`delivery_supervisor.py`](file:///D:/bc/scripts/delivery_supervisor.py) searches within the repository checkout and resolves the canonical repository path automatically.
2. **SHA-256 Tolerance & Normalization**: Evaluates committed git blob hash, working tree disk hash, CRLF/LF normalized hashes, and cryptographic 16+ hex prefix matches (`len >= 16`). Standardizes the citation to the canonical committed object hash for downstream bundle validation in [`actions_delivery.py`](file:///D:/bc/scripts/actions_delivery.py).
3. **Shell Wrapper Token Extraction in Baseline Gate**: Tokenizes shell wrapper arguments (e.g. `bash -lc "cd lux && mix test.unit ..."`) using alphanumeric word boundaries so subproject targets (e.g. `test.unit`) are correctly recognized, permanently eliminating false "dropped baseline test target" rejections.
4. **Verified by Comprehensive Test Suite**: 92 test cases across `test_cline_delivery_ownership.py`, `test_actions_migration.py`, and `test_preparation_contract.py` pass 100%.

## Progress that is real

Four sampled green workflows produced actual release artifacts with successful
native receipts and red-to-green regression proof, and published matching heads:
Lux PRs [1115](https://github.com/Spectral-Finance/lux/pull/1115),
[1116](https://github.com/Spectral-Finance/lux/pull/1116),
[1117](https://github.com/Spectral-Finance/lux/pull/1117), and
[1118](https://github.com/Spectral-Finance/lux/pull/1118).
They are open and AWAITING_REVIEW, with no remote checks/reviews observed; publication
is not merged delivery or payment. The snapshot's sole DELIVERED row was an older
livefire sandbox issue, not a newly completed customer issue.

Model errors are one contributor, as the #86 regression contract demonstrates.
The artifacts do not establish per-call responder identity well enough for a clean
DeepSeek-versus-Nemotron causal comparison. Confirmed cwd, schema and cache-handling
defects exist independently of that comparison.

## Repair priorities supported by this evidence

1. Make argv, cwd, environment, test paths and recovery source inputs explicit and
   consistent across real execution and release. Validate facts/types/paths; give
   the model gate feedback to correct its plan instead of silently guessing context.
2. Repair the cwd composition once, then independently probe the exact invocation
   used by engineering and release, including monorepos and malformed command input.
3. Preserve actual source edits and ownership/attempt history while excluding build
   contamination from source recovery. Verify continuation against the offending
   real checkpoint, not an empty fixture.
4. Apply the same factual capacity gate to every dispatch origin. Let the repair
   agent assess the actual cause and changed prerequisites before spending an attempt.
5. Complete the original suite's real boundary wiring. Keep independent probes
   independent of delivery campaigns, count BLOCKED as incomplete, and revalidate
   failed/affected assertions and source provenance on resume.
6. Report current-generation status separately from historical diagnostics, repeat
   sightings, expected fault injections, refusals and maintainer waiting states.

Detailed captured evidence: `scratch/rca-20261104/runs.json`, `fleet-state.json`,
`commits.txt`, `customer/`, `coverage/`, `retries/`, `surface/`, and `dispo/`.
This RCA assigns confirmed examples and shared mechanisms; it does not claim every
one of the 41 failed customer invocations has been individually diagnosed.
