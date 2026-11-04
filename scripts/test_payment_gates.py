"""No missing/malformed/non-finite funding can authorize dispatch or publication."""
import os
import unittest
from unittest.mock import patch

from payment_gates import require_paid_offer
from pipeline_evidence import bind_proof
from test_pipeline_repairs import Store, Transport, context
import actions_dispatch


class PaidOfferFacts(unittest.TestCase):
    def test_unknown_and_nonfinite_values_refuse_before_reservation_or_post(self):
        for value in (None, '', 'NaN', 'sNaN', 'Infinity', '-Infinity', 'bad', '0', '-1', True):
            with self.subTest(value=value), patch.dict(os.environ, {'ALLOW_UNPRICED_FOUNDER': 'false'}):
                api, store, ctx = Transport(), Store(), context()
                proof = bind_proof({'funding': {'usd_value': value}}, ctx)
                with self.assertRaisesRegex(ValueError, 'Paid offer'):
                    actions_dispatch.dispatch(api, store, ctx, proof, ['normal'],
                        sovereign_admission=True, competition={'blocking': False})
                self.assertEqual(api.posts, [])
                self.assertEqual(store.rows, {})

    def test_valid_usd_and_converted_foreign_offers(self):
        for funding in ({'usd_value': '250'}, {'amount': '250', 'currency': 'USD'},
                        {'amount': '1', 'currency': 'ETH', 'usd_value': '2500'}):
            with self.subTest(funding=funding):
                require_paid_offer({'funding': funding})

    def test_missing_foreign_conversion_is_not_zero_or_authorization(self):
        with self.assertRaises(ValueError):
            require_paid_offer({'funding': {'amount': '1', 'currency': 'ETH'}})

    def test_founder_exception_does_not_allow_arbitrary_invalid_paid_claims(self):
        with patch.dict(os.environ, {'ALLOW_UNPRICED_FOUNDER': 'true'}):
            require_paid_offer({'funding': {'currency': 'FOUNDER'}, 'funding_status': 'UNPRICED_OWNER_REQUEST'})
            with self.assertRaises(ValueError):
                require_paid_offer({'funding': {'usd_value': 'NaN'}})
        with patch.dict(os.environ, {'ALLOW_UNPRICED_FOUNDER': 'false'}):
            with self.assertRaisesRegex(ValueError, 'No Free Service'):
                require_paid_offer({'funding': {'currency': 'FOUNDER', 'usd_value': '250'}})


if __name__ == '__main__':
    unittest.main(verbosity=2)
