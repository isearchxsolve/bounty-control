# Market study 2026-11-06 — why targeting, not volume, decides payout

Measured 2026-11-06 (live web + API probes), before any further dispatch. This study is
the reason for the gate changes in `scripts/bounty_admission.py` (REPO_ACTIVE_DAYS=30,
COMPETITION_SWARM=3, BOUNTY_ESCROW_ONLY) and `scripts/pr_conversion_watch.py`
(ABANDON_AFTER_DAYS=14).

## Real-world samples (not ours)

- **240-PR AI-agent field report (DEV.to, May 2026, 30+ repos, 1 week):** 72 merged / 240
  = 30% headline, but 100% of merges came from 8 of 30+ repos (82% from 3). Spray-and-pray
  per random repo ≈ 0%. Failure modes: ghost repos (no commit >30d) 35%, PR races 20%
  (10–15 competing PRs within hours of posting), honeypots 15%, bait-and-switch 10%,
  style police 10%, reserved 5%, token traps 5%. Rules that worked: skip repos with no
  commit in 30d; skip issues with ≥3 existing PRs; repos that already merged your PRs →
  82% acceptance (0% → 80% credibility effect).
- **30-day platform test (AgentUpdate 2026 money map):** OSS bounty merge rates 5–30%
  by platform (Immunefi <1%), 80% only on token programs. Fresh bounties attract
  **8–158 competing agent PRs within hours** (agent saturation). Payment after merge:
  1–2 weeks typical, up to 2–8 weeks.
- **BountyOS hourly scan of 5 platforms (Algora/Opire/IssueHunt/BountyHub/TaskBounty):**
  144 verified live bounties, $25,410 total, ~9,900 issues scanned/day; **~29% of scanned
  "bounty" issues are noise** (dead repos, honeypots, swarms, stale tags). Algora ≈ 90%
  of tracked value, BountyHub ≈ 9%. ~1/3 of real bounties are "sniper" (<48h old,
  <3 competing PRs).
- **CHAOSS / academic PR metrics (millions of PRs):** median time-to-merge <7d = healthy;
  7–30d = yellow; 30–90d = red/dead. Fast *review* is hours-days on active repos.

## Our own record (86 PRs, author:isearchxsolve, pulled 2026-11-06)

- **Merged: 2 — both in our own repos** (self-merges). Third-party bounty merges: **0**.
- Closed-unmerged: 47, **100% closed within 24h, median 5.4h**. October burst: 66 PRs;
  2026-10-24 alone = 40 created, 40 closed ≤24h, **0 merged ever**.
- Interpretation: attention (a human looking) is FAST — median 5.4h. What never happens is
  the merge/payout. Time-to-close ≠ time-to-merge. Waiting on limbo PRs is free work.

## Forensics on our 4 live PRs (2026-11-06)

| PR | Escrow? | Blocker | Verdict |
|---|---|---|---|
| microg/GmsCore#3970 | **Yes — BountyHub $300 bot attestation** | race with mau16ro #3968 (/attempt 6h earlier) | only one with a real payout path |
| fyne-io/fyne#6637 | No (sponsor pool, 50% already paid to a human) | ub3dqy P1 (GL upload-byte aliasing) — fixed & tested 2026-11-06; andydotxyz distrusts bounty-tracker PRs | fix pushed, awaiting maintainer |
| stride3d/stride#3816 | No (verbal/OC promise) | MsEpsilon: "OP seems like a bot… shouldn't be allowed" (guideline) | policy wall; left for Eideren |
| kendraio/kendraio-app#615 | No (2021 OpenCollective pledge) | team self-implemented (garter-black 2026-11-04) | parked |

## Rules now encoded as gates (facts, not vibes)

1. **Escrow-only:** offer must be attested by a platform bot (TRUSTED_BOTS); verbal/
   sponsor offers → `NO_PLATFORM_ESCROW` (BOUNTY_ESCROW_ONLY=1 in the workflow).
2. **Repo vitality:** no push in 30 days → `REPOSITORY_MERGES_STALE` (REPO_ACTIVE_DAYS=30).
3. **Competition swarm:** ≥3 open PRs referencing the issue → refuse (COMPETITION_SWARM=3).
4. **Abandon rule:** our PR with no maintainer activity for 14 days → `ABANDONED` /
   stop engaging (ABANDON_AFTER_DAYS=14 in pr_conversion_watch).
5. **Fast eye levers (process, already in the door):** small clean diff, issue-linked
   title, native-test proof in PR body, one factual @maintainer ping, reviewer replies
   within hours, honest AI-assistance disclosure when asked (never fake authorship).
