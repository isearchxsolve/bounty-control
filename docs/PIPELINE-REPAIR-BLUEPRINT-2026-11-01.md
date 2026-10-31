# Pipeline repair blueprint

Baseline: b5c6e0919f1975b858edf5c576c59ee5976492a3. Line numbers in this section refer
to that baseline; the implementation appendix records final locations and exact source snippets.
This blueprint covers F01–F20 from PIPELINE-FORENSIC-AUDIT-2026-11-01.md.

## Contract and order of work

**Priority correction from the user's independent review:** the 103 refusals largely screened
unsuitable supply correctly. They are not 103 discarded valid opportunities. Track supply quality
separately from the eight execution-failure records. Production search must read current payer
commitments and actual bounded scope, not copy monetary mentions out of digests, prizes or grants.
The repair uses model interpretation with literal source, payer, amount and source-revision checks;
it does not grow a news-bot blacklist or another static query list. F02 remains a real defect,
but is not asserted to explain the historical zero yield.

**Visibility decision:** keep this repository public, as requested, to retain free standard
GitHub-hosted runner usage. Concurrency and job timeouts remain bounded; no paid larger runner
or visibility change is part of these repairs. Remove credential literals and keep credentials
in Actions secrets. Making a repository private would not revoke previously exposed credentials.

1. **Ownership before throughput (F04/F05/F16).** At actions_dispatch.py:738 and :1002,
   DISPATCHING/DISPATCHED cease being retryable. Every event carries dispatch_id. At
   actions_github.py:283, a claim compares this generation inside the CAS operation.
   At actions_reconcile.py:33, cancellation must be followed by a completed-run observation;
   otherwise ownership stays reserved. Released records revoke the old owner's writes.

   ```python
   if dispatch_id is not None and old.get("dispatch_id") != dispatch_id:
       raise ValueError("Dispatch generation mismatch")
   if not confirmed_dead:
       continue
   ```

   Acceptance: overlapping reservation calls send once; an old event cannot claim a new
   generation; rejected or unconfirmed cancellation cannot authorize takeover.

2. **Evidence, not default approval (F01/F03/F06).** Replace actions_delivery.py:427–455
   defaults with explicit errors. Introduce a shared evidence contract containing task identity,
   source revision and proof digest. A changed issue/comment snapshot requires the search agent
   to reconsider it; code checks byte identity, open state, completeness and repository availability.
   Rejected work may be reconsidered only under changed source evidence, retaining prior history.

   ```python
   if source.get("sovereign_admission") is not True:
       raise ValueError("Sovereign admission evidence missing")
   if proof["source_revision"] != source_revision(context):
       raise ValueError("Admission source changed; agent reconsideration required")
   ```

   Acceptance: absent/false stamps fail; exact proof survives door → dispatch → claim → release;
   source mutation fails factual validation without a new keyword or classification rule.

3. **One production intake path (F01/F08/F09/F10/F11/F17/F20).** At
   actions_dispatch.py:1181 route sovereign mode to a dedicated small intake orchestrator.
   Preserve the existing legacy search implementation for explicit non-agent use. The production
   orchestrator consumes verified rows through a callback as they arrive; it does not repeat
   regex admission, repository-intent judgement or code classification. Persist queue disposition,
   full evidence, refusal journal and unpriced leads under BOUNTY_STATE_DIR. Use one shared
   workflow concurrency group for discovery/hydration local cache writers.

   ```python
   result = agent_door.find_issues(..., on_admitted=ingest)
   # ingest writes the verified row before attempting its bounded dispatch.
   ```

   Acceptance: callback dispatch happens before search returns; corrected fresh proof is not
   hidden by an old checked row; partitions use an explicit source lane; a quiet/error cycle
   still writes a receipt and a full refusal census. Cached capacity facts actually exclude.

4. **Repairable search journal (F02/F11).** At cline_entry_door.py:137 and :946,
   deduplicate submissions by canonical content rather than issue identity. Recheck changed
   submissions; reuse identical accepted rows only. Keep final decisions per issue and an
   append-only event journal. Detect shortlist truncation. Consume row callbacks on the owning
   thread rather than running GitHub verification in a detached daemon tailer.

   ```python
   submission = json.dumps(row, sort_keys=True, separators=(",", ":"))
   if submission in checked_submissions:
       return
   ```

   Acceptance: bad quote → fixed quote for the same issue verifies twice and admits once;
   unpriced/refused events survive multiple rounds; no verifier continues after return.

5. **Correct phase outcomes (F07/F13/F14).** At actions_delivery.py:975, publication failure
   takes precedence over successful engineering. At kaggle_engine_worker.py:2851 restrict
   preparation's deliverable to clean source, native plan and reproduction specification.
   At actions_delivery.py:914 preserve strict base currency and classify movement as a
   retryable preparation race, so normal engineering recovery rebases/reverifies retained work.

   ```python
   for phase in ("publish", "engineer"):
       if failure.exists():
           return read_json(failure)
   ```

   Acceptance: publish transport failure retains its diagnostic; preparation prompt does not
   order product edits; changed base produces a typed retry obligation without publishing stale code.

6. **Independent native-plan review (F12).** At actions_release.py:99 and
   actions_delivery.py:578 require a separate model review of the exact plan and cited native
   source files before host execution. Model interpretation is delegated; host checks review
   identity, source hashes, unchanged source and exact plan digest. Retain existing regression,
   native exit-code and immutable-test gates. Do not extend a shell-command blacklist.

   Acceptance: a synthetic-success plan has no valid review and cannot arm release; the reviewer
   receives the actual manifest/CI files and reports its verdict in a host-validated artifact.

7. **Recovery isolation and complete observations (F15/F16).** At actions_reconcile.py:130
   isolate each record's failure and cache the ledger once per pass. Add complete workflow-scoped
   run pagination to actions_github.py; correlate acknowledgement using generation in run-name.
   Report unresolved observations explicitly and do not turn unknown API results into clearance.

   Acceptance: one corrupt/conflicting task does not prevent a later valid task from reconciling;
   a second page of delivery runs is visible; an old generation cannot acknowledge a new event.

8. **Post-publication obligations (F18).** At actions_delivery.py:874/945 persist claim
   submission receipts and failures. Reconciliation reports claim retry obligations and separates
   merged delivery from unobserved payment. Never infer accepted claim or cash receipt from merge.
   No new external comments or payment actions are sent by this local repair exercise.

   Acceptance: failed claim remains durable/actionable; merge records payment as unverified.

9. **CI and acceptance coverage (F19).** Add pull_request to actions-contracts.yml, compile/lint
   new production modules and run all door suites by import-based discovery. Move
   test_cline_entry_door.py:339's main block to the end. Add cross-boundary offline regressions
   for the incidents above; retain useful existing tests, updating fixtures only for explicit
   contract changes (missing evidence can no longer be an approval).

10. **Final verification and handoff.** Run affected tests, workflow configuration checks,
    compilation and F821 lint. Record exact commands/results and remaining deployment obligations.
    No push, deployment or new live bounty delivery is implied by local passing tests.

## Deployment and compatibility

- Existing active claims retain owner identity; generation enforcement applies to newly
  dispatched events. Old events without the matching generation cannot bypass new claim gates.
- Existing rejected records are retained as history. No bulk reset or blind replay of the 103
  refusals is authorized by a code repair; changed source evidence is required for reconsideration.
- Existing proof without source binding must be reconsidered at the door. This deliberately
  fails visibly rather than manufacturing historical provenance.
- The legacy standalone local/email/fleet deployments remain separate; this repair changes
  the scheduled Actions path and shared plumbing, not unknown external processes.

## Implementation appendix

Final line numbers, exact snippets, test results, and any remaining limitations are appended
after implementation. This document is created before application source edits.

## Implemented changes and final source excerpts

These are exact excerpts of the final local working tree, generated from AST line locations.
Baseline references above remain historical; use the locations below for review. Files are
not committed or pushed by this repair. Excerpts are truncated only at the stated line boundary.

| Finding | Implemented change | Verification / remaining boundary |
| --- | --- | --- |
| Supply quality | Production door interprets current payer commitment and bounded work; host verifies payer, literal offer, amount, scope quote and actual product blob | Offline source/citation regressions pass; live economic yield remains unmeasured |
| F01 | Production routes to sovereign_discovery; exact proof/competition carried | Streaming-to-claim regression |
| F02 | Content-based rechecking, persistent decision journal | Corrected quote tested |
| F03 | Missing evidence fails; durable generation/proof/source must match | Missing/changed evidence tested |
| F04 | No blind retry of pending dispatch; generation and send-attempt cap | Duplicate/old-event regressions |
| F05 | Confirmed death before release; revoked owners cannot publish | Rejected/unconfirmed cancellation regressions |
| F06 | Changed source or explicit model reconsideration of the exact old refusal; history retained | Legacy refusals are not blindly replayed |
| F07 | Publication failure precedes engineering success | Failure diagnostic regression |
| F08 | Synchronous verified-row callback dispatches while search runs | Callback dispatch before finder return tested |
| F09 | Dedicated decision queue; fresh sovereign writes become pending in legacy queue too | Production queue bypasses stale checked status |
| F10 | Explicit source_lane and founder leads sent through model verification | Partition regression; external founder listener still needs configuration |
| F11 | Agent workspaces/journals/unpriced leads under cached state; disposable profiles outside cache | Local durable file checks; cache writers serialized |
| F12 | Independent model plan review bound to native source hashes and exact plan digest | Validator/digest tests; real reviewer turn not invoked locally |
| F13 | Preparation returns clean source and a plan, implementation belongs to later phase | Preparation contracts pass |
| F14 | Strict base guard retained; movement becomes typed retryable race | Existing baseline contracts; live rebase/reverification not exercised |
| F15 | One snapshot, per-record recovery errors, durable reconciliation report | Bad record does not block later record |
| F16 | Delivery-only complete run pages and generation-bearing run names | Pagination, stale generation and dispatch acknowledgement contracts |
| F17 | Remembered capacity is applied, not just used to skip probes | Cached exclusion regression |
| F18 | Claim submission/failure and retry obligation persisted; payment stays UNVERIFIED; read-only conversion watcher scheduled | Actual bot acceptance and settlement remain external observations, not inferred success |
| F19 | PR trigger, door/incident suites via discovery, main guard moved, new modules compiled/linted | Workflow parse/trigger checks and full door suites |
| F20 | Empty/error cycle receipts, full refusal census, distinct outcome counts | Quiet-cycle regression and persisted reconciliation summary |
| Credential hygiene | PAT-shaped test literal replaced with a synthetic constructed fixture; fixed relay defaults removed; empty relay auth denied; CI scan added | Local scan clean; remote revocation/rotation and history remediation still required |

The production agent's source interpretation is model work. No new bot-name blacklist, static
search-query list or code-classification regex was added. The legacy search implementation is
still available only when the sovereign entry door is explicitly disabled.

### Verification receipts

- Broader selected contracts: 49 modules, with the one sandbox-blocked Git fixture passing outside
  the sandbox (nine tests). Logs: `_probe/repairs-2026-11-01/`.
- Focused door/claim/ownership pass before the final four regression additions: 163 passed in 14.14s.
- Additional targeted pass covering the new capacity/deadline/reconsideration/credential checks,
  conversion watcher and taxonomy: 58 passed in 2.07s.
- ICU integrity script now uses an isolated database and search cursor; all 16 sections passed.
  The Windows SQLite cleanup error observed on the first isolated attempt was repaired and the
  final rerun completed without that error.
- Deployment-packaging focused run: **174 passed in 18.25 seconds**, including the additional
  founder/probe regressions committed concurrently in 592c5c3.
- Changed Python compilation, workflow YAML validation, F821 lint and current-tree credential
  scan passed. CI now imports the deployed package to catch missing dependency files immediately.
- No new upstream PR, bounty comment, payment action, deployment, push or visibility change was
  performed. The repository remains public on standard GitHub-hosted runner configuration.

### Operational follow-through

1. Revoke/rotate previously published PAT/relay credential material through the owning services;
   local deletion and a clean current-tree scan do not invalidate exposed values or erase history.
2. Configure new relay tokens through environment/secrets before using legacy relay utilities.
3. Deploy the reviewed commit, then measure one bounded live search and delivery with real receipts.
   Passing offline contracts do not establish candidate quality, model provider readiness or payment.
4. Observe actual platform claim acceptance and payment separately. These repairs retain truthful
   unknown states and follow-up obligations; they do not invent platform-specific payment adapters.
5. The read-only conversion watcher observes at most 20 PRs per scheduled pass. Expanding external
   legacy deployments or a full historical secret/history purge is outside the verified local change.

### Evidence contract

`scripts/pipeline_evidence.py:24` — exact lines 24–46.

```python
def require_evidence(source, context=None):
    if source.get("sovereign_admission") is not True:
        raise ValueError("Sovereign admission evidence missing")
    proof, competition = source.get("admission"), source.get("competition")
    if not isinstance(proof, dict) or not proof:
        raise ValueError("Admission proof missing")
    if not isinstance(competition, dict) or competition.get("blocking") is not False:
        raise ValueError("Competition evidence missing or blocking")
    if competition.get("verified") is False or str(competition.get("verdict", "")).startswith("unverified"):
        raise ValueError("Competition observation unavailable")
    if context is not None:
        identity = task_id(context["repo"], context["issue_number"])
        if proof.get("task_id") != identity:
            raise ValueError("Admission task identity mismatch")
        if proof.get("source_revision") != source_revision(context):
            raise ValueError("Admission source changed; agent reconsideration required")
        if context["issue"].get("state", "").lower() != "open":
            raise ValueError("Admitted issue is no longer open")
        if not context.get("complete_comments"):
            raise ValueError("Admission source comments incomplete")
        if context.get("repository", {}).get("archived") or context.get("repository", {}).get("disabled"):
            raise ValueError("Repository is unavailable")
    return proof, competition
```

### Model admission and source quality

`scripts/cline_entry_door.py:542` — exact lines 542–610.

```python
def model_admission_refusal(row, context_builder, source_reader=None):
    """Verify the model's cited decision; do not classify the work a second time."""
    from decimal import Decimal
    from bounty_admission import amounts, FLOOR
    from bounty_fx import quote as fx_quote
    from issue_scout import quote_is_present
    from pipeline_evidence import bind_proof
    from actions_github import GitHubError
    try:
        context = context_builder(row['repo'], row['issue'])
        if not context.get('complete_comments'):
            return 'INCOMPLETE_COMMENTS', None, None
        documents = [context['issue'], *context['comments']]
        funding = row.get('funding') or {}
        source = next((d for d in documents if d.get('html_url') == funding.get('source_url')), None)
        if source is None:
            return 'FUNDING_SOURCE_MISSING', None, None
        text = (source.get('title', '') + '\n' + (source.get('body') or ''))
        quote = row.get('reward_quote') or ''
        if not quote_is_present(quote, text):
            return 'REWARD_QUOTE_NOT_IN_SOURCE', None, None
        if funding.get('payer') != (source.get('user') or {}).get('login'):
            return 'PAYER_SOURCE_MISMATCH', None, None
        if not str(row.get('admission_reason') or '').strip():
            return 'AGENT_DECISION_MISSING', None, None
        authority = funding.get('authority_quote') or ''
        if not authority or not quote_is_present(authority, text):
            return 'AUTHORITY_QUOTE_NOT_IN_SOURCE', None, None
        amount, currency = Decimal(str(funding['amount'])), funding['currency'].upper()
        if not any(a == amount and c == currency for a, c, _ in amounts(quote)):
            return 'QUOTED_AMOUNT_MISMATCH', None, None
        rate = {'basis': 'USD face value', 'usd_rate': '1'} if currency in ('USD','USDC','USDT') else fx_quote(currency)
        usd = amount * Decimal(str(rate['usd_rate']))
        if usd < FLOOR:
            return 'BOUNTY_FLOOR', None, None
        scope = row.get('scope_quote') or ''
        if not scope or not any(quote_is_present(scope, d.get('title','')+'\n'+(d.get('body') or '')) for d in documents):
            return 'SCOPE_QUOTE_NOT_IN_SOURCE', None, None
        code = row.get('code_evidence') or {}
        if code.get('is_product_code') is not True or not code.get('path') or not code.get('quote'):
            return 'PRODUCT_SOURCE_EVIDENCE_MISSING', None, None
        from pathlib import PurePosixPath
        path = PurePosixPath(code['path'])
        if path.is_absolute() or '..' in path.parts or '\\' in code['path']:
            return 'PRODUCT_SOURCE_PATH_INVALID', None, None
        if source_reader is None:
            from actions_github import GitHub
            from urllib.parse import quote as url_quote
            source_reader = lambda repo, name: GitHub().api(
                f"repos/{repo}/contents/{url_quote(name, safe='/')}")
        import base64
        product = source_reader(row['repo'], code['path'])
        if (not isinstance(product, dict) or product.get('type') != 'file'
                or product.get('sha') != code.get('sha') or product.get('encoding') != 'base64'):
            return 'PRODUCT_SOURCE_REVISION_MISMATCH', None, None
        actual = base64.b64decode(product['content']).decode('utf-8', errors='replace')
        if not quote_is_present(code['quote'], actual):
            return 'PRODUCT_SOURCE_QUOTE_MISMATCH', None, None
        proof = {'funding': {**funding, 'usd_value': str(usd), 'quote': rate, 'raw': quote},
                 'agent_reason': row['admission_reason'], 'scope_quote': scope,
                 'code_evidence': code,
                 'source_issue': context['issue'].get('html_url'), 'lane': row.get('lane', 'bounty')}
        if row.get('reconsideration'):
            proof['reconsideration'] = row['reconsideration']
        return None, None, bind_proof(proof, context)
    except (GitHubError, OSError) as exc:
        return 'ISSUE_UNREADABLE', str(exc), None
    except (ValueError, KeyError, TypeError) as exc:
        return 'DECISION_EVIDENCE_INVALID', str(exc), None
```

### Production streaming intake

`scripts/sovereign_discovery.py:15` — exact lines 15–144.

```python
def discover(lanes, max_dispatches=2, live=False, state_dir=None, hydrate_only=False,
             finder=None, api=None, store=None):
    from actions_dispatch import dispatch, repository_size_kb, repository_over_capacity
    from agent_door import find_issues
    folder = Path(state_dir or os.environ.get("BOUNTY_STATE_DIR", "scratch/actions-discovery"))
    folder.mkdir(parents=True, exist_ok=True)
    api, store = api or GitHub(), store or StateStore()
    counts, dispatched, seen = Counter(), [], set()
    refusal_counts, qualified_ids = Counter(), set()
    capacity = {}
    ledger = None
    # One workflow concurrency group serializes cache writers. Per-task remote CAS is
    # still authoritative for ownership, including callers outside this workflow.
    con = sqlite3.connect(folder / "agent-queue.sqlite3", timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS decisions(task_id TEXT PRIMARY KEY,payload TEXT,"
                "revision TEXT,disposition TEXT,at TEXT)")

    def records():
        nonlocal ledger
        if ledger is None:
            ledger = list(store.records() or ())
        return ledger

    def event(phase, **fields):
        document = {"at": utcnow(), "phase": phase, **fields}
        with (folder / "agent-events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document) + "\n")
        print(json.dumps(document), flush=True)

    def save(identity, row, disposition):
        con.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?)",
                    (identity, json.dumps(row), digest(row), disposition, utcnow()))
        con.commit()

    def ingest(row):
        revision = digest(row)
        if revision in seen:
            return
        seen.add(revision)
        identity = task_id(row["repo"], row["issue"])
        save(identity, row, "received")
        counts["received"] += 1
        try:
            lane = row.get("source_lane") or row.get("lane")
            # 'bounty' was the old admission type, not a configurable search lane.
            if lane == "bounty":
                lane = "normal"
            if lane not in lanes:
                raise ValueError("OUT_OF_LANE")
            context = api.issue_context(row["repo"], row["issue"])
            proof, verdict = require_evidence(row, context)
            context["lane"] = row.get("lane")
            if repository_over_capacity(repository_size_kb(api, context["repo"])):
                raise ValueError("CAPACITY_EXCLUDED")
            counts["qualified"] += 1
            qualified_ids.add(identity)
            if not live:
                save(identity, row, "preview")
                return
            if len(dispatched) >= max_dispatches:
                save(identity, row, "capacity_wait")
                counts["capacity_wait"] += 1
                return
            if "used" not in capacity:
                active = []
                for status in ("queued", "in_progress", "waiting", "pending", "requested"):
                    active.extend(api.workflow_runs(store.repo, status=status))
                reservations = {r["task_id"] for r in records()
                                if r.get("status") in ("DISPATCHING", "DISPATCHED", "CLAIMED", "ENGINEERING", "VERIFIED", "PUBLISHING")}
                capacity["used"] = max(len({r["id"] for r in active}), len(reservations))
            if capacity["used"] >= 4:
                save(identity, row, "capacity_wait")
                counts["capacity_wait"] += 1
                return
            result = dispatch(api, store, context, proof, [lane],
                              sovereign_admission=True, competition=verdict)
            dispatched.append(result)
            capacity["used"] += 1
            save(identity, row, "dispatched")
            event("DISPATCHED", task_id=identity)
        except (ValueError, GitHubError, OSError, KeyError, TypeError) as exc:
            counts[str(exc)] += 1
            refusal_counts[str(exc)] += 1
            save(identity, row, "deferred")
            event("AGENT_HANDOFF_DEFERRED", task_id=identity, reason=str(exc))

    door = {}

    def write_summary():
        pending = con.execute("SELECT count(*) FROM decisions WHERE disposition IN "
                              "('capacity_wait','deferred','received')").fetchone()[0]
        summary = {"at": utcnow(), "mode": "LIVE" if live else "READ_ONLY",
                   "door_reason": door.get("reason"), "counts": dict(counts),
                   "qualified_unique": len(qualified_ids), "dispatched": dispatched,
                   "pending_hydration": pending}
        for name, document in (("receipts.jsonl", summary),
                               ("census.jsonl", {**summary, "refusals": dict(refusal_counts)})):
            with (folder / name).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(document) + "\n")
        print(json.dumps(summary), flush=True)
        return summary
    try:
        if hydrate_only:
            # Only source-bound agent decisions are replayed; factual freshness is checked
            # again. Changed sources go back to the search agent on its next pass.
            rows = [json.loads(r[0]) for r in con.execute(
                "SELECT payload FROM decisions WHERE disposition IN ('capacity_wait','deferred') ORDER BY at")]
            for row in rows:
                ingest(row)
            door = {"reason": "HYDRATE_ONLY"}
        else:
            door = (finder or find_issues)(root=str(folder / "agent-workspaces"),
                rounds=int(os.environ.get("BOUNTY_AGENT_ROUNDS", "1")),
                timeout=int(os.environ.get("BOUNTY_AGENT_TIMEOUT", "600")),
                limit=int(os.environ.get("BOUNTY_AGENT_ROW_LIMIT", "0")),
                on_admitted=ingest, lanes=lanes,
                prior_refusals=[r for r in records() if str(r.get("status", "")).startswith("REJECTED_")])
            for row in door.get("rows") or []:
                ingest(row)
            for refusal in door.get("refused") or []:
                counts[refusal.get("reason", "UNKNOWN_REFUSAL")] += 1
                refusal_counts[refusal.get("reason", "UNKNOWN_REFUSAL")] += 1
        return write_summary()
    except Exception as exc:
        counts["DISCOVERY_ERROR"] += 1
        event("DISCOVERY_ERROR", error=type(exc).__name__, reason=str(exc))
        write_summary()
        raise
    finally:
        con.close()
```

### Dispatch fencing and bounded reconsideration

`scripts/actions_dispatch.py:735` — exact lines 735–793.

```python
def dispatch(api, store, context, proof, lanes, remote_repair=False, preparation_budget=None,
             sovereign_admission=None, competition=None):
    """Dispatch one admitted task, carrying the entry door's verdicts with it.

    ``proof`` is the admission proof. ``sovereign_admission`` and ``competition`` are the
    door's own stamps; when a caller does not supply them they are derived from ``proof``
    rather than omitted, because a stamp that silently disappears in transit is worse than
    no stamp at all: the delivery side reads a missing verdict as a default and reports a
    door ruling that never travelled (measured 2026-10-31, see docs/SOVEREIGN-STAMP-AUDIT).
    """
    repo, number = context["repo"], context["issue_number"]
    identity, dispatch_id = task_id(repo, number), uuid.uuid4().hex
    if isinstance(proof, dict) and "source_revision" not in proof and "issue" in context:
        from pipeline_evidence import bind_proof
        proof = bind_proof(proof, context)
    stamps = _sovereign_stamps(proof, sovereign_admission, competition)
    def reserve(old):
        dispatch_attempt = int((old or {}).get("dispatch_attempt", 0)) + 1
        if dispatch_attempt > 3:
            raise ValueError("Bounded dispatch attempts exhausted")
        if old:
            status = old.get("status", "")
            retryable = retry_eligible(old) and int(old.get("attempt", 0)) < 3
            previous_revision = (old.get("admission") or {}).get("source_revision")
            reconsideration = proof.get("reconsideration") or {}
            explicitly_reviewed = (old.get("updated_at")
                                   and reconsideration.get("previous_updated_at") == old["updated_at"]
                                   and str(reconsideration.get("reason") or "").strip())
            changed_refusal = (status.startswith("REJECTED_")
                               and proof.get("source_revision")
                               and ((previous_revision and proof["source_revision"] != previous_revision)
                                    or explicitly_reviewed)
                               and int(old.get("attempt", 0)) < 3)
            if changed_refusal:
                old = {**old, "refusal_history": [*old.get("refusal_history", []),
                       {"status": status, "reason": old.get("reason"),
                        "admission": old.get("admission"), "at": old.get("updated_at")} ]}
                retryable = True
            if not retryable:
                raise ValueError("Existing durable task state: " + status)
        return {**(old or {}), "task_id": identity, "repo": repo, "issue_number": number,
                "status": "DISPATCHING", "dispatch_id": dispatch_id, "admission": proof,
                "dispatch_attempt": dispatch_attempt,
                **stamps,
                "lanes": sorted(set(lanes)), "dispatched_at": utcnow(), "attempt": (old or {}).get("attempt", 0)}
    store.mutate(identity, reserve)
    budget = preparation_budget if isinstance(preparation_budget, int) else FULL_PREPARATION_BUDGET_SECONDS
    payload = {"event_type": "bounty_task_dispatch", "client_payload": {
        "repo": repo, "issue_number": number, "task_id": identity, "lanes": sorted(set(lanes)),
        "mode": "deliver", "dispatch_id": dispatch_id, "preparation_budget_seconds": budget, **stamps}}
    api.api(f"repos/{store.repo}/dispatches", "POST", payload)
    def acknowledge(old):
        if old and old.get("dispatch_id") == dispatch_id and old["status"] == "DISPATCHING":
            return {**old, "status": "DISPATCHED"}
        if not old:
            raise ValueError("Dispatch state disappeared")
        return old  # A runner can claim before the POST acknowledgement arrives.
    store.mutate(identity, acknowledge)
    return identity
```

### Claim generation gate

`scripts/actions_github.py:325` — exact lines 325–352.

```python
    def claim(self, repo, number, owner, run_url, harness_sha, recovery=False, budget_seconds=None,
              dispatch_id=None):
        identity = task_id(repo, number)
        def reserve(old):
            old = old or {"task_id": identity, "repo": repo, "issue_number": number, "attempt": 0}
            if dispatch_id is not None and old.get("dispatch_id") != dispatch_id:
                raise ValueError("Dispatch generation mismatch")
            if (dispatch_id is not None and old.get("status") not in ("DISPATCHING", "DISPATCHED")
                    and not (old.get("status") == "CLAIMED" and old.get("owner") == owner)
                    and not recovery):
                raise ValueError("Dispatch generation is not claimable")
            if old.get("owner_revoked") == owner:
                raise ValueError("Task ownership revoked")
            if old.get("status") == "DELIVERED":
                raise ValueError("Task already delivered")
            if old.get("status") in ("PUBLISHED_PENDING_CHECKS", "AWAITING_REVIEW"):
                raise ValueError("Owned PR is pending; reconcile it before another engineering run")
            if old.get("owner") == owner and old.get("status") == "CLAIMED":
                # Same owner re-claiming: refresh the lease timestamp.
                claimed_at = old.get("claimed_at")
                if claimed_at:
                    claimed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - claimed).total_seconds()
                    if age > CLAIM_TTL_SECONDS:
                        # Lease expired even for the same owner: fall through to re-claim.
                        pass
                    else:
                        return old
```

### Owner revocation gate

`scripts/actions_github.py:382` — exact lines 382–387.

```python
    def owned_update(self, identity, owner, **fields):
        def update(old):
            if not old or old.get("owner") != owner or old.get("owner_revoked") == owner:
                raise ValueError("Task ownership lost")
            return {**old, **fields}
        return self.mutate(identity, update)
```

### Publication owner check

`scripts/actions_github.py:389` — exact lines 389–394.

```python
    def assert_owner(self, identity, owner):
        record, _ = self.read(identity)
        if (not record or record.get("owner") != owner
                or record.get("owner_revoked") == owner):
            raise ValueError("Task ownership lost")
        return record
```

### Complete delivery run pagination

`scripts/actions_github.py:159` — exact lines 159–171.

```python
    def workflow_runs(self, repo, status=None):
        """Complete delivery-workflow run observations, not a mixed 100-run window."""
        rows, page = [], 1
        while True:
            params = {"per_page": 100, "page": page}
            if status:
                params["status"] = status
            result = self.api(f"repos/{repository(repo)}/actions/workflows/engine2.yml/runs?" + urlencode(params))
            batch = result["workflow_runs"]
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1
```

### Cancellation requires observed death

`scripts/actions_reconcile.py:36` — exact lines 36–115.

```python
def sweep_stale_runs(api, store, job_timeout_seconds=None, cancel_wait_seconds=5, records=None):
    """F5: release tasks whose owning run has outlived its own job window.

    A record is swept only on proof, never on absence of life:

    * the owner must parse as a real run id -- a missing or malformed owner is written
      ``FAILED_MISSING_TERMINAL_RECEIPT`` with a diagnostic instead of guessed at;
    * the run must still be ``in_progress`` (a completed run belongs to the existing
      reconciliation branch) and must have outlived ``job_timeout + grace``;
    * the run is cancelled through the API and the cancellation is awaited, then the task
      is written ``FAILED_RUNNER_SHUTDOWN`` with ``swept: true``.

    ``attempt`` is deliberately untouched: the selector is never widened to accept
    ``CLAIMED``, so a sweep makes a task retryable through the ordinary bounded budget and
    a flapping run cannot loop forever.
    """
    timeout = DEFAULT_JOB_TIMEOUT_SECONDS if job_timeout_seconds is None else int(job_timeout_seconds)
    limit = timeout + SWEEP_GRACE_SECONDS
    receipts = []
    for record in (store.records() if records is None else records) or ():
        try:
            if record.get("status") not in ACTIVE_STATUSES:
                continue
            run_id = str(record.get("owner") or "").split(":")[0]
            if not run_id.isdigit():
                receipts.append(_release(
                    store, record, "FAILED_MISSING_TERMINAL_RECEIPT",
                    "Claim owner is missing or malformed; refusing to guess a run", swept=False))
                continue
            try:
                run = api.api(f"repos/{store.repo}/actions/runs/{run_id}")
            except GitHubError:
                continue  # unknown is never proof of death
            if run.get("status") == "completed":
                continue  # the existing completed-run branch owns this case
            started = record.get("claimed_at") or run.get("run_started_at")
            if not started:
                started = record.get("claimed_at")
            if not started:
                continue  # no clock to measure: refuse to guess an age
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(str(started).replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                continue
            if age <= limit:
                continue
            try:
                api.api(f"repos/{store.repo}/actions/runs/{run_id}/cancel", "POST", {})
            except GitHubError:
                print(json.dumps({"phase": "CANCELLATION_UNCONFIRMED", "task_id": record["task_id"]}), flush=True)
                continue
            confirmed_dead = False
            try:
                confirmed_dead = api.api(f"repos/{store.repo}/actions/runs/{run_id}").get("status") == "completed"
            except GitHubError:
                pass
            deadline = time.time() + max(0.0, float(cancel_wait_seconds))
            while not confirmed_dead and time.time() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.time())))
                try:
                    if api.api(f"repos/{store.repo}/actions/runs/{run_id}").get("status") == "completed":
                        confirmed_dead = True
                        break
                except GitHubError:
                    break
            if not confirmed_dead:
                print(json.dumps({"phase": "CANCELLATION_UNCONFIRMED", "task_id": record["task_id"]}), flush=True)
                continue
            receipts.append(_release(
                store, record, "FAILED_RUNNER_SHUTDOWN",
                f"Run {run_id} outlived the {timeout}s job timeout (age {int(age)}s); cancelled and released",
                swept=True, swept_run=run_id, job_timeout_seconds=timeout,
                takeover_reason="stale run exceeded job timeout and grace"))
        except (GitHubError, ValueError, KeyError, TypeError, OSError) as exc:
            receipt = {"task_id": record.get("task_id"), "phase": "RECONCILE_DEFERRED",
                       "diagnostic": str(exc), "at": utcnow()}
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
    return receipts
```

### Content-aware stream cursor

`scripts/cline_entry_door.py:142` — exact lines 142–158.

```python
class ShortlistStream:
    """A byte cursor that also detects truncate/rewrite, including a longer replacement."""
    def __init__(self, path):
        self.path, self.offset, self.prefix = path, 0, None

    def read(self):
        try:
            with open(self.path, "rb") as handle:
                previous = handle.read(self.offset)
            if self.prefix is not None and hashlib.sha256(previous).digest() != self.prefix:
                self.offset = 0
        except OSError:
            return []
        rows, self.offset = new_rows(self.path, self.offset)
        with open(self.path, "rb") as handle:
            self.prefix = hashlib.sha256(handle.read(self.offset)).digest()
        return rows
```

### Corrected submissions and durable decisions

`scripts/cline_entry_door.py:1096` — exact lines 1096–1185.

```python
def iterate(workdir: str, rounds: int = 3, run=run_cline_search, verify=verify_rows,
            limit: int = 0, first_prompt: Optional[str] = None, admission_client=None,
            on_admitted=None, **run_kwargs) -> Dict[str, object]:
    """Search, verify, and feed the refusals back so the agent corrects itself.

    The agent is not judged once and dismissed: each round's refusals become the next round's
    instructions, which is how a search that finds unpayable rows converges instead of
    submitting them. Bounded rounds, so a stubborn agent cannot loop forever.

    Rows already admitted are preserved across rounds and re-appended to the shortlist, so a
    round that rewrites the file from scratch cannot discard work an earlier round won.
    """
    admitted: List[dict] = []
    history: List[dict] = []
    refusals: List[dict] = []
    unpriced: List[dict] = []
    stream_path = os.path.join(workdir, "admitted-stream.jsonl")
    live: Dict[str, List[dict]] = {"admitted": [], "refused": [], "unpriced": []}
    banked_keys = set()
    decisions = {}

    def submission_key(row):
        return json.dumps(row, sort_keys=True, separators=(",", ":"))

    def remember(one):
        for slot in ("admitted", "refused", "unpriced"):
            for entry in one.get(slot) or []:
                subject = entry.get("row", entry)
                decisions[row_key(subject)] = (slot, entry)
                with open(os.path.join(workdir, "decisions.jsonl"), "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"decision": slot, "entry": entry}) + "\n")
                if slot == "admitted" and on_admitted is not None:
                    on_admitted(entry)

    def row_key(row: dict):
        return (str(row.get("repo") or "").lower(), row.get("issue"))

    def bank(row: dict) -> None:
        """Verify a row the instant the agent writes it, and keep it whatever happens next.

        This is the reason the round's work survives: a row admitted at second 40 is already in
        the pipeline when the wall-clock budget kills the agent at second 800.
        """
        key = submission_key(row)
        if key in banked_keys:
            return
        try:
            one = verify([row], limit=limit, admission_client=admission_client)
        except Exception:  # a single-row failure must never abort the search
            return
        banked_keys.add(key)  # only after a verdict, so a failed verify can still be retried
        remember(one)
        for slot in ("admitted", "refused", "unpriced"):
            live[slot].extend(one.get(slot) or [])
        fresh = one.get("admitted") or []
        if fresh:
            with open(stream_path, "a", encoding="utf-8") as handle:
                for banked in fresh:
                    handle.write(json.dumps(banked, ensure_ascii=False) + "\n")
            top = fresh[0]
            print(json.dumps({"phase": "ENTRY_ROW", "repo": top.get("repo"),
                              "issue": top.get("issue"), "reward_usd": top.get("reward_usd"),
                              "live": True}), flush=True)
        for entry in (one.get("refused") or []) + (one.get("unpriced") or []):
            subject = entry.get("row") or {}
            print(json.dumps({"phase": "ENTRY_DECISION", "repo": subject.get("repo"),
                              "issue": subject.get("issue"),
                              "reason": entry.get("reason"),
                              "reward_usd": subject.get("reward_usd"),
                              "live": True}), flush=True)

    for round_number in range(1, max(1, rounds) + 1):
        for slot in ("admitted", "refused", "unpriced"):
            live[slot].clear()
        if round_number == 1:
            prompt = first_prompt or SEARCH_PROMPT
        elif not refusals:
            # Measured 2026-10-31 (run 41183429400): with a quota-free brief the agent returned
            # four rows, nothing was refused, and the configured second round never ran - the
            # extra round was wired as a repair round only. Time left on the clock is time to
            # search, so a clean round continues the search instead of ending it.
            prompt = CONTINUE_PROMPT
        else:
            listed = "\n".join(
                "- {repo}#{issue}: {reason}".format(
                    repo=str(entry["row"].get("repo")), issue=entry["row"].get("issue"),
                    reason=entry["reason"])
                for entry in refusals)
            prompt = FEEDBACK_PROMPT.format(refusals=listed or "(none)")
        kwargs = dict(run_kwargs)
```

### Independent native-plan reviewer

`scripts/delivery_supervisor.py:24` — exact lines 24–56.

```python
def review_native_plan(worktree, plan, sources, artifact_dir, command_builder, execute):
    """Ask a separate model turn to read the native source and review the exact plan."""
    from pipeline_evidence import digest
    root = Path(worktree).resolve()
    for source in sources:
        path = (root / source['path']).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']):
            raise ValueError('Native-plan review source is missing or changed')
    folder = Path(artifact_dir) / 'plan-reviews'
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / (uuid.uuid4().hex + '.request.json')
    response = request.with_suffix('.review.json')
    before = source_snapshot(worktree)
    document = {'plan': asdict(plan), 'plan_sha256': digest(asdict(plan)), 'sources': sources}
    request.write_text(json.dumps(document, indent=2), encoding='utf-8')
    prompt = f'''Independently review the native verification plan in {request}.
Read the actual cited repository manifests, scripts and CI files, following their references.
Determine whether these commands really build and exercise this repository, and whether the
tests, lint and format coverage match its native requirements. Shell exits or printed success
are not test evidence. Read commands and targets; do not infer coverage from their names alone.
Do not edit repository files, install anything, run the plan, commit, push or send messages.
Your only deliverable is {response}, JSON with approved (boolean), reason (your evidence-backed
interpretation), plan_sha256 (the exact request digest), and sources (the exact cited list).
Reject synthetic success, missing coverage or commands unsupported by the cited native sources.
The host verifies all hashes and executes independently; your approval is not a test receipt.'''
    result = execute(command_builder(worktree, prompt), cwd=worktree, timeout=1800)
    if source_snapshot(worktree) != before:
        raise ValueError('Native-plan reviewer changed source or HEAD')
    if result.exit_code:
        raise ValueError('Native-plan reviewer failed: ' + str(result.stderr or result.stdout))
    review = json.loads(response.read_text(encoding='utf-8'))
    return validate_plan_review(review, plan, sources)
```

### Review evidence validation

`scripts/delivery_supervisor.py:11` — exact lines 11–21.

```python
def validate_plan_review(review, plan, sources):
    """Check the review's exact claim; interpretation belongs to the reviewer model."""
    from pipeline_evidence import digest
    if (not isinstance(review, dict) or review.get('approved') is not True
            or not str(review.get('reason') or '').strip()):
        raise ValueError('Independent native-plan review did not approve: ' + str(review))
    if review.get('plan_sha256') != digest(asdict(plan) if is_dataclass(plan) else vars(plan)):
        raise ValueError('Native-plan review digest mismatch')
    if review.get('sources') != sources or not sources:
        raise ValueError('Native-plan review source citations mismatch')
    return review
```

### Publication failure precedence

`scripts/actions_delivery.py:1004` — exact lines 1004–1032.

```python
def terminal_result(folder, job_status):
    """The record a finished run leaves, inferred from what it wrote.

    The one failure class the taxonomy exists for used to be unclassifiable here. A SIGTERM
    (``exit_143``) kills the Python process before any ``except`` block can run, so neither
    ``engineering-result.json`` nor ``*-failure.json`` is written, and the run was recorded
    as ``FAILED_MISSING_RECEIPT`` -- an absent record treated as an absent receipt. Measured
    twice on 2026-10-29 (runs 40862366271 and 40862319897).

    Writing nothing while exiting non-zero is only possible if the phase was terminated
    before it could report, so that case is classified ``FAILED_RUNNER_SHUTDOWN`` and
    flagged ``inferred``: the conclusion comes from the absence of both files, never from an
    observation, and an inference must never be recorded as one.
    """
    folder = Path(folder)
    result_file = folder / "engineering-result.json"
    for phase in ("publish", "engineer"):
        failure = folder / (phase + "-failure.json")
        if failure.exists():
            return read_json(failure)
    if result_file.exists():
        return read_json(result_file)
    if job_status != "success":
        return {"status": "FAILED_RUNNER_SHUTDOWN", "kind": "runner_shutdown",
                "retryable": True, "inferred": True,
                "diagnostic": "No engineering result and no failure record: the phase was "
                              "terminated before it could report (exit 143 / runner shutdown)",
                "at": utcnow()}
    return {"status": "FAILED_MISSING_RECEIPT"}
```

### Shared execution deadline

`scripts/kaggle_engine_worker.py:1779` — exact lines 1779–1795.

```python
def run_command_safe(argv: List[str], cwd: str, timeout: int = 120, input: Optional[str] = None) -> CommandResult:
    start = time.time()
    if _CLINE_EXECUTION_DEADLINE is not None:
        remaining = cline_turn_timeout_seconds()
        if remaining <= 0:
            from delivery_errors import ClineBudgetExhausted
            raise ClineBudgetExhausted(0)
        timeout = min(timeout, remaining)
    try:
        resolved_argv = list(argv)
        if resolved_argv and sys.platform == "win32":
            cmd_path = shutil.which(resolved_argv[0])
            if cmd_path:
                resolved_argv[0] = cmd_path
        proc = run_streamed_process(
            resolved_argv,
            cwd=cwd,
```

### Credential literal CI gate

`scripts/check_tracked_secrets.py:8` — exact lines 8–23.

```python
def scan(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'],
                            capture_output=True, check=True, timeout=30)
    findings = []
    for name in result.stdout.decode('utf-8').split('\0'):
        path = root / name
        if not name or not path.is_file():
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        for match in re.finditer(r'github_pat_[A-Za-z0-9_]{60,}|gh[pousr]_[A-Za-z0-9]{36,}', content):
            findings.append({'path': name, 'line': content.count('\n', 0, match.start()) + 1,
                             'kind': 'credential-shaped-literal'})
    return findings
```

### Source fingerprints

| File | SHA-256 of reviewed working file |
| --- | --- |
| .github/workflows/actions-contracts.yml | `157b174bd0c6432c87d70230de770245601a255eb63af77f6bed0502cb8cf91b` |
| .github/workflows/bounty-discovery.yml | `995f622d21d14b8930ade7b223fbed560df82b749ed511fe7f706fa3e795cc44` |
| .github/workflows/bounty-hydration.yml | `15157f49e25fda55cb76b1ed999a45dbeb364b3a39c39e18abc15f2def038b3f` |
| .github/workflows/engine2.yml | `0282600d2683f563e1e032f1d3e61aeefe9c233695af0c7b278e23afb98e4fe2` |
| scripts/actions_delivery.py | `8192ba28fcb0471356f53c6953dbe58ffc60660cccc920b0bb8f3eb9b841cab5` |
| scripts/actions_dispatch.py | `26e11ddc9ac8f417006ca33c7973267a4efa78f60e03824a561a938e88c90582` |
| scripts/actions_github.py | `01890f8ae4590627c20a626fb834fe5c98dc66f32caee7c9f071c7c8aa687b6c` |
| scripts/actions_reconcile.py | `6f330a04ac9b692ec2af936c562007a403dec43ae10671ccfcd0d484221561a6` |
| scripts/agent_door.py | `5c9663cfeac9d0b97e0e327937ae06c2db697b283203481cb709d6ef4c760d65` |
| scripts/autonomous_icu_pipeline.py | `97b9c5ca170391b9a7e73ea4375535a748f86ccc93a00a720a4157b111d342e9` |
| scripts/build_kaggle_worker.py | `59c0083260cae901cecbdfcba0b565b14590113d8285ef9ae155579bf7a01ba3` |
| scripts/check_tracked_secrets.py | `129a0b61aec5584f8be5c65e8481175f2a080c8aa1cbc54d39e9017c11e08d2d` |
| scripts/delivery_supervisor.py | `cb615d850181fcd8c99574e3358fc2b416e883d721ce46143797597b071912b2` |
| scripts/deploy_local_fleet_proxy.py | `ccf4ab04eb9445ac4a1aeaa6029a30d2a8a25556caf113a08c7d696063e7b010` |
| scripts/fleet_local_relay.py | `d8f82ffbf546a6f95db52c99d1072a4867703073365177c07697584a1b79035d` |
| scripts/kaggle_engine_worker.py | `960e6cb92fc3e656a1b52df5463c915f2c6f0821696dfee7826bea1536a08b76` |
| scripts/migrate_fleet_ledger_to_sqlite.py | `70d21bfc86bf4a0288d3e432d792612661ad7bb3915c58f53d6042a57a9ef99c` |
| scripts/monitor_fleet.py | `7415200d82ec3dad739a8d065eeaffbcd6a3a06151fd86cb3e442e7e2fabe10a` |
| scripts/pipeline_evidence.py | `04df1b62ca0af824c8f1825d2ccaba1774c3db5ad0fc245cc860010f4904c602` |
| scripts/print_fleet_logs.py | `9664e4cc92360cd35553f4bfd9d6898548f68de1444b94e79d06edbec77350d2` |
| scripts/run_codex_architectural_partition.py | `b809852f46d83a81c2bd858d2d340755e2ce73d6d244cb44daaacbbf6ac044c2` |
| scripts/sovereign_discovery.py | `f6e51d48bfea364011670c1fbe48c2626a0d6ba0f51dc29d00d14503775cb1b5` |
| scripts/test_agent_door.py | `0686cb5d6b3dc19ad2a5a6b72949d9c6b4fc8d38593483b06ade7578daa2f706` |
| scripts/test_claim_lease.py | `15fd1be884a08905dd83a7c1ee9e85be5878ca052128dd93e396f30e1e2122e1` |
| scripts/test_icu_pipeline_suite.py | `d99e88721bab7cf899496c203d931ecd59715801120bfa34284bd07883c9c6ee` |
| scripts/test_pipeline_repairs.py | `cbefb1b56c896e1a3e7cde3f9b3e87804bb0ed6a36d364482fecca79fa153106` |
| scripts/test_sovereign_delivery.py | `61a88c759092eaf3e9ac40adba5d071f6bca76f15e80d80115f6c17815aeded0` |
| scripts/test_sovereign_stamps.py | `66f8a3af55782d12183d17b6e60dc7428b730686c431b6b17cf0118c0387eccd` |
