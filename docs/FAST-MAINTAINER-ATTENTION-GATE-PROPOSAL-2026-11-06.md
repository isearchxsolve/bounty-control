# Getting a maintainer's attention quickly: forensic evidence and proposed gates

Date: 2026-11-06. Project: `isearchxsolve/bounty-control`, local checkout `D:\bc`.
**Attention-gate deliverable: a proposal, with read-only forensic collection.**
No attention gates, public PRs, review requests, comments, account settings or
workflows were changed for this study. A subsequent explicit user request
authorized local changes to the PR/issue presentation templates; those changes
are described in section 11 and do not implement the proposed targeting gates.

## Decision

Optimize for **the earliest useful action by an appropriate human maintainer**.
The strongest proposed change is to make a demonstrated review route and a
reviewable, issue-specific contribution part of target selection and publication
preparation. Repository busyness, merge count, a green check, a bounty amount and
an automated label do not establish that anyone responsible will look at our PR.

Keep the funding, commercial-risk, source-integrity, ownership and native release
gates. Fast attention must not be purchased by submitting unverified work, making
false claims, concealing automation or sending repeated notifications.

The priority order is:

1. Select wanted work with an identifiable, currently reachable review owner.
2. Understand the repository's actual contribution and notification conventions.
3. Present a focused change with a useful first screen and exact evidence.
4. Use one legitimate review route promptly when publication is ready.
5. Observe human response separately from automation, CI and merge; answer it quickly.

This can improve the probability and speed of attention. A gate cannot force a
volunteer to read a PR or guarantee a response deadline.

## 1. What “eye on the PR” can actually mean

GitHub does not give us a public per-maintainer read receipt. Therefore the metric
must say **observable attention**, not pretend to measure someone's eyesight.

| Event | What it establishes | What it does not establish |
| --- | --- | --- |
| PR created | Publication happened | A maintainer received, opened or understood it |
| Review requested / CODEOWNERS routing | A review request was created; GitHub documents notification behavior | Notification delivery, reading or a response SLA |
| CI, coverage comment, auto-label or AI review | Automation ran | A human maintainer looked |
| Another contributor reviews | A person engaged and may have found useful defects | That person can approve, merge or represent the maintainer |
| Maintainer-associated comment/review or authorized human triage | An observable action by a relevant human account | Favorable review, acceptance, merge or payment |
| Merge | Integration occurred | Fast external review, accepted bounty claim or payment |

Record these clocks separately:

- `created_at`: always retained as the absolute publication clock.
- `ready_for_review_at`: for a draft, the actual transition to ready; never reset
  `created_at` to make waiting appear shorter.
- `first_external_human_at`: excludes the author and identified automation.
- `first_maintainer_action_at`: first verified maintainer review, comment or triage.
- `first_substantive_maintainer_response_at`: meaningful review/answer, separate
  from a label or routing action.
- `first_useful_response_at`: a reasoned fix request, approval, routing response or
  explained rejection; bare insults, bot text and empty labels are not this metric.
- `author_response_latency`: how long we take to answer a human's actionable request.
- `merged_at`, `claim_status`, `payment_status`: separate downstream outcomes.

Do not game the primary objective by maximizing fast rejection. Show rejection,
requested changes, constructive engagement and favorable review separately.

## 2. Evidence collected and its limits

### Local evidence, inspected rather than assumed

The checked-out revision was `52fe501fc39f75e059836b98f96d32257d599f90`.
`scripts/bounty_admission.py` and `scripts/pr_conversion_watch.py` already had
uncommitted changes when this investigation began. References below describe
those working files, not a claim that the changes were deployed.

| Local source | What it contributes |
| --- | --- |
| `_probe/prs.json` | Historical 66-row author snapshot: 18 open, 47 closed, one merged; it does not contain first-human-event histories. |
| `scratch/all_prs.json` | Curated 18-row delivery inventory: 15 AWAITING_REVIEW, one CLOSED_UNMERGED, one FAILED_REMOTE_CHECKS, one DELIVERED. A ledger status is not a maintainer-response timestamp. |
| `scratch/verified-resume-41568509447/intake-41564183447/pr-conversion/report-20261031T233042Z.json` | Historical 20-PR watcher report: 18 external, 13 NEEDS_NUDGE, zero external merges. |
| Same directory, `report-20261103T023723Z.json` | Later 20-PR report: 17 external, 12 NEEDS_NUDGE, zero external merges. These snapshots overlap; they are not 40 independent PRs. |
| `scripts/pr_conversion_watch.py` | Existing review/CI/inactivity classification and proposed 14-day abandonment rule. |
| `scripts/actions_dispatch.py` | Merge/activity/daylight ordering and intake “first response” measurement. |
| `scripts/actions_delivery.py` | Public PR body, issue engagement comment and publication path. |
| `.github/workflows/bounty-discovery.yml` | PR observation is coupled to the discovery workflow and limited to 20 PRs in its invocation. |
| Existing funnel and forensic documents under `docs/` | Historical hypotheses and corrections. Their historical conclusions were not substituted for current API evidence. |

Fingerprints and sampling details are in
[the evidence manifest](evidence/PR-ATTENTION-MANIFEST-2026-11-06.json).

### New live GitHub sample

Read-only GitHub API collection finished at **2026-11-06 07:35:56 UTC**; analysis
used **07:37:22 UTC / 13:07:22 IST** as the observation cutoff. Requests were
collected over several minutes, not as an atomic snapshot.

- Author search returned all **86 visible PRs** for `isearchxsolve`; this fit in
  one 100-item search page. A separate search for `niloydassana-maker` returned zero.
- **Four controlled/self-test PRs** were separated: two in `bounty-proof`, one in
  `isearchxsolve/oss-hunter-livefire`, one in `tine1117/oss-hunter-livefire`.
- The remaining **82 authored PRs** are the noncontrolled author cohort.
- Collected the **20 most recently created PRs, any outcome**, from each of eight
  repositories where we submitted work: Fyne, Lux, microG, Perimeter, Spiralclass,
  Stride, assistant-runtime and Kendraio.
- Those 160 peer observations included 13 PRs already in the author cohort.
  Removing the overlap leaves **147 other-author peer PRs**.
- The deduplicated evidence table contains **233 unique PRs**: 86 authored plus
  147 additional peers. There are 229 after excluding the four controlled PRs.
- Comments, reviews and timeline connections were read with a first-100 bound;
  **no connection reported another page** in this sample. There was no silent
  truncation of those connections.

The [233-row CSV](evidence/PR-ATTENTION-2026-11-06.csv) contains links, roles,
timestamps, diff sizes and first-action evidence. Raw public API captures and
derived summaries are retained locally in
`scratch/pr-attention-forensics-20261106/`.

### How the human/maintainer proxy was constructed

Author comments/reviews were excluded. GitHub `Bot` accounts were excluded. A
comment/review counted as maintainer-associated when its association was OWNER,
MEMBER or COLLABORATOR, or the actor was independently identified that way in the
same repository's captured evidence. A personal repository's owner also supplied
role evidence. Nonauthor human-account label, merge, close and review-request
actions were counted separately as authorized triage.

These are conservative role proxies, not an exhaustive list of real maintainers.
A CONTRIBUTOR or NONE account can be a knowledgeable reviewer without authority;
unknown roles must remain unknown. Some services, such as Coveralls, use a `User`
account, so account type alone is not proof of humanity. Coveralls did not qualify
as a maintainer in the primary counts. A human account can also run automation;
substantive response should be manually/agent-verified from content.

### Quantitative observations

| Cohort | PRs | PRs with an observed maintainer action | Created at least 24h ago and not currently draft | Maintainer action within 24h in that creation-age set |
| --- | ---: | ---: | ---: | ---: |
| Our noncontrolled PRs | 82 | 4 | 80 | 4 / 80 = 5.0% |
| Other-author peers, all roles | 147 | 18 | See CSV; role strata are more useful | Not used as the principal comparison |
| Other-author peers, outsider associations only | 80 | 14 | 72 | 13 / 72 = 18.1% |
| Same outsider peer stratum, created in preceding 30 days | 68 | Not a separately fitted model | 60 | 13 / 60 = 21.7% |
| Our PRs in the eight comparison repositories | 18 | 1 | 16 | 1 / 16 = 6.25% |

“Outsider” here means the author was not OWNER, MEMBER or COLLABORATOR in captured
metadata. It does not mean first-time contributor. Membership metadata is current
at capture, not a reconstructed relationship at submission time.

For substantive maintainer comments/reviews, rather than any triage, the outsider
peer cohort had **10 / 72 within 24 hours**; our cohort had **4 / 80**. Three peer
24-hour successes were thus triage/routing rather than maintainer dialogue.

**Important exposure correction:** our historical 82-PR cohort contains **35
currently open and 47 closed PRs**. All 47 closed within 24 hours of creation,
and 43 have an author-initiated closure event. Those withdrawals/closures compete
with attention: the table's raw creation-cohort percentages must not be presented
as if every PR stayed available for review for a full day. They are not a clean
estimate of how quickly maintainers respond to our current, verified deliveries.
The CSV retains closure timestamps and author-closure evidence for re-analysis.

**78 / 82** had no captured maintainer action at cutoff. Some were withdrawn;
others remain open and censored. Neither group establishes permanent future
silence. The currently open subset contains 35 PRs, 33 aged at least 24 hours,
and one with an observed maintainer-associated action.
The four observed responses have a responder-only median of about 2.61 hours;
reporting that as our overall median would hide the 78 unresolved PRs. An overall
first-attention median is not established by this observation window.

The peer comparison is descriptive, not a causal estimate of how much any gate
will improve our response rate. Repositories differ in activity, backlog and
contribution type. Kendraio's latest 20 include older PRs. Original PR descriptions
may have been edited; current body length is not necessarily publication length.
Former drafts, censored young PRs, policy changes and unavailable private
conversations further limit inference. Self-withdrawal, fast negative closure,
merge and right-censoring should be treated as separate competing outcomes in a
later response-time analysis. No publication-hour or diff-size threshold
was fitted from this small convenience sample.

## 3. Case forensics: what actually got attention

| Case and primary evidence | Observation | Gate implication |
| --- | --- | --- |
| [microG #3947](https://github.com/microg/GmsCore/pull/3947) | A nonauthor human requested review about **16.9 minutes** after creation. Two files, 25 changed lines; the description explains the work-profile failure and names actual device testing. | A bounded, recognizable problem and a real reviewer route are a promising combination. The review request is routing/triage, not proof that its recipient immediately read it. |
| [Fyne #6651 review](https://github.com/fyne-io/fyne/pull/6651#pullrequestreview-5749364170) | Maintainer-associated response after **41.4 minutes**, acknowledging that the fix works. Two files, 114 changed lines, specific mechanism and regression coverage. | Put the behavior, cause, fix and decisive evidence where a maintainer can understand them immediately. |
| [Fyne #6657 comment](https://github.com/fyne-io/fyne/pull/6657#issuecomment-6640899491) | Constructive maintainer response after **55.7 minutes**, including a CI correction and a race in the new test. | Human attention is not conditional on every remote check already being green. Keep author-owned repairs distinct from legitimate requests for maintainer action. |
| [microG #3961](https://github.com/microg/GmsCore/pull/3961#issuecomment-6614539788) | A tiny two-line PR received a duplicate-of response in **35.8 minutes** and closed. | Smallness alone does not make a contribution wanted. Check whether another PR already solved the same need. |
| [Our Rekordcrate #279](https://github.com/Holzhaus/rekordcrate/pull/279#pullrequestreview-5639721357) | Maintainer-associated changes request in **52.2 minutes**, followed by closure. | Fast attention can be an unfavorable outcome. It must not be counted as successful review conversion. |
| [Our Agora #25](https://github.com/Shashwat-Kumar/agora/pull/25#issuecomment-6435910404) | Owner response in **2.61 hours**, closing without merge because claimed debate turns did not exist. | Source-truth and task-fit gates protect attention quality. Do not manufacture tests, discussion evidence or completed behavior. |
| [Our Perimeter #82](https://github.com/pavel1337/perimeter/pull/82#issuecomment-6628835981) | Owner response in **17.79 hours**, acknowledging use of parts of the approach in #83, explaining a scheduling defect and closing the original PR. | Useful attention, technical adoption, merge and payout are different outcomes. This is not proof of paid completion or, by itself, IP theft. |
| [Our Fyne #6637](https://github.com/fyne-io/fyne/pull/6637) | About **8.47 days** old at cutoff; no maintainer-associated action in the captured data. A [NONE-associated reviewer](https://github.com/fyne-io/fyne/pull/6637#pullrequestreview-5720057328) reported a specific native queue regression despite package tests passing. The body leads with SHAs and command arrays. | CI green and “someone reviewed” do not establish maintainer review or semantic correctness. Resolve credible findings; lead with the concrete fix, not execution plumbing. |
| [Our Stride #3816](https://github.com/stride3d/stride/pull/3816#pullrequestreview-5789352947) | A CONTRIBUTOR explicitly says they cannot approve/reject, then raises automation and testing concerns. Automated labels and our own comments exist; no captured maintainer action. | Record contributor feedback without claiming maintainer review. Check actual repository automation policies; do not disguise agent work as human authorship. |
| [Stride #3810](https://github.com/stride3d/stride/pull/3810) | Human triage in **2.52 hours** despite 227 files and 2,321 changed lines. | Do not turn “small is easier” into an arbitrary hard file/line ceiling. Large cohesive changes need a review plan and owner agreement. |
| [assistant-runtime #248](https://github.com/eandualem/assistant-runtime/pull/248) | Its AI/bot comment appears about ten seconds after creation; no captured maintainer action. All 19 other sampled PRs in that repository were merged, without captured nonauthor human attention in our metric. | A fast bot and an active self-merge stream can coexist with a cold outside contribution. Measure outsider attention directly. |
| [Lux #1115](https://github.com/Spectral-Finance/lux/pull/1115) and its cohort | No captured maintainer action on our 11 PRs or the 13 other-author PRs in this recent sample. | Further concentration should need an explicit evidence-backed reason or exception. Do not keep spending engineering simply because issues advertise substantial amounts. This snapshot alone is not proof of permanent abandonment or fraud. |

The contributor's policy citation in the Stride review requires verification: the
referenced repository issue #586 is a cubemap problem, not sufficient evidence of
an automation policy. A root `CONTRIBUTING.md` lookup returned 404; that does not
prove there is no policy elsewhere. The proposed gate must read the applicable
current policy instead of turning a reviewer's claim into an automatic ban.

### Why the 14-day “dead PR” inference must be removed

Two deliberately selected counterexamples, **not pooled into the peer rates**:

- [Fyne #6505](https://github.com/fyne-io/fyne/pull/6505) was created August 25 and
  merged October 13, about **48.6 days** later.
- [Fyne #6103](https://github.com/fyne-io/fyne/pull/6103) was created February 9 and
  merged October 24, about **257.3 days** later. Its captured public timeline
  includes a July maintainer comment and an October integration after a long gap.

These do not prove that indefinite follow-up is economical. They prove that a
long wait is not a deterministic “never merges” fact. Our own noncontrolled cohort
is younger than 14 days at this cutoff, so it cannot validate a 14-day terminal
rule either. Parking an unanswered PR can be an explicit effort-budget decision;
permanent abandonment must not masquerade as a statistical certainty.

## 4. What the existing gates miss

| Inspected local behavior | Problem for the attention objective | Proposed disposition |
| --- | --- | --- |
| `repository_intent()` uses total merges and merge/push recency | It observes activity, not response to an outside author or relevance to our component. Self-merges can dominate. | Retain the observations; replace their role as a sufficient attention decision with source-backed agent assessment of outsider review behavior. Explicit closed/read-only state remains factual. |
| `is_daylight_active()` infers availability from recent push and five commit hours | Commit author timing, bots and global contributor activity are not the target reviewer's availability. | Demote to a weak, labelled timing hint; prefer the actual review owner's observed review times and stated schedule. Do not hold a ready PR indefinitely for a guessed timezone. |
| Founder/band, hardness, liquidity and velocity can dominate ordering | Difficulty, payout and organizational type do not establish a short review path. | Keep eligibility/commercial constraints; rank attention-ready work within them using real review-route evidence. Do not replace one fixed keyword score with another. |
| `first_response_minutes_median` in dispatch | It measures disposition of an intake row, including our own refusal/qualification, rather than human response to a PR. | Preserve/rename it as intake latency in a future compatible change; add separately named PR-attention clocks. |
| `pr_facts()` counts every review state | A bot or unrelated contributor review can make a PR look in-review. Our Stride/Fyne examples show why actor identity matters. | Track actor, association/authority evidence, review type, commit and first maintainer response independently. |
| All historical review states are aggregated with CHANGES_REQUESTED taking priority | An old request can dominate a later approval; dismissed reviews and source-head changes need chronological handling. | Evaluate current applicable review state per actor/head without erasing history. A model interprets requested work; code checks identities and timestamps. |
| Proposed last-maintainer clock uses `created_at` for REST review objects and falls back to PR `updated_at` | REST reviews use `submitted_at`; fallback can be refreshed by our own comments and bot churn. | Use actual actor-specific event timestamps. Unknown remains unknown. Keep the no-response clock anchored to creation/ready state. |
| A pending/failing check takes precedence over attention state | Awaiting external workflow approval can be misreported as a reason merely to wait or fix our code. | Split author-owned failure, CI running, CI unavailable, baseline failure and maintainer-approval-required. Request only the action the maintainer can actually perform. |
| `NUDGE_AFTER_DAYS=2` | A follow-up delay is not an initial routing mechanism and is not a universal repository SLA. | Plan initial routing at publication. Calibrate later follow-up to repository convention and observed response behavior. |
| Proposed `ABANDON_AFTER_DAYS=14` / `stop_engaging` | Converts censored inactivity into a terminal judgment; misses late recoveries and explicit review promises. | Replace with reversible low-priority/attention-deferred disposition plus a recorded reason and reactivation conditions. Never auto-close/reopen to gain visibility. |
| PR body starts with generic issue resolution and verification plumbing | It makes a busy reviewer derive the actual mechanism from a long report. | Use a specific symptom/cause/change/evidence summary; preserve detailed evidence in an accessible collapsed section. |
| A sponsorship/payout footer is appended to every public body | It is not a review route; its effect on response was not causally measured. | Keep platform-required claim syntax and commercial evidence. Make optional solicitation absent from the initial review request by default, unless policy/explicit agreement requires it. Do not infer payment protection from a sponsor link. |
| Watcher runs inside discovery, and the invocation selects only 20 updated PRs | Long discovery cycles and selection churn can delay observation or starve older open PRs; our author search has 86 visible PRs. | Plan a separate bounded observation obligation, with pagination/coverage receipts and event-triggered decisions where available. Keep watching read-only unless a communication action is explicitly authorized. |

The existing publisher does post an engagement comment to the original issue.
That is an existing route, not an absent feature to reinvent. The gap is whether
it reaches the appropriate owner, follows repository policy and asks a useful
specific question. No explicit reviewer-request operation was found in the
inspected publisher path; that must not become an unconditional new requirement,
because outside contributors may lack permission to request reviews.

## 5. Proposed gate contract

### Principles

- **Code checks facts; an agent reads and decides.** Owner selection, policy
  interpretation, reviewability and attention priority belong to a model with
  read tools and cited evidence, in accordance with Law 85.
- Add PASS / HOLD / UNKNOWN / NOT_APPLICABLE and a named reason. Missing data is
  not evidence that a maintainer is absent or uninterested.
- A soft priority signal must not quietly become a permanent admission veto.
- Each gate should verify one boundary and have independently supplied inputs;
  no campaign must first succeed merely to exercise an attention gate.
- Keep source versions and original evidence. A revised owner, policy or PR head
  can invalidate a decision without justifying duplicate work or reset counters.

### Gate register: add, change, retain or remove

| ID / stage | Disposition | Exact obligation | Agent judgment / factual check | Failure or unknown behavior |
| --- | --- | --- | --- | --- |
| ATT-01 / target selection | ADD: wanted-work and policy fit | Current issue, relevant changes and applicable contribution/automation policy support this kind of contribution. | Agent interprets scope/policy; code verifies cited URL, revision and literal excerpt. | HOLD on explicit conflict; UNKNOWN on missing source. Never impersonate human authorship. |
| ATT-02 / before expensive work | ADD: owner and route | Identify a responsible person/team or established triage channel for the changed component, with evidence. | Agent reads current CODEOWNERS on the base branch, contribution instructions, recent relevant reviews and issue discussion. Code verifies identities/source facts. | UNKNOWN/clarification lane if no verified route; do not invent a handle or mass-mention maintainers. |
| ATT-03 / target priority | CHANGE: outside-contributor responsiveness | Inspect recent comparable outside PRs, responses, unanswered backlog and what the maintainer actually accepted/rejected. | Agent interprets a representative sample; code computes censored clocks and excludes author/bot/self-test activity. | Low priority or bounded exception, not “no response means dead.” Small/new repositories remain eligible with an explicit rationale. |
| ATT-04 / before publication | ADD: first-screen reviewability | Title and opening explain the user-visible problem, exact mechanism, focused change, decisive evidence and any limitation; name where review should start. | Agent self-reviews the actual diff and summary. Code checks required references/receipt identity, not writing quality via keyword lists. | Repair presentation or narrow/split work where technically appropriate. No arbitrary line-count rejection. |
| ATT-05 / release | RETAIN: truth and verification | All existing source, native verification, regression, scope, ownership, security and commercial checks remain satisfied. Claim only evidence actually obtained. | Existing factual gates; agent resolves semantic findings against actual artifacts. | Repair before presenting work as verified. Do not relabel failures to produce attention-ready status. |
| ATT-06 / publication | ADD: ready-state and base/target check | Correct upstream repository/base/issue/head, intended ready-versus-draft state, and supported contribution declarations. | Factual API/state check plus verified policy decision. | Fix wrong routing/state. A draft can be intentional but is not counted as a ready-for-review publication. |
| ATT-07 / immediately after ready publication | ADD: legitimate routing decision | Choose one repository-approved route: automatic CODEOWNERS, formal review request if permitted, original issue handoff or an established triage channel. Include the concrete review/approval request. | Agent chooses; code checks permission, target, duplicate action and outcome receipt. | Permission denial is a route limitation, not a nonexistent reviewer. Do not retry forbidden requests or send unsolicited DMs/email. No action executes without authorization. |
| ATT-08 / post-publication CI | CHANGE: unblock the correct actor | Separate code-caused red CI, external approval required, known baseline failure, running CI, unavailable checks and no configured CI. | Code observes status and head; agent interprets the actual diagnostic. | Repair our failure; request authorized approval with local evidence when it is a maintainer action. Do not wait for an approval-dependent run to become green before requesting approval. |
| ATT-09 / observation | ADD: real attention receipt | Record first routing, first outside-human, first verified maintainer action and first substantive response with event permalink, actor evidence, timestamp and PR head. | Factual event collection, with agent resolution of ambiguous identities/content. | UNKNOWN on incomplete pages/API failure; never fill missing attention from CI, our own comments or `updated_at`. |
| ATT-10 / human response | ADD: responder obligation | Read and answer the specific question, fix the requested issue or acknowledge an explicit schedule. Preserve prior verification; revalidate affected facts. | Agent interprets response; code retains task/PR identity, owner, head, commitments and receipts. | Named pending action with an owner and deadline appropriate to the repository. Do not restart discovery for an already-owned PR. |
| ATT-11 / follow-up | CHANGE: bounded and policy-aware | Use an established review route first; later follow-up must contain new useful information or an appropriate specific request and respect previous acknowledgments. | Agent decides whether a follow-up is warranted; code checks prior contact, acknowledgment, cooldown and authorization. | Wait/park with reason if not warranted. Stop reminders after explicit refusal or promised review date until circumstances change. No repeated “all tests green” noise. |
| ATT-12 / inactive work | REMOVE terminal age inference; ADD reversible parking | Age and no response affect the attention budget but do not prove future impossibility. Record the last human event and reactivation trigger. | Agent allocates effort; code preserves history and observes subsequent events. | ATTENTION_DEFERRED, not fabricated abandonment. Keep PR/counters/evidence; do not auto-close/reopen or reset the waiting clock. |
| ATT-13 / portfolio allocation | ADD: bounded concentration review | Before allocating more engineering to a repository already holding unanswered PRs from us, compare expected attention and other eligible targets. | Agent evaluates current evidence and any explicit maintainer invitation. Code measures our pending load and available capacity. | Defer additional speculative work or record a justified exception. A maintainer requesting a series must not be blocked by a fixed one-PR limit. |

### Signals to remove from the hard attention decision

Do not automatically approve or reject attention readiness based on high bounty,
stars, total historical merges, nationality/location, day-of-week, five commit
hours, small diff size, an AI/bot review, all CI green, a sponsor footer, or a
fourteen-day age. Some are useful contextual observations; none alone establishes
that the right person will respond quickly.

This does not remove exact permission, funding, source-truth, security, closed
issue, archived repository, duplicate work or release-verification checks.

## 6. Notification and review evidence from primary sources

These sources support mechanics and hypotheses, not guaranteed response times:

- [GitHub: requesting a review](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/requesting-a-pull-request-review)
  documents the write-permission requirement and that requested reviewers receive
  notifications. Outside contributors cannot assume this operation is available.
- [GitHub: CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
  explains base-branch ownership and automatic review requests. Draft PRs do not
  automatically request owners; ready-for-review transitions trigger the owner
  notification behavior. Do not add/change upstream CODEOWNERS merely to gain attention.
- [GitHub: helping others review](https://docs.github.com/en/pull-requests/concepts/helping-others-review-your-changes)
  recommends focused changes, specific context, self-review and linking related
  work. This supports reducing the reviewer's comprehension burden; it does not
  establish a universal file-count cutoff.
- [GitHub: approving fork workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)
  confirms that an upstream maintainer may have to approve a workflow. Approval
  required must not be confused with our code failing or CI merely running.
- [GitHub: allowing maintainer edits](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork)
  describes a collaboration option and its workflow/secret implications. The three
  inspected PRs #6637, #3816 and #3970 already allow maintainer edits, so disabling
  that option does not explain their silence. Preserve branch ownership and do
  not enable access indiscriminately as an attention trick.
- [Hasan et al.: first response study](https://arxiv.org/abs/2304.08426)
  analyzed 111,094 closed PRs in ten projects and found important bot/human timing
  differences. Its closed-PR population and definition differ from ours; its
  results do not supply our response SLA.
- [Khatoonabadi et al.: maintainer/contributor response latency](https://arxiv.org/abs/2311.07786)
  studied 20 projects and found associations involving description length,
  submission timing and contributor history. These are prioritization hypotheses,
  not causal guarantees or a reason to ban new contributors.
- [Google's reviewer guidance](https://google.github.io/eng-practices/review/reviewer/speed.html)
  distinguishes prompt responses from completed review and describes a one-business-
  day response expectation within its own setting. That is useful operational
  guidance, not an enforceable SLA on unrelated open-source maintainers.

## 7. A review package the agent should prepare

This is a content contract, not a new boilerplate body pasted onto every PR:

> **Title:** the component and concrete behavior corrected.
>
> **Why:** who is affected and a reproducible before-state, with the original issue.
>
> **Change:** the actual mechanism and narrow scope; identify the first file to review.
>
> **Evidence:** the decisive regression result and relevant native/platform checks,
> with accurate limits and a link to fuller diagnostics.
>
> **Request:** one specific review/triage/approval action for the relevant owner,
> through the repository's accepted route.

For a platform-specific performance or UI claim, generic package tests may not
demonstrate the claimed behavior. Provide the relevant device/runtime evidence or
clearly state what remains unverified. The Fyne review illustrates why this matters.

Keep base/head, provenance, complete command output and receipts available behind
the summary. Do not erase them to look less automated. Follow required automation,
licence and contributor declarations; readable prose is not permission to claim
human authorship. Keep required bounty claim syntax separate from optional
solicitation and never insert private payment coordinates or credentials.

## 8. Independent probes for the proposed gates

No real PR creation, public ping or successful delivery campaign is required to
test these predicates. Use archived/public read-only evidence and independently
supplied inputs. Any later publication or contact action requires its own authority.

| Probe | Input supplied independently | Required result |
| --- | --- | --- |
| ATT-P01 | PR receives a coverage bot comment and green CI | No human/maintainer attention receipt created |
| ATT-P02 | Bot uses a `User` account but content/profile establish automation | Automation remains excluded; evidence of classification retained |
| ATT-P03 | Author posts several comments or pushes a new head | Original waiting clock retained; no maintainer response manufactured |
| ATT-P04 | An unaffiliated contributor reviews; no maintainer event exists | External-human attention recorded, maintainer authority remains unverified |
| ATT-P05 | Human maintainer adds a label with no review text | Triage clock recorded; substantive-response clock remains unset |
| ATT-P06 | Draft becomes ready after several days | Both creation and ready clocks retained; correct CODEOWNERS/base behavior assessed |
| ATT-P07 | External author cannot request a reviewer | Permission limitation recorded; agent chooses an authorized alternative, no repeated POST |
| ATT-P08 | CI requires maintainer approval | Maintainer-approval obligation identified, not “wait for green” deadlock |
| ATT-P09 | One historical changes-requested review, later approved/dismissed | Correct latest applicable actor/head state; old history preserved |
| ATT-P10 | Repository has many owner self-merges and unanswered outsider PRs | Total merge count cannot satisfy outsider-attention evidence by itself |
| ATT-P11 | An API page or actor timestamp is missing | UNKNOWN/incomplete evidence, never zero-latency or a silent dead-project verdict |
| ATT-P12 | No response for 14 days, followed by a valid maintainer event | Reversible parking/reactivation; retained original age and evidence |
| ATT-P13 | Large cohesive PR with owner invitation, versus tiny unwanted duplicate | Agent evaluates wanted scope and review plan; no mechanical size-based inversion |
| ATT-P14 | Existing explicit invitation or a promised review date | Preserve the invitation/schedule; do not spam or apply a blind inactivity veto |
| ATT-P15 | 86 authored PRs, watcher page selects only 20 | Coverage/pagination and unobserved remainder visible; old work not silently dropped |
| ATT-P16 | Claimed screenshot/test/issue fact absent from source | Named source-truth failure before public claims are made |
| ATT-P17 | Proposed contribution policy cited by another commenter, but citation is unrelated | Re-read the authoritative policy; do not manufacture a ban or permission |
| ATT-P18 | Prior attention decision reused after policy, owner, head or route changes | Revalidate changed prerequisites; keep earlier receipts and task identity |

Pure routing/counting cases are not labelled live service failures. Read-only API
cases should state which real boundary was exercised. Model judgments should be
evaluated against reviewed cases and counterexamples; no finite sample should be
reported as a mathematical proof of all future maintainer behavior.

## 9. Implementation order for a later, separately authorized change

1. **Measurement first:** separate attention, CI, contributor review, maintainer
   review and merge; preserve clocks and actor evidence. Correct timestamp,
   chronological-state and pagination gaps without changing old receipts.
2. **Targeting and preparation:** give the agent repository policy, reviewer-owner
   sources and comparable outside-PR histories before expensive engineering.
   Let it return a cited attention plan, not a new static attention score.
3. **Publication presentation and routing:** keep release gates; require a specific
   review package and one permitted route as soon as a verified PR is ready.
4. **Observation and response:** decouple attention observation from long discovery
   runs, account for all owned PRs, and act on the maintainer's actual question.
5. **Follow-up and concentration:** replace unsupported terminal-age inference with
   bounded reversible effort decisions; measure whether attention improves.

Suggested internal objectives, **policy targets rather than empirical guarantees**:
prepare the routing decision before publication; record its permitted action or
explicit limitation in the publication cycle; detect a newly observed human
response within a bounded watch interval, initially 15 minutes if API budget
allows; alert on an actionable response we have not handled within one of our
working hours. Do not hold a valid PR waiting for a guessed reviewer work window.

To assess effectiveness later, compare predeclared, comparable outside-contributor
cohorts by repository/component and report 6h/24h/72h response rates only for PRs
observed that long. Keep unresolved PRs censored. Report constructive engagement,
negative triage, author response time, duplicate/noisy contacts and review quality
alongside speed. Do not infer causality from a few favorable examples, and do not
withhold safety or truth checks for an experiment.

## 10. Handoff decision

The proposed attention gate is **“appropriate owner + wanted work + reviewable
evidence + a legitimate route,”** supported by a measured response history and an
honest waiting clock. It is not **“busy repository + green checks + another ping.”**

The local and real-world samples establish concrete defects in the existing
attention proxies and justify the gate changes above. They do not establish a
universal fastest publication hour, a magic PR size, a guaranteed response time,
or permission to contact maintainers during this documentation task.

## 11. Authorized presentation update after the study

The user subsequently requested a template change and specified neutral wording,
with disclosure only when asked. That presentation change is implemented locally:

- The Actions publisher asks the engineer for a short `review_note` in the
  existing regression artifact: title, actual cause/fix, specific changes,
  limitations and disclosure only when explicitly requested, including a request
  in repository contribution requirements. The note travels in the release receipt.
- The default PR text makes no unsolicited AI disclosure and no claim of human
  authorship. An explicitly supplied/requested disclosure remains visible.
- Titles no longer get the automatic `fix: #number -` tracker prefix. The Actions
  path uses the engineer's change-focused title when supplied; older receipts
  safely fall back to the existing issue title without inventing a mechanism.
- The opening presents the concrete change. Commands and base/head provenance
  remain in an expandable details section; command quoting and working-directory
  wrappers are retained. Required issue links and bounty claim commands remain.
- Testing text reflects recorded exit results. Missing/malformed regression
  evidence does not acquire a success claim. Limitations stay visible. Credential
  scanning also applies to the rendered Actions title/body.
- The issue handoff is shorter, with reproduction/evidence inside details. Its
  existing private-payment-coordinate guard is retained.
- Both older posting paths use a shorter opening and expandable receipts. Their
  planned scenario lists remain available but are no longer described as proof
  that every listed scenario actually ran. The corresponding presentation
  assertions were updated; native verification gates were not weakened.
- The existing sponsorship footer remains inside the Actions details block for
  compatibility. The proposal to make solicitation optional is not implemented
  as a separate commercial-policy change here.

[See the rendered-text preview](PR-PRESENTATION-PREVIEW-2026-11-06.md). It uses
explicitly illustrative fixture data, not a claimed customer delivery.

Validation: 24 claim/presentation tests, 11 funnel/report tests and the outreach
self-test passed. Four affected regression suites passed: Actions migration,
Cline delivery ownership, ICU pipeline integrity and pipeline repairs. Compilation,
F821 checks and whitespace checks passed; the tracked credential scanner reported
no findings. Regression report:
`scratch/pr-template-20261106/final-regression/20261106T080333570584Z/report.json`.

These are local code/test results, not evidence that response times have already
improved. No existing public PR/comment was edited, no review request was sent,
and no deployment was performed. The attention-gate register above remains a
documented proposal rather than an implemented gate policy.
