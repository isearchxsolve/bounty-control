# Escrow market measurement, 2026-11-06

Measured live through the GitHub search API, before any roster or gate change is justified
by it. Every number below came from one API call and is reproducible today; the pool moves
hourly, so re-measure before acting on this document.

## Addressable pool

**Corrected 2026-11-07.** The first version of this file reported 34 open escrow-attested
issues, because it queried only `commenter:algora-pbc` (33) plus polar-sh and opire. The
gate trusts six bot identities; I measured three, and never measured `bountyhub-bot`. A
measurement that omits half the signal is not a measurement.

| Query | Open issues |
| --- | --- |
| `commenter:algora-pbc is:issue is:open` | 33 |
| `commenter:bountyhub-bot is:issue is:open` | **25** |
| `commenter:polar-sh is:issue is:open` | 1 |
| `commenter:opire is:issue is:open` | 0 |
| `commenter:algora-io is:issue is:open` | 0 |
| **Total** | **59** |

The bountyhub 25 are the ones that matter, and the first version of this document had never
seen them: `react/react#37620`, `inventree/InvenTree#12064`,
`mailcow/mailcow-dockerized#6249`, `go-github`, `client-go`, `auditpulse-core#1-3`.

## The winnable subset, per ticket

Age and competing open PRs measured per ticket on 2026-11-06. "Winnable" means under 60 days
old **and** fewer than 3 competing open PRs.

| Ticket | Age | Competing open PRs | Verdict |
| --- | --- | --- | --- |
| `sharmiaalono/go-github#5` | 49d | **15** | swarmed |
| `YieldAnchor/yield-general#8` | 51d | **8** | swarmed |
| `Emmanuel-Ugochukwu1/auditpulse-core#3` | 53d | **36** | swarmed |
| `Emmanuel-Ugochukwu1/auditpulse-core#2` | 53d | **25** | swarmed |
| `Emmanuel-Ugochukwu1/auditpulse-core#1` | 53d | **26** | swarmed |
| `react/react#37620` | 54d | **14** | swarmed |
| `CornelParsch21/client-go#1` | 87d | 3 | at the cap |
| `gitdalisar/mod-Faction-Free#27` | 118d | 2 | unswarmed, old |
| `inventree/InvenTree#12064` | 158d | **1** | unswarmed, old |
| `gqrx-sdr/gqrx#1445` | 299d | 5 | swarmed |
| `mailcow/mailcow-dockerized#6249` | 653d | **1** | unswarmed, old |
| `thesofproject/linux#5002` | 903d | **1** | unswarmed, old |
| `gqrx-sdr/gqrx#1336` | 998d | 6 | swarmed |
| `webonyx/graphql-php#1493` | 1065d | **1** | unswarmed, old |
| `mastodon/mastodon#10088` | 2816d | **0** | unswarmed, very old |
| `microg/GmsCore#1272` | 2180d | 5 | swarmed, and ours |

**The market's shape is a trade-off, not a shortage:** the recent tickets are all swarmed
(8-36 claimants); the unswarmed ones are 118 to 2816 days old. **Zero tickets are both fresh
and unswarmed.** A bounty that opens today has none of either problem, which is why
`sort:created-desc` and a 30-minute cron matter more than roster breadth.

Two more measured facts a title cannot express:

1. **A dollar figure in a title is not escrow.** `microg/GmsCore#2843` publishes `[$2340]`
   in its title while the BountyHub link in its body says **$50**.
2. **Not every bot comment is a live escrow.** `MetaFam/Fork-The-World#5` is attested by
   `gitcoinbot` — a 2020 comment on a platform that no longer exists. The pipeline's real
   `TRUSTED_BOTS` set correctly excludes gitcoin, so it is refused; a looser scan produced
   that false positive.

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

Breadth is not the lever - 120 queries over a 59-ticket universe cannot create a winnable
row. The founder lane's evidence-bearing queries name `commenter:algora-pbc` three times
and `commenter:polar-sh` once, and **name `bountyhub` nowhere** - the largest single
attested surface, 25 tickets, in the richest repos. That gap is open and recorded here
rather than silently fixed.
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
