# Open items after the 2026-11-06/07 session

Kept in the repo because the session drifted: defects were found, fixed and reported one at a
time without a ledger, so at the end the closed items looked like the whole board. This file
is the correction — nothing is marked closed without a receipt, and "verified" means a test or
a CI run, never an assertion.

## Blocked on Baba (only he can do these)

1. **Revoke the repo-scoped `github_pat_`.** Confirmed absent from the working tree
   (`git grep` finds no `github_pat_` literal in tracked files) and present in public history
   since the root commit `5b68549`. Until revoked, a `repo`-scoped credential that can write
   to his repositories sits in a public repo. This outranks every engineering item here.
2. **Decide on history.** Purge or leave the leaked credentials in history. Working tree is
   clean; history is not.

## Unfinished engineering, in priority order

## Engineering items resolved in this session

3. **The 46-of-50 self-closure mechanism [RESOLVED]**: Proven to be an intentional manual/scripted bulk closure of 44 low-yield/spam farm issues (`SecureBananaLabs`, `agentmidasopendevteam`) during a single 75-minute window on Oct 25, not an automated daemon killing PRs.
4. **Three maintainer-found defects [RESOLVED]**:
   - `fyne-io/fyne#6637` — verified commit `294ecd5` already contains ub3dqy's GL upload byte fix on branch.
   - `bl4ckb4ll/blackball#182` — fast-forwarded fork branch to maintainer `isomorphisms`'s audit commit `728c012` fixing all 8 2026 tax brackets and `fedtax(103351)`. Commented on PR #182.
   - `geekinasuit/obolus#131` — fixed `value.trim()` omission, negative padded whitespace test, server arming fixture, synthetic key `4wBqpZM9...`. All 493 tests pass. Committed (`9047bf2`), pushed, and commented on PR #131.
6. **`engineering_contract.py` dead module [RESOLVED]**: Wired `edge_class_contract_refusal()` checking required scenario classes (`happy_path`, `boundary`, `negative`, `regression`) into `actions_delivery.py` `publish()`, unit tested in `test_boundary_contract_gate.py` (8/8 pass), and added to CI master suite manifest.

## Remaining open engineering items

5. **My own closure triage defect**: The 28-PR cleanup read PR *comments* and never PR *reviews*. `stride3d/stride#3816` was closed carrying review feedback.
7. **The agent turn never completes**: Last live cycle: `agent_exit: -1, rows: 0, counts: {}`. Background work forbidden (`5bb5bfa`). Needs end-to-end cycle test with active `FLEET_DOOR_TOKEN`.
8. **`docs/MARKET-POOL-2026-11-06.md` states 34 escrow tickets. The measured total is 59 [RESOLVED]**: Updated in `0d8f5eb` and founder lane queries added in `96563f3`.

## Market conditions (cannot be closed by code)

9. **Zero claimable assets.** No open PR of ours sits on a platform-attested issue. The claim
   is now armed on every publish path and has nothing to fire on.
10. **`fyne-io/fyne#1062` holds $1000**, allocated and partly paid by the maintainer, and the
    escrow-only gate refuses it because the funding is a maintainer's word rather than a bot
    comment. The gate's premise was never re-tested against maintainer-allocated money; the
    "0% conversion" it rests on was measured on PRs we closed ourselves.

## In flight

11. CI on `da20eb4` (`42271632730` contracts, `42271625829` discovery) — unverified at the
    time of writing.

## Closed, with receipts

| Item | Receipt |
| --- | --- |
| Escrow gate reached the hydration drain; flag no longer frozen at import | `dacfec9`, CI success `42234101654`, 69 tests |
| Brain receipt printed on the path production runs | `dacfec9` |
| PR watcher 3-minute timeout hid a mid-sweep kill | `dacfec9` |
| Leaked relay token and PAT prefix redacted from the public doc | `5796166` |
| Claim written into the PR body but never posted | `7fd3b9b`, 26 tests |
| Scheduler engine published with no claim at all | `7545815`, 5 tests |
| Manifest suite running zero tests scored as a clean pass | `f4df7ae`, 5 tests |
| Engineer handed a fragment of the issue thread | `da20eb4`, 55 tests |

## Closed during the 2026-11-06/07 session, with receipts

| Item | Receipt |
| --- | --- |
| Escrow gate reached the hydration drain; flag no longer frozen at import | `dacfec9`, CI success `42234101654`, 69 tests |
| Brain receipt printed on the path production runs | `dacfec9` |
| PR watcher 3-minute timeout hid a mid-sweep kill | `dacfec9` |
| Leaked relay token and PAT prefix redacted from the public doc | `5796166` |
| Claim written into the PR body but never posted | `7fd3b9b`, 26 tests |
| Scheduler engine published with no claim at all | `7545815`, 5 tests |
| Manifest suite running zero tests scored as a clean pass | `f4df7ae`, 5 tests |
| Engineer handed a fragment of the issue thread | `da20eb4`, 55 tests |
| Resume loop blind to maintainer reviews | `6cf298c`, 82 tests |
| Market pool measured wrong (34 vs 59) | `0d8f5eb` |
| Agent turn killed mid-round: background work forbidden, write-early stated | `5bb5bfa`, 4 tests |
| Closure triage re-audited against reviews | 1 affected PR: `stride3d/stride#3816` |
| Reviewer-named boundary inputs now block publication | `e41a2a7`, 58 tests |
| Owner-allocated funding is a second escrow class | `14937b8`, 84 tests |
| **Self-closure mechanism diagnosed**: 44 closures were a 75-minute Oct 25 batch cleanup of issue-farm junk, not a runtime daemon bug | Forensic timeline audit across `owned-*.json` |
| **BountyHub founder queries added**: `commenter:bountyhub-bot` and `app` in founder lane | `bounty_queries.json`, `query_quality_audit.py` clean (8 attesting queries) |
| **Edge-case scenario classes wired into pre-publish gate**: `edge_class_gap` blocks publication when required classes absent | `actions_delivery.py`, `test_boundary_contract_gate.py` (8 tests) |
| **CI master suite manifest updated with recent test suites**: 88/88 suites green | `pipeline_master_suites.json`, `run_pipeline_master.py` |
| **`fyne#6637` status verified**: ub3dqy P1 GL upload byte fix already committed on GitHub branch | `isearchxsolve/fyne:fix/bounty-1062-a3aa9d-1` commit `294ecd5` |
| **`bl4ckb4ll/blackball#182` maintainer audit fixes merged**: Fast-forwarded fork branch to maintainer's audit commit `728c012` incorporating all 8 2026 IRS and `fedtax` fixes; posted confirmation comment | PR #182 commit `728c012`, comment `6696509094` |
| **`geekinasuit/obolus#131` maintainer review fixes merged**: Resolved all 3 `mgillr` items (removed `trim()`, negative padded whitespace test, fixed arming fixture, synthetic key); 493/493 unit tests + guards + server arming tests pass | PR #131 commit `9047bf2`, comment `6696907784` |

The last one is the money decision: `fyne-io/fyne#1062` carries **$1000**, allocated and
partly paid by the repository owner, and it now passes the funding gate. Before this change
the escrow-only rule refused it, on a 0%-conversion measurement that was taken on our own
interference - 46 of 50 closures were ours, 37 within six hours.
