"""O8: no issue is admitted on a bounty word alone.

Measured 2026-11-01 over the whole authored PR surface: 66 PRs, each replayed through the
live ``admit()``. 39 were refused ``CURRENT_ISSUER_OFFER_MISSING``, 9 ``HARD_ISSUE_EVIDENCE_
MISSING``, 5 ``MIRROR_OR_NON_ENGINEERING``, 2 ``MARKETING_OR_EXPERIMENT``, 3
``CLOSED_OR_READ_ONLY``, 1 ``UNBOUNDED_SCOPE``, 7 admitted. **Zero** of the 7 admitted issues
had funding evidence weaker than a maintainer offer or a platform attestation.

The four issues that looked like O8 violations were not:

    paraloom-labs/paraloom-core#988   author Mannerless, assoc NONE, self-declared $150  -> refused
    Tarsnap/kivaloo#365               author ugin-man,    assoc NONE, self-declared $100  -> refused
    SecureBananaLabs/bug-bounty#12667 author dwaddle,     assoc NONE, self-declared $780  -> refused
    limitlessprojects/Go-Hybrid#1594  author JRCage,      assoc NONE, self-declared $500  -> refused

And the four that carry a genuine ``algora-pbc[bot]`` attestation are refused on the floor,
not on authority: ``arakoodev/EdgeChains#290`` ($50), ``tryabby/abby#68`` ($40),
``javelin-anticheat/py-workedtask#4`` ($100) are all below the live 250 floor, and
``SecureBananaLabs/bug-bounty#30`` ($750) is admitted.

So the property holds today. This suite exists so it cannot stop holding: it pins the
whole-admission verdict, not just the comment-level authority, for every funding shape the
corpus contained. ``test_admission_trust.py`` pins *who* may commit money; this pins that
the answer to "may this issue be dispatched at all" is never yes without evidence.
"""
import unittest

from bounty_admission import FLOOR, admit

# The floor is a policy knob that has already moved twice (80 -> 2000 -> 250). These fixtures
# assert on authority and evidence, so they pin a fixed floor and stay meaningful when the
# live one moves again. The live floor is asserted separately at the bottom.
FIXTURE_FLOOR = 250

REPO = "measured/example"
ISSUE_URL = "https://github.com/measured/example/issues/1"


def issue(title, body, login="stranger", association="NONE"):
    return {"title": title, "body": body, "state": "open", "html_url": ISSUE_URL,
            "user": {"login": login}, "author_association": association}


def comment(login, body, association="NONE"):
    return {"user": {"login": login}, "author_association": association,
            "html_url": ISSUE_URL + "#issuecomment-1", "body": body}


def context(issue_doc, comments=()):
    return {
        "repo": REPO,
        "issue_number": 1,
        "repository": {"owner": {"login": "measured"}, "name": "example",
                       "full_name": REPO, "archived": False, "disabled": False},
        "issue": issue_doc,
        "comments": list(comments),
        "complete_comments": True,
        "fetched_at": "unit fixture",
    }


# A body that clears the engineering-evidence gate, so every refusal below is about funding
# and nothing else. Without this the fixtures would pass for the wrong reason.
HARD_EVIDENCE = ("The replay guard in src/bridge/CrossChainBridge.sol is incomplete; "
                 "verifySignature() never binds the destination chain id, so a signature "
                 "from chain A is accepted on chain B.")


def attestation(login, amount):
    """A platform attestation shaped like the real algora-pbc[bot] comment."""
    return comment(login,
                   "## $%s bounty [ Stacylia ](https://algora.io/Stacylia)\n"
                   "### Steps to solve:\n"
                   "1. **Start working**: Comment `/attempt #1` with your implementation plan\n"
                   "2. **Submit work**: Create a pull request including `/claim #1`\n"
                   "3. **Receive payment**: 2-5 days post-reward." % amount)


class TitleWordAloneIsNeverFunding(unittest.TestCase):
    def test_a_bounty_word_in_the_title_from_a_stranger_is_refused(self):
        """The measured shape of paraloom-core#988 and kivaloo#365."""
        ctx = context(issue("[BOUNTY] Non-atomic state transitions in ComputeStorage",
                            HARD_EVIDENCE + "\n\nSeverity: Medium ($150 USDC)"))
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")

    def test_a_bounty_label_plus_an_amount_from_a_stranger_is_refused(self):
        """The measured shape of SecureBananaLabs#12667 ($780 in the poster's own body)."""
        doc = issue("[Bounty 80] login signs a valid token for any credentials", HARD_EVIDENCE)
        doc["labels"] = [{"name": "bounty"}]
        ctx = context(doc, [comment("dwaddle", "/bounty $780")])
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")

    def test_a_contributor_cannot_declare_its_own_bounty(self):
        """A CONTRIBUTOR is not funding authority, whatever it writes."""
        ctx = context(issue("[BOUNTY] fix the decoder", HARD_EVIDENCE, association="CONTRIBUTOR"),
                      [comment("ugin-man", "Please assess eligibility under our $500 pool.",
                               association="CONTRIBUTOR")])
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")

    def test_a_stranger_cannot_ride_on_a_maintainers_bounty_word(self):
        """The maintainer says "bounty"; the stranger supplies the amount. Refused."""
        ctx = context(issue("[BOUNTY] fix the decoder", HARD_EVIDENCE, association="MEMBER"),
                      [comment("drive-by", "I will pay $900 for this.", association="NONE")])
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")


class RealEvidenceIsStillAdmitted(unittest.TestCase):
    def test_a_platform_attestation_above_the_floor_is_admitted(self):
        """The measured shape of SecureBananaLabs#30 ($750, algora-pbc[bot])."""
        ctx = context(issue("Benchmark APIs with p50, p95 latency", HARD_EVIDENCE),
                      [attestation("algora-pbc[bot]", "750")])
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertEqual(reason, "")
        self.assertEqual(proof["funding"]["amount"], "750")
        self.assertEqual(proof["funding"]["payer"], "algora-pbc[bot]")

    def test_a_maintainer_offer_above_the_floor_is_admitted(self):
        """The measured shape of outerbase/starbasedb#59 ($250, MEMBER)."""
        ctx = context(issue("Database dumps do not work on large databases", HARD_EVIDENCE,
                            login="Brayden", association="MEMBER"),
                      [comment("Brayden", "Bounty: $250 USD for this fix.", association="MEMBER")])
        proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
        self.assertEqual(reason, "")
        self.assertEqual(proof["funding"]["amount"], "250")

    def test_a_platform_attestation_below_the_floor_is_refused(self):
        """EdgeChains#290 ($50), abby#68 ($40), py-workedtask#4 ($100): authority is fine,
        the amount is not. Refusing these is the floor working, not a funding gap."""
        for amount in ("50", "40", "100"):
            ctx = context(issue("BOUNTY: integrate a redaction utility", HARD_EVIDENCE),
                          [attestation("algora-pbc[bot]", amount)])
            proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
            self.assertIsNone(proof, "amount %s must be refused" % amount)
            self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")


class ThePropertyHoldsForEveryShape(unittest.TestCase):
    """The O8 assertion itself, stated once over every funding shape in the corpus."""

    def test_no_shape_without_evidence_is_admitted(self):
        shapes = {
            "title word only": context(issue("[BOUNTY] fix it", HARD_EVIDENCE)),
            "label only": context(issue("fix it", HARD_EVIDENCE)),
            "stranger amount": context(issue("[BOUNTY] fix it", HARD_EVIDENCE),
                                       [comment("x", "/bounty $900")]),
            "contributor self-declared": context(
                issue("[BOUNTY] fix it", HARD_EVIDENCE, association="CONTRIBUTOR"),
                [comment("x", "bounty $900", association="CONTRIBUTOR")]),
            "no funding at all": context(issue("fix the decoder", HARD_EVIDENCE)),
        }
        for name, ctx in shapes.items():
            proof, reason = admit(ctx, floor=FIXTURE_FLOOR)
            self.assertIsNone(proof, "%s must not be admitted" % name)
            self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING", name)

    def test_the_live_floor_is_the_measured_value(self):
        """The floor is 250 in production. If it moves, this line and the docs move with it."""
        self.assertEqual(FLOOR, 250)


if __name__ == "__main__":
    unittest.main()
