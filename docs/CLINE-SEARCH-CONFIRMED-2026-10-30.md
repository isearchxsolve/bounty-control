# Cline as the search door: confirmed live (2026-10-30)

## The question
Does Cline actually search GitHub, or does it only look convincing?

## The answer: yes, with receipts
Run `D:\door-runs\run-46505af25a`, workspace built by `scaffold_workspace()`, agent driven through
the local NVIDIA gateway (`127.0.0.1:8099/v1`, 120B). Transcript `D:\tmp\scout-wt2.log`.

Five real search calls, verbatim from the transcript:

    gh search issues --label bounty --state open --limit 40 --json number,title,url,repository
    gh search issues "bounty" --state open --limit 40 --json number,title,url,repository
    gh search issues --label bounty --label "good first issue" --state open --limit 40 --json ...
    gh search issues --label bounty --label "help wanted" --state open --limit 40 --json ...

Agent's own words at the start: "I'll start by searching GitHub for open bounty issues using the
`gh` CLI as specified in TASK.md."

Output: 10 rows, 0 refusals on the first gate pass. Every row was then re-checked against GitHub
(`gh api repos/{repo}/issues/{n}`) and the reward sentence was required to appear literally.

## What actually made it work (after six failed attempts)
1. **The engine's shape, not the engine's prompt.** The delivery engine hands Cline a git worktree
   with the work described inside it. A bare empty directory made the agent hunt for a repository
   and a task; it read our own source files instead of searching.
2. **Engine flag parity.** `[--data-dir, --provider, --model, --key, -y, --retries, -c, prompt]`
   and nothing else. Each flag I had added broke a run: `--system` demanded a TTY, `--json` with
   `--thinking` produced exploratory loops that never searched.
3. **PowerShell, named in the task.** Cline runs Windows PowerShell. `ls -la`, `&&` and
   `2>/dev/null` all fail there, and a failing shell call ends the run. The task file now says so.
4. **Provider file read back, never assumed.** `auth --baseurl` then read `providers.json` and
   require model + baseUrl + key. A hand-written file lost its `baseUrl` and the key went to OpenAI.

## Defects found by running it
1. **bash-in-PowerShell**: every tool call failed in one run (0 searches). Fixed in TASK.md.
2. **Amount-less reward quotes**: `### Bounty:  USDC (Escrow Locked)` passed the literal-quote gate
   because the sentence really was in the issue, but names no money. Added
   `quote_states_an_amount()`; re-running the same 10 rows now refuses 5 and admits 5
   ($250, $350, 250 USDC, $50, $25).

## Not claimed
Search-rate-limit deltas are not usable as proof here: the authenticated search quota resets per
minute, so a before/after reading showed no change even though searches ran. The transcript lines
and the independently re-fetched issues are the proof.

## Next
Wire the door into discovery, and put `scaffold_workspace`, the engine flag set and the amount guard
behind tests in CI (43 door tests pass locally, no network).

## Second round: autonomy, on Baba's order (2026-10-30 ~15:30-16:00 UTC)

Order: "do not handcuff Cline, let it exercise full autonomy; external validation gates are there
to guard and feed feedback to it."

**Removed from the brief** (they were judgements written as instructions): the numbered first step,
the list of `gh search` commands, and the digests/hackathons/design-only taxonomy.
**Kept:** environment facts (no source code here, `gh` authenticated, the shell is PowerShell) and
the output contract `shortlist.jsonl`, because code needs an interface at all.
**Gates:** unchanged, and the feedback now states what each check means instead of a repair script.

### Local proof with no recipe
`D:\tmp\scout-auto.log` (run-a09ef17a2c): 4 `gh search` calls, 30 `gh issue view` calls, 3 rows,
**2 admitted, 1 refused**. Nothing in the brief told it what to search or what counts as money.

### The gates earned their keep, and one of them was wrong
Refused rows were re-read from source, not argued with:
- `Rooner-Plugins/bank-value-changes#3` quotes "I'm willing to pay for this to be added." — real
  intent, **no amount anywhere in the issue**. Correct refusal.
- `boxbilling/boxbilling#889` is titled "[WILL PAY FOR CODE]" and states **no figure**. Correct.
- `microg/GmsCore#2994` was refused by **our own bug**: the bounty is written `[14999$]` and the
  amount pattern only allowed `$14999`. Fixed, pinned with a regression test.

### Feedback loop measured
`D:\tmp\scout-feedback.log`: round 1 = 4 rows / 2 admitted; round 2 = 3 rows / 1 admitted; union
3 admitted. The refusals reached the agent (`REWARD_QUOTE_HAS_NO_AMOUNT` appears twice in its
transcript), but it repeated the class instead of repairing it — it rewrote the file from scratch
and dropped rows it had already won. That is the next fix, and it is an interface fix, not a rule:
give it an append-only round file and let code keep what already passed.

### CI proof, first attempt (run 41082208983, commit 806c451)
    ENTRY_DOOR cline INSTALLING cline@3.0.74
    NVIDIA_PROXY up on http://127.0.0.1:8099/v1 keys=1
    ENTRY_DOOR gateway UP
    history round1: 9 rows, 8 admitted, 1 refused | round2: 9 rows, 1 admitted, 8 refused
    AGENT_DOOR reason=OK rows=8
    AGENT_QUEUE queued=8 skipped=0

### What is NOT proven
- No door row was dispatched in that cycle: the 2 dispatches came from the pre-existing backlog
  (task ids 717a4365…, e746238b…, neither in the door's 8).
- The `CURRENT_ISSUER_OFFER_MISSING` / `NO_TRUSTED_OFFER` refusals in that window were **static-lane**
  rows — the door ids do not intersect them. The door's 8 rows are in the persisted queue and get
  their turn on a later cycle; that is the check to run next.
- Round 2 admitting 1 of 9 is a real weakness in how the feedback is shaped, not a gate fault.
