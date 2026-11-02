# Live publication 404 investigation

## Finding

`fiztoz/uptime-phoenix` restricts pull request creation to collaborators. The real
publisher account, `isearchxsolve`, has read access and no push/maintain/admin access.
The production attempt pushed its verified change to the correct fork, then received
HTTP 404 when creating the upstream pull request. The repository's contribution
restriction explains why reading/forking/comparing succeeds while PR creation fails.

GitHub documents the policy in [Disabling pull requests](https://docs.github.com/en/enterprise-cloud%40latest/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/disabling-pull-requests).
For personal repositories, a collaborator must be invited. The API policy fields are
documented in [Repository REST settings](https://docs.github.com/en/enterprise-cloud%40latest/rest/repos/repos?apiVersion=2026-03-10).

## Actual observations

- [Failed production publication](https://github.com/isearchxsolve/bounty-control/actions/runs/41488848364):
  failure at `POST repos/fiztoz/uptime-phoenix/pulls`; release artifacts were retained.
- Fork: `isearchxsolve/uptime-phoenix`, parent `fiztoz/uptime-phoenix`.
- Branch: `fix/bounty-198-bd3966-1`.
- Verified pushed commit: `91b3f2944371148dafcd94da994d5716792216e7`.
- GitHub's actual comparison against upstream main reports one commit ahead, zero behind.
- Repository is public, not archived or disabled, and allows forks.
- `has_pull_requests: true` and `pull_request_creation_policy: collaborators_only`.
- Publisher permissions: `pull: true`; `push`, `triage`, `maintain`, `admin`: false.
- [Read-only assertion using the actual GH_PAT secret](https://github.com/isearchxsolve/bounty-control/actions/runs/41496416710)
  passed. It authenticated as `isearchxsolve`, reported OAuth scopes
  `gist, read:org, repo, workflow`, read the repository and pull list, and verified the
  expected policy and lack of push permission. No upstream write was performed.

This distinguishes an upstream access restriction from a missing fork, missing branch,
invalid login, or absent general `repo` scope. No upstream permission was changed and no
extra PR was attempted to test or bypass the owner's restriction.

## Master live campaign

[Campaign 41495586293](https://github.com/isearchxsolve/bounty-control/actions/runs/41495586293)
was started from deployed SHA `966b5e18991f56963dec84588d3fa89cad0db9de`, with real
model admission, Actions delivery, native verification, publication, corruption checks,
merge and reconciliation. Its positive delivery is
[run 41496156712](https://github.com/isearchxsolve/bounty-control/actions/runs/41496156712).

The campaign finished **FAILED_ENGINEER**, with publication correctly skipped. Its
agent-written `regression.json` supplied `expected_failure: days_to_seconds(1) == 86400`,
but the actual restored-base test output was `AssertionError: 3600 != 86400`. The base
did fail on the defect, but its output did not contain the declared literal evidence.
The existing verification gate correctly refused it after bounded repair; it was not
relaxed to turn this run green. Artifacts are retained under
`scratch/live-investigation-delivery-41496156712/` and
`scratch/live-investigation-41495586293/`. Test fixtures were closed.

The original
production retry [41493943796](https://github.com/isearchxsolve/bounty-control/actions/runs/41493943796)
was also still executing engineering during the investigation; no success is inferred.

## Same suite pointed at the original issue

The master driver now accepts an existing original issue through `--target` and `--issue`.
No separate audit phase is used. The fixture setup binds the original issue instead of
creating source/issue fixtures; release gates and passing requirements are retained.

Actual invocation:

```powershell
python scripts/live_pipeline_integration.py run --target fiztoz/uptime-phoenix --issue 198 --run-dir scratch/master-original-uptime-phoenix-198
```

It returned **exit 1 at preflight** with the observed live publication policy and the
exact refusal `Target restricts PR creation to collaborators; publisher has no write access`.
No original issue, repository source, CI, PR or production state was changed by this run.
Later stages were not counted as passed. Evidence is in
`scratch/master-original-uptime-phoenix-198/run.json`.

## Coverage gap and consequence

The master positive fixture belongs to the publisher account. A successful fixture
publication establishes that permitted publication works, but does not establish
that another owner's repository accepts outside PRs. The existing random-resource
404 fault does not exercise this collaborator-only publication restriction.

The pipeline carried a repository-owner issue and literal code/funding evidence through
admission, but did not gate on this explicit GitHub contribution policy. Its failure
receipt classified the publication 404 as retryable, and another engineering attempt
started. Re-engineering the same fix cannot grant repository collaborator access.

The follow-up repair should check the platform's explicit publication-policy facts
before dispatch and again before publication, retain a named access-blocked result,
and preserve the verified patch for authorized handoff. Reading intent and deciding
whether another delivery route is worthwhile remains the model's responsibility.
The upstream owner must grant collaboration or change policy for this account to open
the PR. This investigation does not change production admission/retry behavior.

## Reproduce the read-only assertion

Use the same credential as the publisher:

```powershell
python scripts/publication_access_probe.py --repo fiztoz/uptime-phoenix --expect-policy collaborators_only --expect-push false
```

The probe prints credential category, authenticated login, non-secret scope/request
headers, repository policy and permissions, and assertion outcome. It never prints a
token or posts a PR. The hosted diagnostic branch is
`diagnose/publication-access-20261102`; its workflow overrides are isolated from main.

Original release artifacts and failure logs are under
`scratch/publication-404-41488848364/`, including `publisher-policy-probe.log` and
`publication-failure.log`.
