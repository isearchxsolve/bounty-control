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
