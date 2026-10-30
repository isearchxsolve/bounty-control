"""Thread-safe Token Harbor router for DeepSeek Flash.

Secrets remain in the local vault.  This module never logs or exposes API keys.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, List, Optional, Tuple
from urllib import error, request


TOKEN_HARBOR_URL = "https://tokenharbor.ai/v1/chat/completions"
DEEPSEEK_FLASH_MODEL = "deepseek-v4.1-flash:free"
DEFAULT_KEY_FILE = r"D:\anonym\vault\tokenharbor_keys.json"
DEFAULT_TIMEOUT_SECONDS = 120
TOKEN_HARBOR_KEYS_ENV = "TOKENHARBOR_KEYS_JSON"

READY = "READY"
LEASED = "LEASED"
COOLDOWN = "COOLDOWN"
DISABLED = "DISABLED"


@dataclass
class _KeySlot:
    secret: str
    state: str = READY
    cooldown_until: float = 0.0
    rate_limit_count: int = 0


Transport = Callable[[str, dict, int], Tuple[int, Dict[str, str], object]]


class TokenHarborRouter:
    """Leases one key at a time and fails over without revealing credentials."""

    def __init__(
        self,
        keys: Optional[List[str]] = None,
        key_file: str = DEFAULT_KEY_FILE,
        transport: Optional[Transport] = None,
        clock: Callable[[], float] = time.time,
        jitter: Optional[Callable[[], float]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self._jitter = jitter or random.random
        self._transport = transport or self._http_transport
        self._cursor = 0
        self._slots = [_KeySlot(secret=key) for key in (keys or self._load_keys(key_file)) if key]

    @staticmethod
    def _load_keys(key_file: str) -> List[str]:
        # Kaggle workers receive their own encrypted secret at runtime.  The
        # laptop's vault remains local and is never copied into a kernel or a
        # queue payload.  Missing or malformed credentials deliberately fail
        # closed when the router is first used.
        raw_env = os.environ.get(TOKEN_HARBOR_KEYS_ENV, "").strip().lstrip("\ufeff")
        if raw_env:
            try:
                document = json.loads(raw_env)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{TOKEN_HARBOR_KEYS_ENV} must contain a JSON key list.") from exc
        else:
            document = None
            try:
                from kaggle_secrets import UserSecretsClient  # type: ignore
                raw_secret = UserSecretsClient().get_secret(TOKEN_HARBOR_KEYS_ENV)
                if raw_secret:
                    document = json.loads(raw_secret.strip().lstrip("\ufeff"))
            except Exception:
                # A local process has no Kaggle secret provider; use its vault.
                document = None
            if document is None:
                with open(key_file, "r", encoding="utf-8-sig") as handle:
                    document = json.load(handle)
        if isinstance(document, list):
            values = document
        elif isinstance(document, dict):
            values = document.get("keys", document.get("value", []))
        else:
            raise ValueError("Token Harbor key file must contain a key list.")
        if not isinstance(values, list) or not all(isinstance(key, str) for key in values):
            raise ValueError("Token Harbor key file contains invalid key entries.")
        return values

    @staticmethod
    def _http_transport(api_key: str, payload: dict, timeout: int) -> Tuple[int, Dict[str, str], object]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            TOKEN_HARBOR_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, dict(response.headers.items()), json.loads(raw)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload_data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload_data = {"error": raw}
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, payload_data

    def _refresh_cooldowns_locked(self) -> None:
        now = self._clock()
        for slot in self._slots:
            if slot.state == COOLDOWN and now >= slot.cooldown_until:
                slot.state = READY
                slot.cooldown_until = 0.0

    def _lease_key(self) -> Optional[Tuple[int, _KeySlot]]:
        with self._lock:
            self._refresh_cooldowns_locked()
            if not self._slots:
                return None
            for offset in range(len(self._slots)):
                index = (self._cursor + offset) % len(self._slots)
                slot = self._slots[index]
                if slot.state == READY:
                    slot.state = LEASED
                    self._cursor = (index + 1) % len(self._slots)
                    return index, slot
        return None

    def _release_ready(self, slot: _KeySlot) -> None:
        with self._lock:
            if slot.state == LEASED:
                slot.state = READY

    def _disable(self, slot: _KeySlot) -> None:
        with self._lock:
            slot.state = DISABLED
            slot.cooldown_until = 0.0

    @staticmethod
    def _retry_after_seconds(headers: Dict[str, str]) -> Optional[float]:
        retry_after = next((value for key, value in headers.items() if key.lower() == "retry-after"), None)
        if not retry_after:
            return None
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (TypeError, ValueError, IndexError):
                return None

    def _cool_down(self, slot: _KeySlot, headers: Dict[str, str]) -> None:
        with self._lock:
            slot.rate_limit_count += 1
            retry_after = self._retry_after_seconds(headers)
            if retry_after is None:
                # 2, 4, 8 ... seconds with sub-second jitter, bounded at five minutes.
                retry_after = min(300.0, float(2 ** min(slot.rate_limit_count, 8))) + (self._jitter() * 0.5)
            slot.cooldown_until = self._clock() + retry_after
            slot.state = COOLDOWN

    @staticmethod
    def _extract_text(payload: object) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return text.strip() if isinstance(text, str) and text.strip() else None

    @staticmethod
    def _error_text(payload: object, fallback: str) -> str:
        if isinstance(payload, dict):
            problem = payload.get("error")
            if isinstance(problem, dict):
                return str(problem.get("message") or fallback)
            if problem:
                return str(problem)
        return fallback

    def call(self, prompt: str, system_prompt: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Tuple[bool, str, str, Optional[str]]:
        if not isinstance(prompt, str) or not prompt.strip():
            return False, "", DEEPSEEK_FLASH_MODEL, "Prompt must be a non-empty string."
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            return False, "", DEEPSEEK_FLASH_MODEL, "Timeout must be a positive number of seconds."
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": DEEPSEEK_FLASH_MODEL, "messages": messages}
        network_attempts = 0
        last_error = "No Token Harbor key is currently ready."

        while True:
            leased = self._lease_key()
            if leased is None:
                return False, "", DEEPSEEK_FLASH_MODEL, last_error
            _, slot = leased
            try:
                status, headers, response_payload = self._transport(slot.secret, payload, timeout)
            except (error.URLError, TimeoutError, OSError) as exc:
                self._release_ready(slot)
                network_attempts += 1
                last_error = (
                    f"Token Harbor transient network failure after {timeout}s "
                    f"(fallback attempt {network_attempts}): {exc}"
                )
                if network_attempts >= 2:
                    return False, "", DEEPSEEK_FLASH_MODEL, last_error
                continue
            except Exception as exc:  # Transport adapters must not strand a lease.
                self._release_ready(slot)
                return False, "", DEEPSEEK_FLASH_MODEL, f"Token Harbor transport failure: {exc}"

            headers = headers or {}
            if 200 <= status < 300:
                self._release_ready(slot)
                text = self._extract_text(response_payload)
                if text:
                    return True, text, DEEPSEEK_FLASH_MODEL, None
                return False, "", DEEPSEEK_FLASH_MODEL, "Token Harbor returned no chat completion text."
            if status == 429:
                self._cool_down(slot, headers)
                last_error = self._error_text(response_payload, "Token Harbor rate limited the request.")
                continue
            if status in (401, 403):
                self._disable(slot)
                print(f"[TOKENHARBOR ALERT] Disabled one API key after HTTP {status}; attempting ready fallback.")
                last_error = self._error_text(response_payload, "Token Harbor rejected an API key.")
                continue
            if 500 <= status < 600:
                self._release_ready(slot)
                network_attempts += 1
                last_error = self._error_text(response_payload, f"Token Harbor server error ({status}).")
                if network_attempts >= 2:
                    return False, "", DEEPSEEK_FLASH_MODEL, last_error
                continue
            self._release_ready(slot)
            return False, "", DEEPSEEK_FLASH_MODEL, self._error_text(response_payload, f"Token Harbor request failed ({status}).")

    def status(self) -> dict:
        with self._lock:
            self._refresh_cooldowns_locked()
            counts = {READY: 0, LEASED: 0, COOLDOWN: 0, DISABLED: 0}
            now = self._clock()
            cooldowns = []
            for index, slot in enumerate(self._slots):
                counts[slot.state] += 1
                if slot.state == COOLDOWN:
                    cooldowns.append({"key_index": index, "remaining_seconds": max(0.0, round(slot.cooldown_until - now, 3))})
            return {"model": DEEPSEEK_FLASH_MODEL, "total_keys": len(self._slots), "states": counts, "cooldowns": cooldowns}


_default_router: Optional[TokenHarborRouter] = None
_default_router_lock = threading.Lock()


def _get_default_router() -> TokenHarborRouter:
    global _default_router
    with _default_router_lock:
        if _default_router is None:
            _default_router = TokenHarborRouter()
        return _default_router


def call_deepseek_flash(prompt: str, system_prompt: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Tuple[bool, str, Optional[str]]:
    """Call DeepSeek Flash and report unavailable credentials as a closed failure."""
    try:
        success, response_text, _, error_message = _get_default_router().call(prompt, system_prompt, timeout)
        return success, response_text, error_message
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, "", f"Token Harbor router unavailable: {exc}"


def get_router_status() -> dict:
    """Return aggregate router state without exposing any API keys."""
    try:
        return _get_default_router().status()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"model": DEEPSEEK_FLASH_MODEL, "total_keys": 0, "states": {}, "error": str(exc)}
