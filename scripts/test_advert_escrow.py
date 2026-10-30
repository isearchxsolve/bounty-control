"""Pins the escrow-advertisement gate in both directions.

Measured on 2026-10-29 over the `label:bounty` search horizon. Two repositories publish
issues that are not defects in their own code at all: each advertises a payout held
elsewhere and prints the raw wallet addresses needed to claim it. They mirror each other,
so one advert appears twice in the horizon, and both passed every earlier gate -- they
carry a real dollar figure in the title from a trusted OWNER, and the mirrored copy is a
mirror only in wording, not in any field the admission code reads.

The refusal is deliberately narrow: a wallet address ALONE is not refused, because a
project that publishes a donation address is doing something ordinary. The escrow
vocabulary is required too, so the two signals must agree before an issue is discarded.
"""
import unittest

from bounty_admission import CRYPTO_WALLET, ESCROW_ADVERT, admit as _admit

# The genuine-issue fixtures carry the amounts those issues actually published ($250,
# $2340, $300, $400). The admission floor moved from 80 to 2000 on 2026-10-29, a separate
# policy knob, so it is pinned here: this suite measures whether an escrow advert is
# refused and whether a genuine funded defect is not, and neither question is about price.
FIXTURE_FLOOR = 80


def admit(context, quote=None, floor=FIXTURE_FLOOR):
    """Admission under the floor these fixtures were authored against."""
    return _admit(context, quote=quote, floor=floor)

from test_program_offers import attestation, context

# Verbatim head of the alfrexo95/bounty-bot advert (issue #60), doubled-title shape intact.
FARM_BODY = """\U0001f916 **Bounty con Pago Garantizado (Escrow)**

- **T\u00edtulo:** [Bounty] \U0001f4b0 Bounty Seguro ($$250): [Bounty] \U0001f4b0 Bounty Seguro ($$250)
- **Monto:** $$250
- **Plataforma:** GitHub Issue

---

### \U0001f4b0 Payment Details
- BTC: bc1qt3rukpe7qp737zj5j5xpxxmcqv90cfefhg5e00
- ETH: 0xA5E6eB31868A85127B1ED82b8C760193356206ED
"""

# Verbatim head of the mirror (zhangjiayang6835-cyber/bounty-plaza #4171).
MIRROR_BODY = """### \u8d4f\u91d1\u5e73\u53f0 / Platform
GitHub

### \u539f\u59cb\u94fe\u63a5 / Source URL
https://github.com/alfrexo95/bounty-bot/issues/58

### \u6f0f\u6d1e\u63cf\u8ff0 / Description
\U0001f4b0 Bounty Seguro ($$250): \U0001f916 **Bounty con Pago Garantizado (Escrow)**
- BTC: bc1qt3rukpe7qp737zj5j5xpxxmcqv90cfefhg5e00
"""

FARM_TITLE = "\U0001f4b0 Bounty Seguro ($$250): [Bounty] \U0001f4b0 Bounty Seguro ($$250)"

# Genuine funded work measured in the same sample: real defect, real payout, no wallets.
GENUINE = [
    ("[BOUNTY] WearOS Support [$2340]",
     "WearOS is not supported. The watch build in src/wear/MainActivity.kt fails to bind "
     "the sensor service and throws a NullPointerException on connect."),
    ("[$250] Fix race condition in the report composer",
     "The composer sends a duplicate request when two tabs submit at once. See "
     "src/pages/Report/ReportComposer.tsx and the useSubmit hook."),
]


class EscrowAdvertRefusalTests(unittest.TestCase):
    def test_the_measured_farm_advert_is_refused(self):
        verdict, reason = admit(context(FARM_TITLE, FARM_BODY, full_name="alfrexo95/bounty-bot"))
        self.assertIsNone(verdict)
        self.assertEqual(reason, "ADVERT_OR_ESCROW_SPAM")

    def test_the_mirrored_copy_of_the_same_advert_is_refused(self):
        verdict, reason = admit(context(
            FARM_TITLE, MIRROR_BODY, full_name="zhangjiayang6835-cyber/bounty-plaza"))
        self.assertIsNone(verdict)
        self.assertEqual(reason, "ADVERT_OR_ESCROW_SPAM")

    def test_both_signal_patterns_fire_on_the_measured_body(self):
        self.assertIsNotNone(CRYPTO_WALLET.search(FARM_BODY))
        self.assertIsNotNone(ESCROW_ADVERT.search(FARM_TITLE + "\n" + FARM_BODY))


class EscrowAdvertPrecisionTests(unittest.TestCase):
    def test_genuinely_funded_defects_are_not_refused(self):
        """The two real funded issues carry no wallet, so the new gate never sees them.

        Expensify/App pays on a title-borne amount attested by its own automation, so the
        fixture supplies that attestation the way the live issue does.
        """
        for title, body in GENUINE:
            with self.subTest(title=title[:40]):
                verdict, reason = admit(context(title, body, [attestation()]))
                self.assertIsNotNone(verdict, reason)
                self.assertNotEqual(reason, "ADVERT_OR_ESCROW_SPAM")

    def test_a_project_publishing_a_donation_address_is_not_refused(self):
        """A wallet alone is ordinary; only the escrow advert makes it a refusal."""
        verdict, reason = admit(context(
            "[$300] Fix pagination off-by-one in the exporter",
            "The exporter skips the last row. See src/export/paginate.py.\n\n"
            "Donations to the project: bc1qt3rukpe7qp737zj5j5xpxxmcqv90cfefhg5e00",
            [attestation()]))
        self.assertIsNotNone(verdict, reason)

    def test_escrow_wording_alone_is_not_refused(self):
        """Escrow vocabulary without a claimable wallet stays admissible."""
        verdict, reason = admit(context(
            "[$400] Settlement worker drops the escrow release callback",
            "The escrow release callback is dropped when the worker restarts. See "
            "src/settlement/worker.py and the retry queue in src/settlement/queue.py.",
            [attestation()]))
        self.assertIsNotNone(verdict, reason)


if __name__ == "__main__":
    unittest.main()
