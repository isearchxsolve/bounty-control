"""Deterministic fixtures for funding authority; not live delivery receipts.

GitHub apps report their login with a ``[bot]`` suffix. ``TRUSTED_BOTS`` declared
``algora-pbc`` without it, so ``algora-pbc[bot]`` -- the account that actually
publishes Algora's funding attestation on somebody else's issue -- never matched:

    UnsafeLabs/Bounty-Hunters#920   "## $900 bounty [ Stacylia ]"  -> untrusted
    UnsafeLabs/Bounty-Hunters#919   "## $250 bounty [ Stacylia ]"  -> untrusted
    UnsafeLabs/Bounty-Hunters#917   "## $350 bounty [ Stacylia ]"  -> untrusted

Every such issue was then reported as CURRENT_ISSUER_OFFER_MISSING even though the
platform that pays had published the amount. These fixtures pin the repair and,
just as importantly, pin what must NOT change: a stranger's comment is never an
offer, a CONTRIBUTOR still cannot commit the project's money, and the floor holds.
"""
import unittest

from bounty_admission import FLOOR, admit as _admit, trusted

# The Algora attestations below carry the amounts those issues actually published ($900).
# The admission floor moved from 80 to 2000 on 2026-10-29, which is a separate policy
# knob from funding authority; pinning it here keeps this suite testing who may commit
# money rather than re-breaking whenever the floor moves. The floor itself stays covered:
# ``test_an_attestation_below_the_floor_is_still_refused`` reads the live FLOOR.
FIXTURE_FLOOR = 80


def admit(context, quote=None, floor=FIXTURE_FLOOR):
    """Admission under the floor these fixtures were authored against."""
    return _admit(context, quote=quote, floor=floor)


def context(comments, association="CONTRIBUTOR", body=None):
    return {
        "repo": "UnsafeLabs/Bounty-Hunters",
        "issue_number": 920,
        "repository": {"owner": {"login": "UnsafeLabs"}, "archived": False, "disabled": False},
        "issue": {"title": "Fix cross-chain replay attack in CrossChainBridge signature verification",
                  "body": body if body is not None else (
                      "The replay guard in src/bridge/CrossChainBridge.sol is incomplete; "
                      "verifySignature() never binds the destination chain id."),
                  "state": "open", "html_url": "https://github.com/UnsafeLabs/Bounty-Hunters/issues/920",
                  "user": {"login": "clankerjournalist"}, "author_association": association},
        "comments": comments,
        "complete_comments": True,
        "fetched_at": "unit fixture",
    }


def attestation(login, amount, association="NONE"):
    return {"user": {"login": login}, "author_association": association,
            "html_url": "https://github.com/UnsafeLabs/Bounty-Hunters/issues/920#issuecomment-1",
            "body": ("## $%s bounty [ Stacylia ](https://algora.io/Stacylia)\n"
                     "### Steps to solve:\n"
                     "1. **Start working**: Comment `/attempt #920` with your implementation plan\n"
                     "2. **Submit work**: Create a pull request including `/claim #920`\n"
                     "3. **Receive payment**: 2-5 days post-reward." % amount)}


class FundingAuthorityTests(unittest.TestCase):
    def test_platform_app_login_publishes_a_trusted_offer(self):
        self.assertTrue(trusted(context([]), attestation("algora-pbc[bot]", 900)))

    def test_every_declared_bot_is_trusted_in_both_spellings(self):
        for login in ("algora-pbc", "algora-pbc[bot]", "algora-io[bot]", "polar-sh[bot]", "opire[bot]"):
            with self.subTest(login=login):
                self.assertTrue(trusted(context([]), attestation(login, 900)))

    def test_a_stranger_cannot_publish_an_offer(self):
        self.assertFalse(trusted(context([]), attestation("luccas12348486", 900)))

    def test_a_contributor_cannot_commit_project_money(self):
        self.assertFalse(trusted(context([], association="CONTRIBUTOR"),
                                 attestation("clankerjournalist", 900, "CONTRIBUTOR")))

    def test_owner_and_member_remain_funding_authority(self):
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                self.assertTrue(trusted(context([], association=association),
                                        attestation("maintainer", 900, association)))

    def test_platform_attestation_admits_the_issue(self):
        proof, reason = admit(context([attestation("luccas12348486", 900),
                                       attestation("algora-pbc[bot]", 900)]))
        self.assertEqual(reason, "")
        self.assertIsNotNone(proof)
        funding = proof["funding"]
        self.assertEqual((funding["amount"], funding["currency"]), ("900", "USD"))
        self.assertEqual(funding["payer"], "algora-pbc[bot]")
        self.assertIn("signature", " ".join(proof["technical_signals"]))
        self.assertIn("src/bridge/CrossChainBridge.sol", proof["component_references"])

    def test_an_attestation_below_the_floor_is_still_refused(self):
        # Deliberately calls the real ``admit`` with the live default floor: this is the
        # one test in the suite that measures the floor itself, so it must not go through
        # the FIXTURE_FLOOR shim above.
        low = int(FLOOR) - 1
        proof, reason = _admit(context([attestation("algora-pbc[bot]", low)]))
        self.assertIsNone(proof)
        self.assertEqual(reason, "CURRENT_ISSUER_OFFER_MISSING")


if __name__ == "__main__":
    unittest.main()
