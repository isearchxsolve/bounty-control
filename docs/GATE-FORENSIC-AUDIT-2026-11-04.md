# Historical gate audit and repairs — 2026-11-04

Repository: `isearchxsolve/bounty-control`, checkout `D:\bc`.
Historical baseline: `20ae33f5d783c4e7889e766ad1b63e931d8e36e2`.
The companion [structural inventory](GATE-FORENSIC-INVENTORY-2026-11-04.json)
records exact working-file hashes: 26 control-plane/shared modules, 379 raise,
assertion and named-return sites, and eight workflow fingerprints. These are
structural sites, not 379 independently established defects or exhaustive proofs.

## Conclusion

The recurring pattern is **inconsistent evidence and authority at boundaries**.
Some gates interpreted prose as facts, some newer entry paths bypassed older
protections, recovery reused evidence without checking its prerequisites, and
some repairs relaxed verification instead of repairing the submitted evidence.
Green test/workflow status also sometimes meant a refusal, a blocked check, or a
mocked boundary, rather than a delivered and paid result.

The repair follows Law 85: give the agent real sources and tools to interpret
commercial intent; keep literal evidence, identities, money shape, hashes,
ownership, capacity and actual execution receipts in code. Do not grow a blacklist
of allegedly dishonest repositories or a new prose classifier for every incident.
Law 86 remains binding: retain the task, artifacts, dispatch generation, ownership
and bounded history; reconsider only invalid evidence and continue from the
earliest stage that genuinely needs repetition.

No gate can establish that an arbitrary counterparty will pay in the future.
This audit does not certify proven IP theft, legal protection from an attribution
footer, all optional external deployments, or complete live master-suite parity.

## Evidence and chronology

| Evidence | Established observation | Gate implication |
| --- | --- | --- |
| [November 1 forensic audit](PIPELINE-FORENSIC-AUDIT-2026-11-01.md), F01–F20 | Split admission, manufactured approvals, duplicate dispatch, ownership/recovery and reporting failures were independently identified. Its historical counts require the corrections in that document. | Do not equate earlier diagnosis or a green suite with current deployed verification. |
| `3b9c2d2`, `5c61e36`, `b9861d1`, `21b53bd` | Production moved to a sovereign model entry door, with source-bound proof and generation-fenced handoff. | A protection added only to legacy `admit()` is not automatically enforced by `verify_model_rows()`. |
| [Lux PR #1059 comment](https://github.com/Spectral-Finance/lux/pull/1059#issuecomment-6584678943), November 2, 18:12:38 UTC | A CONTRIBUTOR alleges nonpayment and warns of a possible scam. It is on a linked PR, outside issue #54's own comments. PR #1059 belongs to another contributor; it is not evidence that our code was stolen. | Read linked discussions; treat the allegation as material review evidence, not an adjudicated fraud finding. |
| `87dc54a` | A raw issue-age/withdrawal check was added across row paths. | Issue activity is not offer renewal; withdrawn, renewed, quoted and disputed statements need chronological interpretation. |
| `28d227b`, `fba2eec` | Merge recency and activity telemetry were added to economic targeting. | Activity can inform prioritization, but it is not settlement or escrow evidence. |
| `b459a38`, `c4d849f` | No Free Service and co-authorship changes were introduced. | Missing USD valuation still bypassed dispatch; attribution cannot make payment or IP appropriation impossible. |
| `501f0f1`, `20ae33f` | Community-warning and stale-offer gates were added and documented. | Warning enforcement was absent from the production model path; programme membership or any trusted-bot comment could bypass stale-funding checks as supposed escrow. |
| [Overnight RCA](PIPELINE-ROOT-CAUSE-ANALYSIS-2026-11-04.md) and [run 41743861212](https://github.com/isearchxsolve/bounty-control/actions/runs/41743861212) | Six repair deliveries overlapped despite intake's four-slot capacity. Cache bytes, cwd and malformed argv failures were multiplied by retries. | Repairs must consume the same capacity and retain bounded attempts; source/runtime faults must not be classified as poor engineering. |
| `32b0a08` and inspected `delivery_supervisor.validate_plan()` | A same-prefix but corrupted 64-character hash could be accepted and rewritten as the correct hash. The positive monorepo test explicitly used a corrupted suffix. Any new test target could also satisfy the preservation guard. | Reinstate exact committed-source hashes and preservation of the required baseline targets. Correct the evidence/fixture rather than fabricate its successful validation. |
| [Independent run 41683203688](https://github.com/isearchxsolve/bounty-control/actions/runs/41683203688) | The historical report said passed with two BLOCKED receipts and `full_e2e_passed=false`; some imported suites still replace providers. | BLOCKED is unfinished. A passing subset cannot certify full live E2E or settlement. |

Live read evidence for this audit is retained locally under
`scratch/gate-forensics-20261104/`. The initial issue #54 snapshot contained 34
documents and the actual PR #1059 warning. The later connected regression also
reads PR reviews, inline comments and the licence endpoint. Raw snapshots and
test logs are ignored local evidence, not permanently published artifacts.

## Gate-by-gate disposition

This table covers the control-plane gate families across the indexed modules.
The machine-readable inventory supplies individual check locations and source
fingerprints; returned refusals and model decisions also require the manual
path analysis below. KEEP does not mean every external condition was re-executed
live during this audit.

| Gate family / owner | Disposition | Factual boundary and interpretation |
| --- | --- | --- |
| Workflow entry, lane and issue scope / `agent_door`, `sovereign_discovery` | KEEP | Actual authorized issue/repository and lane; no expansion of a scoped repair into unrestricted discovery. |
| Issue existence, open state, repository availability / `cline_entry_door`, `pipeline_evidence` | KEEP | Read GitHub state, archived/disabled flags and complete comments. API failure is unavailable evidence. |
| Current payer, source authority, scope, by-design, code-task, expiry and commercial intent / model door | REPAIR placement; agent interprets | Read actual authors, offer chronology and source code. Code verifies URLs, payer/source login, literal offer/scope quotes, parsed amount, product blob and task identity. No second downstream quality judgment. |
| Legacy regex admission / `bounty_admission`, legacy hydration | RESTRICT legacy status | Kept for compatibility and its original contracts; it does not replace the production model review. Its primary-only proof cannot authorize claim or publication without the new review. Do not claim these legacy heuristics were all deleted. |
| Community nonpayment / `commercial_context` | REPLACE automatic fraud verdict | Existing warning phrases are triage/citation signals only. Require source-bound agent review on every fully collected production candidate, including allegations, negation, quotations, responses and uncertainty. No additional keyword list or repository blacklist. |
| Linked evidence / `commercial_context.collect` | ADD missing read boundary | Fetch timeline-linked PR bodies, full issue comments, reviews, inline comments, README/contribution terms, licence and merge observations. At most 12 linked PRs; overflow or required read failure is explicit incomplete evidence. This is a bounded source scope, not a global fraud search. |
| Offer staleness / model door and legacy funding helper | REMOVE raw production inference; repair legacy hold | `updated_at`, an unrelated new comment and bot presence do not renew an offer. Model reviews actual chronology. Legacy age policy uses the exact cited offer publication date and returns review-needed/unknown, not a nonpayment verdict. Missing legacy creation dates remain explicitly unmeasured. |
| Escrow / all admission paths | REMOVE unsupported exemptions | Programme membership and a bot comment do not establish a funded escrow balance. No escrow receipt is invented. An actual fresh cited offer can fund an old issue without being called escrow. |
| Repository merge count, recency, commit hours / targeting | REMOVE automatic production economic veto; retain observations | Model interprets observed activity with current terms. Merge count/push time does not establish payment. The legacy high-value path no longer waives unknown repository observations because a bot appeared. |
| Monetary shape and No Free Service / `payment_gates` | REPAIR and share | Dispatch, claim and publication require a finite positive recorded USD value, or explicit USD/USDC/USDT face amount. Foreign offers need a recorded conversion. Missing/zero/negative/NaN/infinite values cannot authorize work. The existing explicit unpriced-founder environment exception remains named, off by default, and is never represented as paid funding. |
| Changed commercial evidence / claim and publication | ADD revalidation | Source digest and literal citations must still match before work or public exposure. Legacy proof requires review. Persist a generation/owner-fenced review hold immediately, retain artifacts/counters, record the failed phase, and prevent automatic engineering retries for a commercial hold. |
| Competition / door plus last-minute race checks | KEEP | Competition has its own evidence and unavailable state. A newly appeared real claimant is a changed prerequisite, not a reason to repeat original admission. No change to the existing competitor contract. |
| Dispatch generation, duplicate send and bounded attempts / `actions_dispatch`, `StateStore` | KEEP | CAS reservation, matching generation, acknowledgement and existing attempt/send caps remain. Reconsideration retains old refusal history; no counters are reset. |
| Capacity and repair backlog / discovery and reconciliation | REPAIR repair path | Count complete active delivery-run pages and durable reservations. Repairs now share the existing four-slot limit and increment local use after dispatch. Capacity unknown/wait does not spend an attempt or erase the obligation. Concurrent independent external dispatchers are not globally serialized by this local count. |
| Worker lease, cancellation and publication owner / `StateStore`, delivery | KEEP | Revoked/stale owners cannot publish; ownership is checked separately from an agent's report. Preserve the existing cancellation/sweep contracts. |
| Runtime, gateway, throttle and deliverable shape / worker, proxy/router, typed errors | KEEP | Real exit/timeout/missing artifact and malformed argv/receipt are distinct from engineering verdicts. Existing bounded retry/backoff remains; no change to model selection or budget policy. |
| Preparation source and native plan / supervisor | REPAIR weakened factual gates | Exact full SHA-256 of the cited committed object; unsafe paths refused before basename recovery. An untracked source can only match its actual bytes. Do not accept a short prefix, a corrupted suffix, altered disk bytes as a committed-object citation, or silently complete a guessed digest. |
| Native verification, baseline protection and target preservation / supervisor, release | KEEP and restore | Native phase arrays, non-synthetic commands, actual successful receipts, nonzero test count, untouched baseline and red-to-green regression stay mandatory. Preserve baseline targets through shell wrappers; a different test target no longer substitutes for a dropped required target. |
| Companion path, cwd, generated cache and checkpoint restoration / release, worker | KEEP prior factual protections; monitor | Keep real source/test artifacts, path and archive bounds, baseline SHA and native execution coordinates. The earlier binary-cache/cwd incidents remain causal evidence; this audit does not relabel old failures as post-fix failures. Existing broader path/expected-failure heuristics still deserve independent regression probes. |
| Independent release, bundle, native receipts and base SHA / delivery, release | KEEP | Retain original immutable bundle/manifest, base/head identity and native command requirements. An upstream race requires actual rebase/reverification. No relaxed release gate is introduced to obtain green. |
| Publication access, fork identity, head and credentials / publisher, access probe | KEEP | Credential-specific observed permissions and actual target policy; read access is not a promise that a later write will succeed. Co-author/provenance footer is attribution only. No public comment or PR was posted for this audit. |
| Secret exposure / tracked-secret gate | KEEP with explicit scope | Existing credential-shaped literal scanner is enforced in CI. It does not certify old history, artifacts, model context or every credential format. Never print secret values in audit evidence. |
| Remote checks, reviews, merge, claim and settlement / reconcile, conversion watch | KEEP distinct outcomes | No checks, pending checks, approval required, merge, accepted claim and paid settlement are different facts. `payment_status=UNVERIFIED` remains until independent payment evidence exists. Delivery is not proof of payment. |
| Test verdict, BLOCKED and subtests / live runner | REPAIR false green | Every planned parent needs PASS and every recorded receipt must be PASS. BLOCKED/NOT_RUN/fixture failure cannot disappear from the verdict. A passing child does not complete its failed parent. Full E2E remains a separate, false-by-default claim. |
| Probe continuation and provenance / live runner, campaign resume | REPAIR reuse | Archive the pre-resume report and superseded receipts. Reuse only complete PASS methods with unchanged source fingerprints and unchanged recorded live-source prerequisites. Unknown/changed provenance invalidates reuse, while retaining history. A targeted repair cannot erase unselected failures. |

## Implemented commercial decision contract

The scout receives a real read-only tool, rather than another list of fraud rules:

```powershell
python scripts/commercial_context.py --repo OWNER/REPO --issue NUMBER
```

The agent reads the returned sources as untrusted data, investigates material
terms/allegations and provides:

```json
{
  "commercial_review": {
    "decision": "proceed",
    "source_revision": "exact digest returned by the tool",
    "reason": "source-backed assessment of current payment, publication terms and risks",
    "evidence": [{"source_url": "actual document permalink", "quote": "literal excerpt"}]
  }
}
```

`hold` and `reject` remain valid agent decisions but cannot authorize dispatch.
Code checks collection completeness, matching revision, nonempty explanation,
literal citations and acknowledgement of each signalled warning document. It
cannot prove that the model understood every sentence correctly. New warnings
outside the old phrase signals must still be assessed by the agent reading the
full sources. Relevant external policies and conversations outside this bounded
collector remain an agent investigation responsibility, not an invented proof.

At claim/publication, changed or missing review produces
`REJECTED_COMMERCIAL_REVIEW`, `kind=commercial_review`, `retryable=false`,
`review_required=true`, and `resume_phase=claim|publish`. This is an explicit
extension of the documented terminal taxonomy, with a strict taxonomy regression;
it does not weaken native verification or mark work delivered. A pre-claim hold is
written against the exact pending dispatch generation so reconciliation cannot
mistake it for a missing worker receipt and blindly redispatch it.

The next agent must read the retained diagnosis, re-review real changed sources,
cite the existing record's `updated_at` in explicit reconsideration when required,
and keep task/generation/attempt/publication history. Existing retired refusals
and exhausted budgets are not bulk-replayed. A publication hold keeps its release
artifacts; reuse them only after their actual source, base, ownership and native
receipt prerequisites are revalidated. The recorded phase is a continuation
instruction, not a fabricated success receipt or a new automatic resume driver.

## Verification and reproducible commands

All verification below must distinguish offline execution from connected probes.
The regression manifest still contains its original suites and assertions; three
additional suites cover monetary facts, commercial evidence/hold behavior and
live-runner receipt integrity. Positive fixtures now contain the paid/reviewed
evidence their existing ownership/reservation assertions require. The former
positive corrupted-hash fixture was corrected, and explicit negative checks now
prove that corrupted/truncated hashes and dropped targets are refused.

```powershell
# Regenerate the structural evidence without importing the pipeline.
python scripts/audit_pipeline_gates.py --output docs/GATE-FORENSIC-INVENTORY-2026-11-04.json

# All reviewed offline regression suites; this does not certify live E2E.
python scripts/run_pipeline_master.py --output scratch/gate-forensics-20261104/verified-master

# Connected historical incident probe plus local factual-gate regressions.
python scripts/run_pipeline_live_probes.py --test test_commercial_context_live --test test_payment_gates --test test_commercial_context --test test_live_probe_receipts --output scratch/gate-forensics-20261104/verified-live

# Continue an existing probe report, preserving valid completed observations.
python scripts/run_pipeline_live_probes.py --resume PATH_TO_PRIOR_REPORT
```

The last command resumes fault probes, not customer discovery. The runner
conservatively invalidates receipt reuse when any fingerprinted Python source
changes because an exact dependency impact map is not available. It retains the
old evidence; it does not pretend it exercised the new gate. Live test inputs
include one real historical issue/linked warning plus deliberately incomplete
decision inputs. No customer engineering, publication, payment or external
messaging is performed by the new incident probe.

Final measured results are retained in
[GATE-FORENSIC-VALIDATION-2026-11-04.json](GATE-FORENSIC-VALIDATION-2026-11-04.json):

| Check | Actual result |
| --- | --- |
| Full offline manifest | 69/71 initially passed; the two failures were retained, not overwritten. |
| Failed-suite continuation | All 39 delivery-ownership tests and all 118 door tests passed after correcting the committed-LF hash fixture and replacing jargon in the brief. Together with unchanged completed suites, all 71 manifest suites have a current passing observation. |
| Other affected-suite continuation | Sovereign delivery, pipeline repair/capacity, and commercial-context suites passed. The monetary and receipt suites also passed in the final connected/factual run. |
| Final connected/factual run | 28 methods, 46 PASS receipts, zero BLOCKED. Four methods read the actual GitHub incident; 24 methods test local guards with controlled inputs. |
| Live incident evidence | The report records the actual PR #1059 comment URL and source digest `0c80dd8525add7d9ce91c5d5699200be60e603ba9b7633a0045d131b4dd81a52`. |
| Compilation / F821 / workflow syntax / whitespace | Passed for the changed runtime modules, both inspected workflow YAML files parsed, and `git diff --check` passed. |
| Tracked credential-shaped literals | Scanner returned no findings in the current tracked working files; this is not a historical-secret audit. |
| Full live E2E, payment settlement, deployment | Not established by these results. Changes are in the local working tree; this audit did not push/deploy or start a customer campaign. |

The validation artifact identifies each latest suite receipt and preserves the
original failed observations. It deliberately does not rewrite a failed full-run
report into a fictional all-green first attempt. Raw reports are under
`scratch/gate-forensics-20261104/{verified-master,final-hash-fixture,continuation,final-live}/`.

## Remaining assurance boundaries

1. The original independent master contains mixed real and replaced boundaries.
   [The current inventory](LIVE-FAULT-PROBE-INVENTORY-2026-11-04.md) distinguishes
   these; importing a mock-based module into the live runner does not convert it.
   These repairs add a real commercial-source probe and honest reporting, not a
   claim of completed full live master conversion.
2. A recent successful probe receipt is not yet an automatic deployment gate for
   every production revision. Manual live probes remain separate from push CI.
   The changed factual guards act at runtime, but CI green alone cannot authorize
   claims of real external success.
3. Historical IP/credential exposure needs independent artifact/history evidence
   and counterparty facts. The supplied allegation supports a commercial review
   hold, not a proven theft finding. Licence/attribution metadata does not enforce
   a payer's future conduct.
4. Genuine platform escrow balance, accepted claim and actual settlement require
   observed provider receipts. No new scanner or model assertion supplies them.
5. Optional local/email/fleet deployments and already-running workers on older
   revisions are not changed by a local checkout repair. Existing valid artifacts
   must be resumed under the repaired revision, with their factual gates intact.
