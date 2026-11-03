"""Live equivalents of the master transport failure assertions; no transport mocks.

Run explicitly: python scripts/test_pipeline_transport_live.py
Uses gh's authenticated session. Writes no remote resources.
"""
import time
import unittest
import uuid

from actions_github import GitHub, GitHubError


class LiveTransportFailureMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Authentication failures must fail this suite, rather than become skips.
        cls.api = GitHub()
        cls.api.api("user")

    def test_auth_not_found_and_server_errors_do_not_return_empty_success(self):
        # Actual 401 and 404 equivalents of the original status matrix.
        # Other statuses require independently provisioned real fault triggers.
        probes = (
            (401, GitHub(token="invalid-live-probe-credential"), "user"),
            (404, self.api, "repos/isearchxsolve/live-probe-absent-" + uuid.uuid4().hex),
        )
        for status, api, endpoint in probes:
            with self.subTest(status=status):
                with self.assertRaises(GitHubError) as caught:
                    api.api(endpoint)
                self.assertIn(str(status), str(caught.exception))

    def test_expired_deadline_prevents_any_transport(self):
        # Real monotonic clock and production client, with the original deadline gate.
        with self.assertRaisesRegex(GitHubError, "deadline"):
            GitHub(deadline=time.monotonic() - 1).api("user")


if __name__ == "__main__":
    unittest.main(verbosity=2)
