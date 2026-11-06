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

3. **The 46-of-50 self-closure mechanism.** 46 of our 50 closed PRs were closed by our own
   account; 37 within six hours of creation, 10 within one hour. Undiagnosed. This is the
   wound that makes every other fix academic — a PR that dies the same afternoon cannot be
   claimed, reviewed or merged.
4. **Three maintainer-found defects, all unfixed, all blocked on a local toolchain:**
   - `fyne-io/fyne#6637` — native upload-queue check fails 3 of 4 on our branch, base passes
     all 4. Reviewer named the fix: "a local version that retains separate upload bytes
     passes all four". Needs Go; not installed.
   - `bl4ckb4ll/blackball#182` — `fedtax(103350)` is a positive 22%-bracket tax and
     `fedtax(103351)` returns 0; the function's last branch is `return (0)`. Reproduced in
     code. Needs bash + bc; neither installed.
   - `geekinasuit/obolus#131` — failing test after our own fix. Needs cargo; not installed.
5. **My own closure triage defect.** The 28-PR cleanup read PR *comments* and never PR
   *reviews*, so `stride3d/stride#3816` was closed carrying MsEpsilon's unread warning:
   "the OP seems like a bot (or behaving like one) and the source looks entirely
   LLM-generated, I'd be very cautious with this PR". Re-audit every closure against reviews.
6. **`engineering_contract.py` is a dead module.** It pins reviewer-named boundary inputs and
   the edge-class requirement, but nothing calls it, so no publication is gated by it. Wire it
   into the pre-publish path or delete it — an unused gate is worse than none, because it
   reads as a fix.
7. **The agent turn never completes.** Last live cycle: `agent_exit: -1, rows: 0, counts: {}`.
   The turn spent its budget launching background scanners that outlived it and was killed
   mid-investigation. Found; not fixed. Nothing can be admitted until a turn finishes.
8. **`docs/MARKET-POOL-2026-11-06.md` states 34 escrow tickets. The measured total is 59.** I
   under-measured by never querying `bountyhub-bot`, which holds 25. The document is wrong in
   the repo.

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
