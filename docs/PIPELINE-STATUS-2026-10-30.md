# Pipeline status — 2026-10-30 (comprehensive)

Written on Baba's question: *"is pipeline up and running with all repairs"*. Every claim below
carries the run id, commit, or command that produced it. Where something is **not** running, it
says so in the same voice as what is.

---

## 1. Verdict in one paragraph

The **code is repaired and green** (nine repairs, 477 tests local, CI green on `02b8a3c`, nine repairs landed
tonight, five workflows active). The **schedule has never fired once** — every run in the repo's
history is a `push` or a `workflow_dispatch` I triggered by hand (`push=6, workflow_dispatch=4`,
zero `schedule`). The **funnel is alive and honest but empty**: a live run searched 680 issues
across four lanes and dispatched nothing, for stated reasons. The **engine has never patched a
real ticket** in its life. And the queue between finder and drainer, which was silently split
into two cache silos, is now proven joined — hydration read the 33 rows discovery had queued,
where before the fix it read 0 while discovery held 890.

Money moved: **$0**. Nothing in this document is a claim of progress toward a rupee except where
a bank credit would be.

---

## 2. What the pipeline is

Two legs, as the house law requires, never summed:

| leg | metric | where it lives |
| --- | --- | --- |
| bounty leg | reviewable upstream patches per week | `bounty-control` (public) + GitHub Actions |
| marketplace leg | qualified buyers who replied per week | LinkedIn service requests via the phone lane |

This document covers the bounty leg. The marketplace leg is in `docs/FUNNEL-*` and the proposal
log (`war-log/evidence/market_proposals_log.jsonl`).

### 2.1 The chain

```
bounty-discovery.yml   every 15 min (cron 7,22,37,52)   -> search 4 lanes, queue pending rows
bounty-hydration.yml   every 15 min (cron 2,17,32,47)   -> drain pending on the core API budget
discovery-heartbeat.yml every 10 min                    -> re-trigger discovery when the cron misses
engine2.yml            dispatched by the funnel          -> claim -> engineer -> reconcile -> publish
actions-contracts.yml  on every push                     -> the contract test wall
```

### 2.2 The gates, in the order they run

1. **Query policy** `unassigned-no-closing-pr-no-video-demo-no-not-a-defect-contextual-branches-v5`
2. **Repository intent** — is this repo actually a place work gets reviewed
3. **Admission** (`bounty_admission.py`) — demands an *issuer-authored* offer: an amount, a
   currency, from the owner, a collaborator, or a platform bot on the trusted list. No offer, no
   ticket. This is the gate that stops the house working for free.
4. **Competition** — refuses tickets where a credible claimant already has a pull request
5. **Capacity** — refuses repositories above 750,000 KB (the runner's honest limit)
6. **Ordering** — band -> two-edged (difficulty x urgency conjunction) -> solvency -> difficulty
   -> quietness
7. **Claim** — reserves the ticket durably before engineering starts
8. **Engineering** — Cline, native tests, isolation, competition re-check
9. **Reconcile + publish** — the PR, with `/claim` in the body where a platform bot exists

---

## 3. The eight repairs landed tonight

| # | commit | what was broken | evidence it is fixed |
| --- | --- | --- | --- |
| 1 | `e544ae2` | submodule gitlink `_bp_audit/_h` broke every checkout | `scripts/test_gitmodules_integrity.py` |
| 2 | `f8bb342` | no way to claim a bounty -> merge without payment | `claim_line`, `pr_body`, `post_claim`; 11 tests |
| 3 | `551bd61` | the hardness moat was written and never imported | wired into `candidate_sort_key`; AST test pins the import; founders moved to band 0 |
| 4 | `ce84fe1` | admission trusted `bountyhub-bot`; the real marker is `bountyhub-app[bot]` | 5 admissions of 45 probed, where 3 query shapes gave 0 of 24 |
| 5 | `db79bbe` | any open PR counted as competition, so slop refused the hardest tickets | blocks only on landed author, green checks, or maintainer attention; 11 tests |
| 6 | `ebc5a52` | difficulty and urgency were separate sorts; neither alone is a strategy | `two_edged_score = min(hard, burn) + 0.25*burn`; 15 tests |
| 7 | `02b8a3c` | none of the three new test modules was in the CI list | run `41014254815` executes 12 + 11 + 11 tests inside CI |
| 8 | `b3eed93` | the durable queue was two silos: discovery wrote `discovery-*`, hydration read `hydration-*` | hydration run `41016832562` reads `queued_total_pending: 33` — the exact rows discovery queued |
| 9 | (this commit) | that same run then died `KeyError: 'velocity_24h'`: the drain indexes a field hydrate-only runs never measure | `scripts/test_hydrate_only_path.py` (4 tests) + a clean drain on the next run |

Repairs 8 and 9 masked each other, which is the clearest lesson of the night. Repair 8 is the most consequential. Measured before it: discovery run `41015165018` reported
`pending_hydration: 890`; hydration run `41015801660` then reported `queued_total_pending: 0` and
drained nothing. Two state directories (`/tmp/bounty-discovery`, `/tmp/bounty-hydration`) behind
two cache prefixes. The drainer could never see what the finder found, so every discovery run
rediscovered from scratch and burned the search budget it believed it was saving.

Repair 8 then exposed repair 9, because the two defects hid each other. The empty queue meant the
drain loop body never executed, so nobody ever hit `KeyError: 'velocity_24h'` - an index into a
field that hydrate-only runs deliberately never measure, three lines below a comment explaining
that they never measure it. The moment the queue was joined, run `41016832562` saw 33 rows, entered
the loop, and failed. A drain that reports success while doing nothing and a drain that crashes on
contact look identical from the outside: both produce zero dispatches.

---

## 4. Live verification receipts

### 4.1 Code and contracts

- `473 tests OK` locally (39.6 s), including the three gate modules.
- CI `02b8a3c` **success** — and it runs the gate tests, not just the old wall.
- Working tree clean, nothing unpushed in either repository.

### 4.2 Discovery, real run `41016386370` (06:51Z)

```
programs.raw 540 | normal.raw 63 | startup.raw 63 | founder.raw 14
CURRENT_ISSUER_OFFER_MISSING 42 | HARD_ISSUE_EVIDENCE_MISSING 16
REPORTED_BEHAVIOUR_DECLARED_BY_DESIGN 1 | unknown_or_competing 1
qualified_fresh 0 | qualified_unique 0 | dispatched []
pending_hydration 33 | first_response_minutes_median 1.24 (n=59)
```

680 issues seen, 0 admitted, 0 dispatched, every rejection named. **This is the funnel working as
a filter and finding nothing — not a crash.**

### 4.3 Hydration, real run `41016832562`

`{"phase": "HYDRATE_ONLY", "queued_total_pending": 33}` — the shared queue works.

### 4.4 Model wire, canary `41008228114`

`model-wire.json`: `provider=openai-compatible, model=deepseek-v4.1-flash:free, completions=2,
tool_results=1`, gateway `17 keys READY`, HTTP 200. **A wire check, not engineering.**

### 4.5 Engine attempts on a real ticket

| run | target | outcome |
| --- | --- | --- |
| `41009455287` | `bounty-proof#8` | `Admission blocked: CURRENT_ISSUER_OFFER_MISSING` |
| `41010953607` | `microg/GmsCore#1272` | `Competing open PR: microg/GmsCore#3944` |

Both refusals are correct and both are the point: manual dispatch cannot bypass admission.

### 4.6 The wire on this laptop

`relay :8777` -> `{"ok":true,"son":"relay-live","bank":45153,"reports":554}`.
`browser gate :7880` -> `{"ok":true,"queue":[],"granted":166,"released":166}`.

---

## 5. What is NOT running (said plainly)

| item | state | consequence |
| --- | --- | --- |
| **Scheduled cron** | **0 scheduled runs ever** (`push=6, workflow_dispatch=4`) | nothing runs unless a human dispatches it. The repo was created 04:47Z today; GitHub can delay schedule activation, but 4 hours is past the usual window and it must be treated as unproven. |
| **discovery-heartbeat** | never ran at all | the safety net for a missed cron is itself not running |
| **hydration** | never ran on its own; ran once by hand after repair 8 | the queue now drains when asked, not on a timer |
| **Engineering** | never patched a real ticket | the Cline lane is proven only by the canary wire check |
| **Publish** | never opened a real PR | the claim path is tested, not exercised |

This is the honest answer to "is it up and running": **the machine is built and its parts pass;
the automation has never taken a single step on its own.**

---

## 6. Why nothing dispatches even when run

From the discovery histogram above, and from the $17,889 microG probe:

- **42 of 60 rejections are `CURRENT_ISSUER_OFFER_MISSING`** — most issues that look like bounties
  carry no issuer-authored amount. The gate is right; the supply is thin.
- **16 are `HARD_ISSUE_EVIDENCE_MISSING`** — a ticket with no reproducible evidence is not work we
  can verify, so it is refused.
- Of the 5 tickets that *are* funded and admitted (BountyHub), all four microG ones are covered by
  credible claimants, and every one scores **−31.2** on the two-edged sword: difficulty 95 with
  urgency −25 (dead since March), or the reverse.

Funded + hard + cold is the bounty board's whole inventory. That is a market fact, not a bug.

---

## 7. The two guides Baba pointed at

`D:\DOWNLOADS\Startup_Bug_Bounty_Hunter_Guide.pdf` (8,176 b) and
`D:\DOWNLOADS\Agentic_Silo_Founder_Bug_Bounty_Guide.pdf` (7,818 b), both generated 27 Oct 2026,
describe a four-layer ladder of organisational liquidity:

| layer | shape | friction |
| --- | --- | --- |
| 1 | open-source issue bounties | "low conversion, weak economics, volunteer maintainers" |
| 2 | large-enterprise programmes | real impact, heavy process |
| 3 | funded startups / small companies | lower friction, higher urgency |
| 4 | **agentic / silo-founder** | near-zero friction; decision latency minutes to hours |

**They match the measurements exactly.** Layer 1 is where this pipeline has spent its whole life,
and tonight's evidence is layer 1's description verbatim: a funded ticket, a claimant waiting
since April, and a maintainer who never replied because nobody there loses money per hour.

The guides' operating rules already match the code: signal over volume, impact first, deterministic
repro, minimal evidence, written-only, and — their key metric — **time-to-first-meaningful-response**,
which the funnel already records as `first_response_minutes_median` (1.24 min, n=59 here).

### 7.1 The gap the guides expose

| the guides require | what we have |
| --- | --- |
| targets at layer 3-4: founders, silo companies, security contact, agent-native | no target list, no security-contact discovery, no stage tagging |
| deliverable = **production-vulnerability report**: impact in money first, deterministic repro, dual audience (human founder + evaluating agent) | we produce **code patches**. There is no report format, no impact-in-money generator |
| **no posted bounty exists at layer 4** | our admission gate *requires* a posted issuer offer, so it structurally excludes the highest-liquidity layer |
| track time-to-first-response per target, keep a short high-signal list | one aggregate median, no per-target ledger |

That last row is the strategic consequence: **layer 4 money cannot arrive through the bounty
gate**, because at layer 4 nobody has posted money — the finding is what gets bought. That is the
marketplace/service leg, which is why the two-legged law exists.

---

## 8. Money accounting

| item | amount |
| --- | --- |
| collected tonight | **$0 / Rs 0** |
| admissions proven | 5 funded tickets, $17,889 total, all refused on competition with reasons |
| proposals sent (marketplace leg) | 4, verified in-thread, **0 replies** |
| payout rails | GitHub Sponsors under review; Wise not verified; Stripe not verified; Algora no longer sells bounties |

---

## 9. Next steps, in the order I would take them

1. **Make the schedule actually fire, or stop pretending it exists.** Either GitHub begins firing
   the crons after activation, or the heartbeat job is the mechanism — and the heartbeat has never
   run. Until one of them starts on its own, the pipeline is a manual tool.
2. **Prove one real engineering run.** The only thing that has never happened is a ticket → patch →
   PR. It needs a ticket that passes admission *and* competition, which the boards cannot supply
   tonight.
3. **Build the layer-4 path the guides describe**: a wounded-founder target list with stage tags,
   a one-screen impact-first report template, and per-target time-to-first-response. This is the
   leg where the money in the guides actually lives.
4. **Wire urgency into the marketplace ranking** (`urgency_score.py` already exists and is tested):
   send to the bleeding first, not to the best-fitting.
5. **Retire the stale-claim question** only on a wider sample: `#3286` has been silent since March,
   and a lapsed claim should not block a fresh tested patch forever.

---

## 10. One line to keep

The engine is built, its gates are honest, and its queue is finally one queue. What it has never
had is a customer with money on fire — and the harder a ticket is, the less the crowd is the
obstacle and the more the payer's urgency is.

## 14. The agent door, wired (2026-10-30)

Law 85 came out of this work: endless hand-rolling is the signal that a judgement has been written
as static code. Applied here as a split: **the agent decides what to look at; code decides whether
the claim is true.**

| piece | who | why |
|---|---|---|
| what to search, which issues pay, how to recover a refused row | the agent | judgement |
| issue exists / open / not a PR | `queue_agent_rows` re-fetch | fact |
| quoted reward sentence appears literally | `issue_scout.quote_is_present` | fact |
| the quote names an amount | `quote_states_an_amount` | fact |
| repo health, capacity, admission, dispatch gates | unchanged | fact |

Wiring: `BOUNTY_ENTRY_DOOR=cline` (default in the workflow, `vars.ENTRY_DOOR` overrides) makes
`discover()` call `agent_door.find_issues()` **after** the static lanes, then
`queue_agent_rows()` writes the survivors through `store_pending_item()` - the same writer the
search lanes use, so there is one queue shape and one admission path.

Fail-closed reasons, all named in the log: `DOOR_DISABLED`, `CLINE_UNAVAILABLE`,
`GATEWAY_UNAVAILABLE`, `DOOR_FAILED`, `NO_ROWS`. A door failure costs a cycle's time and nothing
else, because the static lanes have already run.

Measured before wiring: 5 real `gh search issues` calls, 10 rows, 0 agent-authored assumptions -
every row re-fetched. After the amount guard, 5 admitted ($250, $350, 250 USDC, $50, $25) and
5 refused (`REWARD_QUOTE_HAS_NO_AMOUNT`).

Tests: `test_agent_door.py` (7) and `test_agent_queue.py` (5) plus the 43 door tests and the
existing discovery suites - 91 green, no network.
