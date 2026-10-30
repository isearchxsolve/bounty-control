"""NVIDIA NIM brain for the Cline engineering agent, with key rotation.

Measured before writing this (2026-10-30):

- nvidia/nemotron-3.5-super-vl-120b-a12b returns valid Cline-style tool calls in ~1.5 s.
- nvidia/nemotron-3-ultra-550b-a55b also does, but at ~14 s per call, which is unusable for the
  hundreds of calls one engineering task makes.
- Of the distinct keys available locally, 11 were live and 2 answered HTTP 403.

Rotation is the whole reliability story here: Baba's instruction is one brain and no model
fallback, so a throttle or a revoked key must be survived by moving to the next key, not by
quietly answering from a different model. When every key is dead the call fails loudly, because
an engine that silently changes brain cannot be measured.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Callable, List, Optional, Tuple

NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("NVIDIA_ROUTER_MODEL", "deepseek-ai/deepseek-v4.1-flash")
KEYS_ENV = "NVIDIA_KEYS_JSON"
SINGLE_KEY_ENV = "NVIDIA_API_KEY"

READY, LEASED, COOLDOWN, DISABLED = "ready", "leased", "cooldown", "disabled"


def _log(line: str) -> None:
    print(line, flush=True)


def load_keys() -> List[str]:
    """Keys from NVIDIA_KEYS_JSON (list or {"keys": [...]}), else NVIDIA_API_KEY, else a file."""
    raw = os.environ.get(KEYS_ENV, "").strip().lstrip("\ufeff")
    if raw:
        document = json.loads(raw)
        values = document.get("keys", []) if isinstance(document, dict) else document
        if not isinstance(values, list):
            raise ValueError(f"{KEYS_ENV} must be a JSON key list or {{\"keys\": [...]}}.")
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]
    single = os.environ.get(SINGLE_KEY_ENV, "").strip()
    if single:
        return [single]
    path = os.environ.get("NVIDIA_KEYS_FILE", "").strip()
    if path:
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        values = document.get("keys", []) if isinstance(document, dict) else document
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]
    return []


class _Slot:
    __slots__ = ("secret", "state", "dead_reason", "cooldown_until", "uses")

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.state = READY
        self.dead_reason: Optional[str] = None
        self.cooldown_until = 0.0
        self.uses = 0


class NvidiaRouter:
    """Rotates NVIDIA keys on throttling and revokes dead ones for the life of the process."""

    def __init__(self, keys: Optional[List[str]] = None, model: str = DEFAULT_MODEL,
                 transport: Optional[Callable[[str, dict, int], Tuple[int, object]]] = None,
                 clock: Callable[[], float] = time.time,
                 cooldown_seconds: float = 20.0) -> None:
        self.model = model
        self._clock = clock
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._lock = threading.RLock()
        self._cursor = 0
        self._transport = transport or self._http_transport
        self._slots = [_Slot(k) for k in (keys if keys is not None else load_keys())]

    # ---------------------------------------------------------------- transport
    @staticmethod
    def _http_transport(api_key: str, payload: dict, timeout: int) -> Tuple[int, object]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            NIM_URL, data=body,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                detail = ""
            return exc.code, detail
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------ leasing
    def _lease(self) -> Optional[Tuple[int, _Slot]]:
        with self._lock:
            now = self._clock()
            total = len(self._slots)
            for offset in range(total):
                index = (self._cursor + offset) % total
                slot = self._slots[index]
                if slot.state == DISABLED:
                    continue
                if slot.state == COOLDOWN and slot.cooldown_until > now:
                    continue
                if slot.state == COOLDOWN:
                    slot.state = READY
                slot.state = LEASED
                self._cursor = (index + 1) % total
                return index, slot
            return None

    def _retire(self, slot: _Slot, reason: str) -> None:
        with self._lock:
            slot.state = DISABLED
            slot.dead_reason = reason

    def _cool(self, slot: _Slot) -> None:
        with self._lock:
            slot.state = COOLDOWN
            slot.cooldown_until = self._clock() + self._cooldown

    def _release(self, slot: _Slot) -> None:
        with self._lock:
            if slot.state == LEASED:
                slot.state = READY

    # ------------------------------------------------------------------ calling
    def chat_completion(self, payload: dict, timeout: int = 600,
                        max_attempts: Optional[int] = None):
        """Return (ok, completion, model, error), rotating keys. No model fallback by design."""
        if not isinstance(payload, dict) or not payload.get("messages"):
            return False, {}, self.model, "Cline request requires a non-empty message history."
        if not self._slots:
            return False, {}, self.model, (
                f"No NVIDIA key configured ({KEYS_ENV} or {SINGLE_KEY_ENV}); "
                "the engineering agent cannot start without its brain.")

        forwarded = dict(payload)
        forwarded["model"] = self.model
        forwarded["stream"] = False
        forwarded.pop("stream_options", None)

        budget = max_attempts if max_attempts is not None else len(self._slots)
        attempts = 0
        last_error = "No NVIDIA key is currently ready."
        while attempts < budget:
            leased = self._lease()
            if leased is None:
                return False, {}, self.model, last_error
            index, slot = leased
            attempts += 1
            request_id = uuid.uuid4().hex[:10]
            started = time.monotonic()
            _log(f"NIM_REQUEST START id={request_id} attempt={attempts} "
                 f"key_slot={index} model={self.model} tools={len(payload.get('tools') or [])}")
            status, body = self._transport(slot.secret, forwarded, timeout)
            elapsed = time.monotonic() - started

            if status == 200 and isinstance(body, dict):
                choices = body.get("choices")
                if isinstance(choices, list) and choices:
                    slot.uses += 1
                    self._release(slot)
                    _log(f"NIM_REQUEST END id={request_id} result=OK key_slot={index} "
                         f"elapsed={elapsed:.1f}s")
                    return True, body, self.model, ""

            if status in (401, 403):
                # Revoked or unauthorised: this key will never work. Retire it, not the brain.
                self._retire(slot, f"HTTP {status}")
                last_error = f"key slot {index} rejected (HTTP {status})"
                _log(f"NIM_REQUEST END id={request_id} result=KEY_RETIRED key_slot={index} "
                     f"status={status} elapsed={elapsed:.1f}s")
                continue
            if status == 429 or (isinstance(status, int) and 500 <= status < 600) or status == 0:
                # Throttled or transient: park this key briefly and try the next one.
                self._cool(slot)
                last_error = f"key slot {index} unavailable (HTTP {status or 'network'})"
                _log(f"NIM_REQUEST END id={request_id} result=ROTATE key_slot={index} "
                     f"status={status or 'network'} elapsed={elapsed:.1f}s")
                continue

            self._release(slot)
            detail = body if isinstance(body, str) else json.dumps(body)[:200]
            last_error = f"NVIDIA returned HTTP {status}: {detail[:200]}"
            _log(f"NIM_REQUEST END id={request_id} result=BAD_RESPONSE key_slot={index} "
                 f"status={status} elapsed={elapsed:.1f}s")
            break

        return False, {}, self.model, (
            f"Every NVIDIA key failed after {attempts} attempt(s); last: {last_error}")

    # ------------------------------------------------------------------- status
    def status(self) -> dict:
        with self._lock:
            states = {READY: 0, LEASED: 0, COOLDOWN: 0, DISABLED: 0}
            for slot in self._slots:
                states[slot.state] += 1
            return {"provider": "nvidia-nim", "model": self.model, "total_keys": len(self._slots),
                    "states": states,
                    "dead_keys": [{"key_index": i, "reason": s.dead_reason}
                                  for i, s in enumerate(self._slots) if s.state == DISABLED]}
