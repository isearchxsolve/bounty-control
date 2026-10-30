# Funnel yield forensic - 2026-10-30 (items 1-4)

Evidence-only review of why the live bounty funnel converts nothing, and what each of the four
remediation items actually is once measured. Every number below comes from a file or an API
response named in `9. Receipts`. Nothing here is projected.

## 0. Verdict in one paragraph

The funnel does not fail at the admission floor, at supply, or at the agent's ability to write
code. It fails at **our own preparation plumbing and preparation contract**, applied to a
candidate set that is **largely not a code-change request at all**. Of 38 durable task records,
**28 died before any patch could be judged**: 16 were refused by Cline as not-a-code-change (its
reasons are correct), and 12 "engineer failures" contain **zero** engineering-capability
failures - 4 missing-artifact errors, 3 dirty baselines, 2 upstream races, 2 misclassified
refusals, 1 missing plan phase. The only real, reviewable engineering output in a month is a
single open PR (`fyne-io/fyne#6637`). Supply was never the binding constraint, and the floor
change was never the lever.

## 1. Corrections to my earlier analysis (three retractions)

I asserted each of these and the receipts disproved them. They are recorded so the analysis is
not repeated downstream.

| My earlier claim | What the receipts show |
| --- | --- |
| "No dispatch ever happened; the funnel is one bug away from working." | False. 32 dispatch cycles and 38 fleet-state tasks exist since Oct 27; the machinery runs. |
| "`phpseclib#1293` was admitted with no trusted offer." | False. `terrafrost` is `author_association: MEMBER`, so `trusted()` was correct; it was dispatched 23:05:37Z and correctly refused by Cline as a release-timing question. |
| "The $2,000 floor was the binding constraint." | False causally. `FLOOR` was `80` until `449e17e` (Oct 29 17:39Z), then `2000` for ~2h20m, then `250`. **Every** recorded failure happened at floor 80, the loosest setting. Lowering it changed no outcome. |

A fourth, from this session: "the 7 receipt/deliverable failures are recoverable yield - our
harness discarded engineer work." **Wrong.** See `3.`: the work never completed, and the runner
artifacts are gone, so nothing is recoverable. The correct reading is a cost defect, not lost yield.

## 2. The census (durable state, `bounty-control` @ `615d1328`, 38 records)

| Status | Count | Meaning |
| --- | --- | --- |
| `REJECTED_PREPARATION` | 16 | Cline refused the task before writing a patch (reasons in `4.`) |
| `FAILED_ENGINEER` | 12 | Phase error after claim (classes in `5.` - none are code-fixing failures) |
| `FAILED_MISSING_RECEIPT` | 5 | Run produced no result/failure document |
| `FAILED_DELIVERABLE_MISSING` | 2 | Skeleton never replaced / baseline left dirty |
| `AWAITING_REVIEW` | 2 | One internal (`bounty-proof#8` -> PR 9), one external (`fyne-io/fyne#1062` -> PR 6637) |
| `DELIVERED` | 1 | `bounty-proof#3` -> own PR 6 (only merge in the account) |

Concentration matters: `Expensify/App` accounts for **19 of 38** records. The remaining 19 are
spread across 13 repositories, several of which are not software projects at all
(`alfrexo95/bounty-bot` x3, `ruohong2018/ruohong2018.github.io`, `superpreviousattending/canyonendrum`).

### 2.1 The concentration that explains the whole funnel

The census splits cleanly in half **by repository**, and each half has exactly one dominant
defect. This is the most useful table in the document.

| | `Expensify/App` (19) | Everyone else (19) |
| --- | --- | --- |
| Not a code-change request (refused correctly) | 3 - all "already resolved" | **13** |
| Died in our harness (memory / artifact / baseline / race) | **16** | 3 |
| Reached review with a real patch | **0** | 3 (2 `AWAITING_REVIEW`, 1 `DELIVERED`) |

The 16 `Expensify/App` harness deaths are **one cause wearing four labels**, which is why
counting statuses alone misleads. All of them are the same 3.39 GB repository killing a 16 GiB
runner, recorded at whatever point the SIGTERM landed:

| Symptom | Count | Where the kill landed |
| --- | --- | --- |
| `FAILED_MISSING_RECEIPT` | 5 | no result or failure document written |
| dirty baseline (`clean, unchanged upstream baseline`) | 4 | after the worktree was touched, before restoration |
| missing artifact (`No such file ... .preparation.json`) | 4 | before the write-early skeleton was replaced |
| `FAILED_DELIVERABLE_MISSING` (skeleton never replaced) | 1 | same, later |
| upstream moved | 1 | after a long run, upstream advanced |
| misclassified refusal | 1 | `#105153`, a by-design refusal |

**All four `missing artifact` cases are `Expensify/App`** (`#75905`, `#104400`, `#104231`,
`#100290`). That reclassifies them: they are not a writer/reader path disagreement, they are the
same SIGTERM arriving before the skeleton was replaced. Class A and the 7 receipt failures share
one root cause.

So the honest answer to "is it supply, gates, or engineering?" is: **it is two defects, not one,
and they do not overlap.** Half the pool is one repository that we prepared the most expensive
possible way (configuration); the other half is candidates that were never code-change requests
(precision). Neither half is supply, and neither half is an engineering-capability failure - one is
an admission defect, the other is our own cost choice.

**Corrected 2026-10-30.** This section first said "a repository this runner cannot prepare". That
was wrong, and Baba caught it: "git actions is a worldwide standard for large scale engineering -
how do other people use it then?" Expensify/App runs its own suite on GitHub Actions every day, on
`blacksmith-8vcpu` and `blacksmith-16vcpu` runners with warm per-shard caches; their lint workflow
documents a "~12GB each" cold-worker cost, which is why they do not use the free runner either. So
the limit was not the machine, it was our preparation: a cold 3.39 GB checkout, no dependency
cache, the plan scheduling workspace-wide `test`/`lint`, and an agent overriding the heap to 14 GiB.
Configuration is fixable, and R3 of the repair plan now fixes it. The size exclusion stays only
until a live run proves the cheap path.

### 2.1b Two of my own numbers were wrong, measured 2026-10-30

Recorded because the repair order was built on them:

1. **`HYDRATION_BATCH` is 60, not 300.** The 300 belongs to the standalone hydrate lane
   (`--hydrate-only --hydrate-batch 300`); the discovery lane's own window is 60, and the current
   cycle's fresh hits consume nearly all of it (measured 59/60, 38/60, 27/60). So
   `pending_hydration` does not drain: `93,777 -> 93,732 -> 93,833` over about forty minutes. My
   "78,743 backlog / 1,200 rows an hour / 65 hours" arithmetic was wrong in both directions. This
   is table hygiene, not the reason yield is zero.
2. **This repository's cron is erratic, and that was already known.** `discovery-heartbeat.yml`
   opens with "F8: the discovery cron is erratic - even a correct schedule can simply not fire".
   The evidence: heartbeat `*/10` ran at 01:16, 21:29, 16:51, 11:35 (every 4-5 hours);
   `bounty-hydration` fired once in two hours; discovery survives only because the heartbeat
   re-dispatches it. Any lane that depends on its own cron must have a heartbeater, or it is a lane
   that stops silently.

### 2.2 What has never been measured: whether engineering works

The data does not exonerate the engineer - it barely exercises it. **3 of 38 records reached
review**, and 2 of those 3 are our own `bounty-proof` repository. Exactly **one external PR
exists** (`fyne-io/fyne#6637`). "Not an engineering failure" is true of this census because the
pipeline almost never got there; it is not evidence that the engineering stage is sound.

## 3. Item 1 - `FAILED_MISSING_RECEIPT` (5) and `FAILED_DELIVERABLE_MISSING` (2)

**All 7 are `Expensify/App`.** Attempts span 2026-10-27 to 2026-10-29, all at floor 80.

Root cause, read from the run log of `40862366271` (`Expensify/App#102333`, engineer job
11:03:47Z -> 11:42:25Z = 38m38s, conclusion `failure`, exit 143):

- The agent ran `ESLINT_CONCURRENCY=2 NODE_OPTIONS=--max_old_space_size=14336 npm run lint`
  itself, i.e. it **overrode the `NODE_OPTIONS=--max-old-space-size=3072` cap** the workflow
  sets for the F14 memory defect.
- Its own polling recorded `Memory is at 15Gi used, 240Mi free`, node RSS `14,386,664 KB`,
  swap `~8.4GB`.
- At 11:42:23Z the runner sent SIGTERM (`##[error]Process completed with exit code 143`).
  SIGTERM kills the Python process before any `except` block can write a report, so no
  `engineering-result.json` and no `*-failure.json` existed.

That is a **cost defect with a 38-minute burn**, not a receipt-gate bug:

- `cancel-in-progress: false` - not a concurrency cancellation.
- Engineer `timeout-minutes: 330`, step `300`; the job died at 38 minutes - not a timeout.
- The misclassification side (`exit 143` -> `FAILED_RUNNER_SHUTDOWN`, `inferred: true`) is
  already implemented in `actions_delivery.terminal_result` and pinned by
  `test_failure_taxonomy.py`.

**Already fixed in code, verified this session:** commit `cc1183b` ("decline tasks this runner
cannot prepare, and stop inviting the 14 GB command") landed both halves -

1. `CAPACITY_MAX_REPOSITORY_KB = 750000`; `Expensify/App` is `3,391,646 KB`, so it is now
   declined at dispatch and counted as `CAPACITY_EXCLUDED` (visible, not lost). Measured live in
   run `40956097088`: `CAPACITY_EXCLUDED: 4`, `capacity_excluded_repositories: ["Expensify/App"]`.
2. The preparation prompt now carries a HARD RULE: one targeted command, and repo-wide
   lint/typecheck/build/test belong in `plan` (`kaggle_engine_worker.py` ~2868).

Verification: `test_capacity_gate.py` 16 passed; `test_cline_delivery_ownership.py` 12 passed.

**Residual risk, stated:** the capacity gate is a size proxy. A repository under 750 MB whose
lint reaches >7 GiB would still invite the same death, because an inline `NODE_OPTIONS=...` in
an agent-authored shell command replaces the workflow cap. The cheap backstop, if wanted, is a
`node` shim earlier on PATH that clamps `--max-old-space-size` regardless of what the agent
exports. Not implemented; not yet justified by a second measurement.

**Two more costs found later the same day, and fixed** (`docs/FUNNEL-REPAIR-PLAN-2026-10-30.md`
R3.1): the verification plan scheduled workspace-wide `npm test` / `npm run lint` for *any* Node
repository regardless of size, and every run re-downloaded the entire dependency tree. A heavy
checkout now gets no workspace-wide command (the targeted test is the local receipt, upstream CI is
the authority for the full suite) and the package-manager caches are restored between runs. Pinned
by `test_plan_memory_budget.py`, 10 tests. Note what was deliberately *not* changed: clone depth,
because `rev-list --count pre..post` needs both commits and the 14 GiB came from the lint program,
not from history.

**Item 1 status: closed. No yield recoverable.**

## 4. Item 2 - `REJECTED_PREPARATION` (16): Cline's own reasons, three structural classes

Each line is Cline's written refusal, classified. All 16 are correct refusals; the defect is that
we paid a claim and a preparation run to discover something cheap text could have said.

| Case | Cline's class | Structural class |
| --- | --- | --- |
| `Expensify/App#85907` | already fixed by a merged, production-deployed PR; regression tests ship upstream | ALREADY_RESOLVED |
| `Expensify/App#101616` | already-resolved / competing-PR case | ALREADY_RESOLVED |
| `Expensify/App#101675` | no reproducible defect at base_sha `0a22a58` | ALREADY_RESOLVED |
| `BruceFeIix/picker#1904` | auto-generated daily RSS/link digest, label `daily` | AUTO_DIGEST |
| `ruohong2018/ruohong2018.github.io#671` | auto-generated daily security-news digest | AUTO_DIGEST |
| `alfrexo95/bounty-bot#27`, `#28`, `#53` | auto-generated, self-referential bounty advertisement from the repo's own bot | BOT_ADVERTISEMENT |
| `keepassxreboot/keepassxc#255` | maintainer-labelled EPIC feature request; **funding withdrawn** | EPIC / NO_OFFER |
| `dotnet/runtime#36748` | generic architecture-support umbrella/enquiry ("are there any plans...") | NON_CODE |
| `bolivian-peru/os-moda#3` | video-production / marketing bounty, not a code change | NON_CODE |
| `sybil-solutions/local-ai-registry#216`, `#223` | hardware-verified recipe bounty; acceptance needs physical GPU | NON_CODE |
| `Cyon0x/earnly#1` | pure contact/payment-status inquiry | QUESTION |
| `phpseclib/phpseclib#1293` | release-timing / support question | QUESTION |
| `superpreviousattending/canyonendrum#546` | SEO/link-farm spam, 40+ word keyword-stuffed title | SPAM |

Class totals: `NON_CODE` 4, `ALREADY_RESOLVED` 3, `BOT_ADVERTISEMENT` 3, `AUTO_DIGEST` 2,
`QUESTION` 2, `SPAM` 1, `EPIC` 1.

Why they got through: `is_code_change_request()` (the F9 class-level gate, `8264576`) landed
**2026-10-29 03:36 IST**, i.e. after most of these runs. It is also deliberately **fail-open**:
anything not confidently external/process is admitted. And admission's `HARD` vocabulary is too
weak - it includes `bug\w*|error\w*|fail\w*|broken|issue\w*|problem\w*|defect\w*`, so a support
question that says "problem" is a "hard signal".

**Unmeasured, and it must be measured before any gate is written:** I attempted to replay all 16
through the current `is_code_change_request()` and the run died on a cp1252 decode error in the
`gh` subprocess - so **the current catch rate is unknown**. That replay (with `encoding='utf-8'`)
is the first task of item 2; it produces both the catch rate and the false-positive set.

### Gates proposed, one per measured case (NOT yet implemented)

| Gate | Rule | Case it would have caught | Risk |
| --- | --- | --- | --- |
| `AUTO_DIGEST` | title matches `^\[[^\]]*\]\s*\d{4}-\d{2}-\d{2}$`, or labels intersect `{daily, digest, news, auto-generated}` | picker#1904, ruohong#671 | low |
| `BOT_ADVERTISEMENT` | repo matches `(bounty|bounties)[-_]?(bot|hub|board)` and body declares itself auto-generated / notifies about another repo | bounty-bot#27/#28/#53 | low |
| `QUESTION` | title begins with `may i know / are there any plans / when will / how do i / can you tell` or ends `?`, AND body has no expected-vs-actual pair | phpseclib#1293, earnly#1, dotnet#36748 | medium - real bugs are sometimes filed as questions |
| `EPIC_OR_UMBRELLA` | labels intersect `{epic, rfc, discussion, feature request, question}` | keepassxc#255 | medium - would have dropped some legitimate feature work |
| `NON_CODE_DELIVERABLE` | body requires physical hardware or a non-code artefact (`recipe for`, `film`, `video`, `blog post`, `referral`) | sybil#216/#223, os-moda#3 | low |
| `SPAM` | title > 18 words with < 3 function words, or no sentence-terminating structure | canyonendrum#546 | low |
| `ALREADY_RESOLVED` | at dispatch, refuse when a merged PR in the repo references the issue (`competition()` already does this) | 85907, 101616, 101675 | unknown - these three still reached preparation, so the existing check missed them; needs a look before a new check is added |

Expected yield of item 2: **not new merges** - it removes cost. 16 of 38 records currently burn a
claim plus a preparation run each. This is a throughput/latency fix, and it raises precision so
the dispatch budget lands on tasks that can actually be prepared.

## 5. Item 3 - `FAILED_ENGINEER` (12): zero engineering-capability failures

This is the finding that changes the picture. Classified from each record's `failures[]`
diagnostic:

| Class | Count | Cases | Whose defect |
| --- | --- | --- | --- |
| A. missing preparation artifact (`[Errno 2] No such file or directory: '/tmp/fleet-artifacts/delivery-supervisor/<id>.preparation.json'`) | 4 | `Expensify/App#75905`, `#104400`, `#104231`, `#100290` | ours - the file the reader requires was never written (or never exported) |
| B. dirty baseline ("Cline preparation must leave a clean, unchanged upstream baseline") | 3 | `Expensify/App#100120`, `#102241`, `#104461` | contract/agent discipline |
| C. upstream moved ("Prepared baseline is not the current upstream default") | 2 | `librepods-org/librepods#878`, `Expensify/App#70080` | race - cheap and safe to retry |
| D. misclassified refusal ("not a request for a concrete code change") | 2 | `xpex-systems-ai/GXEON-AI#452`, `Expensify/App#105153` | taxonomy - these are `REJECTED_PREPARATION`, already fixed in `retry_eligible`/taxonomy |
| E. missing plan phase ("Mandatory native plan phase missing: builds") | 1 | `isearchxsolve/bounty-proof#1` | contract |

Implications, stated plainly:

1. **The agent's ability to fix bugs is not measured by this data.** In 4 of 12 cases the
   preparation document that the reader requires did not exist, so the phase could not even
   start; in 6 more the baseline contract failed; in 2 the run was refused, not failed. The
   pipeline has reached actual code-writing a handful of times.
2. **Nine of these twelve are stale labels, not open bugs.** Traced through the code, A, B, C
   and D are already typed (see `5.1`), so a record written today would not carry
   `FAILED_ENGINEER` for any of them. The durable records were written before the taxonomy
   landed and were never rewritten.
3. **One genuine gap existed, and it is now closed** (E, see `5.1`).

Expected yield of item 3: **none recoverable by re-running.** The work in A/C was never
completed, and their runner filesystems are gone. The value delivered is prospective: a
plumbing fault can no longer be filed as an engineering verdict, so the next occurrence is
retried instead of silently costing a task.

### 5.1 What the code already fixed, and the one gap that was real

Found by tracing each diagnostic to the class that raises it, not by reading status names:

| Class | Exception | Status it produces | State |
| --- | --- | --- | --- |
| A missing artifact | `ClineDeliverableMissing` (`read_preparation`, F3) | `FAILED_DELIVERABLE_MISSING`, `retryable: true` | already fixed |
| B dirty baseline | `PreparationContractViolation` (subclass of `ClineDeliverableInvalid`) | `FAILED_DELIVERABLE_MISSING`, `kind: deliverable_invalid`, carries dirty paths | already fixed (pinned by `test_2c`) |
| C upstream moved | `PreparationRace` (F4) | `FAILED_PREPARATION_RACE`, `retryable: true`, carries `overlap`/`ahead_by` | already fixed |
| D misclassified refusal | `REJECTED_` prefix is passed through untouched | `REJECTED_PREPARATION`, terminal | already fixed |
| E missing plan phase | **was a bare `ValueError`** | `FAILED_ENGINEER` (blanket handler) | **fixed this session** |

The run cited in A's diagnostic (`40673403288`, 55 minutes, exit 0, no report) is the same run
the `read_preparation` docstring records, so A was already understood and fixed before this
review; what was missing was the link between that fix and the durable record.

**E, fixed now.** `actions_release.validate_plan_contract(plan, path=None)` raised a bare
`ValueError` for a missing phase and for a bypassed command, so both reached the blanket
handler and were stamped `FAILED_ENGINEER` -- exactly the complaint `test_2c` records for the
dirty baseline. It now raises `PreparationContractViolation` naming the artefact that carried
the incomplete plan, and it also types the bypassed-command case (same object: a plan the agent
supplied). Call sites pass the real artefact: `prepared["report_path"]` in both engineer calls,
`bundle` in `validate_bundle`. Pinned by `test_2d_a_missing_native_plan_phase_is_a_deliverable_violation`,
which builds the exception through the real validator and then drives the real `main()` handler,
so it fails if the raise ever reverts. `test_no_bypass_native_plan` was retargeted from
`ValueError` to `PreparationContractViolation` -- the assertion is equally strong, not relaxed.

Suite after the change: **527 passed, 1 skipped across 43 files** (was 526; the extra test is
`test_2d`).

## 6. Item 4 - the only live real PR

`fyne-io/fyne#1062` -> PR `fyne-io/fyne#6637`, head `4a32ff7c`, status `AWAITING_REVIEW`,
OPEN and MERGEABLE, one comment, awaiting review since 2026-10-28. It is the sole external
deliverable in the census. Whatever else is fixed, this one deserves a follow-up before any
horizon widening: it is the funnel's only proven end-to-end output.

## 7. What the evidence says the binding constraint is

In order, measured:

1. **Capacity, in one repository** (19 of 38 records = 50% are `Expensify/App`; 16 of those died
   in our harness, 0 reached review). Closed by `cc1183b`'s 750 MB gate - which retrospectively
   removes half the census from the pool.
2. **Candidate precision** (13 of the 19 non-Expensify records, 68%, were never code-change
   requests; ~42% of the whole census). Item 2 in `8.`
3. **Harness plumbing and taxonomy** (3 of the 19 non-Expensify records, plus the label problem
   that made 11 already-fixed conditions look like engineering verdicts). Item 3.
4. **Agent capability** - unmeasured, because it is almost never reached (3 of 38).

Consequently: **do not widen the search horizon.** Adding supply right now adds records to
classes 1-3, which is more cost, not more yield. Do not touch the floor either; it is provably
not causal.

## 8. Remediation order, with expected yield

| # | Work | Recovers | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Item 3A/B/C: trace every `FAILED_ENGINEER` diagnostic to the class that raises it | 9 records explained | small | **done** - all were already typed; records are stale labels |
| 2 | Item 3E: type the missing-plan-phase and bypassed-command violations | 1 record + all future ones | small | **done** - 527 tests green |
| 3 | Item 2: replay the 16 through the current classifier (utf-8), then add only the gates that catch a measured case with zero false positives on the admitted set | throughput + precision | medium | next |
| 4 | Item 4: follow up `fyne-io/fyne#6637` | the only live PR | small | pending |

Note on ordering: items 3A and 3C were listed first because they looked like the only place
where paid work was thrown away. Tracing them showed the throw-away already ends in code, so
the expected recovery is zero and the honest next step is item 2, which is the only remaining
class with an unmeasured defect.

## 9. Receipts

- Durable census: branch `bounty-control` @ `615d1328`, `fleet-state/*.json`, 38 documents
  (downloaded to `%LOCALAPPDATA%\Temp\fleet`; histogram and classes computed from them).
- Item 1 run log: `gh run view 40862366271 --log`, engineer job 11:03:47Z -> 11:42:25Z,
  `exit code 143`; agent-authored command
  `ESLINT_CONCURRENCY=2 NODE_OPTIONS=--max_old_space_size=14336 npm run lint`;
  self-reported `15Gi used, 240Mi free`, node RSS `14,386,664 KB`.
- Item 1 fix: commit `cc1183b`; `actions_dispatch.py` `CAPACITY_MAX_REPOSITORY_KB`;
  `kaggle_engine_worker.py` HARD RULE ~2868; live `CAPACITY_EXCLUDED: 4` in run `40956097088`.
- Item 1 verification: `pytest -q test_capacity_gate.py` -> 16 passed;
  `pytest -q test_cline_delivery_ownership.py` -> 12 passed.
- Item 3 code: `kaggle_engine_worker.read_preparation` (docstring records run `40673403288`,
  55 minutes, exit 0, no report); `run_cline_claim_intake` write-early skeleton;
  `delivery_supervisor.py:93`; typed handlers in `actions_delivery.main()`
  (`PreparationRace`, `ClineDeliverableMissing`, `ClineDeliverableInvalid`, `RunnerShutdown`,
  `InfrastructureFault`, `ClineBudgetExhausted`); `delivery_errors.PreparationContractViolation`.
- Item 3E change: `actions_release.validate_plan_contract` now accepts `path` and raises
  `PreparationContractViolation`; call sites `actions_delivery.py` (2x
  `prepared["report_path"]`, 1x `bundle`); new test
  `test_failure_taxonomy.test_2d_a_missing_native_plan_phase_is_a_deliverable_violation`;
  `test_actions_migration.test_no_bypass_native_plan` retargeted to the typed error.
  Full suite: 527 passed, 1 skipped, 43 files.
- Item 2 classifier: commit `8264576` (2026-10-29 03:36 IST), `is_code_change_request`,
  fail-open; `HARD` regex in `bounty_admission.py`.
- Floor history: `449e17e` (80 -> 2000, Oct 29 17:39Z), `aef59dc` (2000 -> 250, Oct 30).

---

## 10. Second leg: the LinkedIn services marketplace (phone lane), measured the same way

Sections 0-9 are the **bounty leg** (issue -> admission -> Cline -> upstream patch -> review). This
section is a **different leg** with a different metric, measured on 2026-10-30 01:00-01:50 IST with
the same rules. The two are never summed: a proposal sent is not an upstream patch, and a module
counter is not a reply.

Leg metric: **qualified buyers who received a proposal and replied.** At the end of this window it
is **4 sent, 0 replies** - and, as in R9.4, the zero is structural, not a market verdict.

### 10.1 The census (35 live request records, `war-log/evidence/market_sweep_log.jsonl`)

| Class | Count | Who |
| --- | --- | --- |
| Business / international (raw classifier hits; **7 true buyers**, see 10.2) | **9** | Nikunj Patel (CEO), Brad Piyush (Founder), Navneet narayan (Founder), Nitin Dhiman (Co-Founder), RISHI GOUR (Founder), Mohan sai vineeth (Co-Founder/COO), Farjana Akter Rakhi (Dhaka - the only international), Premkumar Natarajan, VenkataRao Kuna |
| Job seekers / students (must not be pitched) | **10** | VAISHNAVI PATIL, ANURAG KUMAR, Arihant Jain, Sarthak Rawat, B.mahendra reddy, Saksham Gupta, KATAKAM SANJANA, Ritik Kaushal, Venu Manda, Rohith Reddy |
| Other (employees, recruiters, unanswered) | **16** | Saranraj (Accenture lead), Pankaj Goyal (architect), Karthikeyan (cyber-sec lead), Sailaja (systems eng), Satya Goth, Priyanshu, Nadeem, Nitesh Pandey, Kumar Ch (TA), Mohammed Afroze (TA), nidheesh kc, Abhishek, Manish (`--`), Sanjeet Bala, Rajeev Chauhan, Sourav Shetty |

The distribution is the finding: **10 of 35 requests are people looking for a job**, which is the
same audience/offer mismatch measured on the bounty leg (`13 of 19` non-Expensify records were not
code-change requests). Both legs are full of things that are not buyers.

### 10.2 Classifier precision: 7 of 9, and both false positives are substring matches

The first-pass classifier matched keyword substrings. Two of the nine "business" hits are wrong,
and the exact reason is visible in the headline:

| Record | Keyword that fired | Where it actually is | Truth |
| --- | --- | --- | --- |
| VenkataRao Kuna | `cto` | "Microsoft Fabric, Azure Data **Fa**`cto`**ry**" | Lead Data Engineer, not a CTO |
| Premkumar Natarajan | `owner` | "End-to-End Feature `Owner`ship" | Full Stack Developer, not an owner |

Precision **7/9 (78%)**. This is the same class of defect as the `keyword_spam` gate that R2.7
refused to ship: a token test that reads inside larger words. Word-boundary matching is the repair
(repair plan M2).

### 10.3 What was actually sent (4 proposals, each verified on screen)

| Target | Category | Draft | Chars | Sent (IST) | Receipt |
| --- | --- | --- | --- | --- | --- |
| Nitin Dhiman, Co-Founder @ TECHDAVS | SaaS Development (iOS+Android, from scratch, this week) | `NITIN-saas-dev.txt` | 1463/1500 | 01:11 | `evidence/nitin_sent.png`, `ui_nitin_sent.xml` |
| Nikunj Patel, CEO @ PeacefulQode | Web Design (personal site, <5 pages, self-managed) | `NIKUNJ-web-design.txt` | 1417/1500 | 01:36 | `evidence/nik_sent.png`, `ui_nik_sent.xml` |
| Brad Piyush, Founder @ Apemlab | Business Analytics (data platform, metrics, dashboards; Salesforce-vendor goal) | `BRAD-business-analytics.txt` | 1444/1500 | 01:40 | `evidence/brad_sent.png`, `ui_brad_sent.xml` |
| Navneet narayan, Founder @ SherX | Business Analytics (analyse existing data for strategy, this week) | `NAVNEET-business-analytics.txt` | 1414/1500 | 01:45 | `evidence/nav_sent.png`, `ui_nav_sent.xml` |

Every receipt is the same three-part proof: the message text in the thread, the request card with
`View Proposal`, and an empty composer. Two of them were re-read a second time from the request
sheet, which then said `Proposal submitted`. "Include a phone consultation" was left **unchecked**
on all four (STANDING GO). Ledger: `war-log/evidence/market_proposals_log.jsonl`.

Two of the four drafts were **rewritten after reading the actual request** (Nikunj's was a personal
site, not the audit/dashboard template; Brad's was a Salesforce-vendor analytics brief). Sending the
template as written would have been the `Sachikanta`-class error - a claim the artifact does not
show.

### 10.4 The structural finding: the queue expires under you

- **00:31** - Farjana Akter Rakhi's sheet was open and readable: `Application Development`, `Dhaka`,
  `1 month ago`, `Submit proposal` at `[44,764][529,896]` (`evidence/ui_far2.xml`). Alive.
- **01:45** - a full walk of the same list to its end (the `Direct requests / No direct requests`
  footer) does **not** contain her, and does not contain RISHI GOUR, Mohan sai vineeth or
  VenkataRao either.
- A record that **was not in the earlier log** - Arman Ansari - is present in the live queue.

**Measured fact:** those four were unreachable at send time. **Inference, labelled as such:**
LinkedIn rotated or expired the 27-30 day tail. I did not prove the mechanism and the document does
not claim it. What is proven is that a queue snapshot is a receipt for the moment it was taken.

Consequence for the leg: of the **7 true buyers** in the census, **3 were gone between sweep and
send** - including the *only* international one. A fourth vanished record (VenkataRao) was a
classifier false positive, so it is not a loss; counting the raw 9 would overstate the damage by
one, which is why 10.2 is measured before 10.4 is stated. Any pipeline that sweeps at night and
sends in the morning is measuring a dead list.

### 10.5 Two tool defects measured, not assumed

1. **Injection silently no-ops unless ADBKeyboard is the active IME.** With Gboard active, the
   `ADB_INPUT_B64` broadcast left the composer **empty** - screenshot `evidence/nitin_filled_crop.png`
   shows only the placeholder text, while the char counter read `0 of 1500`. After
   `ime set com.android.adbkeyboard/.AdbIME` the same broadcast landed **1463/1500**
   (`ui_nitin_verify.xml`). Gboard swallows broadcast keystrokes; the injection IME does not. The
   house helper `war-log/phone_linkedin_dm.py:8` still hardcodes the **Nokia** serial and sets no
   IME, so it would have reproduced the failure on this handset.
2. **`uiautomator dump` returns stale content on this device.** Twice the dump described the
   previous screen while the pixels had moved on (`evidence/where2.xml`, `evidence/orient.xml`).
   The screenshot was the truth both times. This is AGENTS.md 52.1/53.2/24 arriving again: screen
   before decision, and a dump is not a screen.

### 10.6 Yield, stated plainly

**0 replies at compile time.** Not "in progress" - four delivered messages and no watcher reading
the thread. The leg has the same hole as the bounty leg (R9.4/O1): the work left the building and
nothing observes what happens to it. Until a reply lane exists, the honest forecast for this leg is
the same as for the other one: **zero, by construction.**

## 11. The payment gate nobody pulled (measured 2026-10-30 03:28Z, live GitHub reads)

Section 0 said "one reviewable PR exists". A live read of every PR this account has ever
published corrects that number and changes the diagnosis.

### 11.1 The census, from the API and not from memory

`scripts/pr_conversion_watch.py` (read-only, exit 0, report
`war-log/evidence/pr-conversion-watch-20261030.md/report-20261030T032811Z.{md,json}`):

| | count |
| --- | --- |
| PRs published | **66** |
| external (not `isearchxsolve/*`) | **64** |
| closed unmerged | **47** |
| open right now | **17** |
| reached **any** human review | **0** |
| merged by an external maintainer | **0** |
| merged at all | **1** - `isearchxsolve/bounty-proof#6`, our own repo |

`external_reviewed = 0`. Not "few". Zero, across 64 PRs.

### 11.2 The closures are not review latency

Median time from open to close: **5.4h**. 46 of 47 inside **8h**; 9 inside **1h**; minimum 0.00h.
Four repositories hold 29 of the 47: `SecureBananaLabs/bug-bounty` (10),
`bujiproject-art/agentmidasopendevteam` (9), `paraloom-labs/paraloom-core`+`-wallet` (7),
`claude-builders-bounty` (3). `SecureBananaLabs` labels its issues `AI agent friendly` beside
price tags (`$350`, `$700`, `$1.2k`). A human does not review and reject 47 PRs across 22
repositories in a median of five hours. **Inference, labelled:** these are mills, and the
`REPEATEDLY_CLOSED_REPO` downgrade in the watch lane exists because of them.

### 11.3 Merge does not release money on Algora - three gates precede payout

1. **`/claim #<issue>` in the PR body** creates the claim. No claim, no award to release.
2. **The maintainer must click *reward*** in the platform dashboard. Algora's own bot message:
   "submitted a pull request that claims the bounty. You can visit your org dashboard to reward."
3. **The solver must have linked GitHub and Stripe on the platform**, or the payout has nowhere
   to land.

Counter-example on one of our own targets: `fyne-io/fyne#1062` - the maintainer awarded 50% to
`@redawl` and `@Jacalz` **by typing an award comment six days later**, not by merging.

Opire is the same, in its own words (docs.opire.dev, verified 2026-10-30): *"Claiming a bounty never
creates an automatic payment"* and *"Creating or claiming a bounty does not create an automatic
payment... each bounty creator reviews whether it meets the requirements. If it does, that creator
arranges payment for their own bounty."* Opire publishes and tracks; the payer pays. And the payer
learns of the work only through the claim: *"Each bounty creator receives your claim and decides
whether the PR meets the issue requirements."*

**Therefore "merge releases payment" is false on Algora, false on Opire, and false on label-style
bounties. The claim is the payment trigger, not the merge.**

### 11.4 This house has never pulled the handle

- `/claim` appears **nowhere** in `scripts/`. `engagement_comment()` posts a six-part
  "founder-facing report" to the issue instead (`actions_delivery.py`, `outreach_report`).
- Four PR bodies sampled on the live API - including the green `fyne#6637` - contain **zero**
  `/claim` matches.
- `vault/` contains no Algora, Opire or Stripe credential. **No payout account is registered.**

**Consequence: even a merge would have paid $0.** The missing step was never the review alone;
the claim token and the payout account were missing too. This is the same class of defect as
section 4 - a lane that cannot express the one action that produces money.

### 11.5 The money that is live on the table

`fyne-io/fyne#1062` is **OPEN** (updated 2026-10-27). Original bounty **$1000**; 50% already
awarded to two other contributors; **$500 remains** on the text-handling work. Our `#6637` sits
on it: 12/12 green, mergeable, **0 reviews**, unclaimed. The maintainer has also written on that
issue: *"Are you sure it's an issue you want to tackle first? If you're coming from a vibe code
bounty tracker it may not be a good fit."* - a representation signal, and the six-part report we
post on issues is the most likely cause of it.

### 11.6 What the corrected diagnosis is

Not "we could not prepare patches" (66 published). Not "the harness is broken" (12/12 green).
Three narrower things:

1. **Target selection** - 29 of 47 closures in four mills that close everything in hours.
2. **No claim token** - the platform never recorded a single claim of ours.
3. **No payout account** - nowhere for money to land even after a claim and a reward.

Two of the three are smaller than any gate in this document, and until they are fixed, every
other improvement is multiplied by zero.

## 12. Two gates that were closed, and where (2026-10-30 03:5x-04:2xZ)

### 12.1 The pipeline was dead at step one, for thirty minutes before anyone looked

Reading the Actions history while measuring produced a finding that outranks every gate in this
document. Every workflow run since `b1cfd41` (02:59Z) had failed **before the first job step**:

```
discover  Run actions/checkout@v4  ##[error]fatal: No url found for submodule path '_bp_audit/_h' in .gitmodules
```

`b1cfd41` - the "sync scripts, docs, and funnel repair artifacts" commit - recorded `_bp_audit/_h`
and `_proof_repo` as submodule gitlinks (mode 160000) with no matching `.gitmodules` stanza.
`_bp_audit/_h` is a clone of *this same repository*, so it could never have had a valid url. The
consequence: discovery, hydration and engine2 all fail at checkout, every 20-minute tick.

**Nothing in `.github/workflows/` or `scripts/` references either path** - verified by grep - so CI
never needed them; they are local scratch trees that reached the index by `git add -A`.

This is the **second** occurrence of the class (`_bounty_repo` did it earlier and was hand-ignored in
`.gitignore` with a comment, which fixed the symptom and not the cause).

**Fix, applied:** `git rm --cached -r _bp_audit/_h _proof_repo`, both paths added to `.gitignore`,
and `scripts/test_gitmodules_integrity.py` pins the rule in both directions - every index gitlink
must have a `.gitmodules` path, and every `.gitmodules` path must be an index gitlink. A commit that
breaks checkout now fails locally, where it costs seconds, instead of failing every workflow, where it
cost nights.

### 12.2 The claim lane exists now, and it refuses to fire on non-platform issues

`actions_delivery.py` gained three pieces:

- `claim_line(context, number)` - pure. Returns `/claim #<n>` **only** when a comment author is a
  trusted bounty bot (`bounty_admission.TRUSTED_BOTS`: algora-pbc, algora-io, polar-sh, opire).
  Prose that merely mentions a platform returns nothing: a maintainer writing "this is not an algora
  bounty" must never make us claim.
- `pr_body(...)` - the public body, now with the claim immediately after `Resolves #N` when one
  applies, so the payer is notified at creation. Extracted from `publish()` so it is testable
  without a network.
- `post_claim(...)` - because both platforms read the command only when content is **created**, an
  already-open PR is claimed with a **PR comment**, never a body edit. Failure prints
  `CLAIM_POSTED_FAILED` and never fails a delivery that already succeeded.

Pinned by `scripts/test_claim_command.py` - 11 tests, including the negative case that a human
mentioning a platform produces no claim. The stale comment in `actions_delivery.py` that claimed
"Algora requires the issue-side /claim comment" was wrong (Opire: the command works "in a comment on
a PR and in the same description of the PR", never on an issue) and is corrected in place.

**Verified:** 118 tests across the delivery blast radius pass (`test_base_branch`,
`test_baseline_relationship`, `test_cline_deliverable`, `test_download_patch_submodule`,
`test_failure_taxonomy`, `test_partition_regressions`, `test_preflight`, `test_preparation_contract`,
`test_preparation_terminal`, plus the two new modules). The full 76-module discover run was attempted
and **did not finish in 20 minutes locally** because a discovery test hits the live GitHub search API
unmocked; that is recorded as a defect of the suite, not reported as a pass.

### 12.3 What is still unproven

The claim lane has never fired on a real platform issue: no issue in the 17 currently open has a
trusted bot comment except where noted, and `fyne-io/fyne#1062` - the one with $500 live - has **no
platform bot at all**, only sponsor language from the maintainer. So `claim_line` correctly returns
`""` there, and the only action on that issue is the human one (O6). The lane is proven by test, not
by a send; that distinction stays in the record until a real claim posts.

### 12.4 C1 is proven by the tree, and the CI oracle is billing-blocked

The first workflow on `4651377` did not run at all:

```
X The job was not started because recent account payments have failed or your spending
  limit needs to be increased. Please check the 'Billing & plans' section in your settings
```

The repository is **private**, so Actions minutes are metered. Two different blockers now exist
where one was suspected: the gitlink break (fixed) and the account's Actions billing (not ours to
fix). **A green tick is therefore not available as an oracle tonight**, so the checkout fix is proven
from the commit tree instead - the object `actions/checkout` and its cleanup actually read:

| commit | mode-160000 entries in the tree |
| --- | --- |
| `b1cfd41` (broken) | `_proof_repo`, `solana-validator-block-ordering`, and `_bp_audit/_h` inside the `_bp_audit` subtree |
| `4651377` (fixed) | `solana-validator-block-ordering` only - and `.gitmodules` declares exactly that one path, with a url |

The failure lived in checkout's post-job **"Removing auth"** phase, which runs
`git submodule foreach --recursive` on the index whether or not `submodules:` is set - which is why
a scratch tree could kill every job including ones that never touched it.

**Stated honestly:** the tree is clean and the rule is pinned by test, but no CI run has yet executed
on the fixed commit. The proof is structural, not observational, and it stays labelled that way until
billing is restored and one tick completes.

### 12.5 The split: the pipeline now lives in a public repository

Actions was billing-blocked on the private archive, and private-repo minutes could never have
covered this pipeline anyway:

```
crons:  '7,22,37,52 * * * *'  +  '2,17,32,47 * * * *'  +  '*/10 * * * *'   = up to 14 runs/hour
free private allowance                                                      = 2,000 min/month
```

At ~1 min a run that is ~10,000 min/month - five times the allowance, every month, forever. Public
repositories get standard runners free and unmetered, so the funnel moved out and the archive stayed
private. This was a deliberate decision, taken with the user's explicit delegation, not a default.

- **Published:** `https://github.com/isearchxsolve/bounty-control` (public) - 205 files, 4 MB:
  the five workflows, 194 engine and test modules, the fixture samples the contracts need, and the
  three funnel documents. Commit `5b68549`.
- **Deliberately not published:** the family archive itself (AGENTS.md and family material stay
  private), `autonomous_icu_pipeline.db` and `deliveries.db` (state), and every file the scrape
  flagged. Measured before the first push: 0 hits for `nvapi-`, `sk-or-v1`, `ghp_` (beyond a regex
  and a docstring example), `AKIA`, RSA blocks or assigned passwords; 0 hits for vault paths, phone
  numbers, DIN, and 0 for Raktima, 498A, IndusInd, Arifine, Soltus, KreditBee, Silchar, pins.txt.
- **Secrets carried across by name only:** `GH_PAT` and `TOKENHARBOR_KEYS_JSON` (both were already
  the only two the workflows reference), set from `vault/` without printing a value.
- **Verified before the first push, in the extracted tree:** 432 contract tests, exit 0, 30.4s.

**The oracle finally answered.** Two runs, both green:

| run | workflow | result |
| --- | --- | --- |
| `41004884451` | Actions migration contracts | **success** (04:48) |
| `41005024759` | Bounty discovery and reconciliation | **success, 3m13s** (04:49) |

The second run's log shows the exact command that used to kill every job now passing:

```
[command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only ...
```

That is C1 satisfied **observationally**, not structurally - see the acceptance row in the repair plan.

**What the live tick actually did:** five lanes searched (`programs`, `normal`, `startup`, `founder`,
plus the Expensify program query), and every candidate was gated with a named reason -
`CURRENT_ISSUER_OFFER_MISSING` for the lordajax.com issues whose funding is not a trusted offer, and
`HARD_ISSUE_EVIDENCE_MISSING` for a run of `test`-shaped repos. No admission passed this window, which
is the gates working, not the engine failing.

Archive state: all five of its workflows now answer `HTTP 403 Unable to disable a workflow that is not
active` - GitHub itself suspended them under the billing block, so the two repositories cannot
double-dispatch while both exist.

### 13. Two doctrine gaps found by reading the code, and both closed

Baba asked for confirmation of three assumptions about the pipeline. Two of them were **not**
what the running code did, so the code was brought to the doctrine rather than the doctrine to
the code.

#### 13.1 The Hardness Moat existed and was never imported

`autonomous_icu_pipeline.py:3234` carries `HARDNESS_PATTERNS` (46 patterns: race condition,
deadlock, use-after-free, consensus, raft, zk-snark, reentrancy, io_uring, ebpf, p99, zero-copy)
and `score_hardness_and_competition()`: +30 per pattern, +50 for a $500+ ticket, +25 for $100+,
and a competition bonus **only when the ticket is hard** (+50 at 0 comments, +35 at <=2, +20 at
<=4, -15 above 15).

Nothing in the CI chain ran it. `actions_dispatch.py` did not import it, no workflow invoked it,
and its only runner was `active_icu_supervisor.py`, which is not in CI. The live lane ranked by
band, then liquidity, then repository quietness, and **never scored hardness once**. That is the
identical defect `liquidity_score.py` had before commit `449e17e` wired it: written, correct,
unused.

**Closed:** `scripts/hardness_score.py` is now the single home (standalone, no pipeline imports,
`--self-test` 13/13, weights unchanged so behaviour stays comparable), and
`candidate_sort_key` reads:

```python
(band, -liquidity, -hardness, velocity)
```

Solvency still decides first, because a payer who cannot pay is worthless however terrifying the
ticket. Hardness then beats quietness, because a quiet repository is only a *proxy* for
competition while the ticket's own vocabulary is evidence of it. Unmeasured stays unmeasured: an
unknown comment count earns neither bonus nor penalty.

#### 13.2 The bands were ordered against the measured evidence

The order was `programs(0) founder(1) startup(2) normal(3)`. The programmes lane led, yet its
flagship target is `Expensify/App` at **3,384,503 KB**, which `capacity_exclusions` refuses at a
750,000 KB ceiling. Measured on run `40898443331`: all six qualified candidates were that one
repository and `dispatched` was empty. A lane that leads and is then discarded starves everything
behind it.

**Decision (taken, not asked): founders first.**

| band | before | after |
| --- | --- | --- |
| founder (layer 3-4, `SILO_FOUNDER_TARGETING_SPEC.md`) | 1 | **0** |
| programs | 0 | 1 |
| startup | 2 | 2 |
| normal | 3 | 3 |

The old order's test was rewritten with the reason in its docstring, not deleted and not
weakened - it still asserts all five bands and still asserts that the strongest lane present
decides.

#### 13.3 The capability limit that stays, stated plainly

The 750,000 KB ceiling was **not** raised to make the new ordering look brave. This runner cannot
prepare a 3.38 GB repository, and pretending otherwise would produce exactly the silent failure
the receipt law forbids. The honest consequence is recorded: the biggest, hardest codebases remain
out of reach until a runner with that capacity exists, and that is a capacity problem, not an
ordering problem.

**Verification:** 444 tests OK in 25.9 s (35 contracts modules + `test_hardness_ordering`, 12
tests), pushed as `551bd61` to the public `bounty-control` repository.

### 14. The bounty channel measured through the browser, and one real gate defect fixed

Baba's instruction removed the need for his hands: Agent 360 on Profile 17 answered the market
question directly, and the answer changed the plan.

#### 14.1 Algora no longer sells bounties

`console.algora.io` in a live browser redirects to the hiring landing page; the rendered text
contains **zero** occurrences of "bounty". `algora.io/bounties` returns 404. Independent
reporting agrees: the global board is gone, only per-org URLs survive. Opire resolves but does
not answer; BountyHub has 17 open issues worldwide; TaskBounty's label returns 0. A September
scan put the entire visible market at **290 bounties worth $19,543**, of which 269 were Algora -
i.e. the money largely left with the platform.

#### 14.2 The defect this exposed: we trusted a bot name that does not exist

The gate's trust list carried `bountyhub-bot`. The marker actually posted is
**`bountyhub-app[bot]`**. Measured on `moorcheh-ai/memanto#1852`, which carries *"A bounty of
$100.00 has been created ... on BountyHub"* and was refused as `CURRENT_ISSUER_OFFER_MISSING`.
A funded ticket was indistinguishable from an unfunded one.

After the fix, the first genuine admissions on record - **5 of 45 probed**, against **0 of 24**
from three earlier query shapes on the same day:

| issue | amount | note |
| --- | --- | --- |
| `microg/GmsCore#2994` | $14,999 | RCS support, accumulated over 3 contributions |
| `microg/GmsCore#2843` | $2,340 | WearOS support |
| `microg/GmsCore#1272` | $300 | Nearby Share, funded 2026-10-26 |
| `microg/GmsCore#580` | $250 | Google Cast |
| `jain-Igtm/CashGPT#1` | $79,200 | **refused**: "CashGPT Live Room" is a chat thread, not a deliverable |

The last row closed a second hole: an owner-written amount inside a chat-room issue passed the
issuer gate because the owner is trusted by design and no engineering was requested.

#### 14.3 Then the competition gate refused every one of them - correctly

All four funded microG tickets are covered by open pull requests opened in the 36 hours before
this measurement:

| issue | competing PR | author | opened |
| --- | --- | --- | --- |
| #580 Google Cast | #3943 | MilindChatrabhuji | 2026-10-29 09:40 |
| #1272 Nearby Share | #3944 | MilindChatrabhuji | 2026-10-29 09:41 |
| #2994 RCS | #3945 | Dimank92 | 2026-10-29 17:27 |
| #2843 WearOS | #3949 | fangjian-bit | 2026-10-30 05:34 |

`MilindChatrabhuji` is also the login posting `/attempt` on `documenso#3463` and
`novuhq/novu#12761`. Other autonomous agents are already doing this, and they arrive within
hours of funding. Live dispatch confirmed the refusal: claim job `41010953607` died with
`ValueError: Competing open PR: https://github.com/microg/GmsCore/pull/3944`.

**So the funnel now works as a filter end to end** - it saw $17,889 of real money and refused
all of it for a stated, correct reason, where this morning it could not see the money at all.

#### 14.4 What this changes about the plan

The bounty channel is a race decided in hours by rivals who are already inside it, with a total
visible pot near $19.5k that has mostly left with Algora. Racing it harder is not a strategy.

Two consequences, both taken:

1. **The engine's paying work is work where we are the reviewer** - the paid service lanes
   (DEV-B Rs 25,000, IDEA-B USD 100) and the repository-licence offers. There the offer is a
   client, not a board, and no competitor can pre-empt it with a PR.
2. **The bounty lane stays alive but cheap** - discovery and admission run free on public
   runners and the competition gate does the refusing. It is a lottery ticket that costs
   nothing to hold, and the moment an uncontested funded ticket appears, the pipeline takes it.
   It is no longer the plan.

### 15. The two-edged sword: hard AND burning, or it is not our ticket

Baba's law, 2026-10-30, in two messages: *"the claimant got no reply cause target issuer had
no urgency.. no ugs in live production burning millions each second. thats why we target silo
wounded founders and startup"*, then *"its a two edged sword the issue is fundamentally hard
and live in production burning millions each second from silo cofounders and startups
pocket"*.

Either edge alone is a losing ticket, and this month produced both failures:

| shape | why it loses | evidence |
| --- | --- | --- |
| **hard, cold** | nobody answers - the issuer feels no cost per hour | `microg/GmsCore#580` funded $250, claimant waiting **since April** for a maintainer word; `#2843` untouched since March |
| **burning, trivial** | solved within hours by whoever reads it first; the moat protects nothing | bystanders open PRs on funded microG issues within 36 hours (`#3943`, `#3944` one minute apart) |
| **hard and burning** | the only shape we win: slop cannot take it, and the payer is losing money while we work | target shape, not yet hit in the bounty channel |

#### 15.1 It is now one number, not two sorts

`scripts/urgency_score.py` scores the payer's own words: production-down (40), revenue
bleeding (35), contract/SLA pressure and security incident (30), escalation language (20),
growth pressure (15), and **-30 for a calm payer** ("no rush", "nice to have", "take your
time"). Age subtracts, because a wound described a year ago is not bleeding today
(-25 beyond 365 days, -10 beyond 180). Self-test 13/13.

`two_edged_score()` in `actions_dispatch.py` is the conjunction:

```
hard    = min(100, hardness_score(hardness_view(item)))
burning = min(100, urgency_score(urgency_view(item)))
score   = min(hard, burning) + 0.25 * burning
```

The `min` means a missing edge cannot be compensated by strength in the other - that is the
whole point of a conjunction. The small urgency term then separates the two failures: between
a hot trivial ticket and a hard dead one, the hot one at least might answer us. Both edges cap
at 100 so one runaway signal cannot manufacture a match. The sort is now:

**band -> two-edged conjunction -> solvency -> difficulty -> quietness**

#### 15.2 Measured on the four funded tickets

| ticket | money | hardness | urgency | two-edged | verdict |
| --- | --- | --- | --- | --- | --- |
| `microg/GmsCore#2994` | $14,999 | -15 | -25 | **-31.2** | one edge only |
| `microg/GmsCore#2843` | $2,340 | 95 | -25 | **-31.2** | one edge only - hard, dead since March |
| `microg/GmsCore#1272` | $300 | -15 | -25 | **-31.2** | one edge only |
| `microg/GmsCore#580` | $250 | -15 | -25 | **-31.2** | one edge only |
| synthetic founder wound | - | 150 | 55 | **68.8** | the shape we want |

$17,889 of real funded money now ranks **below a ticket that does not exist yet**. That is the
honest result: the bounty boards sell hard-and-cold almost exclusively, which is exactly why
claimants sit for months and why this channel is not the plan (section 14.4).

#### 15.3 Known limitation, stated rather than hidden

Hardness is a vocabulary test over the ticket text (46 terms, +30 each, value and competition
bonuses). A ticket that is genuinely deep but described plainly - `#2994` asks for "RCS
Support" and scores **-15** - is under-scored. The fix is repro evidence rather than more
keywords: a stack trace, a failing test, a benchmark, or a linked code path should count as
hard evidence. Not built yet, and not pretended to be.
