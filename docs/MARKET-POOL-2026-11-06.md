# Escrow market measurement, 2026-11-06

Measured live through the GitHub search API, before any roster or gate change is justified
by it. Every number below came from one API call and is reproducible today; the pool moves
hourly, so re-measure before acting on this document.

## Addressable pool

| Query | Open issues |
| --- | --- |
| `commenter:algora-pbc is:issue is:open` | 33 |
| `commenter:polar-sh is:issue is:open` | 1 |
| `commenter:opire is:issue is:open` | 0 |

**34 open escrow-attested issues in the entire indexed market.** Not 34 per run, not 34 per
lane - 34, total, before vitality, capacity, competition and "is this a code task at all".

## The winnable subset is smaller than the pool

Sampled the three that looked most plausible, because a headline bounty and a fundable one
are different facts:

| Issue | Title claim | Real escrow | Competing open PRs | Verdict |
| --- | --- | --- | --- | --- |
| `microg/GmsCore#2843` | [$2340] | **$50** (BountyHub link in body) | **16** | unwinnable - and one of the 16 is our own PR #3970 |
| `Feel-ix-343/markdown-oxide#274` | - | **$5** | 23 comments, maintainer-side reports of "not a markdown-oxide bug" | unwinnable |
| `Feel-ix-343/markdown-oxide#269` | - | **$5** | **33** | unwinnable |
| `Feel-ix-343/markdown-oxide#263` | - | **$5** | **9** | $5 with 9 claimants |

Two lessons the roster cannot express on its own:

1. **A dollar figure in a title is not escrow.** `GmsCore#2843` publishes $2340 in the title
   and $50 in the BountyHub link inside the body. Reading the title is how you waste a run.
   The escrow amount is read from the platform attestation comment, by the same rule the
   escrow-only gate already uses.
2. **Age is the competition.** 18-month-old issues accumulate 16-33 claimants. A bounty that
   opened *today* has none. The founder roster's `sort:created-desc` is therefore the single
   highest-leverage ordering in the file, and the 30-minute cron is fast enough to be first.

## What this means for the roster

Breadth is not the lever - 120 queries over a 34-ticket universe cannot create a winnable
row, and 37 of those queries are vocabulary veins that cannot even surface an attestation.
Precision and **timing** are the levers. The addressable play is to catch an escrow ticket on
the day it opens, and to have the claim armed at that moment - the pipeline's claim only
existed on paper until `7fd3b9b`, and the record shows zero claims ever posted.

There is also a class the escrow gate correctly excludes but the market keeps offering:
verbal/sponsor-priced requests (`Spectral-Finance/lux` publishes $2,000, $750, $300 in issue
titles with no platform bot attestation). The 11-06 study measured that class at 0%
conversion, and the account record agrees - 36 open PRs across non-escrow repos, 0 reviewed,
0 merged. Working them is not volume; it is the funnel pointed at the wrong market.

## Own PRs as of 2026-11-06

36 open PRs; **zero** sit on a platform-attested issue. The intersection of "our published
work" and "claimable escrow" is empty, which is why no claim has ever been posted and none
can be retrofitted.
