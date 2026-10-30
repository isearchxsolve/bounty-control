"""Key rotation for the engineering agent's brain. No network: transport is injected.

Each test pins a behaviour that a live run measured or that would waste a claim if wrong.
"""

import unittest

import nvidia_router as nr

MODEL = nr.DEFAULT_MODEL


def ok_body(text="ok"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class FakeTransport:
    """Answers per key, recording which keys were tried, in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.tried = []

    def __call__(self, secret, payload, timeout):
        self.tried.append(secret)
        if not self.responses:
            return 200, ok_body()
        return self.responses.pop(0)


class Rotation(unittest.TestCase):
    def test_a_revoked_key_is_retired_and_the_next_key_answers(self):
        transport = FakeTransport([(403, "forbidden"), (200, ok_body("answered"))])
        router = nr.NvidiaRouter(keys=["k1", "k2"], transport=transport)
        succeeded, completion, model, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(succeeded, error)
        self.assertEqual(model, MODEL)
        self.assertEqual(transport.tried, ["k1", "k2"])
        self.assertEqual(router.status()["states"][nr.DISABLED], 1)
        self.assertEqual(router.status()["dead_keys"][0]["reason"], "HTTP 403")

    def test_a_throttled_key_rotates_without_being_retired(self):
        transport = FakeTransport([(429, "slow down"), (200, ok_body())])
        router = nr.NvidiaRouter(keys=["k1", "k2"], transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(succeeded, error)
        status = router.status()
        self.assertEqual(status["states"][nr.DISABLED], 0, "a throttle must not kill a key")
        self.assertEqual(status["states"][nr.COOLDOWN], 1)

    def test_a_network_error_rotates(self):
        transport = FakeTransport([(0, "URLError: timed out"), (200, ok_body())])
        router = nr.NvidiaRouter(keys=["k1", "k2"], transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(succeeded, error)

    def test_rotation_wraps_to_the_first_healthy_key(self):
        transport = FakeTransport([(200, ok_body())] * 3)
        router = nr.NvidiaRouter(keys=["k1", "k2"], transport=transport)
        for _ in range(3):
            self.assertTrue(router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})[0])
        self.assertEqual(transport.tried, ["k1", "k2", "k1"], "keys must be used in turn")


class NoModelFallback(unittest.TestCase):
    """Baba's instruction: one brain. Exhaustion must fail loudly, never answer from elsewhere."""

    def test_every_key_dead_fails_with_a_named_reason(self):
        transport = FakeTransport([(403, "forbidden"), (403, "forbidden")])
        router = nr.NvidiaRouter(keys=["k1", "k2"], transport=transport)
        succeeded, completion, model, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertFalse(succeeded)
        self.assertEqual(completion, {})
        self.assertIn("Every NVIDIA key failed", error)
        self.assertNotIn("deepseek", error.lower())

    def test_exhaustion_does_not_call_a_different_provider(self):
        transport = FakeTransport([(403, "forbidden")])
        router = nr.NvidiaRouter(keys=["k1"], transport=transport)
        router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(len(transport.tried), 1, "no second provider may be reached")

    def test_no_configured_key_fails_before_any_request(self):
        transport = FakeTransport([])
        router = nr.NvidiaRouter(keys=[], transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertFalse(succeeded)
        self.assertIn("No NVIDIA key configured", error)
        self.assertEqual(transport.tried, [])


class RequestShape(unittest.TestCase):
    def test_the_model_is_forced_to_the_configured_brain(self):
        captured = {}

        def transport(secret, payload, timeout):
            captured.update(payload)
            return 200, ok_body()

        router = nr.NvidiaRouter(keys=["k1"], model=MODEL, transport=transport)
        router.chat_completion({"messages": [{"role": "user", "content": "hi"}],
                                "model": "something-else", "stream": True})
        self.assertEqual(captured["model"], MODEL)
        self.assertFalse(captured["stream"], "the gateway answers streaming itself")

    def test_an_empty_history_is_refused(self):
        router = nr.NvidiaRouter(keys=["k1"], transport=FakeTransport([]))
        self.assertFalse(router.chat_completion({"messages": []})[0])

    def test_a_200_without_choices_is_not_success(self):
        router = nr.NvidiaRouter(keys=["k1"], transport=FakeTransport([(200, {"object": "empty"})]))
        succeeded, completion, _, _ = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertFalse(succeeded)
        self.assertEqual(completion, {})


class KeyLoading(unittest.TestCase):
    def test_keys_come_from_the_json_list_and_blank_entries_are_dropped(self):
        import os
        saved = os.environ.get(nr.KEYS_ENV)
        os.environ[nr.KEYS_ENV] = '["k1", "", "  ", "k2"]'
        try:
            self.assertEqual(nr.load_keys(), ["k1", "k2"])
        finally:
            if saved is None:
                os.environ.pop(nr.KEYS_ENV, None)
            else:
                os.environ[nr.KEYS_ENV] = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
