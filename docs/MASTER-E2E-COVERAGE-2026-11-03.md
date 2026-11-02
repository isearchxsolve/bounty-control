# Master live integration coverage update

The existing master driver and workflow remain the entry point. Target selection
can point to a real original issue. This update adds production discovery, durable
queue deferral/recovery/replay, live intake health, and mandatory case accounting.
It does not certify that every conceivable infrastructure fault has been exercised.

## Implemented execution path

1. Read deployed discovery, hydration and heartbeat workflows and actual discovery
   artifacts. Check execution freshness, failure status and waiting work without an
   automatic drain. Retain the queue and census.
2. Check actual target access and workflow deployment. Original issues are read;
   sandbox provisioning remains available through the existing contract.
3. Run actual remote state/authentication, ownership/race/retry-cap/corruption cases
   on the isolated fault branch, plus the real rejected-generation Actions run.
4. Use the production discovery agent and evidence validation on the scoped issue.
   A zero dispatch budget must persist a waiting row without touching remote state.
5. Reject corrupted copies of the actual evidence against freshly fetched sources.
6. Reopen the SQLite queue and run production hydration with dispatch budget released.
   Respect actual fleet capacity; verify a second replay creates no generation.
7. Observe actual claim, engineering, independent red/green and native verification,
   release bundle, publication, head checks and real remote CI.
8. Reject corrupt copies of the actual release. After authorized sandbox merge or
   maintainer merge of an original, verify reconciliation replay and unverified payment.
9. Require every case in `run.json.coverage` to PASS before setting
   `end_to_end_passed`. Failed, pending and unexecuted cases cannot pass acceptance.

## Verification

- Deployed implementation: `d89857f9cb27ea775339ac4a5b340324c3ef5544`.
- Contract CI: [41502452032](https://github.com/isearchxsolve/bounty-control/actions/runs/41502452032), success.
- Local contract run: 59/60 passed in the restricted environment. The temporary Git
  clone suite failed there, then passed 1/1 outside the sandbox. Other suites were
  not rerun unnecessarily. Compile, undefined/unused-name and diff checks passed.
- Same hosted master against original `fiztoz/uptime-phoenix#198`:
  [41503760549](https://github.com/isearchxsolve/bounty-control/actions/runs/41503760549), failure.
  Actual discovery artifact showed 32 capacity-wait and 9 deferred rows, with no
  scheduled hydration drain. Target metadata separately showed collaborator-only
  PR creation and no publisher write permission. Both blockers were retained.
- The coverage journal correctly marks dependent cases NOT_RUN, with
  `end_to_end_passed: false`. Original issue/repository were not modified.
- Hosted receipts: `scratch/master-e2e-hosted-41503760549/`.

The newly implemented positive queue-to-delivery path has not completed a live
acceptance campaign: the selected original is access-blocked. A successful contract
CI is not substituted for that missing live evidence. Provider-wide outage, resource
exhaustion, independent reviewer actions and payment settlement remain outside the
controlled live cases, as recorded in the driver and guide.
