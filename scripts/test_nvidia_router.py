"""Key rotation for the engineering agent's brain. No network: transport is injected.

Each test pins a behaviour that a live run measured or that would waste a claim if wrong.
"""

import json
import os
import unittest
from unittest.mock import patch

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


class ParachuteModelContract(unittest.TestCase):
    """The parachute must be aimed at a brain NVIDIA actually serves.

    Measured live 2026-11-02 (discovery runs 41417432357 and 41420103753): TokenHarbor was
    exhausted, either round's failover answered from a router built with this module's default
    model, and that default was the TokenHarbor model name -- which NVIDIA's endpoint does not
    serve. Both rounds died with "No Token Harbor key is currently ready" before writing a
    single row, so the door produced nothing at all for two consecutive pulses.

    This module's own header records the measurement that contradicts the old default: Nemotron
    3.5 Super VL returns valid Cline-style tool calls in ~1.5s, and Nemotron-3-Ultra at ~14s is
    unusable for the hundreds of calls one engineering task makes.
    """

    def test_the_default_model_is_a_nemotron_model(self):
        self.assertTrue(nr.DEFAULT_MODEL.startswith("nvidia/nemotron"),
                        f"the parachute's default brain must be Nemotron, got {nr.DEFAULT_MODEL!r}")

    def test_the_default_model_is_not_the_primary_brain(self):
        import kaggle_engine_worker as worker
        primary = worker.CLINE_MODEL if hasattr(worker, "CLINE_MODEL") else None
        if primary:
            self.assertNotEqual(nr.DEFAULT_MODEL, primary)
        # The name NVIDIA does not serve is the one that used to be the default here.
        self.assertNotIn("deepseek-ai/", nr.DEFAULT_MODEL)

    def test_a_router_built_with_no_model_answers_as_the_measured_brain(self):
        router = nr.NvidiaRouter(keys=["k1"], model=nr.DEFAULT_MODEL)
        self.assertEqual(router.model, nr.DEFAULT_MODEL)

    def test_the_measured_brain_agrees_with_the_workers_failover_constant(self):
        """One variable, one meaning: the failover and this module must not disagree."""
        import kaggle_engine_worker as worker
        self.assertEqual(worker.nvidia_delivery_model(), nr.DEFAULT_MODEL)


class LiveCooldownRegression(unittest.TestCase):
    def test_a_throttled_pool_can_report_and_leave_cooldown(self):
        now = [100.0]
        router = nr.NvidiaRouter(keys=['test'], clock=lambda: now[0], cooldown_seconds=20,
                                 transport=FakeTransport([(429, 'limited'), (200, ok_body())]))
        payload = {'messages': [{'role': 'user', 'content': 'test'}]}
        self.assertFalse(router.chat_completion(payload)[0])
        self.assertEqual(router.seconds_until_ready_key(), 20)
        now[0] += 20
        self.assertEqual(router.seconds_until_ready_key(), 0)
        self.assertTrue(router.chat_completion(payload)[0])

    def test_dead_primary_does_not_prevent_fallback_cooldown_recovery(self):
        from unittest.mock import patch
        import kaggle_engine_worker as worker
        now = [100.0]
        payload = {'messages': [{'role': 'user', 'content': 'test'}]}
        primary = worker.TokenHarborRouter(keys=['test-primary'], clock=lambda: now[0],
            transport=lambda *args: (401, {}, {'error': {'message': 'revoked'}}))
        primary.chat_completion(payload)
        fallback = nr.NvidiaRouter(keys=['test-fallback'], clock=lambda: now[0], cooldown_seconds=20,
            transport=FakeTransport([(429, 'limited'), (200, ok_body())]))
        def advance(seconds):
            now[0] += seconds
        with patch.object(worker, '_get_default_router', return_value=primary), patch.object(worker.time, 'sleep', side_effect=advance):
            outcome = worker.gateway_failover(payload, 'No Token Harbor key is currently ready.', router=fallback)
        self.assertTrue(outcome[0], outcome)


class KeyPool(unittest.TestCase):
    """The parachute's pool is the pool the secret actually publishes, not one key.

    Measured live 2026-11-02 (delivery engine, run 41543384839): production wires only
    NVIDIA_API_KEY, so load_keys() returned one slot, the budget became one attempt, and
    every turn died on "Every NVIDIA key failed after 1 attempt(s)" while 10 other keys
    sat unused. A 429 is one account's cooldown, so a pool of 11 has 11 cooldowns to spend.
    """

    def test_a_json_list_published_as_one_secret_is_the_whole_pool(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": json.dumps(["k1", "k2", "k3"]), "NVIDIA_KEYS_JSON": ""}):
            self.assertEqual(nr.load_keys(), ["k1", "k2", "k3"])

    def test_a_keys_document_published_as_one_secret_is_the_whole_pool(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": json.dumps({"keys": ["k1", "k2"]}), "NVIDIA_KEYS_JSON": ""}):
            self.assertEqual(nr.load_keys(), ["k1", "k2"])

    def test_separated_keys_published_as_one_secret_are_the_whole_pool(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "k1\nk2\n\nk3  ", "NVIDIA_KEYS_JSON": ""}):
            self.assertEqual(nr.load_keys(), ["k1", "k2", "k3"])
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "k1,k2,k3", "NVIDIA_KEYS_JSON": ""}):
            self.assertEqual(nr.load_keys(), ["k1", "k2", "k3"])

    def test_a_single_plain_key_is_still_one_key(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-abc", "NVIDIA_KEYS_JSON": ""}):
            self.assertEqual(nr.load_keys(), ["nvapi-abc"])

    def test_a_pool_in_nvidia_keys_json_still_wins(self):
        with patch.dict(os.environ, {"NVIDIA_KEYS_JSON": json.dumps(["a", "b"]),
                                     "NVIDIA_API_KEY": "single"}):
            self.assertEqual(nr.load_keys(), ["a", "b"])

    def test_eleven_keys_budget_eleven_attempts(self):
        """The budget that made the failure message read 'after 1 attempt(s)'."""
        keys = [f"k{i}" for i in range(11)]
        transport = FakeTransport([(429, "limited")] * len(keys))
        router = nr.NvidiaRouter(keys=keys, transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertFalse(succeeded)
        self.assertEqual(len(set(transport.tried)), 11, "a key was tried twice in one call")
        self.assertIn("after 11 attempt(s)", error, "the pool was not rotated through")

    def test_a_fleet_of_keys_is_used_when_one_secret_publishes_it(self):
        keys = nr._pool_from(json.dumps([f"k{i}" for i in range(11)]), "NVIDIA_API_KEY")
        self.assertEqual(len(keys), 11)
        transport = FakeTransport([(429, "limited")] * 10 + [(200, ok_body("twelfth account"))])
        router = nr.NvidiaRouter(keys=keys, transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(succeeded, error)
        self.assertEqual(len(set(transport.tried)), 11)

    def test_a_pool_survives_one_throttled_key_without_failing_the_call(self):
        keys = [f"k{i}" for i in range(11)]
        transport = FakeTransport([(429, "limited"), (200, ok_body("second brain"))])
        router = nr.NvidiaRouter(keys=keys, transport=transport)
        succeeded, _, _, error = router.chat_completion({"messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(succeeded, error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
