# Live pipeline integration

This suite calls real GitHub APIs, real model providers through the production gateway,
the real Cline CLI, production `engine2.yml`, real GitHub Contents state, real Git
objects, real native commands, and actual PR/merge/reconciliation operations.
It contains no mocked network responses, in-memory replacement ledger, or fabricated
successful engineering/publication receipt.

The existing offline master suite is a separate regression layer. It is not live
end-to-end evidence and does not satisfy this suite's acceptance condition.

The master now runs `intake` before delivery and before merge acceptance. It reads
the deployed discovery/hydration workflows, downloads the latest completed real
discovery artifact, and inspects its SQLite queue and census. It fails on missing
receipts, failed or stale discovery (90 minutes by default, configurable with
`--intake-max-age-minutes`), inactive scheduled discovery, or capacity-wait work
without the scheduled hydration path that replays it. The receipts are retained
under `intake-<run-id>`. A delivery-only success cannot bypass this gate.

An intake failure is retained while independent scoped delivery checks continue;
it still prevents end-to-end acceptance. Scope/access failures stop dependent work.

Admission now uses production `agent_door.find_issues` and `sovereign_discovery.discover`,
scoped to the selected original. The real agent reads sources and submits evidence
through production validation. With a zero dispatch budget the real SQLite queue must
persist `capacity_wait` and leave the remote task ledger untouched. A subsequent call
reopens that database and uses production hydration with a released dispatch budget.
Actual fleet capacity and ownership gates still apply. A second hydration call must
send no additional dispatch and preserve the delivery generation. Corrupted copies
of the actual admission exercise identity, freshness, unavailable competition and
missing-proof rejection without changing upstream sources.

`run.json.coverage` lists every required case as PASS, FAIL, PENDING or NOT_RUN.
Acceptance requires all required cases to pass, including remote storage/auth faults,
claim fencing, queue recovery, real Actions engineering/native checks/publication,
release corruption rejection, merge and reconciliation replay. Individual phases
remain resumable, but cannot mark the campaign green with missing cases.

This tests controlled capacity-budget release against real sources, storage and
Actions. It does not claim scheduler execution under every outage or exhaustive
failure coverage. Provider-wide outages, OOM/disk exhaustion, review by an independent
account and actual payment settlement remain explicitly outside exercised coverage.

The first fully successful campaign, including 19 real fault cases and issue-to-merge
delivery, is recorded in [the repair receipt](PIPELINE-REPAIR-RECEIPT-2026-11-02.md).


## Run

The same suite can target an existing original issue. Only target selection/setup
changes; no replacement issue, seeded source defect, or new upstream CI is created:

```powershell
python scripts/live_pipeline_integration.py run --target fiztoz/uptime-phoenix --issue 198 --run-dir scratch/master-original-198
```

The hosted workflow exposes the same `target_repo` and `issue_number` inputs. Without
an issue number, the existing sandbox behavior remains the default. All stages, native
and release gates, exit semantics, and `end_to_end_passed` requirements remain in force.
An explicit upstream PR access restriction fails preflight and later stages stay
unexecuted. A permitted original target proceeds through the normal pipeline, which
can publish a real PR; cleanup never closes that original issue/PR, and the suite never
merges it on behalf of its maintainer. It can pass merge verification once the maintainer
has merged it. These are the target's real permissions, not bypasses of the suite.

The original mode proposed during investigation was removed: there is no separate
audit contract replacing the master suite.

```powershell
python -u scripts/live_pipeline_integration.py run --run-dir scratch/live-campaign --merge-fixture
```

Requirements: authenticated `gh` with control-repo Actions dispatch and sandbox write
permissions; Python, Git, Node and Cline; the real provider key configuration used by
the production gateway. Do not print or copy secret values into reports. The provided
manual GitHub Actions workflow uses the existing repository secrets.

The approved target is `isearchxsolve/oss-hunter-livefire`; the actual deployed delivery
workflow is in `isearchxsolve/bounty-control`. Preflight verifies owner/admin access and
the target's explicit sandbox description. Provision creates a unique small defective
module, passing native baseline tests, CI, and a clearly labelled unpriced owner request.
There is no fake payment promise. The model must actually read and admit that request.

The production delivery is dispatched normally and receives a 1,800-second engineering
budget. Capacity remains bounded by the production fleet's four-slot gate. The control
ledger is the real production ledger for this test task. Storage fault injection uses
`live-integration/<campaign-id>` instead of its production state branch.

Commands are resumable, but run only one command at a time per run directory:

```powershell
python scripts/live_pipeline_integration.py provision --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py faults --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py negative-claim --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py observe-negative --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py admit --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py dispatch --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py wait --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py artifact-faults --run-dir scratch/live-campaign
python scripts/live_pipeline_integration.py merge --run-dir scratch/live-campaign
```

`observe` takes one snapshot; `wait` polls up to `--wait-minutes` (default 60).
If dispatch acknowledgement is lost, resume `dispatch`: it reads the existing generation
instead of blindly sending another event. A provider or engineering failure stays a
failure. Never seed an admission/release document to get past it. A fresh `admit` performs
another actual model run and retains a separate attempt directory.

The invalid-generation test uses a separate issue and asserts that its rejected claim
caused no state change. `run` executes it before positive dispatch. Fault branch
records deliberately seed input states to exercise gates; they are explicitly labelled
fault inputs and never evidence that engineering or publication occurred.

## Executable live cases

| Case | Actual interaction and required evidence |
|---|---|
| Environment | Authenticated account, target admin permission, active production workflow, local/deployed SHA |
| Fixture | Real Git tree/commit and GitHub issue URL; unique module and passing baseline |
| Provider/scout | Real provider calls, actual Cline tools reading GitHub, actual shortlist and verified literal citations |
| Storage roundtrip | Unicode/newline bytes written and reread from GitHub Contents with a remote blob SHA |
| CAS conflict | Actual competing remote revision; stale SHA PUT receives 409/422 and preserves winning bytes |
| Concurrent claim | Two barrier-synchronized calls against real GitHub state; exactly one owner and one attempt |
| Claim replay | Same owner/generation reclaims without consuming another attempt |
| Stale generation | Real durable current generation rejects an old generation |
| Wrong/revoked owner | Actual durable owner/revocation prevents update/assertion |
| Retry cap | Fourth normal claim rejected against a real remote seeded attempt counter |
| Corrupt state | Truncated JSON written remotely; real read fails; original bytes restored |
| Authentication | Invalid test token receives an actual GitHub 401 |
| Missing resource | Random nonexistent test repository receives an actual GitHub 404 |
| Workflow rejection | Real manual Actions run with invalid generation: claim fails for the exact expected reason; engineer/publish skipped; ledger unchanged |
| Dispatch | Real `repository_dispatch`, durable generation, task ID and storage revision |
| Claim/engineering | Actual Actions jobs, claimed owner, model/native execution, downloaded artifacts |
| Publication | Actual PR and exact matching release/durable/remote head SHA; no simulated status transitions |
| CI | GitHub check-runs/statuses for the actual PR head; absent/pending/held/failing is not green |
| Release control | Validate the actual downloaded release bundle with a real remote clone and Git object inspection |
| Corrupt release | Copies of that actual receipt with incorrect task/head/tree/file manifest, missing native receipts, false red/green results must be refused |
| Merge/replay | Actual sandbox merge; two production reconciliation passes converge to DELIVERED |
| Payment | Must remain UNVERIFIED; no settlement is performed or inferred |

A successful campaign requires `end_to_end_passed: true`, a passed invalid-generation
run, and no failed live fault assertions. Exit zero from an individual phase means only
that phase completed; PENDING is not an end-to-end pass. The complete `run` command
returns nonzero if it cannot finish through merge. Reports preserve failures rather than
rewriting the earlier attempt as successful after a retry.

## Scope and gaps

This is a scoped live issue-to-merge exercise. It uses the production Cline search
function and evidence gates with a specified test issue. It does not prove unrestricted
scheduled discovery can find arbitrary commercial work. It also does not claim that
every possible failure has been exercised.

Provider failures can occur naturally and remain in the logs. The default isolated
gateway serves the actual production handler on a private port with real provider calls;
`--gateway existing` exercises the pre-existing local proxy instead. Neither supplies
fake model output. The real production Actions engineering jobs use their own deployed
gateway and configured secrets.

Not yet executable as controlled live injections: provider-wide outage/429 campaigns,
runner disk-full/OOM, process death at every publication boundary, GitHub-wide outage,
cross-account reviewer approval/change requests, untrusted fork credential isolation,
and financial settlement. Killing shared workers, exhausting shared quotas, corrupting
production task records, or inventing paid bounty claims is not an acceptable way to
claim that coverage. These require disposable worker-level fault controls and, for
reviews, a second authorized identity. The run journal lists these gaps explicitly.

If an early real stage fails, later stages remain unexecuted. The driver must report
that actual failure; it must never substitute a fixture success to finish the diagram.

## Artifacts and cleanup

`run.json` is the durable journal; phase logs, Cline attempt outputs, admission proof,
actual Actions job observations, downloaded release bundles and native receipts supply
the evidence. Profiles containing local proxy credentials are excluded from the workflow
upload list. Actual test-owned GitHub URLs and hashes are retained in the journal.

`cleanup` closes only this campaign's issue and unmerged PR after its workflow is
completed. It retains source fixtures, the fault branch, production task history and
Actions artifacts for diagnosis. It does not delete repositories, erase failures, stop
other workers, or turn off shared automation. The suite never changes production modules.
