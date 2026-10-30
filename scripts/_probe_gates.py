"""Probe the proposed F9 refusal gates against the hand-labelled sample.

Read-only. Applies each candidate predicate to the 45 ``needs_code_change`` items (any refusal
there is a false negative and disqualifies the gate) and to the 16 measured Cline refusals (how
many does the gate actually catch).

Prints a table. Nothing is written, nothing is imported from actions_dispatch except the existing
helpers, so the production classifier is untouched.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from actions_dispatch import (  # noqa: E402
    _CODE_BODY_KEYWORDS,
    _CODE_TITLE_KEYWORDS,
    _has_code_reference,
)

SAMPLE = os.path.join(HERE, "f11_sample", "f11_labeling_sample_60.json")
FIXTURES = os.path.join(HERE, "f9_sample", "f9_refusals_16.json")

AUTO_DIGEST_TITLE = r"^\[[^\]]{0,40}\]\s*\d{4}-\d{2}-\d{2}\b"
AUTO_DIGEST_LABELS = {"daily", "digest", "auto-generated", "automated"}
QUESTION_TITLE = (
    r"^(?:may\s+i\s+know|are\s+there\s+any\s+plans|when\s+(?:will|is|does)|"
    r"how\s+(?:do|can)\s+i|can\s+you\s+tell|is\s+it\s+possible|"
    r"(?:contact|support|general)\s+question)\b"
)
REPRO_EVIDENCE = (
    r"\b(?:steps\s+to\s+reproduce|expected\s+(?:behaviou?r|result)|"
    r"actual\s+(?:behaviou?r|result)|stack\s*trace|traceback)\b"
)
UMBRELLA_LABELS = {"epic", "rfc", "discussion", "feature request", "proposal"}
HARDWARE_REQUIRED = (
    r"\bhardware[- ](?:verified|validation|required|dependent)\b|"
    r"\brequires?\s+(?:a\s+|an\s+|the\s+)?(?:physical|real)\s+"
    r"(?:device|card|gpu|hardware|machine)\b|"
    r"\bacceptance\s+requires?\b[^\n]{0,80}\b(?:physical|hardware|card|gpu)\b"
)
# A named consumer GPU/CPU product is hardware we cannot provision on a hosted runner.
HARDWARE_PRODUCT = (
    r"(?:intel\s+arc|radeon|geforce|ryzen|apple\s+m\d|"
    r"rtx\s*\d{4}|gtx\s*\d{3,4}|arc\s+[abc]\d{3})"
)
VIDEO_DELIVERABLE = r"\b(?:film|shoot|record|produce)\s+(?:a\s+)?(?:real\s+)?(?:demo|video)\b"
FUNCTION_WORDS = {"a", "an", "the", "is", "are", "was", "were", "in", "on", "for",
                  "to", "of", "and", "or", "with", "when", "that", "this", "it"}


def has_code_keyword(title_l, body_l):
    return bool(_CODE_TITLE_KEYWORDS & set(title_l.split())
                | _CODE_BODY_KEYWORDS & set(body_l.split()))


def gate_auto_digest(title, body, labels):
    title_l, body_l = title.lower(), body.lower()
    labels_l = {str(x).lower() for x in labels}
    if re.search(AUTO_DIGEST_TITLE, title_l) and labels_l & AUTO_DIGEST_LABELS:
        if not _has_code_reference(body_l):
            return True
    return False


def gate_question(title, body, labels):
    title_l, body_l = title.lower(), body.lower()
    if re.search(QUESTION_TITLE, title_l) and not re.search(REPRO_EVIDENCE, body_l):
        if not _has_code_reference(body_l):
            return True
    return False


def gate_question_opening(title, body, labels):
    """Variant: interrogative title OR interrogative first 200 chars of the body."""
    title_l, body_l = title.lower(), body.lower()
    opening = " ".join(body_l.split())[:200]
    if re.search(QUESTION_TITLE, title_l) or re.search(QUESTION_TITLE, opening):
        if not re.search(REPRO_EVIDENCE, body_l):
            if not _has_code_reference(body_l):
                return True
    return False


def gate_umbrella(title, body, labels):
    labels_l = {str(x).lower() for x in labels}
    return bool(labels_l & UMBRELLA_LABELS) and not _has_code_reference(body.lower())


def gate_hardware(title, body, labels):
    """Deliverable needs a physical card: no runner can satisfy it."""
    body_l = body.lower()
    if re.search(REPRO_EVIDENCE, body_l):
        return False
    return bool(re.search(HARDWARE_REQUIRED, body_l)) or bool(
        re.search(HARDWARE_REQUIRED, title.lower()))


def gate_hardware_product(title, body, labels):
    """The issue names a physical product, so acceptance needs that hardware in hand."""
    body_l = body.lower()
    if re.search(REPRO_EVIDENCE, body_l):
        return False
    return bool(re.search(HARDWARE_PRODUCT, title.lower())
                or re.search(HARDWARE_PRODUCT, body_l))


def gate_video(title, body, labels):
    """Deliverable is a video/film, which no patch produces."""
    body_l = body.lower()
    if re.search(REPRO_EVIDENCE, body_l):
        return False
    return bool(re.search(VIDEO_DELIVERABLE, " ".join(body_l.split()))) or bool(
        re.search(VIDEO_DELIVERABLE, title.lower()))


def gate_spam(title, body, labels):
    title_l = title.lower()
    words = re.findall(r"[a-z][a-z'-]*", title_l)
    if len(words) >= 18 and len(FUNCTION_WORDS & set(words)) < 3:
        return not _has_code_reference(body.lower())
    return False


GATES = [
    ("G1 auto_digest", gate_auto_digest),
    ("G3 question (title)", gate_question),
    ("G3b question (title|opening)", gate_question_opening),
    ("G4 umbrella", gate_umbrella),
    ("G5a hardware_required", gate_hardware),
    ("G5a2 hardware_product", gate_hardware_product),
    ("G5b video_deliverable", gate_video),
    ("G6 keyword_spam", gate_spam),
]


def load(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    sample = load(SAMPLE)
    fixtures = load(FIXTURES)
    positives = [i for i in sample if i.get("hand_label") == "needs_code_change"]

    print("false negatives (of %d) and catch (of %d open refusals)\n"
          % (len(positives), len(fixtures)))
    print("%-28s %10s %10s   %s" % ("gate", "false-neg", "caught", "problems"))
    print("-" * 96)

    for name, gate in GATES:
        false_neg = []
        for item in positives:
            if gate(item.get("title", ""), item.get("body_preview", ""),
                    item.get("labels", [])):
                false_neg.append("%s#%s" % (item["repo"], item["number"]))
        caught = []
        for case in fixtures:
            if case.get("gate_admitted") is False:
                continue  # already refused today; not this gate's job
            if gate(case["title"], case["body"], case["labels"]):
                caught.append("%s#%s" % (case["repo"], case["number"]))
        problems = []
        if false_neg:
            problems.append("FN: " + ", ".join(false_neg[:3]))
        print("%-28s %10d %10d   %s" % (name, len(false_neg), len(caught),
                                        "; ".join(problems) or "clean"))
        if caught:
            print("%30s %s" % ("", "catches " + ", ".join(caught)))

    # A gate must also not fire on an item that still has a genuine code keyword - that is the
    # signal the existing CODE CHANGE block would have used.
    print("\noverlap check: a gate firing where the issue still carries code keywords")
    for case in fixtures:
        if case.get("gate_admitted") is False:
            continue
        title_l, body_l = case["title"].lower(), case["body"].lower()
        if not has_code_keyword(title_l, body_l):
            continue
        fired = [name for name, gate in GATES
                 if gate(case["title"], case["body"], case["labels"])]
        if fired:
            print("  %s#%s keywords=true gates=%s"
                  % (case["repo"], case["number"], ",".join(fired)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
