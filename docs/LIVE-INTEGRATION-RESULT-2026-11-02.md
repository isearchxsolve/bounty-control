# Actual live integration result — 2026-11-02

**Result: FAILED in production engineering; not an end-to-end pass.**

This report comes from newly executed real service calls and GitHub Actions jobs, not
mock responses or replayed historical success. Production code was not patched to make
the test green. The live driver, workflow and run instructions are in
`scripts/live_pipeline_integration.py`, `.github/workflows/pipeline-live-integration.yml`
and `docs/LIVE-PIPELINE-INTEGRATION.md`.

## Remote evidence

- Campaign: `r86314ea55eb4`.
- [Real owner-request fixture](https://github.com/isearchxsolve/oss-hunter-livefire/issues/1).
- [Actual fixture commit](https://github.com/isearchxsolve/oss-hunter-livefire/commit/d6c0ad31365cd3785f42a66e8b427709e7bc4c9b).
- [Actual production delivery](https://github.com/isearchxsolve/bounty-control/actions/runs/41456288563).
- [Actual invalid-generation rejection](https://github.com/isearchxsolve/bounty-control/actions/runs/41457042954).
- Production harness SHA: `b9f245366c7c6d94d52c8be985d41977a7c85187`.
- Durable task ID: `f6e765705b42f1517363469c39d501fd`.
- Dispatch generation: `4e5270a06c5a4255aa19d8b4c77cfcf7`.
- Fault-only state branch: `live-integration/r86314ea55eb4` in the control repository.

## What actually ran

| Stage | Observed result |
|---|---|
| Existing local gateway | Scout failed on actual TokenHarbor 429/free allowance exhaustion |
| Current isolated production gateway | Actual TokenHarbor calls exhausted available slots; actual NVIDIA fallback returned tool calls |
| Real Cline scout | Read issue and source through GitHub; wrote its own candidate |
| Admission | Production literal-source, amount/owner, code-blob, repository and competition gates admitted the owner request |
| Dispatch | Real repository_dispatch and durable generation created |
| Claim job | Succeeded in production Actions |
| Model wire and preparation | Live model tool round trip and real native baseline succeeded |
| Engineering | Produced changed source and a companion regression test, then failed release artifact verification |
| Publication | Skipped by Actions after engineering failure |
| Finish/reconciliation | Recorded FAILED_ENGINEER, retryable, with failure history |
| PR/CI/merge/payment | Not reached by this positive case; not counted as passed |

## Failure chain

The first retained release-verification feedback states:

```text
Independent release verification failed: [Errno 2] No such file or directory:
'/tmp/fleet-artifacts/regression.json'
```

The engineering contract requires this JSON receipt to name companion test paths,
the exact native regression command and the specific expected failure. The host
could not execute its independent red-to-green release proof without that receipt.

Recovered source artifacts contain `return days * 86400` and a new regression test
covering 1/2/7 days, zero, negative inputs, booleans and nonintegers. Thus the final
"no changes" label is not evidence that the model never implemented the fix.

Later model turns explicitly treated the missing receipt as infrastructure they should
not create. The bounded loop eventually recorded:

```text
Bounded Cline delivery repair exhausted: Cline failed closed on turn 1:
Cline completed without modifying repository files; using legacy proposal fallback.
```

Observed failure: the engineering-to-release artifact handoff was not completed, and
the final diagnosis obscures the earlier missing-receipt failure. The model's source
fix alone must not be substituted for the absent release proof. The test correctly
remains red. Root-cause repair and a fresh full live rerun are still required.

## Fault tests actually exercised

Eleven GitHub-backed cases passed: Unicode state roundtrip; stale SHA write conflict;
two simultaneous claimants with exactly one winner; same-owner replay; stale generation;
wrong owner; revoked owner; attempt cap; remote truncated-JSON detection and restoration;
actual invalid-token HTTP 401; actual missing-repository HTTP 404.

A twelfth independent case submitted an invalid generation to the real delivery
workflow. Its claim job failed with `Matching admitted dispatch generation required`,
engineering and publication were skipped, and its separate task's ledger stayed unchanged.

These are bounded real failures and observations. They are not full coverage of every
possible outage, crash timing, review state, resource exhaustion or financial operation.
The driver also implements validation of corrupt copies of actual release artifacts,
publication/head matching, real CI, merge and replay; this campaign could not execute
those downstream cases because the real engineering stage failed.

## Test-driver correction

The first negative workflow dispatch used a commit SHA as its `ref`. GitHub explicitly
rejected that request with HTTP 422 (`No ref found`). The driver was corrected to use
the real branch ref; the rejected attempt remains in the journal. The successful
negative test above is the subsequent actual Actions run, not the rejected API request.

## Retained local evidence

Under `scratch/live-pipeline-20261102/`:

- `run.json`: live event journal, remote IDs and `end_to_end_passed: false`.
- `scout-result.json`, `scout/agent.log`: initial real 429 failure.
- `scout-2/result.json`, `scout-2/agent.log`: actual admitted scout attempt.
- `admission.json`: actual model candidate and verified proof.
- `jobs.json`, `remote-state.json`: actual Actions jobs and failed durable state.
- `production-failure.log`: actual failed engineering job log.
- `negative-claim.log`: actual invalid-generation claim refusal.
- `artifacts-41456288563/`: actual claim, provider wire, preparation, failure and recovery artifacts.

The positive run consumed approximately six minutes from dispatch through terminal
reconciliation; its engineering allowance was bounded to 1,800 seconds. No customer
repository was modified and no payment was represented as earned. Test issues are
closed after verification, while source/state/artifact evidence is retained. The new
manual suite workflow is prepared locally; it has not been published to the control repo.
