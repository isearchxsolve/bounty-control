# Production repairs during live master execution

The same master suite was executed from the real entry door against original
`fiztoz/uptime-phoenix#198`. Production code was repaired in response to its failures;
the release and evidence gates were retained.

## Repairs

- `21b53bd`: hydration selects the actual agent queue; the coordinator and CLI retain
  the two-round repair budget; explicit upstream PR restrictions block reservation
  before spending another engineering attempt.
- `7f59b35`: hydration runs independently of long discovery calls and never writes
  an old snapshot over discovery's shared cache. Remote task CAS still fences dispatch.
- `565b983`: the agent can call `check_entry_shortlist.py`, the real read-only
  production verifier; every repair round retains its scope and tool access; exact
  verifier details reach the agent; the existing owner-request field is in the schema.
- `c4f2413`: restore the missing NVIDIA cooldown refresh method; a permanently
  unavailable primary cannot suppress the fallback's positive cooldown; unexpected
  failover exceptions are surfaced rather than hidden behind the primary error.
  The NVIDIA regression suite is now included in the master allowlist.

## Live evidence

- [Drain 41533546368](https://github.com/isearchxsolve/bounty-control/actions/runs/41533546368)
  succeeded: HYDRATE_ONLY, 43 decisions examined, 20 qualified, two real dispatches.
  Eighteen source revisions required agent reconsideration; three exceeded repository
  capacity and two repositories were unavailable. These refusals were not bypassed.
- Released original issues: `jorgedvp/aks-store-demo#4` and `getkcoin-alt/itsmay#27`.
- [Master 41534682363](https://github.com/isearchxsolve/bounty-control/actions/runs/41534682363)
  passed LIVE_INTAKE against actual drain artifacts, then exposed provider exhaustion.
  Logs showed working NVIDIA responses followed by HTTP 429 and the broken cooldown path.
- [Contract CI 41535878917](https://github.com/isearchxsolve/bounty-control/actions/runs/41535878917)
  succeeded on the provider repair. Seventeen router tests also passed locally, including
  cooldown expiry and recovery while the primary pool has no recoverable key.
- [Post-repair master 41535881398](https://github.com/isearchxsolve/bounty-control/actions/runs/41535881398)
  was started on the repaired production version. Its final live outcome must be checked
  before treating the provider and entry-door repairs as live acceptance evidence.

## External constraint

The selected upstream repository allows PR creation only by collaborators. The publisher
has read access and no push permission. Code cannot grant that upstream permission.
Publication and full E2E success must remain blocked until the upstream owner changes
access or another permitted original is selected. No payment settlement is inferred.
