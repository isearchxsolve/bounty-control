# Funnel repair plan - exact code, exact lines (2026-10-30)

Companion to `docs/FUNNEL-YIELD-FORENSIC-2026-10-30.md`. That document explains **why** the
funnel yields zero. This one is the **executable** half: every step names the file, the anchor
text, the exact current code, the exact replacement, the test that pins it, and what to do if it
does not work.

Baseline: `master` @ `74b5330`, with the item 3E change already applied in the working tree
(uncommitted). Suite at that point: **527 passed, 1 skipped, 43 files**.

## How to read a step

Every step has the same six parts:

| Part | Meaning |
| --- | --- |
| **Anchor** | the exact text to search for. Line numbers are from `74b5330` and **will drift** as steps land - always anchor on text, never on the number. |
| **Current** | the code as it exists today, verbatim. |
| **Replace with** | the code to paste, verbatim. |
| **Why** | the measured case this exists for. If you cannot name a case, do not add the gate. |
| **Pin** | the test that fails if this is reverted. No test, no merge. |
| **If it fails** | the honest fallback. Never widen a gate to make a test pass. |

## Order of work, and why

| Step | Work | Status |
| --- | --- | --- |
| **R0** | Measurement harness + the real catch rate | **DONE** - measured `3/16 (19%)` |
| **R1** | Freeze the 16 real refusals as labelled fixtures | **DONE** - `scripts/f9_sample/f9_refusals_16.json`, all 16 classed |
| **R2** | The refusal gates, scored against the 45-sample before being proposed | **APPLIED** - 5 gates, 0 false negatives, live catch `11/16 (69%)`, suite 532 passed |
| **R3** | Capacity backstop for the F14 heap override | HOLD - needs a second measured case |
| **R4** | `fyne-io/fyne#6637` follow-up | **READY** - 13/13 checks green, 0 reviews |
| **R5** | Item 3E record (already applied - documented so it is not re-done or silently reverted) | **DONE** - in the working tree, uncommitted |

Rule for R2: a gate that refuses a case which is **not** in the measured refusal set, or that
refuses any of the 45 `needs_code_change` items in `scripts/f11_sample/f11_labeling_sample_60.json`,
does not ship. Precision gains are worth nothing against a false negative.

---

# R0 - Measure before gating

## R0.1 Why this exists

`is_code_change_request()` is the F9 class gate (`8264576`, 2026-10-29 03:36 IST). It is
deliberately **fail-open**: anything not confidently external or process is admitted. Of the 16
`REJECTED_PREPARATION` records, Cline refused all 16 - but **nobody has measured how many the F9
gate would have refused**, because the last attempt died on a cp1252 decode error while reading
`gh` output on Windows.

So the first artefact is not a gate. It is the number.

## R0.2 New file: `scripts/replay_refusals.py`

```python
"""Replay the measured REJECTED_PREPARATION tasks through the F9 class gate.

Answers one question with a number: of the N tasks Cline refused at preparation time, how
many does ``is_code_change_request`` refuse today? Without this number any new gate is
guesswork.

Reads the refusal list from ``--from-fleet-state`` (a local directory of fleet-state JSON
documents) or from an explicit ``--case repo#number`` list. Fetches each issue through the
GitHub API and never writes to the repository.

Windows note: ``gh`` output is decoded as UTF-8 explicitly. The 2026-10-30 attempt died with
``UnicodeDecodeError: 'charmap' codec ... 0x8f`` because subprocess fell back to cp1252 for a
repo whose body contained an emoji.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from actions_dispatch import is_code_change_request  # noqa: E402

REFUSAL_STATUS = "REJECTED_PREPARATION"


def cases_from_fleet_state(directory):
    """(repo, number, cline_reason) for every record Cline refused at preparation."""
    found = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("status") != REFUSAL_STATUS:
            continue
        # Cline's refusal text lives at the top level on the records written by the
        # 2026-10-28 dispatch loop; older records carried it under failures[].
        reason = str(record.get("reason") or "")
        if not reason:
            for failure in record.get("failures") or []:
                reason = str(failure.get("diagnostic") or failure.get("reason") or "")
                if reason:
                    break
        found.append((record["repo"], record["issue_number"], reason))
    return found


def gh_json(endpoint):
    """GitHub REST read with explicit UTF-8, so cp1252 can never decide a result again."""
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError("gh api " + endpoint + " failed: "
                           + result.stderr.decode("utf-8", "replace").strip())
    return json.loads(result.stdout.decode("utf-8", "replace"))


def main(argv=None):
    # The Windows console is cp1252. One non-ASCII character in a title or reason killed the
    # 2026-10-30 attempt mid-run; make the stream safe before anything is printed.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-fleet-state", default=None,
                        help="directory of fleet-state JSON documents")
    parser.add_argument("--case", action="append", default=[],
                        help="explicit repo#number, repeatable")
    parser.add_argument("--write-fixtures", default=None,
                        help="write the fetched cases as a labelled fixture file")
    args = parser.parse_args(argv)

    cases = cases_from_fleet_state(args.from_fleet_state) if args.from_fleet_state else []
    for spec in args.case:
        repo, number = spec.rsplit("#", 1)
        cases.append((repo, int(number), ""))
    if not cases:
        parser.error("no cases: pass --from-fleet-state or --case")
    cases.sort()

    rows, refused = [], 0
    for repo, number, cline_reason in cases:
        issue = gh_json(f"repos/{repo}/issues/{number}")
        labels = [l.get("name", "") if isinstance(l, dict) else str(l)
                  for l in issue.get("labels", [])]
        admitted, reason = is_code_change_request(
            issue.get("title", ""), issue.get("body") or "", labels)
        if not admitted:
            refused += 1
        rows.append({
            "repo": repo,
            "number": number,
            "title": issue.get("title", ""),
            "body": (issue.get("body") or "")[:1500],
            "labels": labels,
            "cline_refused": bool(cline_reason),
            "cline_reason": cline_reason[:400],
            "gate_admitted": admitted,
            "gate_reason": reason,
        })
        print(f"{repo}#{number}: {'ADMITTED' if admitted else 'refused'} - {reason}")

    total = len(rows)
    print(f"\nCATCH RATE {refused}/{total} refused by the F9 gate "
          f"({(100.0 * refused / total) if total else 0:.0f}%)")

    if args.write_fixtures:
        with open(args.write_fixtures, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        print("wrote " + args.write_fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## R0.3 Run it

```bash
cd /d/anonym
python scripts/replay_refusals.py \
  --from-fleet-state "$LOCALAPPDATA/Temp/fleet" \
  --write-fixtures scripts/f9_sample/f9_refusals_16.json
```

## R0.3 What it returned (measured 2026-10-30, this is no longer a prediction)

```text
CATCH RATE 3/16 refused by the F9 gate (19%)
```

The three refusals are `alfrexo95/bounty-bot#27`, `#28`, `#53` - all refused by the **existing**
`external: body matches external patterns` branch. Per case:

```text
ADMIT  BruceFeIix/picker#1904                              [needs_code_change]
ADMIT  Cyon0x/earnly#1                                     [unclear_fail_open]
ADMIT  Expensify/App#85907                                 [needs_code_change]
ADMIT  Expensify/App#101616                                [needs_code_change]
ADMIT  Expensify/App#101675                                [needs_code_change]
REFUSE alfrexo95/bounty-bot#27                             [external: body]
REFUSE alfrexo95/bounty-bot#28                             [external: body]
REFUSE alfrexo95/bounty-bot#53                             [external: body]
ADMIT  bolivian-peru/os-moda#3                             [needs_code_change]
ADMIT  dotnet/runtime#36748                                [unclear_fail_open]
ADMIT  keepassxreboot/keepassxc#255                        [needs_code_change]
ADMIT  phpseclib/phpseclib#1293                            [unclear_fail_open]
ADMIT  ruohong2018/ruohong2018.github.io#671               [needs_code_change]
ADMIT  superpreviousattending/canyonendrum#546             [unclear_fail_open]
ADMIT  sybil-solutions/local-ai-registry#216               [needs_code_change]
ADMIT  sybil-solutions/local-ai-registry#223               [needs_code_change]
```

Two things this settles, both previously guessed:

1. The F9 gate is **not inert** - it already refuses one whole class (the bot advertisements).
2. `phpseclib#1293` and `canyonendrum#546` both land in `unclear_fail_open`, i.e. the gate did not
   judge them at all. Two of the three cases that made earlier analyses wrong were cases the gate
   never saw.

## R0.4 Honest outcomes, and which one happened

| Result | What it means | Do next |
| --- | --- | --- |
| `n = 0` | inert on this population | R2 in full |
| **`0 < n < 10`** | **partial - build gates only for the classes it misses** | **R2, subset - this is the case that occurred (n = 3)** |
| `n >= 14` | already effective; the refusals predate the gate | build nothing; move to R3/R4 |
| an item in the 45-sample now refused | a false negative exists | stop and fix that first |

Because `n = 3`, R2 was built as a **subset**: five gates, each scored against the 45-sample before
being proposed, one dropped because it was already covered and one disqualified for refusing a real
bug. The scoring table is in R2.0.

---

# R1 - Freeze the 16 as fixtures

After R0 the fixtures exist at `scripts/f9_sample/f9_refusals_16.json`. Commit them **before**
any gate is written, so the next session inherits the measurement instead of repeating it.

Shape of each row (written by R0.2, do not hand-edit):

```json
{
  "repo": "phpseclib/phpseclib",
  "number": 1293,
  "title": "May i know when new composer package version will release?",
  "body": "...first 1500 chars...",
  "labels": ["help wanted"],
  "cline_refused": true,
  "cline_reason": "Cline preparation blocked: Issue #1293 is a release-timing/support question...",
  "gate_admitted": true,
  "gate_reason": "needs_code_change"
}
```

Each row also carries `"expected_class"`, assigned after reading Cline's own reason. The vocabulary
used is the measured one, and it records *decisions*, not just classes:

| `expected_class` | Count | Meaning |
| --- | --- | --- |
| `AUTO_DIGEST` | 2 | gated by G1 |
| `QUESTION` | 2 | gated by G3 |
| `UMBRELLA` | 1 | gated by G4 |
| `HARDWARE_PRODUCT` | 2 | gated by G5a |
| `VIDEO_DELIVERABLE` | 1 | gated by G5b |
| `ALREADY_CAUGHT` | 3 | already refused today by the `external` branch - pinned by a test, **no new gate** |
| `ALREADY_RESOLVED_UNREACHABLE` | 3 | knowingly not gated; the name says why (R2.9) |
| `UNGATED` | 2 | no acceptable gate exists (spam, and one label-less umbrella) |

The three `ALREADY_CAUGHT` rows matter: without them a later session will read the fixture file,
see three unrefused-by-name cases, and write a redundant `bot_advertisement` gate. The
`test_the_three_already_caught_cases_stay_refused` test in R2.10 exists to prevent exactly that.

---

# R2 - The refusal gates (measured 2026-10-30)

**Read R0 first.** The catch rate was measured before any gate was written, and it changed the
plan: one proposed gate was already covered by existing code, one was disqualified by a false
negative, and two had to be redesigned because the first form caught nothing.

## R2.0 What the measurement returned

`python scripts/replay_refusals.py --from-fleet-state "$LOCALAPPDATA/Temp/fleet"
--write-fixtures scripts/f9_sample/f9_refusals_16.json`:

```text
CATCH RATE 3/16 refused by the F9 gate (19%)
```

The three caught are `alfrexo95/bounty-bot#27`, `#28`, `#53`, refused by the **existing**
`external: body matches external patterns` branch. So the F9 gate is not inert, but on this
population it moved only one class.

Then each candidate gate was scored against both sets with `scripts/_probe_gates.py`
(false negatives measured on the 45 hand-labelled `needs_code_change` items; catch measured on the
13 refusals the gate set does not already refuse):

| Gate | False negatives (of 45) | Catches (of 13) | Verdict |
| --- | --- | --- | --- |
| `auto_digest` | **0** | 2 | **ship** |
| `question` (title) | **0** | 2 | **ship** |
| `question` (title or opening line) | 0 | 2 | rejected - no gain, more surface |
| `umbrella` | **0** | 1 | **ship** |
| `hardware_product` | **0** | 2 | **ship** |
| `video_deliverable` | **0** | 1 | **ship** |
| `bot_advertisement` (new) | - | 0 | **dropped** - already caught by `external` |
| `hardware_required` (phrase form) | 0 | 0 | **dropped** - caught nothing |
| `keyword_spam` | **1** | 0 | **disqualified** |

Combined result: **3 existing + 8 new = 11 of 16 refusals (69%), zero false negatives.**
The five that stay admitted are honest gaps, listed in R2.9.

## R2.1 The insertion anchor

**File:** `scripts/actions_dispatch.py`
**Anchor:** the last line of the PROCESS block

Current (line 1479 at `74b5330`):

```python
            return (False, "REFUSED_NOT_A_CODE_CHANGE: " + reason)

    # --- 3. CODE CHANGE: admit --------------------------------------------
```

Insert the R2 block **between** those two statements, so the function reads
`... PROCESS ... -> REFUSAL CLASSES -> CODE CHANGE -> FAIL-OPEN`.

Three invariants every gate obeys:

1. Return the prefix the caller already counts on:
   `(False, "REFUSED_NOT_A_CODE_CHANGE: <class>: <fixed detail>")`. The caller does
   `counts[code_reason] += 1` (`actions_dispatch.py:1154`) and
   `counts["admission_changed." + code_reason] += 1` (`:1277`), so the detail must be a **fixed
   string per branch** - never interpolated issue text, or the summary key space explodes.
2. The gates are checked **after** PROCESS, so nothing the current code refuses changes.
3. They run **before** the CODE CHANGE block by necessity: a digest body is full of code-ish words,
   which is exactly why the code-keyword test admits it. `_probe_gates.py` prints that overlap
   explicitly (5 cases) so the override is a decision, not an accident.

## R2.2 New pattern constants

**File:** `scripts/actions_dispatch.py`
**Anchor:** `_PROCESS_LABELS = frozenset({"triage", "process", "meta", "roadmap", "pilot"})`
(current line 1375)

Add directly below it:

```python
# F9 refusal classes. Each one exists because a measured Cline refusal named the class;
# see docs/FUNNEL-REPAIR-PLAN-2026-10-30.md section R2.0 for the false-negative count that
# authorised it. A gate with no measured case, or with any false negative, is not added.
_AUTO_DIGEST_TITLE = r"^\[[^\]]{0,40}\]\s*\d{4}-\d{2}-\d{2}\b"
_AUTO_DIGEST_LABELS = frozenset({"daily", "digest", "auto-generated", "automated"})
_QUESTION_TITLE = (
    r"^(?:may\s+i\s+know|are\s+there\s+any\s+plans|when\s+(?:will|is|does)|"
    r"how\s+(?:do|can)\s+i|can\s+you\s+tell|is\s+it\s+possible|"
    r"(?:contact|support|general)\s+question)\b"
)
_REPRO_EVIDENCE = (
    r"\b(?:steps\s+to\s+reproduce|expected\s+(?:behaviou?r|result)|"
    r"actual\s+(?:behaviou?r|result)|stack\s*trace|traceback)\b"
)
_UMBRELLA_LABELS = frozenset({"epic", "rfc", "discussion", "feature request", "proposal"})
# A named consumer part is hardware this runner cannot be given. Measured on the two $50
# "recipe for <card>" bounties, whose acceptance is a benchmark on that physical card.
_HARDWARE_PRODUCT = (
    r"(?:intel\s+arc|radeon|geforce|ryzen|apple\s+m\d|"
    r"rtx\s*\d{4}|gtx\s*\d{3,4}|arc\s+[abc]\d{3})"
)
_VIDEO_DELIVERABLE = r"\b(?:film|shoot|record|produce)\s+(?:a\s+)?(?:real\s+)?(?:demo|video)\b"
```

**No new import is needed.** `actions_dispatch.py:12` already has a module-level `import re`, so the
snippets call `re.search` directly. (`is_code_change_request`'s helpers import it locally as `_re`;
that is local to those functions and is not visible where the new block is inserted.) Verified
2026-10-30 with `sed -n '1,25p' scripts/actions_dispatch.py`.

### ESCAPE LAW (paid for on 2026-10-30)

While building this section, a regex written through a shell heredoc lost its `r` prefix and
`\b` became a literal **backspace byte** (U+0008). The gate then matched nothing, and the
measurement quietly said "0 caught" - a gate that looks implemented and does nothing. Always
verify after writing a pattern:

```bash
cd /d/anonym/scripts && python -c "
import _probe_gates as P
for name in ('_AUTO_DIGEST_TITLE','_QUESTION_TITLE','_HARDWARE_PRODUCT','_VIDEO_DELIVERABLE'):
    print(name, repr(getattr(P, name))[:90])"
```

A correct pattern shows `'\\b...'` or `'\\s'`; a corrupted one shows `'\x08'` or `'\x0c'`.

## R2.3 Gate G1 - `auto_digest` (2 cases, 0 false negatives)

Insert at the R2.1 anchor:

```python
    # --- 2b. REFUSAL CLASSES (measured 2026-10-30) ------------------------
    # A dated, digest-labelled issue is a bot's link roundup. Two measured cases:
    # BruceFeIix/picker#1904 and ruohong2018/ruohong2018.github.io#671.
    if (re.search(_AUTO_DIGEST_TITLE, title_l)
            and labels_set & _AUTO_DIGEST_LABELS
            and not _has_code_reference(body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: auto_digest: dated title plus digest label")
```

`labels_set` already exists in the function (built for the PROCESS label check). If the local
variable is named differently, use the same one - do not build a second set.

## R2.4 Gate G3 - `question_without_defect` (2 cases, 0 false negatives)

```python
    # An interrogative title with no reproduction evidence anywhere in the body. The repro
    # guard is what keeps real bugs filed as questions admitted: two measured cases
    # (phpseclib#1293, earnly#1) and zero false negatives on the 45-item sample.
    if (re.search(_QUESTION_TITLE, title_l)
            and not re.search(_REPRO_EVIDENCE, body_l)
            and not _has_code_reference(body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: question_without_defect: interrogative title, no repro")
```

**Title only, deliberately.** The body-opening variant (`are there any plans ...` in the first 200
chars) caught the same two cases and nothing more, while widening the surface to every issue whose
body opens with a question. It was measured and rejected.

## R2.5 Gate G4 - `umbrella_request` (1 case, 0 false negatives)

```python
    # A maintainer-labelled EPIC/RFC is a multi-issue intention, not a task one runner can
    # prepare. Measured: keepassxreboot/keepassxc#255.
    if labels_set & _UMBRELLA_LABELS and not _has_code_reference(body_l):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: umbrella_request: epic/rfc label, no code reference")
```

**Separate defect in the same case, deliberately not fixed here:** Cline also found that case's
$200 offer *withdrawn*. `admit()` (`bounty_admission.py:529`) only asks whether an offer exists
now. Screening comments for withdrawal language (`funding withdrawn`, `bounty cancelled`) is a
different gate on a different path, and one case is not a measurement.

## R2.6 Gate G5 - `hardware_product` and `video_deliverable` (3 cases, 0 false negatives)

The first form of this gate used `\brecipe\s+for\b` and `\bhardware[- ]verified\b` and caught
**zero** cases: both `sybil-solutions/local-ai-registry` bounties *mention* a config file, so the
`not _has_code_reference` guard suppressed them. The guard was right to fire - the issue really
does reference repository files. The honest discriminator is that acceptance needs a **physical
part**, so the gate keys on the product name instead.

```python
    # Acceptance needs a physical part this runner will never have: the two measured
    # $50 "recipe for <card>" bounties are benchmarked on that card in someone's machine.
    if not re.search(_REPRO_EVIDENCE, body_l):
        if re.search(_HARDWARE_PRODUCT, title_l) or re.search(_HARDWARE_PRODUCT, body_l):
            return (False, "REFUSED_NOT_A_CODE_CHANGE: hardware_product: acceptance needs a physical part")

    # No reproduction guard here, deliberately: the measured case carries "steps to reproduce"
    # only in the repository's issue-template footer, so the guard read boilerplate as evidence.
    # The phrase "film a real demo" is decisive on its own and refuses nothing in the 45-sample.
    if (re.search(_VIDEO_DELIVERABLE, title_l)
            or re.search(_VIDEO_DELIVERABLE, body_l)):
        return (False, "REFUSED_NOT_A_CODE_CHANGE: video_deliverable: deliverable is not source code")
```

The hardware gate swaps the `not _has_code_reference` guard for a `no reproduction evidence` guard,
which is narrower in the right direction: a driver bug that names an RTX card **and** gives
reproduction steps stays admitted. The video gate keeps no guard at all, for the measured reason
above - a template footer is not evidence, and the phrase itself is decisive.

## R2.7 Gates that are NOT added, and why

| Proposed | Outcome | Reason (measured, not assumed) |
| --- | --- | --- |
| `bot_advertisement` | **dropped** | The three `alfrexo95/bounty-bot` cases are already refused by the existing `external: body matches external patterns` branch. Adding a gate for them would be a second rule for one behaviour, plus a signature change to pass the repo name. |
| `keyword_spam` | **disqualified** | It has a **false negative**: it refuses `commonworld-one/commonworld#186`, a genuine code-change request whose title is long and oddly worded. One false negative kills the gate, whatever it catches. |
| `hardware_required` (phrase form) | **dropped** | Matched 0 cases - the phrase "requires a physical" is Cline's summary, not the issue's own words. `hardware_product` replaced it. |
| `ALREADY_RESOLVED` | **not built** | See R2.9 - the three cases are textually indistinguishable from real bugs, and `competition()` already refuses the detectable subset (a merged PR that *closes* the issue). |

## R2.8 The full disposition of all 16 refusals

| # | Case | Class | Who refuses it |
| --- | --- | --- | --- |
| 1 | `BruceFeIix/picker#1904` | AUTO_DIGEST | G1 (new) |
| 2 | `ruohong2018/ruohong2018.github.io#671` | AUTO_DIGEST | G1 (new) |
| 3 | `Cyon0x/earnly#1` | QUESTION | G3 (new) |
| 4 | `phpseclib/phpseclib#1293` | QUESTION | G3 (new) |
| 5 | `keepassxreboot/keepassxc#255` | UMBRELLA | G4 (new) |
| 6 | `sybil-solutions/local-ai-registry#216` | HARDWARE_PRODUCT | G5a (new) |
| 7 | `sybil-solutions/local-ai-registry#223` | HARDWARE_PRODUCT | G5a (new) |
| 8 | `bolivian-peru/os-moda#3` | VIDEO_DELIVERABLE | G5b (new) |
| 9 | `alfrexo95/bounty-bot#27` | ALREADY_CAUGHT | existing `external` |
| 10 | `alfrexo95/bounty-bot#28` | ALREADY_CAUGHT | existing `external` |
| 11 | `alfrexo95/bounty-bot#53` | ALREADY_CAUGHT | existing `external` |
| 12 | `Expensify/App#85907` | ALREADY_RESOLVED_UNREACHABLE | nothing - needs a reproduction attempt |
| 13 | `Expensify/App#101616` | ALREADY_RESOLVED_UNREACHABLE | nothing - needs a reproduction attempt |
| 14 | `Expensify/App#101675` | ALREADY_RESOLVED_UNREACHABLE | nothing - needs a reproduction attempt |
| 15 | `dotnet/runtime#36748` | UNGATED | nothing - an architecture enquiry with no epic label, and its body carries code references |
| 16 | `superpreviousattending/canyonendrum#546` | UNGATED | nothing - the only spam gate was disqualified by its false negative |

**11 of 16 (69%) are now refused before a claim is spent, with zero false negatives.** The other
five cost one preparation run each. That is a deliberate trade: three of them are genuinely only
knowable by trying to reproduce, and buying them with a gate that also refuses real bugs would be
a worse funnel, not a better one.

## R2.9 Why `ALREADY_RESOLVED` gets no gate

- `competition()` (`bounty_admission.py:624-643`) already raises for an open linked PR, for a
  competing open PR, **and** for a merged PR whose body closes the issue. These three survived it,
  which means their fixing PRs do not carry a closing reference - not that the check is missing.
- `#101675` is not "already resolved" at all: Cline found **no reproducible defect at the base
  commit**. That is a reproduction outcome. The only way to know it is to try.
- A text heuristic here would refuse exactly the issues we most want. A bug someone partly fixed
  usually still has a remainder - that is the most valuable issue type in the whole funnel.

Cost of leaving them: three preparation runs. Cost of a wrong gate: a real bug, silently.

# R2.10 - The tests that pin the gates

Two contracts, in this order of importance: **no false negative** first, then each measured class
refused. A precision gain that refuses a real bug is a loss.

## New file: `scripts/test_f9_refusal_gates.py`

```python
"""Refusal gates added 2026-10-30, pinned against the measured Cline refusals.

Two contracts, in this order of importance:

1. No false negative. The 45 hand-labelled ``needs_code_change`` items in
   ``f11_sample/f11_labeling_sample_60.json`` must still be admitted. A precision gain that
   refuses a real bug is a loss, not a win.
2. Each measured refusal class is refused, with a class token the dispatcher can count.

Fixtures are written by ``scripts/replay_refusals.py --write-fixtures``; they are real issue
text, not invented samples. If the fixture file is absent the class tests skip rather than
pass silently, so a missing measurement can never look like coverage.
"""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from actions_dispatch import is_code_change_request  # noqa: E402

REFUSALS = HERE / "f9_sample" / "f9_refusals_16.json"
SAMPLE = HERE / "f11_sample" / "f11_labeling_sample_60.json"

# The token each class must produce, so the dispatcher's counters stay stable.
# Only classes that survived the false-negative measurement appear here (R2.0):
# BOT_ADVERTISEMENT is already covered by the external branch, and keyword_spam was
# disqualified for refusing a genuine code-change request.
EXPECTED_TOKEN = {
    "AUTO_DIGEST": "auto_digest",
    "QUESTION": "question_without_defect",
    "UMBRELLA": "umbrella_request",
    "HARDWARE_PRODUCT": "hardware_product",
    "VIDEO_DELIVERABLE": "video_deliverable",
}


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class ZeroFalseNegativeTests(unittest.TestCase):
    """The guard that outranks every gate."""

    def test_no_gate_refuses_a_labelled_code_change(self):
        refused = []
        for item in load(SAMPLE):
            if item["hand_label"] != "needs_code_change":
                continue
            admitted, reason = is_code_change_request(
                item.get("title", ""), item.get("body_preview", ""), item.get("labels", []))
            if not admitted:
                refused.append((item["repo"], item["number"], reason))
        self.assertEqual(refused, [], "a gate refused a genuine code-change request: "
                                      + json.dumps(refused[:5]))


class RefusalGateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not REFUSALS.exists():
            raise unittest.SkipTest(
                "run scripts/replay_refusals.py --write-fixtures " + str(REFUSALS))
        cls.cases = load(REFUSALS)

    def test_every_gated_class_is_refused(self):
        missed = []
        for case in self.cases:
            expected = case.get("expected_class")
            if expected not in EXPECTED_TOKEN:
                continue
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            if admitted or EXPECTED_TOKEN[expected] not in reason:
                missed.append((case["repo"] + "#" + str(case["number"]),
                               expected, reason))
        self.assertEqual(missed, [], "gated refusals that still pass: "
                                     + json.dumps(missed[:5]))

    def test_the_three_already_caught_cases_stay_refused(self):
        """ALREADY_CAUGHT rows are refused today by the external branch - pin that, do not
        duplicate the rule with a second gate."""
        for case in self.cases:
            if case.get("expected_class") != "ALREADY_CAUGHT":
                continue
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            self.assertFalse(admitted, "regressed: " + case["repo"] + "#" + str(case["number"]))
            self.assertIn("external", reason)

    def test_a_refusal_reason_is_countable(self):
        """The dispatcher counts the whole reason string; it must not carry issue text."""
        for case in self.cases:
            admitted, reason = is_code_change_request(
                case["title"], case["body"], case["labels"])
            if admitted:
                continue
            self.assertNotIn(case["title"][:20].lower(), reason.lower(),
                             "reason must be a fixed string, not interpolated issue text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

## R2.11 Run it

```bash
cd /d/anonym/scripts
python -m pytest -q test_f9_refusal_gates.py test_f9_class_gate.py test_code_change_class.py
```

Expected: **530 passed**, 1 skipped (527 today + 3 new). A *skip* on `RefusalGateTests` means R0
has not run - the measurement is missing, not passing.
---

---

# R3 - Capacity: a configuration fault, not the machine's limit

> **Correction, 2026-10-30. Baba: "git actions is a worldwide standard for large scale
> engineering - how do other people use it then?"** He was right and my earlier framing was wrong.
> I had written that Expensify/App is "too large for the machine". It is not. It is too large for
> **the way we prepared it**. Receipts from their own workflows:

```text
Expensify/App   size: 3,392,588 KB   (the same 3.39 GB we refused at dispatch)
test.yml        runs-on: blacksmith-8vcpu-ubuntu-2404
                NODE_OPTIONS: --max-old-space-size=8192, matrix of 8 shards, per-shard jest cache
lint.yml        runs-on: blacksmith-16vcpu-ubuntu-2404
                "A cold-cache run loads the full TypeScript program into every worker (~12GB each)"
typecheck.yml   runs-on: blacksmith-4vcpu-ubuntu-2404
```

Their repository also dies on a bare `ubuntu-latest`. They rent larger runners, keep `node_modules`
on a sticky disk so it is never reinstalled, shard the suite eight ways and warm a cache per shard.
So the 14 GiB death was **our configuration**, and configuration is fixable. The verdict's second
half changes from "the machine cannot" to "we chose the most expensive preparation available" - an
engineering defect of ours, not a property of GitHub Actions.

## R3.1 What was actually expensive (each named, not assumed)

| Cost | Where it lives | Status |
| --- | --- | --- |
| `npm run lint` across a 3.39 GB workspace, agent overriding the heap to 14 GiB | agent command, 2026-10-29 11:03Z | **fixed** in `cc1183b` (HARD RULE in the prompt) |
| the plan scheduling workspace-wide `test`/`lint` for any Node repo | `discover_verification_plan` | **fixed here** - heavy checkouts get no workspace-wide command, and the deferral prints `PLAN_REPO_WIDE_DEFERRED` |
| `npm install` allowed to resolve instead of `npm ci` | same function | **fixed here** - frozen lockfile when one exists, `install` only when the repo ships none |
| every run downloading and extracting the whole dependency tree again | `engine2.yml` | **fixed here** - `actions/cache` on `~/.npm`, `~/.cache/pip`, `~/.bun/install/cache` |
| full-history `git clone` | `prepare_workspace` | **rejected** - see below |

**Clone depth was deliberately not changed.** The obvious move is `git clone --depth 1`, and I did
not take it: `rev-list --count pre..post` (two gates, lines 2814 and 2999) needs both commits
present, and a shallow clone plus a shallow upstream fetch makes the base commit absent. That trades
a gate for a few hundred MB of disk while the 14 GiB came from the lint program, not from history.
A change with no measured benefit and a measured risk is not a repair.

The residual hole the old version of this section described - an agent exporting its own
`NODE_OPTIONS` past the workflow cap - is **still open** and still unproven by a second case. The
heap-clamp shim is specified in R3.4 and not built, deliberately: one case, and the prompt order plus
the plan budget now attack the same cause from two sides.

## R3.2 The gate stays, and here is what must be true before it moves

`CAPACITY_MAX_REPOSITORY_KB = 750000` still declines Expensify/App at dispatch, and
`test_capacity_gate.py` / `test_hydration_capacity` still pin it. That is correct until a live run
proves the cheap path: **one dispatched Expensify/App task that completes preparation inside the
7 GiB ceiling, with `PLAN_REPO_WIDE_DEFERRED` in its log and a targeted test receipt.** Until that
receipt exists, lifting the size exclusion trades a known refusal for an unknown OOM.

## R3.3 What is now proven, offline

`test_plan_memory_budget.py`, 10 tests, on a real filesystem:

```text
_git_and_install_output_do_not_count            _measurement_stops_past_the_limit
_missing_worktree_is_zero                       _small_repository_keeps_workspace_commands
_heavy_repository_gets_no_workspace_command     _deferral_is_announced_not_silent
_lockfile_selects_the_frozen_install            _no_lockfile_falls_back_to_install
_existing_node_modules_is_not_reinstalled       _heavy_module_go_test_targets_current_package_only
```

Suite after R3: **542 passed, 1 skipped**.

## R3.4 The heap-clamp shim (specified, not built)

If a second case is measured, the fix belongs in the engineer job, not in the prompt - the prompt
already carries the prohibition and it did not bind on 2026-10-29.

**File:** `.github/workflows/engine2.yml`, after the engineer step's `env:` block. Install a shim
earlier on `PATH` than the real `node`, so an inline `NODE_OPTIONS` export cannot take effect:

```yaml
    - name: Clamp the Node heap regardless of what the agent exports (F14)
      run: |
        set -euo pipefail
        mkdir -p /tmp/heap-shim
        REAL_NODE="$(command -v node)"
        cat > /tmp/heap-shim/node <<SHIM
        #!/bin/sh
        case "\${NODE_OPTIONS:-}" in
          *--max-old-space-size=*) export NODE_OPTIONS="--max-old-space-size=3072" ;;
        esac
        exec "$REAL_NODE" "\$@"
        SHIM
        chmod +x /tmp/heap-shim/node
        echo "/tmp/heap-shim" >> "$GITHUB_PATH"
        /tmp/heap-shim/node --version
```

**If it fails:** report it; do not fall back to another prompt sentence, and do not silently drop the
guard.


# R4 - `fyne-io/fyne#6637` (the only live external PR)

**Measured 2026-10-30:**

| Fact | Value |
| --- | --- |
| PR | `fyne-io/fyne#6637` - `fix: #1062 - Android apps are lagging when enter text and scrolling` |
| State | `OPEN`, not draft, `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED` |
| Head | `4a32ff7c24d319fdba38cf353aa94f8937fb5934` |
| Checks | **13 of 13 SUCCESS** - `mobile_tests` (stable + default), `platform_tests` on ubuntu and macos, `static_analysis`, `web_tests` |
| Reviews | **0** |
| Comments | 1 - the `coveralls` bot only (coverage 61.568%, +0.003%) |
| Created / updated | 2026-10-28T20:26Z / 2026-10-29T17:31Z |

`BLOCKED` with every check green means **it is waiting for a human review**, nothing else. The PR
body already carries the verified base SHA (`9fee2527`), the verified head SHA, the regression
proof (companion test fails on upstream, passes with the change) and the native command receipts
(`go build ./...` exit 0, `-tags mobile` demo build exit 0, `-race` test run). That is the strongest
position this pipeline has ever produced, and it needs **no code work**.

## R4.1 The one correct move

One comment. Short, factual, no deadline, no bounty language - a maintainer reads bounty mechanics
as pressure. It answers the question a reviewer will actually ask ("what changed, and how do you
know it works") and then stops:

```text
Re-verified after the CI run on develop (9fee2527).

What changed: <one sentence naming the file and the mechanism>.
Why it fixes #1062: <one sentence connecting the mechanism to the input/scrolling lag>.
Verification: the companion regression test fails on develop and passes with this change;
the full native suite is green in CI (13/13).

Happy to rework the approach if you would prefer it done differently.
```

Fill the two angle-bracket sentences **from the diff, not from the issue**. If the diff cannot
support a one-sentence "what changed", do not comment - improve the PR body instead.

## R4.2 What not to do

- **Do not push to restart CI.** All 13 checks are green; a new commit discards that.
- **Do not comment twice.** One bot comment, zero reviews; a second comment from us inside 24h
  reads as a nudge.
- **Do not open a competing PR** for `#1062`, and do not comment on the issue itself.
- **Never mention payment in public.** `outreach_report._RAILS_RE` exists to refuse it; the same
  rule applies to a PR comment.

## R4.3 Honest expectation

Zero reviews in ~24h is normal at this project's size. This is the funnel's only proven end-to-end
output so far; the correct disposition is patience plus one well-formed comment. It is not a lever
that can be forced, and no amount of gate work changes it.

---

# R5 - Item 3E, already applied (do not re-do, do not revert)

Applied in the working tree on 2026-10-30, uncommitted at the time of writing. Suite: 527 passed,
1 skipped. Recorded so a later session neither rebuilds it nor silently undoes it.

## R5.1 The defect

`actions_release.validate_plan_contract` raised a bare `ValueError` for a missing native plan phase
and for a bypassed command. The blanket handler at `actions_delivery.py:981` stamps everything it
catches as `FAILED_ENGINEER`, so an unusable *agent-supplied* plan was recorded as an *engineering*
verdict. Measured case: `isearchxsolve/bounty-proof#1`, attempt 2, "Mandatory native plan phase
missing: builds" - 1 of 38 records.

It is the same complaint `test_2c` already records for the dirty baseline (run `40852325249`),
which is why the fix reuses that class instead of inventing a status.

## R5.2 Exact changes

**`scripts/actions_release.py:12`** - new import:

```python
from delivery_errors import PreparationContractViolation
```

**`scripts/actions_release.py:99`** - signature gains the artefact name:

```python
def validate_plan_contract(plan, path=None):
```

**`scripts/actions_release.py`** - each of the three raises becomes typed:

```python
        if not getattr(plan, name, None):
            raise PreparationContractViolation(
                path or "<native plan contract>",
                "Mandatory native plan phase missing: " + name)
```

```python
                raise PreparationContractViolation(
                    path or "<native plan contract>",
                    "Native command must be a nonempty argv array in phase " + phase)
```

```python
                raise PreparationContractViolation(
                    path or "<native plan contract>",
                    "Bypassed or synthetic native verification command in phase " + phase
                    + ": " + " ".join(command))
```

**`scripts/actions_delivery.py:503` and `:513`** - the artefact that carried the plan:

```python
        validate_plan_contract(plan, prepared.get("report_path"))
```

**`scripts/actions_delivery.py:702`** - the verified bundle, inside `validate_bundle`:

```python
    validate_plan_contract(plan, bundle)
```

**`scripts/test_failure_taxonomy.py:164`** - new
`test_2d_a_missing_native_plan_phase_is_a_deliverable_violation`. It builds the exception through
the **real** `validate_plan_contract`, then drives the **real** `main()` handler through the
existing `failure_record()` helper, asserting `status == FAILED_DELIVERABLE_MISSING`,
`kind == "deliverable_invalid"`, `status != FAILED_ENGINEER`, and `retry_eligible(record)`.

**`scripts/test_actions_migration.py:460`** - `assertRaises(ValueError)` retargeted to
`assertRaises(PreparationContractViolation)`. The assertion is exactly as strong; the type changed
because the exception *type* is what chooses the ledger status.

## R5.3 Why it matters beyond one record

`ClineDeliverableInvalid` is caught at `actions_delivery.py:949`, **before** the blanket handler at
`:981`. Routing plan defects through it means:

- status becomes `FAILED_DELIVERABLE_MISSING` with `retryable: true`;
- `retry_eligible()` (`actions_dispatch.py:863-884`) therefore retries it, instead of treating it
  as terminal;
- the record names the artefact (`paths`), so the next reader does not need a log dig.

The general rule this establishes, worth keeping: **a defect in an agent-supplied artefact is a
deliverable violation; only a defect in our own reasoning is `FAILED_ENGINEER`.**
---

# R6 - What NOT to build

Each of these was proposed during this investigation and is wrong on the evidence. Recorded so a
future session does not spend a day on them.

| Not this | Because |
| --- | --- |
| **Lower the floor again** | `FLOOR` was `80` - the loosest setting it ever had - during every recorded failure. `250` changed nothing measurable. There is no evidence the floor is causal at any value. |
| **Add search queries / widen the horizon** | Supply was never the shortage: 32 dispatch cycles, 38 records, 1,743 founder leads in a single run. Widening only adds records to the precision and capacity defects, which is cost. |
| **An `ALREADY_RESOLVED` gate** | The 3 measured cases cannot be told apart from real bugs by text. `competition()` already catches the detectable subset (a merged PR that *closes* the issue). The remainder needs a reproduction attempt, which is precisely what preparation does. |
| **Tighten the `HARD` regex in `bounty_admission.py:139`** | The weak vocabulary (`bug\w*\|error\w*\|fail\w*\|...`) is real, but it governs *funding* admission, a different gate with its own sample. One defect at a time. |
| **The Node heap shim (R3)** | Exactly one measured case, and `CAPACITY_MAX_REPOSITORY_KB` already declines that repository. Build on a second measurement, or not at all. |
| **Re-run the 38 failed tasks to "recover" them** | Nothing is recoverable: the task filesystems are ephemeral, and 11 of the 12 `FAILED_ENGINEER` labels are stale text for conditions already fixed in code. |
| **Weaken or delete a gate to make a live run yield** | Forbidden by the project rules and pinned by `test_hydration_capacity` / `test_capacity_gate`. A green run bought with a weaker gate is a lost receipt, not a win. |
| **Claim the funnel is "fixed" because a run dispatched** | Dispatch is not review, and review is not a merge. The only number that counts is at the bottom of this document. |

---

# R7 - Acceptance, ordering, rollback

## R7.1 Definition of done, per step

| Step | Done when |
| --- | --- |
| **R0** | `replay_refusals.py` prints a catch rate for all 16 cases and writes the fixture file. The number is quoted **verbatim** in the next status report - including if it is 0. |
| **R1** | `scripts/f9_sample/f9_refusals_16.json` is committed with `expected_class` filled on all 16 rows (`UNGATED` is an allowed, honest value). |
| **R2** | Only the classes R0 proves are leaking get a gate. `test_f9_refusal_gates.py` passes: zero false negatives on the 45-sample, every gated class refused. Full suite **530 passed, 1 skipped**. |
| **R3** | Not started without a second measured heap-override case. |
| **R4** | One comment posted, or a written decision to wait. No code change. |
| **R5** | Already done: 527 passed, 1 skipped, `test_2d` present. |

## R7.2 Order

`R0 -> R1 -> R2 (surviving classes only) -> full suite -> one live dispatch cycle -> R4 any time.`

The live dispatch cycle exists only to confirm the counters move: the `ADMISSION` lines in the run
log should begin to show the new class tokens (`auto_digest`, `bot_advertisement`, ...). Do not run
R2 and that cycle in the same step - change one thing, measure, then the next.

## R7.3 Rollback

Every step is independent and text-anchored, and nothing migrates state:

- **Gates:** delete the inserted block between the PROCESS and CODE-CHANGE anchors, plus the
  constant block after `_PROCESS_LABELS`. Behaviour returns to fail-open.
- **Fixtures:** a data file. Removing it makes `RefusalGateTests` skip while the
  zero-false-negative test keeps running.
- **R5 (3E):** revert the import, the signature, the three raises, the three call sites and the two
  test edits. Behaviour returns to `FAILED_ENGINEER` - worse, but not broken.
- **R3 shim:** remove the workflow step; `PATH` returns to the real `node`.

Nothing here touches the state database, the durable `bounty-control` branch, the search cursors,
or the floor. There is no migration to unwind, which is why these steps can be landed one at a
time and independently reverted.

## R7.4 The one number to report, always

The funnel's honest health metric is not dispatches, gates, or passing tests:

**qualified candidates that produced a reviewable upstream patch, per week.**

At the 38-record census it was **1** (`fyne-io/fyne#6637`) across roughly a month, and **0** funded
merges. Every step in this document is justified only by moving that number, or by removing a cost
that makes the number harder to see. If a change does neither, it is not a funnel repair.

---

# R8 - Receipts from the 2026-10-30 measurement

Files that exist on disk because of this document. Two are throwaway diagnostics; keep them, they
are how the numbers above were produced.

| File | Kind | What it proves |
| --- | --- | --- |
| `scripts/replay_refusals.py` | new tool | the catch rate `3/16`; reads fleet-state or `--case`, never writes to a repository |
| `scripts/f9_sample/f9_refusals_16.json` | new data | the 16 real issue bodies (title + first 1500 chars), each with Cline's own reason and our `expected_class` |
| `scripts/_probe_gates.py` | diagnostic | the false-negative and catch counts behind the R2.0 table; **read-only**, imports only `_has_code_reference` and the keyword sets |
| `docs/FUNNEL-REPAIR-PLAN-2026-10-30.md` | this file | the plan |
| `docs/FUNNEL-YIELD-FORENSIC-2026-10-30.md` | companion | why the funnel yields zero (the analysis this answers) |

Reproduce the two numbers:

```bash
cd /d/anonym/scripts

# the catch rate, and it rewrites the fixtures
python replay_refusals.py --from-fleet-state "$LOCALAPPDATA/Temp/fleet" \
  --write-fixtures f9_sample/f9_refusals_16.json

# the per-gate scoring table
python _probe_gates.py
```

Both print ASCII-safe summaries; if your console shows `?` where a title had an emoji, the run is
still valid - only the display is lossy.

## R8.1 Three defects found while building this document

Recorded because each one cost time and each one will recur.

1. **`cline_reason` was empty on all 16 rows** at first: the fleet-state records keep Cline's
   refusal at the top level as `reason`, not under `failures[]`. Fixed in `replay_refusals.py`,
   where it now reads `reason` first and falls back to `failures[].diagnostic`.
2. **A regex lost its `r` prefix and `\b` became a backspace byte** while being written through a
   shell heredoc. The gate silently matched nothing and the measurement read "0 caught" - a gate
   that looks implemented and does nothing. See the ESCAPE LAW in R2.2.
3. **The Windows console is cp1252** and one non-ASCII character in an issue title aborted a print
   loop mid-run. `replay_refusals.py` now reconfigures stdout to UTF-8 before printing anything.
   Note this is the *display*; the fixtures are written with `encoding="utf-8"` and are unaffected.

4. **The measurement instrument truncated bodies at 1500 characters**, and that cap changed a
   verdict: `bolivian-peru/os-moda#3` looked like a clean video bounty until the full body showed the
   phrase "steps to reproduce" - in the repository's *template footer*, not in the issue. Two fixes:
   the harness now stores the **full body**, and the video gate keeps no reproduction guard.
5. **`--write-fixtures` erased `expected_class`**, so on the next run every fixture was skipped and
   `test_f9_refusal_gates.py` passed green with **zero coverage**. Fixed twice over: the harness now
   preserves existing labels when it rewrites (printing `16/16 rows carry expected_class`), and
   `test_the_fixture_still_carries_its_labels` fails if any row loses its class.

None of the first three changed a conclusion, but all three could have. The fourth **did** change
one (a gate that appeared to work was being suppressed by boilerplate), and the fifth produced a
green suite that measured nothing - the exact failure mode this whole document exists to prevent.

## R8.2 What is still unproven

- **The gates are installed and measured, but only on 16 cases.** `actions_dispatch.py` now carries
  all five, and the live classifier refuses `11/16 (69%)` with zero false negatives on the 45-item
  sample. That is the number to re-check after the next dispatch cycle, not the number to trust
  forever.
- **The catch rate is measured on 16 cases.** A population that small bounds what can be claimed:
  the gates are shown to be free of false negatives on the 45-item sample and effective on 8 of the
  13 open refusals, and nothing more. A wider claim would need the next census.
- **The `hardware_product` gate is the narrowest of the five.** It keys on product names seen in two
  cases; a bounty for an unlisted part will pass it. That is the correct failure direction (a
  wasted preparation run, never a refused real bug), but it is a limit, not a solution.
- **Item #1's capacity gate and R5 are the only changes that affect production today**, and both
  were already in place before this document.

## R8.3 The document's own code was executed, not just written

Every snippet above was extracted from this file and run on 2026-10-30, rather than trusted because
it looked right. The constants block in R2.2 and the four gate blocks in R2.3-R2.6 were assembled
into one function with the same `title_l` / `body_l` / `labels_set` / `_has_code_reference` inputs
the production function uses, then scored:

```text
45-sample false negatives: 0 | still admitted: 45
new gates catch 8 of 16
    auto_digest             -> BruceFeIix/picker#1904
    auto_digest             -> ruohong2018/ruohong2018.github.io#671
    hardware_product        -> sybil-solutions/local-ai-registry#216
    hardware_product        -> sybil-solutions/local-ai-registry#223
    question_without_defect -> Cyon0x/earnly#1
    question_without_defect -> phpseclib/phpseclib#1293
    umbrella_request        -> keepassxreboot/keepassxc#255
    video_deliverable       -> bolivian-peru/os-moda#3
still admitted: 8
    alfrexo95/bounty-bot#27, #28, #53        (already refused by the external branch)
    Expensify/App#85907, #101616, #101675    (need a reproduction attempt)
    dotnet/runtime#36748                     (label-less architecture enquiry)
    superpreviousattending/canyonendrum#546  (spam gate disqualified)
```

That matched the R2.0 table at the time (`8 new + 3 existing = 11 of 16`), using the code as
printed here, with zero false negatives on the 45-item sample.

**After the gates were applied to `actions_dispatch.py`, the same number was re-measured against the
live classifier, on full issue bodies:**

```text
CATCH RATE 11/16 refused by the F9 gate (69%)
needs_code_change items: 45 | refused now: 0
```

and the suite went from `527 passed, 1 skipped` to **`532 passed, 1 skipped`** (the five new tests).
Three numbers, three independent runs, same answer. If a future edit to a snippet moves them, R2.0 is
no longer true and must be re-measured - the fixture file and `replay_refusals.py` are the instrument.

To repeat the check, save the constants block and the gate blocks to a module and apply the same
scoring loop; the inputs are `title.lower()`, `body.lower()`, `_label_set(labels)` and
`_has_code_reference`, all already exported by `actions_dispatch.py`.

---

# R9 - "Any more repairs needed?" - audited, three answers

Asked on 2026-10-30 after R2 and R3 landed. The audit found one live defect of mine, one measured
throughput fact that contradicts my own arithmetic, and one lane that does not exist.

## R9.1 Defect in my own R3 patch (fixed)

When the worker has no checkout to measure, `run_multi_turn` fell back to a hardcoded plan:

```python
VerificationPlan(baseline_tests=[["npm", "test"]], linters=[["npm", "run", "lint"]])
```

That is the exact pair R3 exists to refuse - "we have measured nothing, so run the two most
expensive commands there are". It sits in the dry-run branch, which is why nothing caught it, and it
is the shape of the original defect. Now `VerificationPlan()`: no checkout, no plan, and the reason
is stated in place.

(`autonomous_icu_pipeline.py:2838` carries the same line. It is a legacy module - only
`scratch/actions-e2e-audit-20261027/` copies import it - so it is recorded here, not edited.)

## R9.2 The backlog does not drain, and it is not a drain problem

`HYDRATION_BATCH = 60`. The hydration window is filled from a priority list of the *current cycle's*
hits, so on three consecutive production runs the fresh work consumed 59, 38 and 27 of those 60
slots, and `pending_hydration` read:

```text
93,777 -> 93,732 -> 93,833   (about 40 minutes apart)
```

It is **not falling**. It grows by roughly a hundred rows every twenty minutes, because discovery
queues far more per cycle than the window can retire. My earlier "78,743 backlog, 1,200 rows/hour,
65 hours" arithmetic was wrong twice over: the batch is 60 and not 300 in the discovery lane, and
the lane's window is spent on fresh work by design.

**This is hygiene, not yield.** The rows that matter for dispatch are the fresh ones, and they are
being hydrated. The residual cost is unbounded growth of the pending table, and the fact that old
rows are cold if anyone ever needs them. `--hydrate-only --hydrate-batch 300` is the lane that would
retire them, and it is written correctly - it just rarely runs (R9.3).

## R9.3 The scheduler in this repository is erratic, and that is measured, not suspected

`discovery-heartbeat.yml` already says it in its own header: *"F8: the discovery cron is erratic -
even a correct schedule can simply not fire."* The timestamps confirm the scale:

```text
discovery-heartbeat.yml   cron */10              01:16, 21:29, 16:51, 11:35   -> every 4-5 HOURS
bounty-hydration.yml      cron 2,17,32,47 * * * *  one run at 00:46 in 2 hours -> 7 slots missed
bounty-discovery.yml      cron */15              00:56, 01:16, 01:36, 01:57, 02:17 -> every ~20 min
```

Discovery survives because the heartbeat re-dispatches it. **Nothing re-dispatches hydration.**
The repair is to apply the proven workaround to the second lane, using the script that already
exists (`discovery_heartbeat.py` takes `--workflow`, `--max-age-minutes`, `--cooldown-minutes`,
`--state`, `--lock`), as one more step in the heartbeat job:

```yaml
    - name: Re-dispatch the hydration drain when its own cron has stalled
      # Same F8 workaround as discovery. The hydration cron has a 15-minute cadence and has been
      # observed to fire once in two hours, so it cannot be trusted to retire the backlog.
      run: |
        python3 -u scripts/discovery_heartbeat.py \
          --workflow bounty-hydration.yml \
          --max-age-minutes 45 --cooldown-minutes 30 \
          --state scratch/hydration-heartbeat.jsonl \
          --lock scratch/hydration-heartbeat.lock
```

**Not applied yet**, and the honest reason: R9.2 shows the backlog is not what blocks yield, so this
buys table hygiene rather than revenue. It is one step, it reuses a tested script, and it should
ship with the next workflow commit rather than alone.

## R9.4 The one repair that is worth more than all of the above

Nothing watches a published PR. `fyne-io/fyne#6637` is open, mergeable, 13/13 checks green, head
`4a32ff7c`, and has had **zero reviews** since 2026-10-28. The funnel can now prepare cheaper and
refuse smarter, and the metric will still read 1 for as long as no maintainer is asked to look. A
lane that reads review state for every published PR and reports "waiting, n days, no reviewer" is
worth more than any gate in this document, and it does not exist. That is O1 in
`docs/FUNNEL-TODO-2026-10-30.md`.

---

# R10 - The marketplace leg (M0-M4), measured 2026-10-30 01:00-01:50 IST

R0-R9 are the bounty leg. This section is the **other leg** - LinkedIn services requests handled on
the phone - and it inherits every rule above. It exists because that leg was worked this window and
produced measurements; it is not a plan for work that was imagined.

Measured starting state (`docs/FUNNEL-YIELD-FORENSIC-2026-10-30.md` 10.): 35 live request records,
**9 raw hits of which 7 are true buyers**, **10 job seekers**, **16 other**; **4 proposals sent**,
**0 replies**; **4 records unreachable at send time, 3 of them true buyers**; classifier precision
**7/9 (78%)** with two substring errors.

| Step | Work | Status |
| --- | --- | --- |
| **M0** | Reply watch for sent proposals | **SPEC READY** - not built, and it is the only step that can move the metric |
| **M1** | Injection helper: serial + IME | **SPEC READY** - defect measured twice tonight, helper is still Nokia-only |
| **M2** | Word-boundary classifier | **SPEC READY** - two measured false positives name the fix |
| **M3** | Queue freshness stamp | **SPEC READY** - expiry measured (10.4) |
| **M4** | Re-check the 4 unreachable qualified targets | **OPEN** - needs a live run, not code |

---

## M0 - Reply watch (the R9.4 of this leg)

**Why.** Four proposals were delivered at 01:11, 01:36, 01:40, 01:45 and **nothing reads the thread
again**. Exactly as with `fyne-io/fyne#6637`, the output left the building unobserved, so the metric
is zero for as long as no lane looks.

**Shape.** One process, one loop, read-only:

1. For every row in `war-log/evidence/market_proposals_log.jsonl` with `status: SENT` and no
   `reply_seen_at`, open that thread (`adb shell am start` on the conversation, or the sheet's
   `Message` button) and dump the last message.
2. If the last message's sender is **not** `Kunal Das`, write `reply_seen_at`, the first 200 chars,
   and a screenshot path into the ledger row, and stop writing to that thread.
3. If the thread is unchanged, write nothing. No heartbeat spam into the ledger.

**Pin.** A fixture with three thread dumps - seller-last, buyer-last, empty - must produce exactly
one `reply_seen_at`. No device needed for the test: the dump reader is a pure function.

**If it fails.** Fall back to a once-a-day manual read of the four threads and log it as a manual
read. Never mark a reply seen from a memory of seeing it.

---

## M1 - Injection helper: serial and IME are both variables

**Anchor.** `war-log/phone_linkedin_dm.py`

**Current** (lines 6-13):

```python
ADB = r'D:\anonym\platform-tools\adb.exe'
SER = 'G2866620341C0402558'
SHOTDIR = r'D:\anonym\war-log\shots'


def run(args, timeout=25):
    return subprocess.run([ADB, '-s', SER] + args, capture_output=True, timeout=timeout)
```

**Replace with** (serial from argv/env, and an IME guard that is paid for tonight):

```python
ADB = r'D:\anonym\platform-tools\adb.exe'
SER = os.environ.get('KILO_SERIAL') or 'G2866620341C0402558'   # Nokia default, kept for old calls
INJ_IME = 'com.android.adbkeyboard/.AdbIME'
NATIVE_IME = 'com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME'


def ime():
    return run(['shell', 'settings', 'get', 'secure', 'default_input_method']).stdout.decode().strip()


def use_injection_ime():
    if ime() == INJ_IME:
        return 'already'
    run(['shell', 'ime', 'enable', INJ_IME])
    run(['shell', 'ime', 'set', INJ_IME])
    if ime() != INJ_IME:
        raise SystemExit('IME_SWITCH_FAILED: broadcast injection will silently no-op')
    return 'switched'


def restore_ime():
    run(['shell', 'ime', 'set', NATIVE_IME])
```

and call `use_injection_ime()` before the first `ADB_INPUT_B64`, `restore_ime()` in a `finally:`.

**Why.** Measured twice in one night: with **Gboard** active the broadcast left the composer empty
(`evidence/nitin_filled_crop.png`, counter `0 of 1500`); with **ADBKeyboard** active the identical
call landed `1463/1500` (`evidence/ui_nitin_verify.xml`). The helper as written hardcodes the Nokia
serial and never touches the IME, so on the IQOO it is a **guaranteed** no-op that looks like a
successful run.

**Pin.** `test_phone_dm_ime.py`: a fake `run()` that records calls must (a) fail the injection path
when the active IME is Gboard, (b) switch and proceed when it is ADBKeyboard, (c) always restore in
the `finally`. **No device in the test.**

**If it fails.** Report it and hold. Never "send anyway" - an empty composer plus a tap on Send is a
silent message loss, the worst outcome in this lane.

---

## M2 - Word-boundary classification

**Anchor.** the classifier is currently an ad-hoc run, not a file; the repair is to give it a home:
`war-log/market_classify.py`.

**Current behaviour** (measured, forensic 10.2): plain `'\(kw\) in headline.lower()`, which matched
`cto` inside **Fa**`cto`**ry** (VenkataRao Kuna, a Lead Data Engineer) and `owner` inside
`Owner`ship (Premkumar Natarajan, a Full Stack Developer). Precision 7/9.

**Replace with:**

```python
import re

def _kw(pattern):
    return re.compile(r'(?<![a-z])' + pattern + r'(?![a-z])')

BUSINESS = [_kw(r'co[- ]?founders?'), _kw(r'founders?'), _kw(r'c[te]o'), _kw(r'cfo'),
            _kw(r'coo'), _kw(r'owners?'), _kw(r'managing\s+directors?'), _kw(r'entrepreneurs?')]
JOB_SEEKER = [_kw(r'students?'), _kw(r'interns?(hip)?s?'), _kw(r'aspiring'), _kw(r'hackathons?'),
              _kw(r'pgdm'), _kw(r'data\s+science'), _kw(r'b\.?tech'), _kw(r'open\s+to\s+work')]
```

Note `c[te]o`: `cto` and `ceo` are both buyers and the character class keeps one pattern.

**Why.** The two false positives are not cosmetic - the leg's whole gate is "do not pitch a job
seeker, do pitch a buyer", and a substring test corrupts both halves. Same law as R2.7: a test that
fires on text inside another word is not a classifier.

**Pin.** `scripts/test_market_classify.py` with the measured cases as fixtures: the 2 false positives
must classify as **not business**; the 7 true businesses must stay business; the **10 job seekers must
not become business** (zero false negatives on that side is the hard requirement, since pitching a
student is the forbidden error).

**If it fails.** Do not add more keywords to compensate. A classifier that needs tuning per record
is a lookup table with extra steps; the honest fallback is human review of 9 rows.

---

## M3 - Queue freshness stamp

**Why.** Measured (forensic 10.4): Farjana Akter Rakhi was readable at **00:31** with `Submit
proposal` on screen; by **01:45** a full walk to the list footer did not contain her, nor RISHI
GOUR, Mohan sai vineeth or VenkataRao. A record that was absent at 00:31 (Arman Ansari) was present
later. The mechanism is unproven; the staleness is measured.

**Change to `war-log/_marketplace_sweep.py`:** write `swept_at` (ISO, IST) on every merged row, and
add `sendable(max_age_h=None)` that returns only rows whose `swept_at` is within the window
(default **6h**) and whose sheet was re-read in this run. A row that fails the window is printed as
`STALE` and never silently included.

**Pin.** A fixture log with one fresh and one 30h-old row: `sendable()` returns exactly one, and the
stale one is named in the output. No device needed.

**If it fails.** Re-sweep before sending. The sweep is cheap; sending a proposal to a request that
no longer exists is not.

---

## M4 - The four unreachable qualified targets

**State.** Drafts exist on disk and were never sent:
`FARJANA-dhaka-php.txt` (the **only international** request in the census),
`RISHI-it-consulting.txt`, `MOHAN-it-consulting.txt`, and no draft for VenkataRao (he was a false
positive, see M2).

**Action.** One live re-check against the current queue before writing a single new draft. If the
requests are gone, the rows are marked `EXPIRED_UNSENT` in the ledger with the timestamp of the check
and they are **not** re-drafted. A request that is not on the queue has no proposal window; DM-ing
the person directly instead is a different lane and needs its own gate.

**Why this is not "just send it anyway":** the ONE HUMAN ONE FUNNEL law. A marketplace request is an
explicit invitation. A cold DM to the same person after their request expired is a different
message with a different consent, and the census shows we have no reply lane to read either one
(M0).

---

## R10.1 Acceptance for this leg

| Step | Done when |
| --- | --- |
| M0 | the 4 sent threads are read once automatically and the ledger carries either a `reply_seen_at` or an explicit "still silent, checked <ts>" |
| M1 | the helper refuses to inject when the IME is wrong, and restores Gboard after every run |
| M2 | the 3 fixture groups pass; the 10 job seekers are still job seekers |
| M3 | a stale row cannot reach a send list, by test |
| M4 | each of the 4 targets has a terminal state: `SENT`, `EXPIRED_UNSENT`, or `REQUEUED` |

## R10.2 The one number to report for this leg

**Qualified buyers who replied, per week.** Not proposals sent (4 tonight), not requests swept (35),
not drafts written (7). Until M0 exists that number is **0** and this document says so.

---

# R11 - The two gates that were actually closed (2026-10-30 04:2xZ)

R0-R9 were built on a pipeline that was, for the last thirty minutes of that work, dead at checkout.
R11 records the two repairs that changed that, and the evidence for each.

| Step | Work | Status |
| --- | --- | --- |
| **C1** | Untrack the undeclared gitlinks that killed `actions/checkout`, and pin the rule | **DONE** - 14 tests, both directions |
| **C2** | Emit the platform claim command that releases a bounty | **DONE in code** - 11 tests; never yet fired live (12.3) |
| **C3** | Full suite in one run | **BLOCKED** - 76-module discover exceeds 20 min locally on an unmocked live API test |

## C1 - checkout integrity

**Measured.** `b1cfd41` (02:59Z) recorded `_bp_audit/_h` and `_proof_repo` as mode-160000 gitlinks with
no `.gitmodules` stanza. `_bp_audit/_h` is a clone of this repository, so no valid url could exist.
Every workflow since failed before its first step:

```
##[error]fatal: No url found for submodule path '_bp_audit/_h' in .gitmodules
```

Grep confirms neither path is referenced by any workflow or script - they are local scratch trees
that arrived via `git add -A`. `.gitignore` already carried a hand-written note about the same class
from `_bounty_repo`, which is why this recurred: the fix had been a comment, not a test.

**Applied.** `git rm --cached -r _bp_audit/_h _proof_repo`; both added to `.gitignore`;
`scripts/test_gitmodules_integrity.py` asserts (a) every index gitlink has a `.gitmodules` path and
(b) every `.gitmodules` path is an index gitlink. A future `git add -A` that swallows a clone fails in
the test suite, not in every workflow.

**Why this is C1 and everything else follows it:** no gate, no hash, no lane in this document can run
when checkout fails. It was invisible because it fails *before* logs that anyone was reading.

## C2 - the claim lane

**Anchor.** `scripts/actions_delivery.py`

Three additions, each with the reason it exists:

1. `claim_line(context, number)` - pure; returns `/claim #<n>` only when a comment author is in
   `bounty_admission.TRUSTED_BOTS`. Prose that mentions a platform is **not** a platform: the
   fyne maintainer's own words ("if you're coming from a vibe code bounty tracker") are exactly the
   signal a bare `/claim` would amplify.
2. `pr_body(context, number, receipt, head, rows, claim="")` - extracted from `publish()` so the body
   is a pure function of evidence and is testable without a network. Claim sits directly after
   `Resolves #N`, before the evidence block.
3. `post_claim(api, repo, pr_number, claim)` - for an **already-open** PR, because both platforms read
   the command only on creation and ignore edits afterwards. A failure prints `CLAIM_POSTED_FAILED`
   and never fails a delivery that already succeeded.

**Evidence behind it** (forensic 11.3-11.4): 64 external PRs, `/claim` in none of the four sampled
bodies, no Algora/Opire/Stripe credential in `vault/`. Even a merge would have paid nothing.

**Pins.** `scripts/test_claim_command.py` (11 tests): three bot spellings produce a claim, human
chatter and platform-mentioning prose produce none, the claim precedes the evidence, the open-PR path
posts a comment, and a failed claim raises nothing.

## C3 - the suite cannot be run in one pass locally (open defect)

`python -m unittest discover -s . -p "test_*.py"` was run and **did not complete in 20 minutes**; the
log shows it executing live GitHub searches (`QUERY WITH HARD GATES ... Returned from GitHub: 50`).
Some discovery test is unmocked. Consequence: the 542-test baseline in R0 cannot be reproduced locally
in one command, so "the suite is green" is only ever said about a selected subset. That is a reporting
integrity problem, not a test-coverage one, and it is listed as open rather than papered over.

**Interim rule:** report the subset and its size. Tonight's: **118 tests, exit 0**, across
`test_claim_command`, `test_gitmodules_integrity`, `test_base_branch`, `test_baseline_relationship`,
`test_cline_deliverable`, `test_download_patch_submodule`, `test_failure_taxonomy`,
`test_partition_regressions`, `test_preflight`, `test_preparation_contract`,
`test_preparation_terminal`.

## R11 acceptance

| Step | Done when |
| --- | --- |
| C1 | **DONE, observational.** A workflow run completes checkout: `41004884451` (contracts, success) and `41005024759` (discovery, success 3m13s) in the public `bounty-control` repository, whose log shows the `git submodule foreach --recursive` step - the exact command that killed every job since `b1cfd41` - completing (forensic 12.5) |
| C2 | a real `/claim #<n>` posts on an issue whose comments carry a trusted bot, and the ledger records it |
| C3 | the unmocked live-API test is identified and marked network, so `discover` completes offline |
| C4 | a live tick classifies candidates with named reasons instead of crashing: run `41005024759` searched five lanes and emitted `CURRENT_ISSUER_OFFER_MISSING` / `HARD_ISSUE_EVIDENCE_MISSING` - **DONE** |

## R12 - the moat is wired, and the bands match the evidence (DONE 2026-10-30)

Closes the two divergences forensic 13 found between the doctrine and the running code.

| item | state | receipt |
| --- | --- | --- |
| `hardness_score.py` extracted as the single home, 46 patterns, original weights | DONE | self-test 13/13 |
| hardness inserted into `candidate_sort_key` between liquidity and velocity | DONE | `test_hardness_ordering` 12 tests |
| founders lead the bands, programmes second | DONE | `test_dispatch_velocity` rewritten with the reason |
| guard: the dispatcher must import the moat | DONE | AST assertion in `test_hardness_ordering.WiringTest` |
| unmeasured comment count earns no bonus | DONE | explicit test |
| 750,000 KB capacity ceiling raised | **NOT DONE, deliberately** | a 3.38 GB repo cannot be prepared here; see forensic 13.3 |

### R12.1 acceptance

| # | criterion | how it was met |
| --- | --- | --- |
| R12a | a hard ticket outranks a trivial one in the same band | `test_hard_ticket_beats_trivial_one_in_same_band` |
| R12b | hardness still loses to liquidity | `test_solvency_still_beats_hardness` |
| R12c | band still dominates hardness | `test_band_dominates_hardness` |
| R12d | the moat cannot silently become dead code again | source-level import assertion |
| R12e | the whole contracts suite stays green | 444 tests, 25.9 s, exit 0 |

### R12.2 one number

A candidate's queue position is now decided by four things in this order: **band, solvency,
hardness, quietness**. Before this lane it was three, and hardness was not one of them.
