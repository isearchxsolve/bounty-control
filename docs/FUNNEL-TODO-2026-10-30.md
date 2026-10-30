# The funnel todo - live, 2026-10-30

**Rule for this file: it is updated as work happens, not at the end.** A line that says DONE
without a receipt in the same line is not done. A line that says OPEN without a reason is not a
plan. When something is measured, the measurement replaces the claim.

Companion documents, in reading order:

1. `docs/FUNNEL-LIVE-STATE-2026-10-30.md` - what the live funnel is and was.
2. `docs/FUNNEL-YIELD-FORENSIC-2026-10-30.md` - the 38-record census and why yield is zero.
3. `docs/FUNNEL-REPAIR-PLAN-2026-10-30.md` - R0-R9, the repairs, measured.
4. this file - what is done, what is next, in one screen.

**The only metric that counts:** qualified candidates that produced a *reviewable upstream patch*,
per week. Not dispatches, not PRs opened, not tests passed. At the 2026-10-30 census that number is
**1** (`fyne-io/fyne#6637`), with **0 reviews** and **0 funded merges** in a month.

**Two legs, two metrics, never summed.** This file now tracks both:

| Leg | Metric | Value at 2026-10-30 |
| --- | --- | --- |
| Bounty (issue -> patch -> upstream review) | reviewable upstream patches per week | **1**, 0 reviews, 0 merges |
| Marketplace (LinkedIn services request -> proposal -> buyer reply) | qualified buyers who replied per week | **0**, from 4 proposals sent to 7 true buyers |

Both are zero-or-one for the same structural reason: the output leaves the house and nothing watches
it (O1 on one leg, O8 on the other).

---

## Verdict, one paragraph

The funnel's machinery works and its supply was never the problem: 32 dispatch cycles, 38 fleet
tasks, 16,463 leads, ~1M URLs queued. The zero is two defects that split the census exactly in half,
and neither is engineering capability. **Half** died inside our own harness on one repository
(`Expensify/App`), where the plan scheduled workspace-wide commands, dependencies were reinstalled
cold every run, and the agent then overrode the heap to 14 GiB on a ~7 GiB runner - a configuration
choice of ours, not a limit of GitHub Actions, which is what Baba's question exposed. **The other
half** were never code-change requests at all: 13 of 19 non-Expensify records were digests,
advertisements, support questions, epics, hardware benchmarks or video bounties. Admission now
refuses 11 of the 16 measured refusals (was 3) with zero false negatives on the 45-sample. What
remains is not a funnel defect but a conversion fact: **one publishable PR exists and nobody has
reviewed it**, and the follow-up lane that would convert it does not exist yet.

---

## Done, with receipts

| # | Item | Receipt |
| --- | --- | --- |
| 1 | Floor landed as reviewed code default at 250 (variable still overrides) | `aef59dc`, `bounty_admission.py:27` |
| 2 | Hydration decoupled from the search-API budget; standalone drain lane added | `bounty-hydration.yml`, `aef59dc` |
| 3 | Time-to-first-response metric | `first_response_minutes_median` in every run summary (57 samples, 3.23 min) |
| 4 | Offer-band classifier: `OFFER_BELOW_FLOOR` vs `NO_TRUSTED_OFFER` | every production refusal measured `NO_TRUSTED_OFFER`, 0 below-floor |
| 5 | Dead lanes closed (`mass_attack_engine` 91 lines, rails guard), engagement comment wired | `aef59dc` |
| 6 | Item #1 root-caused: 7 receipt/deliverable losses were one OOM, not seven causes | run `40862366271`, exit 143, 38m38s |
| 7 | Item #3 closed: 11 of 12 `FAILED_ENGINEER` were stale labels; the 12th (missing plan phase) really was a typed-exception gap | `actions_release.py:99`, `test_failure_taxonomy.py:164` |
| 8 | Item #2 measured: catch rate was **3/16 (19%)**, not unmeasured | `scripts/replay_refusals.py`, `f9_sample/f9_refusals_16.json` |
| 9 | Five refusal gates applied, scored before shipping | live catch **11/16 (69%)**, 0 false negatives on the 45-sample; `test_f9_refusal_gates.py` (5 tests) |
| 10 | Capacity reframed and repaired: plan budget, frozen lockfile, package caches | `_worktree_bytes` + `PLAN_REPO_WIDE_DEFERRED`, `engine2.yml` cache step; `test_plan_memory_budget.py` (10 tests) |
| 11 | Docs corrected where they were wrong (three times), including "too large for the machine" | forensic doc section 2.1, repair plan R3 |
| 12 | Suite green after every step | **542 passed, 1 skipped** |
| 13 | Marketplace queue swept live on the IQOO with requester headlines | `war-log/evidence/market_sweep_log.jsonl` (35 request rows), `war-log/_marketplace_sweep.py` |
| 14 | Queue classified: 9 raw hits (**7 true buyers**) / 10 job-seeker / 16 other | forensic 10.1-10.2; ad-hoc run recorded there, not yet a script (M2) |
| 15 | **4 proposals sent, each verified on screen** - Nitin 01:11, Nikunj 01:36, Brad 01:40, Navneet 01:45 | ledger `war-log/evidence/market_proposals_log.jsonl`; `evidence/{nitin,nik,brad,nav}_sent.png` + matching `ui_*_sent.xml`; drafts in `war-log/roadmap/drafts/market-20261030/` |
| 16 | Injection no-op root-caused: broadcast needs ADBKeyboard as the active IME | empty composer with Gboard active (`evidence/nitin_filled_crop.png`, `0 of 1500`) vs `1463/1500` after `ime set com.android.adbkeyboard/.AdbIME` (`ui_nitin_verify.xml`) |
| 17 | Two drafts rewritten after reading the actual request instead of sending the template | Nikunj (personal site, not an audit), Brad (Salesforce-vendor analytics brief) - forensic 10.3 |
| 18 | Live census of every published PR, from the API: 66 PRs, 64 external, 47 closed unmerged, **0 reviewed, 0 external merged** | `war-log/evidence/pr-conversion-watch-20261030.md/report-20261030T032811Z.json`; forensic 11.1 |
| 19 | Payment mechanism measured from vendor docs: **merge pays nothing** - Opire "claiming a bounty never creates an automatic payment", Algora needs claim+reward+linked account | forensic 11.3; docs.opire.dev/rewards/lifecycle |
| 20 | Claim lane built: `claim_line` / `pr_body` / `post_claim`, fires only on a trusted bot comment | `scripts/actions_delivery.py`; `scripts/test_claim_command.py` (11 tests) |
| 21 | **Checkout was dead since 02:59Z** (gitlink with no `.gitmodules` url) and is now fixed + pinned | `scripts/test_gitmodules_integrity.py` (2 tests); forensic 12.1 |
| 22 | Delivery blast radius green after the changes | **118 tests, exit 0** (subset, named in repair plan R11 C3) |

## Open, in the order that moves the metric

| # | Item | Why it is next | State |
| --- | --- | --- | --- |
| O1 | **Nothing watches a published PR** | built and run live: 66 PRs classified, exit 0 | **LANE EXISTS** - `scripts/pr_conversion_watch.py`; remaining work is a schedule + the nudge itself (O6) |
| O2 | Prove the cheap preparation path on one real `Expensify/App` task, then lift the 750 MB exclusion | converts a known refusal into a measured capability | OPEN - needs a live run, not code |
| O3 | The scheduler in this repo is erratic (F8): heartbeat `*/10` fired at 01:16, 21:29, 16:51, 11:35 - roughly every 4-5h; hydration cron fired **once** in 2h | every cron-driven lane inherits it; the heartbeat pattern is the proven workaround | OPEN - measured, not repaired |
| O4 | `HYDRATION_BATCH = 60` and fresh hits consume almost all of it (measured 59/60, 38/60, 27/60) | the 93k backlog therefore never drains by design; hygiene, not yield | OPEN - by design, undocumented until now |
| O5 | Heap-clamp shim (R3.4) | an inline `NODE_OPTIONS` override still defeats the workflow cap | SPEC READY - one case, deliberately not built |
| O6 | Item #4: the `fyne` comment (one short factual note, no deadline, no bounty language) | **$500 is live on `fyne#1062`** (bounty was $1000, 50% already awarded to two others) and our `#6637` sits on it 12/12 green, unclaimed, unreviewed | OPEN - needs Baba's word. **No `/claim` here**: the issue carries no platform bot, so claiming would be noise |
| O7 | Commit the uncommitted work | 8 changed files, 6 new files | OPEN - never commit without the word |
| O8 | **Nothing watches a sent proposal** - the same hole as O1, on the other leg | 4 delivered at 01:11-01:45, zero reads since; the metric is 0 by construction | OPEN - no lane exists (repair plan M0) |
| O9 | 3 true buyers were **unreachable at send time**: Farjana (the only international), RISHI GOUR, Mohan sai vineeth (+ VenkataRao, a classifier false positive) | measured: her sheet was live at 00:31, gone by 01:45 after a full walk; drafts on disk, unsent | OPEN - needs one live re-check, then `EXPIRED_UNSENT` (M4) |
| O10 | `war-log/phone_linkedin_dm.py:8` hardcodes the **Nokia** serial and never sets the IME | would repeat tonight's empty-composer failure on the IQOO, and look successful | OPEN - M1 |
| O11 | Classifier matches substrings, not words: `cto` in Fa**cto**ry, `owner` in Owner**ship** | precision 7/9; the 2 wrong rows were an engineer and a developer, not buyers | OPEN - M2 |
| O12 | Queue freshness: any marketplace snapshot is stale within hours | 00:31 alive -> 01:45 gone, and a record absent at 00:31 (Arman Ansari) present later | OPEN - M3 (stamp + 6h window) |
| O13 | **No payout account exists** - no Algora, Opire or Stripe credential in `vault/` | even a claim + a reward would have nowhere to land | OPEN - needs you: signup + KYC cannot be delegated |
| O14 | The full suite cannot run in one pass locally (an unmocked live GitHub search test) | 20-minute timeout, so "suite green" is only ever said about a subset | OPEN - identify and mark it network (R11 C3) |
| O15 | 17 open PRs in repos that have never reviewed anything (7 in one repo alone) | nudge list of 14 is mostly mills; the honest list is 3-5 | OPEN - target-quality gate, not yet specced |
| O16 | **GitHub Actions is billing-blocked on this private repo**: "recent account payments have failed or your spending limit needs to be increased" - the first run on `4651377` never started | no workflow can run, so no green tick can serve as an oracle; the checkout fix is proven from the commit tree instead (forensic 12.4) | OPEN - **yours**: Billing & plans |

## Closed as "do not build", with the reason

| Item | Why not |
| --- | --- |
| Widening the search horizon / adding queries | supply already existed; 32 dispatches produced 0 funded merges. Fix-before-widen. |
| A gate on `ALREADY_RESOLVED` refusals | the 3 cases are textually indistinguishable from real bugs; `competition()` already covers the detectable subset; cost is 3 preparation runs, cheaper than one refused real bug. |
| `keyword_spam` gate | refused `commonworld-one/commonworld#186`, a genuine code-change request. One false negative disqualifies. |
| `bot_advertisement` gate | already covered by the existing `external` branch; a second rule for one behaviour is a signature change for nothing. |
| `git clone --depth 1` | `rev-list --count pre..post` needs both commits; the 14 GiB came from the lint program, not from history. No measured benefit, measured risk. |
| Retry tightening / more retries | `retry_eligible()` already separates terminal refusals from retryable failures; nothing measured suggests otherwise. |

## The laws this round added

1. **A gate that refuses a case outside the measured refusal set does not ship.** One false
   negative disqualifies it, whatever it catches.
2. **No gate without a measured case** - "if you cannot name a case, do not add the gate."
3. **Refusal reason strings are fixed per branch**, never interpolated: the dispatcher counts the
   whole reason as a summary key.
4. **Executable proof**: a doc snippet counts only once it has been extracted from the doc and run.
5. **A measurement instrument is part of the measurement.** Truncating issue bodies at 1500 chars
   changed a gate verdict; a fixture rerun that erased hand labels made a green suite measure
   nothing. Both are now pinned by tests.
6. **Measure the runner before blaming it.** "The machine cannot" is a claim about GitHub Actions,
   which is used by far larger repositories every day; the honest question is how they prepare.
7. **Nothing is fixed because it compiles.** 542 tests pass; the yield is still zero until a
   maintainer reviews a patch.
8. **A snapshot of a live queue is a receipt for the moment it was taken, and nothing more.** Three of
   seven true buyers expired between sweep and send, including the only international one. A list is
   not inventory.
9. **Substring matching is not classification.** `Factory` contains `cto`; `Ownership` contains
   `owner`. Both fired, both were wrong, and the same rule disqualifies a refusal gate that matches
   inside words (R2.7).
10. **Injection is a two-variable operation: IME plus focus.** Verifying it with a `uiautomator` dump
    is not verification - the dump returned stale screens twice tonight while the pixels had moved.
    Screenshot first, then claim.
11. **A sent message with no watcher is worth the same as an unsent one, in yield terms.** That is
    O1 and O8, and it is one defect wearing two costumes.

---

## O1 done (2026-10-30 late) - the conversion lane exists, and it overturned the census

`scripts/pr_conversion_watch.py` + `scripts/test_pr_conversion_watch.py` (16 tests, all pass). Read-only:
it never comments, pushes, re-runs CI or closes anything. Live receipt:
`scratch/pr-conversion-watch/report-20261030T030006Z.md` and `.json`.

**First live run: 66 published PRs, 64 external, 0 external merged, 0 external reached review.**
14 actionable. The census of 38 fleet records had said "1 external PR"; the PR surface is larger
because PRs were opened outside the fleet-state lane too. Both statements are true and the larger
number is the real one.

Two defects in my own first version, both caught by running it rather than reading it:

1. `gh` output decoded as cp1252 killed the reader thread mid-JSON while `returncode` stayed 0, so an
   unreadable response arrived as an empty one and the lane printed **"Nothing actionable"** with
   exit 0. That is the "quiet week" trap in miniature. Encoding is now pinned to UTF-8, and an empty
   or unparseable response raises - a probe that cannot read reports `PROBE_FAILED`, never silence.
2. The headline counted our own repository as a market merge. Merges are now reported as
   `external_merged`, separate from `merged`.

### The measured post-publication death rate

47 of 64 external PRs were closed without merge. Fetching every one: **all 47 were closed within 8
hours of opening**, most inside 1 hour, and **29 of them in five repositories**
(`SecureBananaLabs/bug-bounty` 10, `bujiproject-art/agentmidasopendevteam` 9, `paraloom-core` 4,
`paraloom-wallet` 3, `claude-builders-bounty` 3). Those are bounty farms that sweep their PR queue.
The lane now downgrades any open PR in a repository that has already closed two or more of ours to
`REPEATEDLY_CLOSED_REPO / do_not_nudge`: nudging there spends attention on a mill, not a maintainer.

### The funding question - why a merge would still pay nothing

Baba asked why a merged PR did not pay. Measured answer, and it is worse than the question assumes:

- The only merge is `isearchxsolve/bounty-proof#6` - **our own test repository**. No bounty existed,
  nothing was owed.
- **Merge is not a payment trigger.** GitHub has no payment primitive. On every bounty platform the
  merge is a precondition; the money moves when a human or the platform is told to move it, and the
  contributor must have a payout route connected.
- Of the 18 open PRs, **only 4 sit on issues with any funding signal at all**:
  `fyne-io/fyne#6637` -> issue `#1062`, label `Bounty`, `$1000` allocated (an initial `$500`, raised by
  sponsor `@hkparker`), and `andydotxyz` has already awarded `$500` of it by agreement with the
  sponsors for earlier improvements. `paraloom-core#1233/#1234` (`[BOUNTY]` in the title) and
  `Tarsnap/kivaloo#402` (`[bug bounty]`).
- **The other 14 have no money attached whatsoever.** A merge on any of them pays zero by
  construction, which means the queue's ceiling is not 14 payments - it is nearer 4, and one of those
  four has already paid out part of its bounty.

### The uncomfortable sentence on the only funded PR

On `fyne-io/fyne#1062`, the maintainer wrote:

> "Are you sure it's an issue you want to tackle first? If you are coming from a vibe code bounty
> tracker it may not be a good fit."

Our funnel is exactly the behaviour that sentence warns about. So the `fyne` follow-up cannot be a
templated nudge; it has to read as one engineer answering their actual architecture objection, or it
should not be posted at all.

### New open item, from this measurement

**O8 - admission must require funding evidence, not a bounty word in the title.** 14 of 18 open PRs
were opened on issues that cannot pay. That is a target-selection defect of the same class as the
refusal gates, and it is measurable before dispatch (issue labels + platform links + an explicit
amount), unlike anything downstream. It outranks every remaining polish item in this file.
