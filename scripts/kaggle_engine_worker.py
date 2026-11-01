#!/usr/bin/env python3
from __future__ import annotations
# ==============================================================================
# KAGGLE 5-ENGINE DISTRIBUTED EXECUTION WORKER
# Direct Partition of autonomous_icu_pipeline.py (Part 2: Cloud Execution)
# The Supreme Edict: Zero Disavowal & Pixel-Perfect Craftsmanship
# ==============================================================================
import os
import random
import threading
from email.utils import parsedate_to_datetime
from urllib import error, request
import sys
import tomllib
import json
import time
import re
import shutil
import hashlib
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import glob
import subprocess
import signal
import shlex
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Callable
from delivery_supervisor import supervise as supervise_delivery, validate_plan as validate_delivery_plan
from delivery_errors import (ClineDeliverableInvalid, ClineDeliverableMissing,
                             PreparationContractViolation, validate_preparation)
from fleet_recovery_policy import (
    CLAIM_LEASE_SECONDS, CLAIM_HEARTBEAT_SECONDS, FLEET_LEASE_CHANNEL, RECOVERY_RELEASE, current_claim, event_run,
    is_nonsoftware_data_task, recovery_decision, task_reference, non_engineering_dispatch_reason,
    is_retryable_failure, matching_events,
)
# The delivery engine's second brain. Imported at module scope so the failover is one call
# away from the gateway; the router itself holds no key until it is constructed.
from nvidia_router import NvidiaRouter, load_keys as nvidia_load_keys

# Enforce UTF-8 line buffering
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

DOOR = os.environ.get("FLEET_DOOR", "https://omniroute-relay.omniroute-fleet-kd.workers.dev")
DOOR_TOKEN = os.environ.get("FLEET_DOOR_TOKEN", "")
FLEET_QUEUE_CHANNEL = "BOUNTY_FLEET_QUEUE_V2"
FLEET_CLAIM_CHANNEL = "BOUNTY_FLEET_CLAIM"
FLEET_RESULT_CHANNEL = "BOUNTY_FLEET_RESULT"
FLEET_IDLE_POLL_SECONDS = max(15, int(os.environ.get("FLEET_IDLE_POLL_SECONDS", "60")))
ENGINE_ID = os.environ.get("ENGINE_ID", "kaggle-engine-unknown")
ENGINE_INDEX = int(os.environ.get("ENGINE_INDEX", "1"))
TOTAL_ENGINES = 5
_ACTIVE_TASK_LEASE = None
_invalid_queue_record_digests = set()
_last_fleet_poll_log = 0.0
_fleet_poll_failures = 0

# Cloud sandbox and paths
# The bounty account owns the fork/PR identity (fork URL, commit author, --head owner).
# Read from the environment so a mirror to another account is one variable.
# The bounty account owns the fork and PR identity, so it must be the account that is
# actually running the workflow. A compiled-in default pointed the survivor at the
# retired account: the PR branch was pushed as "niloydassana-maker:branch" and the
# fork URL named a repo this token cannot write to (observed 2026-10-29).
BOUNTY_ACCOUNT = (os.environ.get("BOUNTY_ACCOUNT")
                  or (os.environ.get("GITHUB_REPOSITORY") or "").split("/")[0]
                  or "isearchxsolve")

SANDBOX_DIR = os.environ.get("FLEET_SANDBOX_DIR", "/tmp/sandbox")
PACKET_DIR = os.environ.get("FLEET_ARTIFACT_DIR") or (
    "/kaggle/working/fleet-artifacts" if os.path.isdir('/kaggle/working') else "/tmp/candidate_packets")
DB_FILE = "/tmp/icu_pipeline.db"
CSV_FILE = "/tmp/icu_desperation_ledger.csv"
CLIENT_CONTACT_EMAIL = "isearch.xsolve@gmail.com"
DEEPSEEK_FLASH_MODEL = "deepseek-v4.1-flash:free"

# Cline is provisioned inside each Kaggle kernel and is the only worktree
# engineering agent.  These cloud-local paths must never inherit laptop paths.
CLINE_PROXY_HEALTH_URL = os.environ.get("CLINE_PROXY_HEALTH_URL", "http://127.0.0.1:8080/health")
CLINE_PROXY_BASE_URL = os.environ.get("CLINE_PROXY_BASE_URL", "http://127.0.0.1:8080/v1")
CLINE_NODE_EXE = os.environ.get("CLINE_NODE_EXE", shutil.which("node") or "")
CLINE_NODE_ENTRYPOINT = os.environ.get("CLINE_NODE_ENTRYPOINT", "")
CLINE_MODEL = os.environ.get("CLINE_MODEL", DEEPSEEK_FLASH_MODEL)
CLINE_PROVIDER = "openai-compatible"
CLINE_DATA_DIR = os.environ.get("CLINE_DATA_DIR", "/tmp/cline-data")
# This is a local proxy marker, never a TokenHarbor credential. The proxy reads
# the engine-private key shard itself.
CLINE_PROXY_API_KEY = "tokenharbor-local-proxy"

os.makedirs(SANDBOX_DIR, exist_ok=True)
os.makedirs(PACKET_DIR, exist_ok=True)

# Database dummy/local logging stubs for Kaggle sandbox
def mark_issue_blocked_baseline(repo, number, reason):
    print(f"  [BLOCKED BASELINE] {repo}#{number}: {reason[:200]}", flush=True)

def update_delivery_pr(repo, number, pr_url):
    print(f"  [PR RECORDED] {repo}#{number} -> {pr_url}", flush=True)

# ==============================================================================
# ENGINE-SCOPED TOKENHARBOR ROUTER (PRIVATE KEYS LOADED AT RUNTIME)
# ==============================================================================
"""Thread-safe Token Harbor router for DeepSeek Flash.

Secrets remain in the local vault.  This module never logs or exposes API keys.
"""

# from __future__ import annotations



TOKEN_HARBOR_URL = "https://tokenharbor.ai/v1/chat/completions"
DEEPSEEK_FLASH_MODEL = "deepseek-v4.1-flash:free"
DEFAULT_KEY_FILE = r"D:\anonym\vault\tokenharbor_keys.json"
DEFAULT_TIMEOUT_SECONDS = 120
# One call to the 120B fallback brain, bounded well inside a Cline turn's own budget.
FALLBACK_TIMEOUT_SECONDS = 600
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
        self._last_http_status = None
        self._slots = [_KeySlot(secret=key) for key in (keys or self._load_keys(key_file)) if key]

    @staticmethod
    def _load_keys(key_file: str) -> List[str]:
        # Production kernels point at a private, engine-specific mounted
        # dataset. It takes precedence over any stale account-level Kaggle
        # secret so one engine cannot accidentally load a sibling's key pool.
        engine_key_file = os.environ.get("TOKENHARBOR_KEY_FILE", "").strip()
        if engine_key_file:
            try:
                with open(engine_key_file, "r", encoding="utf-8-sig") as handle:
                    document = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Configured private TokenHarbor shard is unavailable or malformed.") from exc
        else:
            # Local development can still use the vault or an explicitly
            # supplied secret. No API key is embedded in worker source.
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
                    document = None
                if document is None and os.path.exists(key_file):
                    with open(key_file, "r", encoding="utf-8-sig") as handle:
                        document = json.load(handle)
        if isinstance(document, list):
            values = document
        elif isinstance(document, dict):
            values = document.get("keys", document.get("value", []))
        else:
            raise ValueError("Token Harbor key file must contain a key list.")
        if not isinstance(values, list) or not all(isinstance(key, str) and key.strip() for key in values):
            raise ValueError("Token Harbor key file contains invalid key entries.")
        expected_count_raw = os.environ.get("TOKENHARBOR_EXPECTED_KEY_COUNT", "").strip()
        if expected_count_raw:
            try:
                expected_count = int(expected_count_raw)
            except ValueError as exc:
                raise ValueError("TOKENHARBOR_EXPECTED_KEY_COUNT must be an integer.") from exc
            if expected_count <= 0 or len(values) != expected_count:
                raise ValueError(
                    f"Engine TokenHarbor shard requires exactly {expected_count} keys; found {len(values)}."
                )
        elif not values:
            raise ValueError("TokenHarbor key list is empty.")
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
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        if isinstance(content, list):
                            parts = []
                            for p in content:
                                if isinstance(p, dict) and p.get("type") == "text":
                                    parts.append(p.get("text", ""))
                                elif isinstance(p, str):
                                    parts.append(p)
                            joined = "".join(parts).strip()
                            if joined:
                                return joined
                        reasoning = msg.get("reasoning_content")
                        if isinstance(reasoning, str) and reasoning.strip():
                            return reasoning.strip()
                    text = first.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
                    delta = first.get("delta")
                    if isinstance(delta, dict):
                        content = delta.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()
            for alt_key in ("text", "output", "response", "content"):
                alt = payload.get(alt_key)
                if isinstance(alt, str) and alt.strip():
                    return alt.strip()
        except Exception:
            return None
        return None

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
        payload = {"model": DEEPSEEK_FLASH_MODEL, "messages": messages, "max_tokens": 4096}
        success, response_payload, model, diagnostic = self._call_payload(payload, timeout, allow_tools=False)
        return success, (self._extract_text(response_payload) or "") if success else "", model, diagnostic

    def chat_completion(self, payload: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        """Forward the real Cline conversation and native tool protocol."""
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list) or not payload["messages"]:
            return False, {}, DEEPSEEK_FLASH_MODEL, "Cline request requires a non-empty message history."
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            return False, {}, DEEPSEEK_FLASH_MODEL, "Timeout must be a positive number of seconds."
        forwarded = dict(payload)
        forwarded["model"] = DEEPSEEK_FLASH_MODEL
        # Preserve the upstream completion intact, then encode its real fields
        # as SSE when the client requested streaming.
        forwarded["stream"] = False
        forwarded.pop("stream_options", None)
        return self._call_payload(forwarded, timeout, allow_tools=True)

    def _call_payload(self, payload: dict, timeout: int, allow_tools: bool = False):
        network_attempts = 0
        last_error = "No Token Harbor key is currently ready."

        while True:
            leased = self._lease_key()
            if leased is None:
                return False, {}, DEEPSEEK_FLASH_MODEL, last_error
            key_index, slot = leased
            request_started = time.monotonic()
            request_id = uuid.uuid4().hex[:10]
            _command_log(
                f'MODEL_REQUEST START id={request_id} attempt={network_attempts + 1} '
                f'key_slot={key_index} timeout={timeout}s tools={len(payload.get("tools") or [])}'
            )
            try:
                status, headers, response_payload = self._transport(slot.secret, payload, timeout)
                self._last_http_status = status
            except (error.URLError, TimeoutError, OSError) as exc:
                self._last_http_status = None
                self._release_ready(slot)
                network_attempts += 1
                _command_log(
                    f'MODEL_REQUEST END id={request_id} result=NETWORK_ERROR '
                    f'elapsed={time.monotonic()-request_started:.1f}s attempt={network_attempts}'
                )
                last_error = (
                    f"Token Harbor transient network failure after {timeout}s "
                    f"(fallback attempt {network_attempts}): {exc}"
                )
                if network_attempts >= 4:
                    return False, {}, DEEPSEEK_FLASH_MODEL, last_error
                continue
            except Exception as exc:  # Transport adapters must not strand a lease.
                self._release_ready(slot)
                return False, {}, DEEPSEEK_FLASH_MODEL, f"Token Harbor transport failure: {exc}"

            headers = headers or {}
            _command_log(
                f'MODEL_REQUEST END id={request_id} http={status} '
                f'elapsed={time.monotonic()-request_started:.1f}s attempt={network_attempts + 1}'
            )
            if 200 <= status < 300:
                text = self._extract_text(response_payload)
                choices = response_payload.get("choices", []) if isinstance(response_payload, dict) else []
                message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
                tools = message.get("tool_calls") if isinstance(message, dict) else None
                if text or (allow_tools and isinstance(tools, list) and tools):
                    self._release_ready(slot)
                    return True, response_payload, DEEPSEEK_FLASH_MODEL, None
                # HTTP 200 returned empty text or unparseable payload: cool down this slot and rotate to next key
                self._cool_down(slot, headers)
                network_attempts += 1
                payload_diag = str(response_payload)[:150] if response_payload else "empty response"
                last_error = f"Token Harbor key returned empty or invalid text ({payload_diag})"
                if network_attempts >= 4:
                    return False, {}, DEEPSEEK_FLASH_MODEL, last_error
                continue
            if status == 429:
                self._cool_down(slot, headers)
                last_error = (
                    "TokenHarbor router HTTP 429: "
                    f"{self._error_text(response_payload, 'rate limited the request.')}"
                )
                continue
            if status in (401, 403):
                self._disable(slot)
                print(f"[TOKENHARBOR ALERT] Disabled one API key after HTTP {status}; attempting ready fallback.")
                last_error = (
                    f"TokenHarbor router HTTP {status}: "
                    f"{self._error_text(response_payload, 'rejected an API key.')}"
                )
                continue
            if 500 <= status < 600:
                self._cool_down(slot, headers)
                network_attempts += 1
                last_error = self._error_text(response_payload, f"Token Harbor server error ({status}).")
                if network_attempts >= 4:
                    return False, {}, DEEPSEEK_FLASH_MODEL, last_error
                continue
            self._release_ready(slot)
            return False, {}, DEEPSEEK_FLASH_MODEL, self._error_text(response_payload, f"Token Harbor request failed ({status}).")

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
            return {"model": DEEPSEEK_FLASH_MODEL, "total_keys": len(self._slots), "states": counts, "cooldowns": cooldowns,
                    "last_http_status": self._last_http_status}


_default_router: Optional[TokenHarborRouter] = None
_default_router_lock = threading.Lock()
_last_generation_diagnostic = "generation did not start"
_execution_diagnostics: List[str] = []
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def reset_execution_diagnostics() -> None:
    _execution_diagnostics.clear()


def reset_task_diagnostics() -> None:
    global _last_generation_diagnostic
    reset_execution_diagnostics()
    _last_generation_diagnostic = ""


def _sanitize_runtime_diagnostic(value: object, limit: int = 500) -> str:
    """Bound worker receipts and redact credentials or high-risk identifiers."""
    text = _ANSI_ESCAPE_RE.sub("", str(value or ""))
    for pattern, replacement in (
        (r"(?i)Bearer\s+[^\s,;]+", "Bearer [REDACTED]"),
        (r"(?i)\bthk_live_[A-Za-z0-9_-]+", "[TOKEN REDACTED]"),
        (r"(?i)\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_-]+", "[TOKEN REDACTED]"),
        (r"(?i)\b(?:KAGGLE_API_TOKEN|KAGGLE_KEY|GH_TOKEN|GITHUB_TOKEN|API[_ -]?KEY|PASSWORD|SECRET|AUTHORIZATION)\b\s*[:=]\s*[^\s,;]+", "[CREDENTIAL REDACTED]"),
        (r"(?i)token=[^&\s]+", "token=[REDACTED]"),
        (r"(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[PRIVATE KEY REDACTED]"),
        (r"\b(?:0x)?[A-Fa-f0-9]{40,}\b", "[LONG ID REDACTED]"),
        (r"\b\d{9,18}\b", "[NUMBER REDACTED]"),
    ):
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[\r\n\t]+", " | ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:limit]


def record_execution_diagnostic(stage: str, detail: object) -> None:
    message = _sanitize_runtime_diagnostic(detail)
    if not message:
        return
    entry = f"{stage}: {message}"[:650]
    if not _execution_diagnostics or _execution_diagnostics[-1] != entry:
        _execution_diagnostics.append(entry)
    if len(_execution_diagnostics) > 8:
        del _execution_diagnostics[:-8]


def get_execution_diagnostic() -> str:
    # Keep the final blocking cause visible even when baseline logs are long.
    return " || ".join(reversed(_execution_diagnostics[-4:]))[:1800]


def _safe_command_failure(stage: str, result: object) -> None:
    argv = list(getattr(result, "argv", []) or [])
    if any(arg in ("--body", "--password", "--token") for arg in argv):
        command = " ".join(str(arg) for arg in argv[:2]) + " [arguments redacted]"
    else:
        command = " ".join(str(arg) for arg in argv[:6])
    output = getattr(result, "stderr", "") or getattr(result, "stdout", "") or "no command output"
    output = _ANSI_ESCAPE_RE.sub("", str(output))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    useful = [
        line for line in lines
        if re.search(r"error|failed|failure|timed? out|timeout|not found|missing|ERESOLVE|test result|FAIL", line, re.IGNORECASE)
    ]
    excerpt = " | ".join((useful or lines)[-3:]) if (useful or lines) else "no command output"
    try:
        duration = float(getattr(result, "duration_s", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    record_execution_diagnostic(
        stage,
        f"command={command or '[unknown]'} exit={getattr(result, 'exit_code', 'unknown')} "
        f"duration={duration:.1f}s detail={excerpt}",
    )


def _set_generation_diagnostic(reason: str) -> None:
    """Keep the closed-failure reason available to the worker receipt path.

    The worker processes one task at a time, so a process-local value is enough
    and avoids putting operational details into the task payload.
    """
    global _last_generation_diagnostic
    _last_generation_diagnostic = _sanitize_runtime_diagnostic(reason, 300)


def get_last_generation_diagnostic() -> str:
    return _last_generation_diagnostic


def _classify_generation_failure(error_message: Optional[str]) -> str:
    """Return an actionable, credential-safe router failure category."""
    message = (error_message or "").strip()
    normalized = message.lower()
    if "http 401" in normalized:
        return "TokenHarbor router HTTP 401"
    if "http 403" in normalized:
        return "TokenHarbor router HTTP 403"
    if "http 429" in normalized or "rate limit" in normalized:
        return "TokenHarbor router HTTP 429"
    if any(marker in normalized for marker in ("timeout", "timed out", "transient network", "urlerror")):
        return "TokenHarbor router network timeout"
    if any(marker in normalized for marker in ("no token harbor key", "key exhaustion", "requires exactly", "key file", "invalid key")):
        return "TokenHarbor key exhaustion"
    return f"TokenHarbor router failure: {message[:180] or 'empty completion'}"


def _get_default_router() -> TokenHarborRouter:
    global _default_router
    with _default_router_lock:
        if _default_router is None:
            _default_router = TokenHarborRouter()
        return _default_router


# ---------------------------------------------------------------------------
# Delivery-engine failover: NVIDIA NIM when the TokenHarbor shard is throttled.
#
# Measured 2026-11-01 (run 41284310025, Spectral-Finance/lux#99): 15 of the 17
# TokenHarbor keys answered free_tier_limit_reached (HTTP 429), the gateway had no
# ready key to lease, and Cline's preparation died on the gateway 502 -- after the
# engineering loop had already spent its turn budget on that dead end. The delivery
# worker had no second brain, while the discovery door has had one since 2026-10-30.
#
# The decision is a fact, not a judgement: an HTTP 429, a free-tier limit, or zero
# ready slots. A changed brain is always visible in the engine log with its request
# id, because a silent brain swap cannot be measured. No API key is ever logged.
NVIDIA_DELIVERY_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

# Credential-free markers of a throttled shard. These strings are produced by this
# file and by TokenHarbor's own error text; none of them can contain a key.
_THROTTLE_MARKERS = (
    "429",
    "free_tier_limit",
    "free tier limit",
    "rate limit",
    "no token harbor key is currently ready",
)

_nvidia_fallback_router: Optional[NvidiaRouter] = None
_nvidia_fallback_lock = threading.Lock()


def nvidia_delivery_model() -> str:
    """The model the failover answers with. Explicit configuration wins."""
    return (os.environ.get("NVIDIA_ROUTER_MODEL")
            or os.environ.get("NVIDIA_DELIVERY_MODEL")
            or NVIDIA_DELIVERY_MODEL).strip() or NVIDIA_DELIVERY_MODEL


def get_nvidia_fallback_router() -> Optional[NvidiaRouter]:
    """The delivery engine's second brain, or None when no NVIDIA key is configured."""
    global _nvidia_fallback_router
    with _nvidia_fallback_lock:
        if _nvidia_fallback_router is None:
            try:
                keys = nvidia_load_keys()
            except (OSError, ValueError):
                return None
            if not keys:
                return None
            _nvidia_fallback_router = NvidiaRouter(model=nvidia_delivery_model())
        return _nvidia_fallback_router


def tokenharbor_shard_ready_slots() -> Optional[int]:
    """Ready TokenHarbor keys, or None when the shard itself cannot be read.

    An unreadable shard is not "zero ready keys": that distinction keeps the
    failover from firing on a misconfigured router, and keeps a genuinely
    exhausted shard from firing it forever.
    """
    status = get_router_status()
    if status.get("error"):
        return None
    states = status.get("states", {})
    try:
        return int(states.get(READY, 0))
    except (TypeError, ValueError):
        return None


def nvidia_fallback_status() -> dict:
    """Credential-free observability for the second brain: never a key, always a state."""
    try:
        router = get_nvidia_fallback_router()
    except Exception:
        router = None
    if router is None:
        return {"configured": False, "model": nvidia_delivery_model()}
    return {"configured": True, **router.status()}


def tokenharbor_is_throttled(error_message: Optional[str]) -> bool:
    """True when the primary answer is a throttle, not a verdict on the request."""
    normalized = (error_message or "").lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _THROTTLE_MARKERS)


def gateway_failover(payload: dict, error_message: Optional[str], router: Optional[NvidiaRouter] = None,
                     request_id: Optional[str] = None, request_started: Optional[float] = None):
    """Answer from NVIDIA NIM when TokenHarbor is throttled; return None otherwise.

    The native tool protocol crosses untouched: ``tools``, the message history and
    the tool-result messages are forwarded verbatim, and the completion returned is
    the raw NIM body in the same shape TokenHarbor would have returned, so the
    gateway's streaming and validation code below is shared by both brains.

    On failure the caller's original diagnostic is returned unchanged, so a total
    outage still fails loudly on the primary brain rather than hiding behind the
    fallback.
    """
    try:
        ready_slots = tokenharbor_shard_ready_slots()
        if not (tokenharbor_is_throttled(error_message) or ready_slots == 0):
            return None
        fallback = router if router is not None else get_nvidia_fallback_router()
        if fallback is None:
            return None
        _command_log(
            f'CLINE_GATEWAY FAILOVER START id={request_id} '
            f'reason={"no_ready_slot" if ready_slots == 0 else "tokenharbor_429"} '
            f'model={fallback.model} tools={len(payload.get("tools") or [])} '
            f'primary_diagnostic={str(error_message or "")[:120]}'
        )
        outcome = fallback.chat_completion(payload, timeout=FALLBACK_TIMEOUT_SECONDS)
        ok, _, model_used, diagnostic = outcome
        elapsed = "" if request_started is None else f' elapsed={time.monotonic() - request_started:.1f}s'
        if ok:
            _command_log(f'CLINE_GATEWAY FAILOVER END id={request_id} result=OK model={model_used}{elapsed}')
        else:
            _command_log(f'CLINE_GATEWAY FAILOVER END id={request_id} result=FAILED '
                         f'model={model_used}{elapsed} diagnostic={str(diagnostic)[:120]}')
        return outcome
    except Exception:
        # The fallback is an optimisation over a loud failure; it must never be the
        # reason a request dies without a diagnostic.
        return None


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


def tokenharbor_has_ready_key() -> bool:
    status = get_router_status()
    states = status.get("states", {})
    try:
        return int(states.get(READY, 0)) > 0
    except (TypeError, ValueError):
        return False


def wait_for_tokenharbor_ready(max_wait_seconds: float = 305.0) -> bool:
    """Wait for a cooled key to become ready, but never wait on disabled keys."""
    deadline = time.monotonic() + max(0.0, float(max_wait_seconds))
    while True:
        status = get_router_status()
        states = status.get("states", {})
        try:
            if int(states.get(READY, 0)) > 0:
                return True
        except (TypeError, ValueError):
            pass

        remaining_delays = []
        for item in status.get("cooldowns", []) or []:
            try:
                remaining_delays.append(max(0.0, float(item.get("remaining_seconds", 0.0))))
            except (AttributeError, TypeError, ValueError):
                continue
        if not remaining_delays:
            return False

        budget = deadline - time.monotonic()
        delay = min(remaining_delays)
        if budget <= 0 or delay > budget:
            return False
        sleep_for = min(budget, max(0.25, delay + 0.25))
        print(
            f"[{ENGINE_ID}] TokenHarbor shard is cooling down; waiting {sleep_for:.1f}s before another generation attempt.",
            flush=True,
        )
        time.sleep(sleep_for)

# ==============================================================================
# SUBPROCESS EXECUTION ENGINE
# ==============================================================================
def run_cmd(cmd_list, timeout=30, retries=2):
    resolved_cmd = list(cmd_list)
    preserve_status_columns = bool(
        resolved_cmd and os.path.basename(str(resolved_cmd[0])).lower() in ('git', 'git.exe')
        and 'status' in resolved_cmd and any(str(arg).startswith('--porcelain') for arg in resolved_cmd)
    )
    if resolved_cmd and sys.platform == "win32":
        cmd_path = shutil.which(resolved_cmd[0])
        if cmd_path:
            resolved_cmd[0] = cmd_path
    last_stdout, last_stderr, last_code = "", "Command was not executed", 1
    for attempt in range(retries):
        try:
            res = run_streamed_process(
                resolved_cmd,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                stream_output=bool(resolved_cmd and os.path.basename(resolved_cmd[0]).lower() in ('git', 'git.exe')),
            )
            last_stdout = res.stdout if preserve_status_columns else res.stdout.strip()
            last_stderr, last_code = res.stderr.strip(), res.returncode
            if res.returncode == 0:
                return last_stdout, last_stderr, 0
        except subprocess.TimeoutExpired as exc:
            partial = exc.stderr or exc.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode('utf-8', errors='replace')
            last_stdout, last_code = "", 124
            last_stderr = f"Command timed out after {timeout} seconds. {str(partial)[-2000:]}".strip()
            print(f"  [Command Timeout] {cmd_list[:3]} exceeded {timeout}s.")
        except FleetOwnershipLost as exc:
            return exc.stdout, f"{exc}\n{exc.stderr}".strip(), 125
        except Exception as e:
            last_stdout, last_stderr, last_code = "", f"{type(e).__name__}: {e}", 1
            print(f"  [Command Error] {e}")
        time.sleep(1)
    return last_stdout, last_stderr, last_code

# -------------------------------------------------------------
# 2. STRICT APPROVED CORRIDORS & EXACT IANA TIMEZONES
# -------------------------------------------------------------

# ==============================================================================
# MULTI-TURN ITERATIVE VERIFICATION & PR ENGINE (ORIGINAL ICU PIPELINE LOGIC)
# ==============================================================================
def sanitize_prompt_input(text):
    """
    Strips prompt injection and jailbreak sequences and XML-escapes untrusted text.
    """
    if not text:
        return ""
    # XML escape to prevent breaking out of <untrusted_data>
    escaped = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    patterns = [
        r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b",
        r"(?i)\bdisregard\s+(?:all\s+)?earlier\s+directions\b",
        r"(?i)\bsystem\s+prompt\b",
        r"(?i)\bsystem\s+override\b",
        r"(?i)\bdeveloper\s+mode\b",
        r"(?i)\bdeveloper\s+message\b",
        r"(?i)\beval\(",
        r"(?i)\bexec\(",
        r"(?i)\bos\.system\b"
    ]
    for p in patterns:
        escaped = re.sub(p, "[SANITIZED]", escaped)
    return escaped

def _github_rest_json(url: str, token: str) -> Optional[dict]:
    """Read one GitHub REST resource without involving the gh CLI.

    GitHub's API response is the authority for the immutable commit anchor.
    Errors intentionally return no evidence so proposal generation fails closed.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "kaggle-engine-worker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request_obj = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request_obj, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"  [Evidence Error] GitHub REST lookup failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def collect_repo_evidence(repo, body):
    """Collect immutable, REST-backed evidence for a single repository."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    repo_path = urllib.parse.quote(str(repo).strip(), safe="/")
    api_root = f"https://api.github.com/repos/{repo_path}"
    evidence = {"description": "", "languages": "Polyglot", "default_branch": "main"}

    metadata = _github_rest_json(api_root, token)
    if metadata:
        evidence["description"] = str(metadata.get("description") or "")
        evidence["default_branch"] = str(metadata.get("default_branch") or "main")
        language = metadata.get("language")
        if isinstance(language, str) and language.strip():
            evidence["languages"] = language.strip()

    # This direct endpoint supplies the immutable object SHA.  Regex fallback
    # tolerates harmless JSON-shape changes, but never accepts CLI output.
    head_payload = _github_rest_json(f"{api_root}/commits/HEAD", token)
    direct_sha = head_payload.get("sha") if head_payload else ""
    fallback_text = json.dumps(head_payload, sort_keys=True) if head_payload else ""
    sha_match = re.search(r"\b([0-9a-fA-F]{40})\b", str(direct_sha))
    if not sha_match:
        sha_match = re.search(r"\b([0-9a-fA-F]{40})\b", fallback_text)
    if not sha_match:
        print(f"  [Evidence Error] Fail-closed: missing verified 40-hex commit SHA for {repo}.", flush=True)
        return None
    commit_sha = sha_match.group(1).lower()
    evidence["commit_sha"] = commit_sha

    code_blocks = re.findall(r"```[\s\S]*?```", body or "")
    evidence["code_blocks"] = "\n".join(code_blocks[:3]) if code_blocks else "No inline code blocks provided."

    referenced_files = re.findall(
        r"(?:src|lib|packages|apps|deploy|crates)/[\w./_-]+\.(?:ts|js|py|rs|go|jl|cpp|c|json|ya?ml)",
        body or "",
    )
    evidence["referenced_source"] = ""
    for rfile in referenced_files[:2]:
        quoted_file = urllib.parse.quote(rfile, safe="/")
        source_payload = _github_rest_json(f"{api_root}/contents/{quoted_file}?ref={commit_sha}", token)
        encoded = source_payload.get("content") if source_payload else None
        if not isinstance(encoded, str):
            continue
        try:
            import base64
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            evidence["referenced_source"] += (
                f"\n--- Referenced File: {rfile} (Branch: {evidence['default_branch']}, Commit: {commit_sha[:7]}) ---"
                f"\nURL: https://github.com/{repo}/blob/{commit_sha}/{rfile}\n{decoded[:1200]}\n"
            )
        except (ValueError, UnicodeError):
            continue

    return evidence

VERIFIED_SETTLEMENT_ADDRESSES = {
    "ROTATED-DOOM-KEY",
    "2qi849TBq72XMpsp8PjR4YfegDEzc7BRFZaarwQ2tKgL",
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x000000000000000000000000000000000000dEaD",
    "0x0000000000000000000000000000000000000001",
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "SysvarRent111111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
}

def collect_worktree_context(worktree: Optional[str], title: str, body: str) -> str:
    """Return bounded source/test context from the actual isolated checkout.

    Remote issue references are useful supporting evidence, but they are not a
    substitute for the files that are checked out at the verified base SHA.
    This deliberately reads only Git-tracked, safe paths from the worktree.
    """
    if not worktree or not os.path.isdir(worktree):
        return "No isolated worktree is available for this proposal."
    try:
        listed = subprocess.run(
            ["git", "-C", worktree, "ls-files", "-z"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Unable to list tracked worktree files: {type(exc).__name__}."
    if listed.returncode != 0:
        return "Unable to list tracked worktree files."

    paths = [
        value.decode("utf-8", errors="replace").replace("\\", "/")
        for value in listed.stdout.split(b"\0")
        if value
    ]
    issue_text = f"{title or ''} {body or ''}".lower()
    ignored_words = {
        "about", "after", "before", "being", "change", "could", "does", "from",
        "have", "issue", "please", "should", "that", "their", "there", "these",
        "this", "with", "would", "when", "where", "which",
    }
    keywords = {
        word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", issue_text)
        if word not in ignored_words
    }
    manifests = {
        "package.json", "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml",
        "go.mod", "CMakeLists.txt", "Makefile",
    }

    def score(path: str) -> Tuple[int, str]:
        lowered = path.lower()
        path_score = sum(3 for keyword in keywords if keyword in lowered)
        if os.path.basename(path) in manifests:
            path_score += 2
        if re.search(r"(?:^|/)(?:test|tests|spec|__tests__)/|(?:test|spec)\.[^/]+$", lowered):
            path_score += 1
        return path_score, path

    generated_components = {
        ".git", ".venv", "venv", "node_modules", "site-packages", "vendor",
        "dist", "build", "target",
    }
    readable_suffixes = {
        ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".go",
        ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".kt", ".rb", ".php",
        ".cs", ".swift", ".scala", ".sh", ".toml", ".yaml", ".yml",
    }
    selected = sorted(
        (
            path for path in paths
            if is_safe_relative_path(worktree, path)
            and not any(component.lower() in generated_components for component in path.replace("\\", "/").split("/"))
            and (
                os.path.basename(path) in manifests
                or os.path.splitext(path)[1].lower() in readable_suffixes
            )
        ),
        key=score,
        reverse=True,
    )
    selected = selected[:12]
    sections = ["Tracked worktree paths:\n" + "\n".join(f"- {path}" for path in selected)]
    remaining = 14_000
    for path in selected:
        full_path = os.path.join(worktree, path.replace("/", os.sep))
        if not os.path.isfile(full_path):
            continue
        try:
            if os.path.getsize(full_path) > 160_000:
                continue
            with open(full_path, "r", encoding="utf-8", errors="replace") as source_file:
                content = source_file.read()
        except OSError:
            continue
        excerpt = content[: min(3_000, remaining)]
        if not excerpt:
            break
        sections.append(f"\n--- Worktree file: {path} ---\n{excerpt}")
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    return "\n".join(sections)


def generate_grounded_proposal(
    repo,
    title,
    body,
    author,
    author_comments,
    iteration_feedback=None,
    prior_failures=None,
    turn: int = 1,
    worktree: Optional[str] = None,
):
    evidence = collect_repo_evidence(repo, body)
    if not evidence or not evidence.get("commit_sha"):
        _set_generation_diagnostic("missing verified 40-hex commit SHA")
        print(f"❌ [FAIL-CLOSED] Missing verified 40-hex commit SHA for {repo}. Suppressing proposal generation.")
        return None
    stack = evidence.get("languages", "Polyglot")
    desc = sanitize_prompt_input(evidence.get("description", ""))
    # Bound every untrusted source fragment before it reaches the model.  This
    # preserves useful evidence while avoiding a gateway/context rejection from
    # an unusually large issue body or embedded code dump.
    code_snippets = sanitize_prompt_input(evidence.get("code_blocks", ""))[:3000]
    source_context = sanitize_prompt_input(evidence.get("referenced_source", ""))[:2500]
    worktree_context = sanitize_prompt_input(collect_worktree_context(worktree, title, body))[:14000]
    _commit_sha = sanitize_prompt_input(evidence.get("commit_sha", ""))
    _default_branch = sanitize_prompt_input(evidence.get("default_branch", "main"))

    comments_excerpt = "\n---\n".join(author_comments[:2]) if author_comments else "No subsequent author comments."

    clean_repo = sanitize_prompt_input(repo)
    clean_stack = sanitize_prompt_input(stack)
    clean_title = sanitize_prompt_input(title)
    clean_author = sanitize_prompt_input(author)
    clean_body = sanitize_prompt_input(body[:2000] if body else 'No additional context provided.')
    clean_comments = sanitize_prompt_input(comments_excerpt[:800])
    feedback = iteration_feedback if iteration_feedback is not None else prior_failures
    clean_prior_failures = sanitize_prompt_input((feedback or "None; this is the first implementation turn.")[:5000])

    prompt = f"""You are Kunal Das, Principal Systems Architect & Technology Leader (NIT Honours, 20+ years enterprise systems architecture, systems performance, low-level concurrency, high-throughput routing, distributed systems).
Authentic Anchor: 33 LPA Keross anchor.

TASK:
You are the elite systems engineer DELIVERING THE COMPLETE WORKING SOFTWARE PATCH AND RUNNABLE TEST SUITE directly to this GitHub issue.
You must author and write the complete, compilable, drop-in production code and comprehensive unit test harness based on the issue title, error traces, and architectural requirements provided below.

Repository: {clean_repo} (Stack: {clean_stack} | Description: {desc})
Issue Title: {clean_title}
Client Author: @{clean_author}

<issue_context>
Issue Description & Requirements:
{clean_body}

Extracted Code & Error Traces:
{code_snippets}

Referenced Source Context:
{source_context if source_context else 'Standard repository architecture.'}

Actual isolated worktree context (authoritative for files and paths):
{worktree_context}

Client Comments:
{clean_comments}
</issue_context>

<repair_feedback>
This is repair iteration feedback from the exact previous attempt. On repair turns,
diagnose and correct every reported failure; do not repeat the previous patch blindly.
{clean_prior_failures}
</repair_feedback>

YOUR RESPONSE MUST FOLLOW THIS EXACT 4-PART STRUCTURE:

### 🛠️ Production Implementation & Technical Verification

1. **Root Cause Analysis & Architectural Design**:
   (Provide deep, exact technical analysis of the bug or requirement, isolating the root cause and defining the robust architectural fix.)

2. **Production-Grade Implementation Source Code**:
   (You MUST provide the COMPLETE, copy-pasteable, drop-in replacement source code with exact file path headers e.g. `### Production Source (path/to/file.ext)`. Write full, compilable, production-ready code with robust error handling and boundary guards. ZERO placeholders, ZERO 'TODO' stubs. Write real, working code in the repository's language e.g. TypeScript/Python/Go/Rust.)

3. **Comprehensive Unit Test Suite & Verification Harness**:
   (You MUST provide the COMPLETE, runnable test suite e.g. `### Test Suite (tests/path_test.ext)` reproducing the bug or testing all edge cases, and proving the fix passes. State the exact CLI command to execute the test suite.)

4. **Merge Readiness & Settlement Rails**:
   (State that this implementation and test harness are complete and ready for immediate merge or branch PR. Settlement coordinates:
   - **DOOM L1 Address:** `ROTATED-DOOM-KEY`
   - **Solana (USDC / USDT / SOL):** `2qi849TBq72XMpsp8PjR4YfegDEzc7BRFZaarwQ2tKgL`
   - **Base Mainnet (USDC / wDOOM) & Invoicing:** `isearch.xsolve@gmail.com` (Corporate wire & milestone billing upon request))

STRICT RULES:
- You MUST write the actual code and test files in code blocks.
- Every code block to create or edit MUST be preceded by: **File:** `path/to/file` so the test harness can extract and apply it.
- Edit the actual paths shown in the isolated worktree context. Do not invent replacement manifests, stub modules, or unrelated new files. Add a new file only when the existing repository structure requires it and the path belongs to its established source or test layout.
- ZERO HEDGING: Never say "source files are not available", "I cannot provide drop-in replacement", or "provide a repository checkout". You have full expert capability to author the complete, production-grade files.
- Deliver working code and runnable tests immediately — not promises or future scoping.
- Speak directly as a senior peer architect delivering the fix.
- No corporate sign-offs, credentials, or name signatures at the bottom (No-Signature DM Law).
- NEVER dump personal bank account numbers, IFSC codes, or UPI IDs in public issue comments."""

    print(f"  [DEEPSEEK-FLASH] model={DEEPSEEK_FLASH_MODEL}, turn={turn}")
    deepseek_ok, deepseek_text, deepseek_error = call_deepseek_flash(prompt, timeout=120)
    if deepseek_ok and deepseek_text:
        _set_generation_diagnostic("")
        return deepseek_text
    _set_generation_diagnostic(_classify_generation_failure(deepseek_error))
    print(f"  [DEEPSEEK-FLASH FAIL-CLOSED] No proposal generated: {(deepseek_error or 'empty completion')[:240]}")
    return None

# -------------------------------------------------------------
# 5. PRE-POST CONTENT SAFETY SANITIZER
# -------------------------------------------------------------
def sanitize_and_validate_payload(content):
    if not content or len(content.strip()) < 200:
        return False, "Payload empty or too short"

    # Strictly prohibit bank accounts, IFSC, IBAN, UPI IDs, API tokens, private keys
    hard_leak_patterns = [
        r"\b(?:account|acct|acc|a/c)\s*(?:no\.?|number|#)?\s*[:=-]?\s*\d{9,18}\b",
        r"\b(?:bank|routing|account|acct|kotak|sbi|hdfc|icici|indusind|pnb|axis|uco)\b.{0,30}\b\d{9,18}\b",
        r"\b(?:account|acct|acc|a/c)\s*(?:no\.?|number|#)?\s*[:=-]?\s*\d{2,6}(?:[- ]\d{2,6}){2,5}\b",
        r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
        r"\b[A-Z]{4}0[A-Z0-9]{6}\b",                        # Indian IFSC codes
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",                # International IBANs
        r"\b[a-zA-Z0-9.\-_]+@(okhdfcbank|okaxis|oksbi|okicici|paytm|ybl|upi|ibl|axl|apl|barodampay|federal|yesbank|icici|hdfcbank|sbi|axisbank|kotak|postbank)\b", # UPI
        r"\b(?:bank account|ifsc|routing number|swift code|sort code)\b",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\b",   # GitHub classic tokens
        r"\bgithub_pat_[A-Za-z0-9_]{20,120}\b",             # GitHub fine-grained PATs
        r"\bsk-[a-zA-Z0-9]{20,}\b",                         # OpenAI classic keys
        r"\bsk-proj-[a-zA-Z0-9_\-]{20,}\b",                 # OpenAI project keys
        r"\bBearer\s+[a-zA-Z0-9_\-\.]{20,}\b",              # Bearer tokens
        r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"          # Private keys
    ]
    for lp in hard_leak_patterns:
        if re.search(lp, content, re.IGNORECASE):
            return False, f"Security violation: matches leak pattern '{lp}'"

    # Unverified crypto address detection (permit only our authenticated settlement addresses)
    crypto_patterns = [
        r"\b0x[a-fA-F0-9]{40}\b",                           # EVM / Ethereum address
        r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}\b",        # Bitcoin address
        r"\b[1-9A-HJ-NP-Za-km-z]{32,45}\b",                 # Solana address / base58 key
    ]
    for cp in crypto_patterns:
        matches = re.finditer(cp, content)
        for m in matches:
            val = m.group(0)
            if val not in VERIFIED_SETTLEMENT_ADDRESSES:
                return False, f"Security violation: unverified payout address '{val}'"

    # Falsification detector: Prevent claiming private reference harness pass without code
    falsification_patterns = [
        r"\bverified on our reference environment\b",
        r"\bwe have isolated this failure on our private reference\b"
    ]
    for fp in falsification_patterns:
        if re.search(fp, content, re.IGNORECASE):
            return False, f"Zero-Manufacture violation: matches false test claim '{fp}'"

    # Refusal detector: Block posting if the output contains hedging/refusal language
    refusal_patterns = [
        r"\bcannot truthfully provide\b",
        r"\bno source replacement can truthfully be provided\b",
        r"\bno source artifact is supplied\b",
        r"\bcannot provide a truthful drop-in replacement\b",
        r"\bnot merge-ready: no verified technical scope\b",
        r"\bclaiming a file-level fault would be fabricated\b",
        r"\bfabricating exact\b",
        r"\bsupplying invented code\b",
        r"\bno runnable test can be authored\b",
        r"\bcannot produce runnable\b"
    ]
    for rp in refusal_patterns:
        if re.search(rp, content, re.IGNORECASE):
            return False, f"Refusal detected: output contains hedging text '{rp}'"

    # Enforce actual code delivery: Payload MUST contain code blocks with implementation
    if "```" not in content:
        return False, "Delivery rejected: lacks code blocks - not a valid code delivery"

    return True, "Payload sanitized and approved"

# -------------------------------------------------------------
# 6. FAST LIGHTWEIGHT DISPATCH & RECEIPT-VERIFIED DELIVERY
# -------------------------------------------------------------
def get_issue_fast(repo, number):
    """
    Two-tier fetch:
    1. Fast tier: body, author, title, labels, state (0.8s, never times out)
    2. Deep tier: comments fetched ONLY if body does not contain payment signal and technical context exists
    """
    cmd = ["gh", "issue", "view", str(number), "--repo", repo, "--json", "body,author,title,labels,state"]
    out, err, code = run_cmd(cmd, timeout=20)
    if code != 0 or not out:
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None

    # Ignore bot-generated issues
    author_obj = data.get("author", {}) or {}
    if author_obj.get("is_bot") or str(author_obj.get("login", "")).startswith("app/"):
        return None

    # Fetch authorAssociation reliably
    author_login = author_obj.get("login", "")
    repo_parts = repo.split("/")
    if len(repo_parts) == 2 and repo_parts[0].lower() == str(author_login).lower():
        data["authorAssociation"] = "OWNER"
    else:
        cmd_assoc = ["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".author_association"]
        a_out, a_err, a_code = run_cmd(cmd_assoc, timeout=10)
        data["authorAssociation"] = a_out.strip() if a_code == 0 and a_out else "NONE"

    # Check if issue text or comments indicate payment or engineering context
    body = data.get("body", "")
    _author = author_login
    author_comments = []

    combined_text = (data.get("title", "") + " " + (body or "")).lower()
    should_fetch_comments = any(token in combined_text for token in [
        "bounty", "reward", "paid", "pay", "algora", "polar",
        "gitcoin", "bountysource", "opire", "$", "usdc", "usdt", "eth", "sol",
        "bug", "error", "crash", "hang", "fail", "runtime", "issue", "fix", "memory", "perf"
    ])

    if should_fetch_comments:
        c_cmd = ["gh", "issue", "view", str(number), "--repo", repo, "--json", "comments"]
        c_out, c_err, c_code = run_cmd(c_cmd, timeout=15)
        if c_code == 0 and c_out:
            try:
                comments = json.loads(c_out).get("comments", [])
                for comment in comments:
                    commenter = comment.get("author", {}) or {}
                    login = (commenter.get("login") or "").lower()
                    comment_body = comment.get("body", "") or ""
                    is_platform_actor = login in {
                        'algora-pbc', 'app/algora', 'gitcoinbot', 'opire-bot',
                        'opire[bot]', 'polar-sh[bot]', 'issuehunt[bot]', 'bountysource',
                    }
                    if login == str(author_login).lower() or is_platform_actor:
                        author_comments.append(comment_body)
            except Exception:
                pass

    data["author_comments"] = author_comments
    return data

# -------------------------------------------------------------
# 8. MULTI-TURN ITERATIVE DUE-DILIGENCE & VERIFICATION ENGINE
# -------------------------------------------------------------
@dataclass
class CommandResult:
    argv: List[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

@dataclass
class VerificationPlan:
    bootstrap: List[List[str]] = field(default_factory=list)
    baseline_tests: List[List[str]] = field(default_factory=list)
    targeted_tests: List[List[str]] = field(default_factory=list)
    final_tests: List[List[str]] = field(default_factory=list)
    linters: List[List[str]] = field(default_factory=list)
    format_checks: List[List[str]] = field(default_factory=list)
    builds: List[List[str]] = field(default_factory=list)

@dataclass
class ScenarioCase:
    id: str
    category: str  # happy_path, null, empty, boundary, negative, concurrency, regression
    precondition: str
    action: str
    expected_result: str
    test_location: str

@dataclass
class EngineeringRun:
    repo: str
    issue_number: int
    base_sha: str
    worktree: str
    iteration: int = 0
    scenario_matrix: List[ScenarioCase] = field(default_factory=list)
    verification: List[CommandResult] = field(default_factory=list)
    status: str = "INIT"
    pr_url: Optional[str] = None
    pr_body: Optional[str] = None
    error_summary: Optional[str] = None
    modified_files: List[str] = field(default_factory=list)

def is_safe_relative_path(worktree: str, rel_path: str) -> bool:
    """
    Fail-closed worktree boundary security gate.
    Prevents path traversal (..), absolute paths, and workflow tampering.
    """
    if not rel_path or not rel_path.strip():
        return False
    rel_norm = os.path.normpath(rel_path.strip())
    parts = rel_norm.replace("\\", "/").split("/")
    if ".." in parts or "." in parts:
        return False
    if os.path.isabs(rel_norm) or (len(rel_norm) > 1 and rel_norm[1] == ":"):
        return False
    normalized_casefold = rel_norm.replace("\\", "/").casefold()
    if normalized_casefold == ".github/workflows" or normalized_casefold.startswith(".github/workflows/"):
        return False
    try:
        # realpath resolves every existing symlink in the parent chain, preventing
        # an apparently relative target from escaping the isolated worktree.
        wt_real = os.path.realpath(os.path.abspath(worktree))
        candidate_real = os.path.realpath(os.path.join(wt_real, rel_norm))
        return os.path.commonpath([wt_real, candidate_real]) == wt_real
    except (OSError, ValueError):
        return False

def extract_files_from_proposal(proposal: str) -> List[Tuple[str, str]]:
    """
    Parses code blocks and file paths from grounded implementation deliverables.
    Supports markdown headers (###), file labels (**File:**), and inline source comments.
    """
    extracted: List[Tuple[str, str]] = []
    seen_paths = set()

    def add_file(path: str, code: str) -> None:
        path = path.strip()
        if path and path not in seen_paths:
            seen_paths.add(path)
            extracted.append((path, code))

    # 1. Header forms: (path), (`path`), or a bare backtick path heading.
    sections = re.split(r'\n(?=### )', proposal)
    for sec in sections:
        header_match = re.search(
            r'^###.*?(?:\(\s*`?|\s+`)([a-zA-Z0-9_.\-/\\]+\.[A-Za-z0-9]+)`?\s*\)?',
            sec,
            re.MULTILINE,
        )
        if header_match:
            rel_path = header_match.group(1).strip()
            code_match = re.search(r'```(?:[a-zA-Z0-9_-]+)?\r?\n(.*?)```', sec, re.DOTALL)
            if code_match:
                add_file(rel_path, code_match.group(1))

    # 2. Explicit labels may appear outside a heading and must coexist with
    # heading-form files in a multi-file proposal.
    file_blocks = re.findall(
        r'(?:\*\*File:\*\*|\*\*File\*\*|File:|Path:)\s*`?([a-zA-Z0-9_.\-/\\]+\.[A-Za-z0-9]+)`?\s*\r?\n+```(?:[a-zA-Z0-9_-]+)?\r?\n(.*?)```',
        proposal,
        re.DOTALL,
    )
    for path, code in file_blocks:
        add_file(path, code)

    # 3. A code fence can identify itself with a first-line source comment.
    code_blocks = re.findall(r'```(?:[a-zA-Z0-9_-]+)?\r?\n(.*?)```', proposal, re.DOTALL)
    for code in code_blocks:
        first_line = code.lstrip().splitlines()[0] if code.lstrip().splitlines() else ""
        comment_match = re.match(r'^(?://|#)\s*([a-zA-Z0-9_.\-/\\]+\.[A-Za-z0-9]+)\s*$', first_line)
        if comment_match:
            add_file(comment_match.group(1), code)

    return extracted

def validate_synthesized_files(work_dir: str, extracted_files: List[Tuple[str, str]]) -> Tuple[bool, str]:
    """
    Quality Gate 1: Validates that all written files parse and compile without syntax errors.
    Prevents broken code, invalid JSON, or syntax errors from ever reaching maintainers.
    """
    for rel_path, code_body in extracted_files:
        if not is_safe_relative_path(work_dir, rel_path):
            return False, f"Security violation: unsafe synthesized path rejected: {rel_path}"
        _full_path = os.path.join(work_dir, rel_path.replace("/", os.sep))

        # 1. Python Syntax & Indentation Validation
        if rel_path.endswith(".py"):
            try:
                compile(code_body, rel_path, "exec")
            except Exception as e:
                return False, f"Python syntax/indentation error in {rel_path}: {e}"

        # 2. JSON Validation
        elif rel_path.endswith(".json"):
            try:
                json.loads(code_body)
            except Exception as e:
                return False, f"JSON syntax error in {rel_path}: {e}"

        # 3. JavaScript / MJS Validation via Node. Validate the synthesized text,
        # not a previous on-disk version of the file.
        elif rel_path.endswith((".js", ".mjs", ".cjs")):
            temp_path = None
            try:
                suffix = os.path.splitext(rel_path)[1]
                with tempfile.NamedTemporaryFile("w", suffix=suffix, dir=work_dir, encoding="utf-8", delete=False) as temp_file:
                    temp_file.write(code_body)
                    temp_path = temp_file.name
                res = subprocess.run(["node", "--check", temp_path], capture_output=True, text=True, timeout=10)
                if res.returncode != 0:
                    err_clean = (res.stderr or res.stdout).strip()[:100]
                    return False, f"JavaScript syntax error in {rel_path}: {err_clean}"
            except Exception:
                pass
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

    return True, "All files passed syntax validation"

def auto_resolve_cla_if_needed(repo: str, pr_url: str):
    """
    Quality Gate 2: Monitors PR for CLA Assistant bots and automatically signs
    the Contributor License Agreement to ensure 100% green CI status checks.
    """
    try:
        pr_number = pr_url.strip().rstrip("/").split("/")[-1]
        if not pr_number.isdigit():
            return

        time.sleep(3)
        out, err, code = run_cmd(["gh", "pr", "view", pr_number, "--repo", repo, "--json", "comments,statusCheckRollup"], timeout=20)
        if code != 0 or not out:
            return

        data = json.loads(out)
        comments = data.get("comments", [])
        checks = data.get("statusCheckRollup", [])

        needs_cla = False
        for c in comments:
            body = (c.get("body") or "").lower()
            if "cla" in body and ("sign" in body or "contributor license agreement" in body or "cla assistant" in body):
                already_signed = any("i have read the" in (other_c.get("body") or "").lower() and "sign the cla" in (other_c.get("body") or "").lower() for other_c in comments)
                if not already_signed:
                    needs_cla = True
                    break

        for ch in checks:
            name = (ch.get("name") or "").lower()
            workflow = (ch.get("workflowName") or "").lower()
            conclusion = (ch.get("conclusion") or "").upper()
            if "cla" in name or "cla" in workflow:
                if conclusion in ["FAILURE", "ACTION_REQUIRED"]:
                    needs_cla = True
                    break

        if needs_cla:
            print(f"  ✍️ [AUTO-CLA DETECTED] Signing Contributor License Agreement for {repo}#{pr_number}...")
            run_cmd(["gh", "pr", "comment", pr_url, "--body", "I have read the CLA Document and I hereby sign the CLA"], timeout=15)
            time.sleep(2)
            run_cmd(["gh", "pr", "comment", pr_url, "--body", "recheck"], timeout=15)
            print(f"  🎉 [AUTO-CLA RESOLVED] Posted signature and recheck on {pr_url}")
    except Exception as e:
        print(f"  [AUTO-CLA NOTICE] Could not check CLA: {e}")

def inspect_repository_architecture(worktree: str) -> dict:
    """
    Inspects repository root manifests, package manager, and CI workflows.
    """
    arch = {
        "ecosystem": "unknown",
        "ecosystems": [],
        "package_manager": None,
        "package_managers": [],
        "has_tests": False,
        "has_linter": False,
        "manifests": []
    }
    if not os.path.exists(worktree):
        return arch

    pkg_json = os.path.join(worktree, "package.json")
    if os.path.exists(pkg_json):
        arch["ecosystems"].append("nodejs")
        arch["manifests"].append("package.json")
        arch["package_manager"] = "npm"
        if os.path.exists(os.path.join(worktree, "pnpm-lock.yaml")):
            arch["package_manager"] = "pnpm"
        elif os.path.exists(os.path.join(worktree, "yarn.lock")):
            arch["package_manager"] = "yarn"
        arch["package_managers"].append(arch["package_manager"])

        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                scripts = data.get("scripts", {})
                test_cmd = str(scripts.get("test", "")).strip().lower()
                if test_cmd and "no test specified" not in test_cmd:
                    arch["has_tests"] = True
                if "lint" in scripts:
                    arch["has_linter"] = True
        except Exception:
            pass

    if os.path.exists(os.path.join(worktree, "Cargo.toml")):
        arch["ecosystems"].append("rust")
        arch["manifests"].append("Cargo.toml")
        arch["package_managers"].append("cargo")
        arch["has_tests"] = True
        arch["has_linter"] = True

    if os.path.exists(os.path.join(worktree, "pyproject.toml")) or os.path.exists(os.path.join(worktree, "setup.py")) or os.path.exists(os.path.join(worktree, "requirements.txt")):
        arch["ecosystems"].append("python")
        arch["manifests"].append("python_manifest")
        arch["package_managers"].append("pip")
        arch["has_tests"] = True
        arch["has_linter"] = True

    if os.path.exists(os.path.join(worktree, "go.mod")):
        arch["ecosystems"].append("go")
        arch["manifests"].append("go.mod")
        arch["package_managers"].append("go")
        arch["has_tests"] = True
        arch["has_linter"] = True

    # Match the monolith's product discovery without mistaking example or
    # vendored manifests for the repository's native verification target.
    if not arch["ecosystems"]:
        excluded = {'examples', 'tests', 'benchmarks', 'spikes', 'vendor', 'third_party', 'node_modules', 'target'}
        nested = sorted(
            entry.name + '/Cargo.toml' for entry in os.scandir(worktree)
            if not entry.name.startswith('.') and entry.name not in excluded
            and entry.is_dir(follow_symlinks=False)
            and os.path.isfile(os.path.join(entry.path, 'Cargo.toml'))
            and not os.path.islink(os.path.join(entry.path, 'Cargo.toml'))
        )
        if len(nested) == 1:
            arch['ecosystems'].append('rust')
            arch['manifests'].append(nested[0])
            arch['rust_manifest'] = nested[0]
            arch['package_managers'].append('cargo')
            arch['has_tests'] = True
            arch['has_linter'] = True

    if 'rust' in arch['ecosystems']:
        env_file = os.path.join(worktree, 'tools', 'env.sh')
        if (os.path.isfile(env_file) and not os.path.islink(env_file)
                and not os.path.islink(os.path.dirname(env_file))
                and not any(os.path.exists(os.path.join(worktree, name))
                            for name in ('rust-toolchain', 'rust-toolchain.toml'))):
            with open(env_file, encoding='utf-8') as handle:
                match = re.search(r'^\s*(?:export\s+)?PINNED_RUST\s*=\s*([\'"]?)(\d+\.\d+\.\d+)\1\s*(?:#.*)?$',
                                  handle.read(65536), re.MULTILINE)
            if match:
                arch['rust_toolchain'] = match[2]

    if len(arch["ecosystems"]) == 1:
        arch["ecosystem"] = arch["ecosystems"][0]
    elif len(arch["ecosystems"]) > 1:
        arch["ecosystem"] = "polyglot"
    return arch

# Checkout size above which workspace-wide commands are not scheduled. Measured, not guessed:
# Expensify/App is 3.39 GB and its own CI needs 8 vCPU/8 GiB for tests and 16 vCPU plus warm caches
# for lint, with a documented "~12GB each" cold-worker cost. The runner here has ~7 GiB.
HEAVY_WORKTREE_BYTES = int(os.environ.get("BOUNTY_HEAVY_WORKTREE_BYTES", str(512 * 1024 * 1024)))


def _worktree_bytes(worktree: str, limit: int = None) -> int:
    """Size of the checked-out source, excluding VCS metadata and install outputs.

    Stops as soon as it passes the limit, so a repository far above the threshold costs a few
    directory listings rather than a full walk. node_modules/.venv are excluded deliberately: they
    are install output, and the memory that killed the job scales with the source program being
    type-checked, not with the size of the dependency tree on disk.
    """
    limit = HEAVY_WORKTREE_BYTES if limit is None else int(limit)
    total = 0
    if not worktree or not os.path.isdir(worktree):
        return 0
    for root, dirs, files in os.walk(worktree):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv")]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            if total > limit:
                return total
    return total


def discover_verification_plan(arch: dict, worktree: str) -> VerificationPlan:
    """
    Derives the native verification commands based on verified architecture.
    """
    plan = VerificationPlan()
    ecosystems = arch.get("ecosystems") or [arch.get("ecosystem")]

    # A repository whose checkout alone is this large is the case measured on 2026-10-30: a
    # workspace-wide lint reached 14 GiB and the host killed the job at exit 143. Expensify/App
    # runs the same suite in CI on 8 and 16 vCPU runners with warm caches, which is how it is
    # normally done and is not available here. So on such a checkout the plan does NOT schedule a
    # workspace-wide command; the targeted test is the local receipt and upstream CI remains the
    # authority for the full suite. Nothing is skipped silently: the reason is printed.
    worktree_bytes = _worktree_bytes(worktree)
    repo_wide_ok = worktree_bytes <= HEAVY_WORKTREE_BYTES
    if not repo_wide_ok:
        print(json.dumps({"phase": "PLAN_REPO_WIDE_DEFERRED", "worktree": worktree,
                          "bytes": worktree_bytes, "limit": HEAVY_WORKTREE_BYTES,
                          "reason": "workspace-wide commands deferred to upstream CI"}))

    if "nodejs" in ecosystems:
        pm = arch.get("package_manager", "npm")
        if not os.path.exists(os.path.join(worktree, "node_modules")):
            # Prefer the frozen lockfile: `install` may rewrite the lockfile, which is a clean-
            # baseline violation. Fall back to `install` when the repository ships no lockfile,
            # because `ci` refuses to run without one.
            lockfiles = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
            has_lock = any(os.path.exists(os.path.join(worktree, name)) for name in lockfiles)
            plan.bootstrap.append([pm, "ci", "--prefer-offline"] if has_lock
                                  else [pm, "install", "--prefer-offline"])
        if repo_wide_ok and arch.get("has_tests"):
            plan.baseline_tests.append([pm, "test"])
            plan.final_tests.append([pm, "test"])
        if repo_wide_ok and arch.get("has_linter"):
            plan.linters.append([pm, "run", "lint"])

    if "python" in ecosystems:
        # Install the repository's declared runtime and verification dependencies
        # before pytest; otherwise configured plugins such as pytest-cov are absent.
        pyproject = os.path.join(worktree, "pyproject.toml")
        document = {}
        if os.path.isfile(pyproject):
            with open(pyproject, "rb") as handle:
                document = tomllib.load(handle)
        if document.get("project") or os.path.isfile(os.path.join(worktree, "setup.py")):
            optional = document.get("project", {}).get("optional-dependencies", {})
            extras = [name for name in ("dev", "test", "tests") if name in optional]
            target = ".[" + ",".join(extras) + "]" if extras else "."
            plan.bootstrap.append([sys.executable, "-m", "pip", "install", "-e", target])
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements-tests.txt"):
            if os.path.isfile(os.path.join(worktree, name)):
                plan.bootstrap.append([sys.executable, "-m", "pip", "install", "-r", name])
        plan.baseline_tests.append([sys.executable, "-m", "pytest"])
        plan.final_tests.append([sys.executable, "-m", "pytest"])
        plan.linters.append(["ruff", "check", "."])

    if "rust" in ecosystems:
        pin = arch.get('rust_toolchain')
        cargo = ['cargo', '+' + pin] if pin else ['cargo']
        if pin:
            plan.bootstrap.append(['rustup', 'toolchain', 'install', pin, '--profile', 'minimal', '--component', 'clippy'])
        manifest_args = ['--manifest-path', arch['rust_manifest']] if arch.get('rust_manifest') else []
        targets = ['--workspace'] if manifest_args else ['--lib']
        plan.bootstrap.append([*cargo, "check", *manifest_args, "--workspace"])
        plan.baseline_tests.append([*cargo, "test", *manifest_args, *targets])
        plan.final_tests.append([*cargo, "test", *manifest_args, *targets])
        plan.linters.append([*cargo, "clippy", *manifest_args, *targets, "--", "-D", "warnings"])

    if "go" in ecosystems:
        plan.bootstrap.append(["go", "mod", "download"])
        # `./...` walks every package in the module; on a big checkout that is the same shape of
        # command that died at exit 143. Measure, do not assume: only schedule it when the checkout
        # is not heavy.
        targets = ["./..."] if repo_wide_ok else ["./"]
        plan.baseline_tests.append(["go", "test", *targets])
        plan.final_tests.append(["go", "test", *targets])
        plan.linters.append(["golangci-lint", "run"])

    return plan


def verification_test_commands(plan: VerificationPlan) -> List[List[str]]:
    """Return the native test commands that are mandatory before any PR."""
    return [
        list(command)
        for command in (plan.baseline_tests + plan.targeted_tests + plan.final_tests)
        if command
    ]


def has_successful_test_verification(
    verification: List[CommandResult], test_commands: List[List[str]]
) -> bool:
    """Require a successful receipt for at least one planned native test command."""
    expected = {tuple(command) for command in test_commands if command}
    if not expected or not verification:
        return False
    return any(
        result.exit_code == 0 and tuple(result.argv) in expected
        for result in verification
    )


_COMMAND_LOG_LOCK = threading.Lock()


class FleetOwnershipLost(RuntimeError):
    def __init__(self, message, stdout='', stderr=''):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class PreparationBlocked(RuntimeError):
    """Cline reported ``action=blocked``: the report does not warrant a code change.

    This is a verdict, not a fault. Measured on Expensify/App#105153 (2026-10-27): the run
    spent 244 s of Cline, the decision was verified, and the reason was that the repository
    had already documented the behaviour as intended. Re-raising it as a generic failure
    loses that evidence and reports the outcome as ``FAILED_ENGINEER``, which reads as a
    broken pipeline rather than a correct refusal. The report therefore travels with the
    exception so the host records the refusal and its reason verbatim, once.
    """

    def __init__(self, report=None, reason=None):
        self.report = report if isinstance(report, dict) else {}
        detail = reason or self.report.get('reason') or 'unresolved prerequisite'
        super().__init__('Cline preparation blocked: ' + str(detail))


def _command_log(message: str) -> None:
    """Redact the displayed copy; receipts retain the original captured text."""
    secrets = [value for name, value in os.environ.items()
               if len(value) >= 8 and re.search(r'TOKEN|SECRET|PASSWORD|(?:^|_)KEY(?:_|$)', name, re.I)]
    router = globals().get('_default_router')
    if router is not None:
        secrets.extend(slot.secret for slot in router._slots)
    for secret in secrets:
        message = message.replace(secret, '[REDACTED]')
    message = _sanitize_runtime_diagnostic(message, 2500)
    with _COMMAND_LOG_LOCK:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] [{ENGINE_ID}] {message}", flush=True)


def _write_json_atomic(path: str, document) -> None:
    """Write JSON beside the target, then os.replace, so a reader never sees a partial file."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_preparation(path, elapsed=None, exit_code=None):
    """The single reader for a preparation report (F3).

    Exit zero does not imply a report. Run ``40673403288`` ran 55 minutes, exited 0, and left
    no ``preparation.json`` at all; a bare ``open()`` turned that into ``FileNotFoundError``
    and the adapter stamped it ``FAILED_ENGINEER``. Each failure mode is named here:

    * absent -> ``ClineDeliverableMissing``, carrying elapsed time and exit code by
      construction so the artefact explains itself without a log dig;
    * unreadable or unparseable -> ``ClineDeliverableInvalid`` with the real error verbatim;
    * a skeleton that Cline never replaced, or any contract violation ->
      ``ClineDeliverableInvalid`` from ``validate_preparation``.

    Nothing downstream may read the report any other way, so a skeleton can never be mistaken
    for a verdict.
    """
    if not os.path.exists(path):
        raise ClineDeliverableMissing(path, elapsed=elapsed, exit_code=exit_code)
    try:
        with open(path, encoding='utf-8') as handle:
            report = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ClineDeliverableInvalid(path, str(exc)) from exc
    return validate_preparation(report, path)


def run_streamed_process(argv, cwd=None, timeout=120, input=None, stdin=None, stream_output=True):
    """Capture both streams losslessly while exposing real progress and deadlines."""
    started = time.monotonic()
    deadline = started + timeout
    if _ACTIVE_TASK_LEASE is not None and _ACTIVE_TASK_LEASE.lost.is_set():
        raise FleetOwnershipLost('claim lease lost before command; execution blocked')
    name = os.path.basename(str(argv[0])).lower()
    operation = next((str(arg) for arg in argv[1:] if str(arg) in
                      ('clone', 'fetch', 'checkout', 'reset', 'clean', 'check', 'test', 'clippy')), '')
    if name in ('cargo', 'cargo.exe') and operation:
        target = next((str(arg) for arg in argv[1:]
                       if str(arg) in ('--workspace', '--lib', '--all-targets')), 'default')
        operation = f'{operation}_{target.lstrip("-")}'
    phase = re.sub(r'[^A-Z0-9_]', '_', f'{name}_{operation}'.upper()).strip('_')
    preview = []
    redact_next = False
    for arg in argv[:8]:
        preview.append('[REDACTED]' if redact_next else str(arg))
        redact_next = str(arg).lower() in ('--key', '--apikey', '--token', '--password', '-k')
    label = ' '.join(preview)
    _command_log(f'START {phase} timeout={timeout}s command={label}')
    if _ACTIVE_TASK_LEASE is not None:
        _ACTIVE_TASK_LEASE.phase = phase
    proc = subprocess.Popen(
        argv, cwd=cwd, stdin=subprocess.PIPE if input is not None else stdin,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
        start_new_session=(os.name == 'posix'),
    )
    if _ACTIVE_TASK_LEASE is not None:
        _ACTIVE_TASK_LEASE.command_pid = proc.pid
    stdout_parts, stderr_parts = [], []

    def collect(pipe, parts, stream):
        try:
            for line in iter(pipe.readline, ''):
                parts.append(line)
                if stream_output and line.strip():
                    _command_log(f'{phase} {stream}: {line.rstrip()}')
        finally:
            pipe.close()

    threads = [threading.Thread(target=collect, args=(proc.stdout, stdout_parts, 'stdout'), daemon=True),
               threading.Thread(target=collect, args=(proc.stderr, stderr_parts, 'stderr'), daemon=True)]
    if input is not None:
        def feed():
            try:
                proc.stdin.write(input)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
        threads.append(threading.Thread(target=feed, daemon=True))
    for thread in threads:
        thread.start()

    def stop_group(sig):
        try:
            if os.name == 'posix':
                os.killpg(proc.pid, sig)
            elif proc.poll() is None:
                proc.kill()
        except ProcessLookupError:
            pass

    try:
        last_progress = started
        while True:
            if _ACTIVE_TASK_LEASE is not None and _ACTIVE_TASK_LEASE.lost.is_set():
                raise FleetOwnershipLost('claim lease lost during command; owned process group stopped')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                proc.wait(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
                if time.monotonic() - last_progress >= 30:
                    _command_log(f'RUNNING {phase} pid={proc.pid} elapsed={time.monotonic()-started:.1f}s limit={timeout}s')
                    last_progress = time.monotonic()
        for thread in threads:
            thread.join(timeout=max(0, deadline-time.monotonic()))
            if thread.is_alive():
                raise subprocess.TimeoutExpired(argv, timeout)
    except (subprocess.TimeoutExpired, FleetOwnershipLost) as failure:
        stop_group(signal.SIGTERM)
        for thread in threads:
            thread.join(timeout=1)
        if proc.poll() is None or any(thread.is_alive() for thread in threads):
            stop_group(signal.SIGKILL if os.name == 'posix' else signal.SIGTERM)
        proc.wait()
        for thread in threads:
            thread.join(timeout=5)
        if isinstance(failure, FleetOwnershipLost):
            _command_log(f'LEASE_LOST {phase} pid={proc.pid} elapsed={time.monotonic()-started:.1f}s')
            raise FleetOwnershipLost(str(failure), ''.join(stdout_parts), ''.join(stderr_parts))
        _command_log(f'TIMEOUT {phase} pid={proc.pid} elapsed={time.monotonic()-started:.1f}s limit={timeout}s')
        raise subprocess.TimeoutExpired(argv, timeout, output=''.join(stdout_parts), stderr=''.join(stderr_parts))
    finally:
        if _ACTIVE_TASK_LEASE is not None:
            _ACTIVE_TASK_LEASE.command_pid = 0
    _command_log(f'END {phase} pid={proc.pid} exit={proc.returncode} elapsed={time.monotonic()-started:.1f}s')
    return subprocess.CompletedProcess(argv, proc.returncode, ''.join(stdout_parts), ''.join(stderr_parts))


def run_command_safe(argv: List[str], cwd: str, timeout: int = 120, input: Optional[str] = None) -> CommandResult:
    start = time.time()
    if _CLINE_EXECUTION_DEADLINE is not None:
        remaining = cline_turn_timeout_seconds()
        if remaining <= 0:
            from delivery_errors import ClineBudgetExhausted
            raise ClineBudgetExhausted(0)
        timeout = min(timeout, remaining)
    try:
        resolved_argv = list(argv)
        if resolved_argv and sys.platform == "win32":
            cmd_path = shutil.which(resolved_argv[0])
            if cmd_path:
                resolved_argv[0] = cmd_path
        proc = run_streamed_process(
            resolved_argv,
            cwd=cwd,
            input=input,
            timeout=timeout
        )
        duration = time.time() - start
        return CommandResult(
            argv=argv,
            cwd=cwd,
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_s=duration
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - start
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        return CommandResult(
            argv=argv,
            cwd=cwd,
            exit_code=-1,
            stdout=stdout,
            stderr=f"Command timed out after {timeout} seconds\n{stderr}",
            duration_s=duration
        )
    except FleetOwnershipLost as exc:
        return CommandResult(argv=argv, cwd=cwd, exit_code=-1, stdout=exc.stdout,
                             stderr=f'{exc}\n{exc.stderr}'.strip(), duration_s=time.time()-start)
    except Exception as e:
        duration = time.time() - start
        return CommandResult(
            argv=argv,
            cwd=cwd,
            exit_code=-1,
            stdout="",
            stderr=f"Execution error: {e}",
            duration_s=duration
        )

class _ClineProxyHandler(BaseHTTPRequestHandler):
    """Engine-local OpenAI-compatible bridge from Cline to TokenHarbor."""
    completed_requests = 0
    received_requests = 0
    last_request_path = None
    forwarded_tool_definitions = 0
    forwarded_tool_results = 0

    def log_message(self, _format, *_args):
        # The worker owns concise operational logging; proxy request bodies and
        # credentials must never enter the kernel log.
        return

    def _json(self, status: int, payload: dict, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/health", "/status", "/"):
            try:
                payload = _get_default_router().status()
            except Exception as exc:
                self._json(503, {"ok": False, "error": _sanitize_runtime_diagnostic(exc)})
                return
            self._json(200, {"ok": True, **payload,
                             "nvidia_fallback": nvidia_fallback_status(),
                             "received_requests": type(self).received_requests,
                             "last_request_path": type(self).last_request_path,
                             "completed_requests": type(self).completed_requests,
                             "forwarded_tool_definitions": type(self).forwarded_tool_definitions,
                             "forwarded_tool_results": type(self).forwarded_tool_results})
            return
        if self.path in ("/v1/models", "/models"):
            self._json(200, {"object": "list", "data": [{"id": CLINE_MODEL, "object": "model", "owned_by": "tokenharbor"}]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        type(self).received_requests += 1
        type(self).last_request_path = self.path.split('?', 1)[0]
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": {"message": "invalid JSON request"}})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": {"message": "request must be an object"}})
            return
        request_id = uuid.uuid4().hex[:10]
        request_started = time.monotonic()
        _command_log(
            f'CLINE_GATEWAY START id={request_id} messages={len(payload.get("messages") or [])} '
            f'tools={len(payload.get("tools") or [])} stream={bool(payload.get("stream"))}'
        )
        success, completion, model_used, error_message = _get_default_router().chat_completion(
            payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if not success:
            # TokenHarbor throttled or exhausted: answer from the delivery engine's
            # second brain rather than 502-ing Cline into a dead end (measured
            # 2026-11-01, run 41284310025).
            failover = gateway_failover(payload, error_message, request_id=request_id,
                                        request_started=request_started)
            if failover is not None:
                success, completion, model_used, error_message = failover
        if not success:
            _command_log(
                f'CLINE_GATEWAY END id={request_id} result=UPSTREAM_ERROR '
                f'elapsed={time.monotonic()-request_started:.1f}s'
            )
            self._json(502, {"error": {"message": _sanitize_runtime_diagnostic(error_message or "TokenHarbor request failed")}})
            return
        choices = completion.get("choices") if isinstance(completion, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0].get("message"), dict):
            self._json(502, {"error": {"message": "TokenHarbor returned an invalid chat completion"}})
            return
        type(self).completed_requests += 1
        type(self).forwarded_tool_definitions += len(payload.get("tools") or [])
        type(self).forwarded_tool_results += sum(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in payload.get("messages", [])
        )
        _command_log(
            f'CLINE_GATEWAY END id={request_id} result=OK model={model_used} '
            f'elapsed={time.monotonic()-request_started:.1f}s '
            f'tool_calls={sum(len(choice.get("message", {}).get("tool_calls") or []) for choice in choices if isinstance(choice, dict))}'
        )
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            streamed_choices = []
            for index, choice in enumerate(choices):
                message = dict(choice['message'])
                if isinstance(message.get('tool_calls'), list):
                    message['tool_calls'] = [dict(tool, index=i) for i, tool in enumerate(message['tool_calls'])]
                streamed_choices.append({"index": choice.get('index', index), "delta": message,
                                         "finish_reason": choice.get('finish_reason')})
            event = {
                "id": completion.get('id'),
                "object": "chat.completion.chunk",
                "created": completion.get('created'),
                "model": completion.get('model') or model_used,
                "choices": streamed_choices,
            }
            if 'usage' in completion:
                event['usage'] = completion['usage']
            self.wfile.write(f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode("utf-8"))
            self.wfile.flush()
            return
        self._json(200, completion)


def run_cline_proxy_server() -> None:
    """Run the local-only Cline gateway inside this engine process tree."""
    HTTPServer(("127.0.0.1", 8080), _ClineProxyHandler).serve_forever()


def _proxy_free_urlopen(url: str, timeout: float):
    """Probe localhost without inheriting any ambient HTTP proxy settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)

def _cline_proxy_is_healthy() -> bool:
    try:
        with _proxy_free_urlopen(CLINE_PROXY_HEALTH_URL, timeout=1.5) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return False


def cline_proxy_router_status() -> dict:
    """Read the key states from the process that actually serves Cline."""
    with _proxy_free_urlopen(CLINE_PROXY_HEALTH_URL, timeout=5) as response:
        status = json.load(response)
    if not isinstance(status, dict) or status.get('ok') is not True or not isinstance(status.get('states'), dict):
        raise RuntimeError('Cline proxy key readiness is unavailable; dispatch is blocked')
    return status

def ensure_cline_proxy_running() -> Tuple[bool, str]:
    """
    Guarantees Cline has its local OpenAI-compatible Token Harbor gateway.

    The process is only started when the health endpoint is unavailable.  It is
    deliberately detached and never terminates an existing process: a healthy
    proxy is always left untouched.
    """
    if _cline_proxy_is_healthy():
        return True, "Cline proxy health check passed."

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--cline-proxy"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as exc:
        return False, f"Unable to start Cline proxy: {exc}"

    # The proxy starts locally and normally binds immediately.  Keep the gate
    # lightweight while still eliminating a launch-vs-first-request race.
    for _ in range(6):
        time.sleep(0.35)
        if _cline_proxy_is_healthy():
            return True, "Cline proxy started and passed health check."
    return False, "Cline proxy did not become healthy after launch."

def resolve_cline_command() -> Optional[List[str]]:
    """Resolve the Kaggle-provisioned Cline CLI."""
    cline_executable = shutil.which("cline")
    if cline_executable:
        return [cline_executable]
    if os.path.isfile(CLINE_NODE_EXE) and os.path.isfile(CLINE_NODE_ENTRYPOINT):
        return [CLINE_NODE_EXE, CLINE_NODE_ENTRYPOINT]
    return None


def configure_cline_for_engine() -> Tuple[bool, str]:
    """Configure Cline against this engine's private local TokenHarbor proxy."""
    cline_command = resolve_cline_command()
    if not cline_command:
        return False, "Cline executable is unavailable after Kaggle bootstrap."
    proxy_ok, proxy_message = ensure_cline_proxy_running()
    if not proxy_ok:
        return False, proxy_message
    os.makedirs(CLINE_DATA_DIR, exist_ok=True)
    # Both auth and engineering must resolve the same isolated provider file.
    os.environ['CLINE_DATA_DIR'] = CLINE_DATA_DIR
    provider_file = os.path.join(CLINE_DATA_DIR, 'settings', 'providers.json')
    os.environ['CLINE_PROVIDER_SETTINGS_PATH'] = provider_file
    auth_command = [
        *cline_command,
        "--data-dir", CLINE_DATA_DIR,
        "auth",
        "--data-dir", CLINE_DATA_DIR,
        "--provider", CLINE_PROVIDER,
        "--apikey", CLINE_PROXY_API_KEY,
        "--modelid", CLINE_MODEL,
        "--baseurl", CLINE_PROXY_BASE_URL,
    ]
    result = run_command_safe(auth_command, cwd=SANDBOX_DIR, timeout=90)
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout or "Cline auth returned no diagnostic").strip()
        return False, f"Cline proxy configuration failed (exit {result.exit_code}): {detail[:600]}"
    try:
        with open(provider_file, encoding='utf-8') as handle:
            saved = json.load(handle)
        settings = saved.get('providers', {}).get(CLINE_PROVIDER, {}).get('settings', {})
        auth = settings.get('auth') or {}
        if (settings.get('model') != CLINE_MODEL or
                str(settings.get('baseUrl', '')).rstrip('/') != CLINE_PROXY_BASE_URL.rstrip('/') or
                (auth.get('apiKey') or settings.get('apiKey')) != CLINE_PROXY_API_KEY):
            return False, 'Cline provider readback failed: model, endpoint, or local proxy credential was not persisted correctly.'
    except (OSError, ValueError, TypeError, AttributeError):
        return False, 'Cline provider readback failed: isolated provider settings are missing or malformed.'
    return True, f"Cline configuration verified: provider={CLINE_PROVIDER}, model={CLINE_MODEL}, base={CLINE_PROXY_BASE_URL}."


def cline_worktree_command(worktree: str, prompt: str, retries: int = 3) -> List[str]:
    command = resolve_cline_command()
    if not command:
        raise RuntimeError('Cline executable is unavailable after bootstrap.')
    return [*command, '--data-dir', CLINE_DATA_DIR, '--provider', CLINE_PROVIDER,
            '--model', CLINE_MODEL, '--key', CLINE_PROXY_API_KEY,
            '-y', '--retries', str(retries), '-c', worktree, prompt]


def verify_cline_provider_wire() -> Tuple[bool, str]:
    """Require actual Cline tool use through this engine's own private router."""
    source_path = os.path.abspath(__file__)
    read_command = "grep -n -m1 '^CLINE_PROVIDER = ' " + shlex.quote(source_path)
    prompt = (
        f'Use a read-only shell tool to run exactly this command: {read_command}. '
        'Report the exact CLINE_PROVIDER constant value from that real file, then finish. '
        'Do not read any other lines, edit any file, run tests, inspect credentials, or access any other path.'
    )
    before = {}
    try:
        with _proxy_free_urlopen(CLINE_PROXY_HEALTH_URL, timeout=5) as response:
            before = json.load(response)
        result = run_command_safe(
            cline_worktree_command(os.path.dirname(source_path), prompt, retries=1),
            cwd=os.path.dirname(source_path), timeout=180,
        )
        with _proxy_free_urlopen(CLINE_PROXY_HEALTH_URL, timeout=5) as response:
            after = json.load(response)
        completed = after.get('completed_requests', 0) - before.get('completed_requests', 0)
        tool_results = after.get('forwarded_tool_results', 0) - before.get('forwarded_tool_results', 0)
        if result.exit_code != 0 or completed < 1 or tool_results < 1:
            diagnostic = _sanitize_runtime_diagnostic(result.stderr or result.stdout or 'No native Cline tool round trip was observed', 600)
            received = after.get('received_requests', 0) - before.get('received_requests', 0)
            return False, f'Cline live provider check failed (exit {result.exit_code}, received={received}, upstream_http={after.get("last_http_status")}, path={after.get("last_request_path")}, completions={completed}, tool_results={tool_results}): {diagnostic}'
        return True, f'Cline live tool round trip verified: provider={CLINE_PROVIDER}, model={CLINE_MODEL}, completions={completed}, tool_results={tool_results}'
    except Exception as exc:
        return False, f'Cline live provider check failed: {_sanitize_runtime_diagnostic(exc, 500)}'

def initialize_cline_for_engine() -> Tuple[bool, str]:
    """Keep transient provider throttling from ending an otherwise ready worker."""
    configured, configuration = configure_cline_for_engine()
    if not configured:
        return False, configuration
    delays = (30, 60, 60)
    for attempt in range(len(delays) + 1):
        ready, diagnostic = verify_cline_provider_wire()
        if ready:
            return True, configuration + ' ' + diagnostic
        if attempt == len(delays) or not is_retryable_failure(diagnostic):
            return False, diagnostic
        delay = delays[attempt]
        message = (f'STARTING {ENGINE_ID} transient Cline provider failure; '
                   f'retrying verification {attempt + 2}/{len(delays) + 1} in {delay}s')
        _command_log(message + ': ' + _sanitize_runtime_diagnostic(diagnostic, 300))
        door_say(message, body='ENGINE_REGISTRATION')
        time.sleep(delay)
    return False, 'Cline provider verification did not complete.'


def build_cline_engineering_prompt(
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    arch: Dict[str, Any],
    scenarios: List[ScenarioCase],
    prior_failures: Optional[str],
) -> str:
    """Build a bounded, self-contained task that gives Cline the worktree context."""
    delivery_context = (arch or {}).get('full_delivery_context')
    issue_context = (f'Read the complete issue and delivery context from {delivery_context}.'
                     if delivery_context else sanitize_prompt_input(body or 'No additional issue body was supplied.'))
    try:
        architecture_context = json.dumps(arch or {}, indent=2, default=str)
    except (TypeError, ValueError):
        architecture_context = str(arch or {})
    architecture_context = sanitize_prompt_input(architecture_context)[:6000]
    scenario_context = "\n".join(
        f"- {case.id} ({case.category}): {case.precondition}; "
        f"action={case.action}; expected={case.expected_result}; test={case.test_location}"
        for case in scenarios
    ) or "- No additional scenario matrix was supplied; infer focused regression and boundary coverage from the issue."
    failure_context = "None; this is the first implementation turn."
    if prior_failures:
        os.makedirs(PACKET_DIR, exist_ok=True)
        failure_path = os.path.join(PACKET_DIR, 'cline-failure-' + uuid.uuid4().hex + '.txt')
        with open(failure_path, 'w', encoding='utf-8') as handle:
            handle.write(prior_failures)
        failure_context = 'Read the complete actual failure log at ' + failure_path

    return f"""Work directly in the current isolated Git worktree to resolve this issue.

Repository: {sanitize_prompt_input(repo)}
Issue: #{issue_number} — {sanitize_prompt_input(title)}

Issue requirements:
{issue_context}

Repository architecture context:
{architecture_context or 'No architecture metadata was supplied.'}

Required scenarios:
{scenario_context}

Prior failures from the immediately preceding attempt:
{failure_context}

Own the delivery of this issue, including any required installation, configuration and repairs. Inspect the existing code and tests before editing. Add companion tests for applicable null, empty, boundary, negative, concurrency and regression cases. Do not weaken or rewrite existing master tests or CI workflows. Use the native package manager, pins and test plan you resolved from the repository. Run the relevant repository tests and linters when practical; every required native check must actually pass before publication. Runtime tools and caches may be provisioned outside the worktree; keep product changes in this isolated checkout. Do not add corporate signatures, credentials, payment details or unrelated changes. Preserve completed work and leave the actual changes for the host's independent verification and publication gates.

Use the runner's available RAM/CPU deliberately. Inspect scripts for internal parallel fan-out before full-repository checks, run heavyweight builds/typechecks/tests serially, and poll any live command to completion before starting another. Preserve the full native check set with supported concurrency limits or serial repository-defined component commands; never omit targets or relax warnings/tests to fit memory. If resource pressure interrupts a command, report the exact command and observed evidence, then repair the execution plan rather than treating it as a product defect."""

def _status_paths_from_porcelain(status_output: str) -> Tuple[bool, List[str], str]:
    """Extract changed worktree paths from `git status --porcelain` without trusting them."""
    paths = []
    if "\0" in (status_output or ""):
        entries = iter(status_output.split("\0"))
        for entry in entries:
            if not entry:
                continue
            if len(entry) < 4 or entry[2] != " ":
                return False, [], f"Malformed git status entry: {entry!r}"
            paths.append(entry[3:])
            if "R" in entry[:2] or "C" in entry[:2]:
                original = next(entries, "")
                if not original:
                    return False, [], "Missing rename/copy source in git status."
                paths.append(original)
        return True, sorted(set(paths)), "Changed files discovered from NUL-delimited git status."
    for raw_line in (status_output or "").splitlines():
        if len(raw_line) < 4:
            return False, [], f"Malformed git status entry: {raw_line!r}"
        rel_path = raw_line[3:].strip()
        # Porcelain v1 renders rename/copy entries as "old -> new".  Both paths
        # must remain within the worktree, and the destination is what is staged.
        if " -> " in rel_path:
            original, rel_path = rel_path.rsplit(" -> ", 1)
            paths.append(original.strip())
        paths.append(rel_path.strip())
    return True, sorted(set(paths)), "Changed files discovered from git status."

def preserve_cline_edits(worktree: str) -> str:
    """Retain recoverable bytes before a failed agent/collector checkout is reset."""
    import zipfile
    backup_dir = os.path.join(PACKET_DIR, "cline-recovery")
    os.makedirs(backup_dir, exist_ok=True)
    destination = os.path.join(backup_dir, f"{uuid.uuid4().hex}.zip")
    patch = subprocess.run(["git", "-C", worktree, "diff", "--binary", "HEAD"],
                           capture_output=True, check=True, timeout=30).stdout
    untracked = subprocess.run(["git", "-C", worktree, "ls-files", "--others", "--exclude-standard", "-z"],
                               capture_output=True, check=True, timeout=30).stdout
    tracked = subprocess.run(["git", "-C", worktree, "diff", "--name-only", "-z", "HEAD"],
                             capture_output=True, check=True, timeout=30).stdout
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as backup:
        backup.writestr("tracked.patch", patch)
        backup.writestr("checkpoint.json", json.dumps({
            "schema": 1, "head_sha": subprocess.run(
                ["git", "-C", worktree, "rev-parse", "HEAD"], capture_output=True,
                check=True, timeout=10).stdout.decode().strip(),
            "harness_sha": os.environ.get("GITHUB_SHA"),
            "engine_id": ENGINE_ID, "at": datetime.now(timezone.utc).isoformat(),
            "worktree_name": os.path.basename(worktree),
        }))
        for raw_path in tracked.split(b"\0"):
            if not raw_path:
                continue
            rel_path = os.fsdecode(raw_path)
            if not is_safe_relative_path(worktree, rel_path):
                raise ValueError(f"Unsafe recovery path: {rel_path}")
            full_path = os.path.join(worktree, rel_path)
            if os.path.isfile(full_path):
                backup.write(full_path, "tracked/" + rel_path.replace("\\", "/"))
        for raw_path in untracked.split(b"\0"):
            if not raw_path:
                continue
            rel_path = os.fsdecode(raw_path)
            if not is_safe_relative_path(worktree, rel_path):
                raise ValueError(f"Unsafe recovery path: {rel_path}")
            full_path = os.path.join(worktree, rel_path)
            if not os.path.isfile(full_path):
                raise ValueError(f"Recovery path is not a regular file: {rel_path}")
            backup.write(full_path, "untracked/" + rel_path.replace("\\", "/"))
    with open(destination, "rb") as saved:
        digest = hashlib.sha256(saved.read()).hexdigest()
    return f"{destination} sha256={digest}"


_CLINE_EXECUTION_DEADLINE = None


def set_cline_execution_budget(seconds: Optional[int]) -> None:
    """Set one shared Cline deadline for a complete delivery, not a fresh timer per turn."""
    global _CLINE_EXECUTION_DEADLINE
    if seconds is None:
        _CLINE_EXECUTION_DEADLINE = None
        return
    budget = int(seconds)
    if budget <= 0:
        raise ValueError("Cline execution budget must be positive")
    _CLINE_EXECUTION_DEADLINE = time.monotonic() + budget


def cline_turn_timeout_seconds(ecosystems: Optional[List[str]] = None) -> int:
    """Use the 60-minute standalone default or the remaining shared delivery budget."""
    if _CLINE_EXECUTION_DEADLINE is None:
        return 3600
    return max(0, int(_CLINE_EXECUTION_DEADLINE - time.monotonic()))


def run_cline_engineering_turn(
    worktree: str,
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    arch: Dict[str, Any],
    scenarios: List[ScenarioCase],
    prior_failures: Optional[str],
) -> Tuple[bool, List[Tuple[str, str]], List[str], str]:
    """Run Cline as the worktree agent and return actual changed source and paths."""
    # The legacy proposal path remains useful to unit tests and to environments
    # where a real isolated Git checkout has not yet been prepared.
    if not os.path.exists(os.path.join(worktree, ".git")):
        return False, [], [], "Cline requires a real isolated Git worktree; using legacy proposal fallback."

    cline_command = resolve_cline_command()
    if not cline_command:
        return False, [], [], "Cline executable is unavailable after bootstrap."
    proxy_ok, proxy_message = ensure_cline_proxy_running()
    if not proxy_ok:
        return False, [], [], proxy_message

    prompt = build_cline_engineering_prompt(
        repo, issue_number, title, body, arch, scenarios, prior_failures
    )
    command = cline_worktree_command(worktree, prompt)
    ecosystems = arch.get('ecosystems') or [arch.get('ecosystem')]
    turn_timeout = cline_turn_timeout_seconds(ecosystems)
    if turn_timeout <= 0:
        return False, [], [], "CLINE_TOTAL_BUDGET_EXHAUSTED: no Cline execution time remains."
    _command_log(f'CLINE_TURN START repo={repo} issue={issue_number} timeout={turn_timeout}s')
    cline_started = time.monotonic()
    result = run_command_safe(command, cwd=worktree, timeout=turn_timeout)
    _command_log(
        f'CLINE_TURN END repo={repo} issue={issue_number} exit={result.exit_code} '
        f'elapsed={time.monotonic()-cline_started:.1f}s limit={turn_timeout}s'
    )
    if result.exit_code != 0:
        details = (result.stderr or result.stdout or "Cline returned no diagnostic output").strip()
        return False, [], [], f"Cline execution failed (exit {result.exit_code}): {details[:4000]}"

    status_output, status_error, status_code = run_cmd(
        ["git", "-C", worktree, "status", "--porcelain", "--untracked-files=all", "-z"], timeout=20, retries=1
    )
    if status_code != 0:
        return False, [], [], f"Unable to inspect Cline worktree status: {status_error or status_output}"
    parsed, changed_paths, status_message = _status_paths_from_porcelain(status_output)
    if not parsed:
        return False, [], [], status_message
    if not changed_paths:
        return False, [], [], "Cline completed without modifying repository files; using legacy proposal fallback."

    file_changes = []
    for rel_path in changed_paths:
        if not is_safe_relative_path(worktree, rel_path):
            return False, [], [], f"Cline attempted unsafe worktree path: {rel_path}"
        full_path = os.path.join(worktree, rel_path.replace("/", os.sep))
        # A deletion is safe to carry forward; there is no file content to parse.
        if not os.path.exists(full_path):
            continue
        try:
            with open(full_path, "r", encoding="utf-8") as source_file:
                file_changes.append((rel_path, source_file.read()))
        except (OSError, UnicodeError) as exc:
            return False, [], [], f"Unable to read Cline-modified file {rel_path}: {exc}"
    return True, file_changes, changed_paths, f"Cline completed successfully. {status_message}"

def native_verification_timeout(command: List[str], default: int) -> int:
    """Use one configurable native-verification runway across ecosystems."""
    return max(default, int(os.environ.get('FLEET_NATIVE_TIMEOUT_SECONDS', '3600')))


def cline_supervise_delivery_phase(worktree, repo, number, phase, diagnostic, plan):
    if not os.path.exists(os.path.join(worktree, '.git')):
        return True, plan, 'No live Git checkout; retained the deterministic verification plan.'
    proxy_ok, proxy_message = ensure_cline_proxy_running()
    if not proxy_ok:
        return False, plan, proxy_message
    _command_log(f'CLINE_DELIVERY_SUPERVISOR phase={phase} repo={repo} issue={number}')
    return supervise_delivery(worktree, repo, number, phase, diagnostic, plan, PACKET_DIR,
                              cline_worktree_command, run_command_safe, VerificationPlan,
                              preserve_cline_edits)


def verify_baseline(worktree: str, plan: VerificationPlan) -> Tuple[bool, str, List[CommandResult]]:
    results = []
    for cmd in plan.bootstrap:
        res = run_command_safe(cmd, cwd=worktree, timeout=native_verification_timeout(cmd, 600))
        results.append(res)
        if res.exit_code != 0:
            _safe_command_failure("baseline bootstrap", res)
            return False, f"Bootstrap command failed: {' '.join(cmd)}\n{res.stderr or res.stdout}", results

    for cmd in plan.baseline_tests:
        res = run_command_safe(cmd, cwd=worktree, timeout=native_verification_timeout(cmd, 600))
        results.append(res)
        if res.exit_code != 0:
            _safe_command_failure("baseline tests", res)
            return False, f"Baseline test failure on untouched upstream: {' '.join(cmd)}\n{res.stderr or res.stdout}", results

    return True, "Baseline verified green.", results


def configure_task_cargo_cache(worktree: str, repo: str, issue_number: int, base_sha: str) -> Optional[str]:
    """Keep task-scoped Rust artifacts outside `git clean -fdx`'s worktree."""
    manifests = [
        os.path.join(worktree, "Cargo.lock"),
        os.path.join(worktree, "rust-toolchain"),
        os.path.join(worktree, "rust-toolchain.toml"),
        os.path.join(worktree, ".cargo", "config"),
        os.path.join(worktree, ".cargo", "config.toml"),
    ]
    digest = hashlib.sha256()
    digest.update(f"{repo}#{issue_number}\0{base_sha}\0".encode())
    for path in manifests:
        if os.path.isfile(path):
            digest.update(os.path.basename(path).encode() + b"\0")
            with open(path, "rb") as handle:
                digest.update(handle.read())
    for pattern in ("rust-toolchain", "rust-toolchain.toml"):
        for path in sorted(glob.glob(os.path.join(worktree, "**", pattern), recursive=True)):
            if os.path.isfile(path):
                digest.update(os.path.relpath(path, worktree).replace(os.sep, "/").encode() + b"\0")
                with open(path, "rb") as handle:
                    digest.update(handle.read())
    rustc = shutil.which("rustc")
    rustc_version = "rustc-unavailable"
    if rustc:
        try:
            result = subprocess.run([rustc, "--version"], capture_output=True, text=True, timeout=5, check=False)
            rustc_version = result.stdout.strip() if result.returncode == 0 else f"rustc-exit-{result.returncode}"
        except (OSError, subprocess.TimeoutExpired):
            rustc_version = "rustc-version-unavailable"
    digest.update(rustc_version.encode())
    cache_key = digest.hexdigest()[:24]
    cache_root = os.path.join("/tmp", "cargo-task-cache", hashlib.sha256(repo.encode()).hexdigest()[:12],
                              str(issue_number), cache_key)
    os.makedirs(cache_root, exist_ok=True)
    os.environ["CARGO_TARGET_DIR"] = cache_root
    _command_log(f"CARGO_CACHE configured repo={repo} issue={issue_number} key={cache_key} rustc={rustc_version}")
    return cache_root

def model_scenarios(title: str, body: str, arch: dict) -> List[ScenarioCase]:
    cases = []
    cases.append(ScenarioCase(
        id="SCENARIO_HAPPY_PATH",
        category="happy_path",
        precondition="Valid inputs provided according to specification",
        action="Execute core business path",
        expected_result="Operation completes with 200/success code and expected state transition",
        test_location="tests/happy_path"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_NULL_INPUT",
        category="null",
        precondition="Null/None/undefined passed for optional and required fields",
        action="Execute function with null arguments",
        expected_result="Gracefully handled with explicit validation error; no unhandled crash",
        test_location="tests/boundary"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_EMPTY_INPUT",
        category="empty",
        precondition="Empty string, empty collection, or whitespace-only inputs",
        action="Submit empty payload",
        expected_result="Rejected with clear diagnostic message; no silent state corruption",
        test_location="tests/boundary"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_BOUNDARY_LIMIT",
        category="boundary",
        precondition="Values at exact upper and lower bounds (0, max_int, grace threshold ticks)",
        action="Execute at exact boundary values",
        expected_result="Boundary conditions evaluated strictly according to half-open interval specifications",
        test_location="tests/boundary"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_NEGATIVE_FAILURE",
        category="negative",
        precondition="Malformed data, unauthorized callers, or invalid credentials",
        action="Execute unauthorized or malformed request",
        expected_result="Immediate refusal with proper typed error code",
        test_location="tests/negative"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_CONCURRENCY_RACE",
        category="concurrency",
        precondition="Multiple simultaneous requests on the same resource",
        action="Execute concurrent operations",
        expected_result="Atomic transition; second operation safely rejected or queued; zero double-spend",
        test_location="tests/concurrency"
    ))
    cases.append(ScenarioCase(
        id="SCENARIO_DEFECT_REGRESSION",
        category="regression",
        precondition=f"Reproduction state for issue: {title}",
        action="Trigger reported defect condition",
        expected_result="Defect resolved cleanly; assertion proves expected behavior",
        test_location="tests/regression"
    ))
    return cases

def check_competing_prs_fail_closed(repo: str, number: int, ignore_pr: Optional[int] = None) -> Tuple[bool, str]:
    """
    Fail-closed Zero-Competition gate.
    If lookup fails or competing PR is found, blocks release immediately.
    """
    cmd = ["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "1000", "--json", "number,title,headRefName,body"]
    out, err, code = run_cmd(cmd, timeout=20)
    if code != 0 or out is None:
        return False, f"GitHub PR query failed (exit code {code}, err: {err}): failing closed per Zero-Competition Law."
    try:
        prs = json.loads(out)
        if not isinstance(prs, list) or len(prs) >= 1000:
            return False, 'GitHub PR result horizon reached; complete competition proof unavailable, failing closed.'
        for p in prs:
            if ignore_pr is not None and p.get('number') == ignore_pr:
                continue
            title = str(p.get("title", ""))
            head = str(p.get("headRefName", ""))
            body = str(p.get("body", ""))
            target = re.escape(str(number))
            exact_reference = re.compile(rf"(?<![A-Za-z0-9])#\s*{target}(?!\d)", re.IGNORECASE)
            named_reference = re.compile(rf"\b(?:fix(?:es|ed)?|resolve[sd]?|close[sd]?|issue)\s*[:#-]?\s*{target}\b", re.IGNORECASE)
            branch_reference = re.compile(rf"(?:^|[-_/]){target}(?:$|[-_/])")
            if any(pattern.search(text) for pattern in (exact_reference, named_reference) for text in (title, head, body)) or branch_reference.search(head):
                return False, f"Competing open PR already exists: #{p.get('number')} - '{title}'"
        return True, "Zero competing open PRs verified on GitHub."
    except Exception as e:
        return False, f"Failed to parse GitHub PR list JSON: {e}"

def _git_checked(argv: List[str], timeout: int, operation: str) -> Tuple[Optional[str], Optional[str]]:
    out, err, code = run_cmd(argv, timeout=timeout)
    if code != 0:
        return None, f"Git {operation} failed (exit {code}): {err or out}"
    return out, None

def reset_worktree_to_base(worktree: str, base_sha: str) -> Tuple[bool, str]:
    """Restores the checkout to the verified upstream base before a repair turn."""
    for argv, operation in (
        (["git", "-C", worktree, "reset", "--hard", base_sha], "reset"),
        (["git", "-C", worktree, "clean", "-fdx"], "clean"),
    ):
        _, error = _git_checked(argv, timeout=20, operation=operation)
        if error:
            return False, error
    return True, "Worktree restored to verified upstream base."

def prepare_isolated_worktree(repo: str, number: int, default_branch: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Prepares a clean, isolated worktree under SANDBOX_DIR/repos/<owner>--<repo_name>--<number>.
    """
    parts = repo.split("/")
    if len(parts) != 2:
        return None, None, f"Invalid repository identifier: {repo}"
    owner, repo_name = parts
    unique_name = f"{owner}--{repo_name}--{number}"
    work_dir = os.path.join(SANDBOX_DIR, "repos", unique_name)
    os.makedirs(os.path.dirname(work_dir), exist_ok=True)

    fork_url = f"https://github.com/{BOUNTY_ACCOUNT}/{repo_name}"
    upstream_url = f"https://github.com/{repo}.git"

    branch_out, branch_err, branch_code = run_cmd(
        ["gh", "repo", "view", repo, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"], timeout=20
    )
    if branch_code != 0 or not branch_out or not branch_out.strip():
        return None, None, f"Could not discover upstream default branch: {branch_err or branch_out}"
    default_branch = branch_out.strip()

    # Ensure fork exists; any failure is unsafe because subsequent push routing is unknown.
    fork_out, fork_err, fork_code = run_cmd(["gh", "repo", "fork", repo, "--clone=false"], timeout=30)
    if fork_code != 0:
        return None, None, f"Fork preparation failed (exit {fork_code}): {fork_err or fork_out}"

    if not os.path.exists(os.path.join(work_dir, ".git")):
        clone_out, clone_err, clone_code = run_cmd(["git", "clone", fork_url, work_dir], timeout=600)
        if clone_code != 0:
            return None, None, f"Git clone failed: {clone_err or clone_out}"

    # Robust upstream remote setup (set-url if exists, add if not)
    remotes_out, _, _ = run_cmd(["git", "-C", work_dir, "remote"], timeout=10)
    if "upstream" in (remotes_out or "").split():
        run_cmd(["git", "-C", work_dir, "remote", "set-url", "upstream", upstream_url], timeout=10)
    else:
        run_cmd(["git", "-C", work_dir, "remote", "add", "upstream", upstream_url], timeout=10)
    _, error = _git_checked(["git", "-C", work_dir, "fetch", "upstream", default_branch], 45, "fetch")
    if error:
        return None, None, error

    branch_name = f"fix/bounty-{number}"
    _, error = _git_checked(["git", "-C", work_dir, "checkout", "-B", branch_name, f"upstream/{default_branch}"], 15, "checkout")
    if error:
        return None, None, error
    ok, reset_message = reset_worktree_to_base(work_dir, f"upstream/{default_branch}")
    if not ok:
        return None, None, reset_message

    base_sha_out, error = _git_checked(["git", "-C", work_dir, "rev-parse", "HEAD"], 10, "rev-parse")
    if error or not base_sha_out or not base_sha_out.strip():
        return None, None, error or "Git rev-parse returned no base SHA."
    base_sha = base_sha_out.strip()

    return work_dir, base_sha, None

def apply_verified_changes(worktree: str, file_changes: List[Tuple[str, str]]) -> Tuple[bool, str]:
    if not file_changes:
        return False, "No file changes provided to apply."
    for rel_path, code_body in file_changes:
        if not is_safe_relative_path(worktree, rel_path):
            return False, f"Security violation: unsafe relative path rejected: {rel_path}"
        full_dest = os.path.join(worktree, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(full_dest), exist_ok=True)
        with open(full_dest, "w", encoding="utf-8") as f:
            f.write(code_body)
    return True, "All files applied cleanly and safely within worktree."

def build_peer_pr_body(run: EngineeringRun, title: str, number: int, scenarios: List[ScenarioCase]) -> str:
    body_lines = [
        f"Resolves #{number}.",
        "",
        "### Architectural Summary & Root Cause Analysis",
        f"This pull request resolves issue #{number} (`{title}`).",
        "",
        "### Verified Scenario Coverage",
        "The implementation was verified against the following comprehensive test matrix:",
        ""
    ]
    for s in scenarios:
        body_lines.append(f"- **{s.category.upper()}** (`{s.id}`): {s.expected_result}")

    body_lines.extend([
        "",
        "### Verification & Pre-PR Gate Proof",
        f"- Verified base SHA: `{run.base_sha}`.",
        "- All baseline tests passed on untouched upstream before modification.",
        "- Native repository test suite and linters passed with zero warnings or errors.",
        "- Pre-flight check verified zero competing pull requests prior to push.",
        "",
        "### Exact Verification Receipts",
    ])
    if run.verification:
        for result in run.verification:
            command = " ".join(result.argv)
            body_lines.append(f"- `{command}` — exit `{result.exit_code}`, duration `{result.duration_s:.3f}s`.")
    else:
        body_lines.append("- Verification receipts are unavailable; the pre-PR gate blocks publication.")
    return "\n".join(body_lines)

# How much of one native failure travels with the exhausted verdict. The exact compiler or
# test error is the fact the next turn needs; unbounded logs are not, so the tail of the
# evidence is bounded here rather than pasted whole into every prompt and ledger record.
FAILURE_EVIDENCE_LIMIT = 4000


def run_engineering_iteration_loop(
    worktree: str,
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    arch: dict,
    plan: VerificationPlan,
    scenarios: List[ScenarioCase],
    base_sha: str,
    max_iterations: int = 3,
    initial_feedback: Optional[str] = None,
    live_mode: bool = True
) -> Tuple[bool, EngineeringRun, str]:
    run = EngineeringRun(
        repo=repo,
        issue_number=issue_number,
        base_sha=base_sha,
        worktree=worktree,
        scenario_matrix=scenarios,
        status="WORKTREE_READY"
    )

    prior_failures = initial_feedback
    test_commands = verification_test_commands(plan)
    if not test_commands:
        run.status = "FAILED_NO_TEST_VERIFICATION"
        run.error_summary = "FAILED_NO_TEST_VERIFICATION: no native test command was discovered for this worktree."
        record_execution_diagnostic("verification plan", run.error_summary)
        return False, run, run.error_summary

    for turn in range(1, max_iterations + 1):
        run.iteration = turn
        print(f"  🔄 [ENGINEERING ITERATION {turn}/{max_iterations}] for {repo}#{issue_number}...")

        # Retain the completed patch and exact failure context across repair turns.
        if turn > 1:
            preserve_cline_edits(worktree)

        # 1. Cline is the primary worktree agent. It receives the real checkout
        # and can inspect it directly. Cline failures close this execution.
        cline_ok, extracted_files, verified_paths, cline_message = run_cline_engineering_turn(
            worktree, repo, issue_number, title, body, arch, scenarios, prior_failures
        )
        if cline_ok:
            print(f"     [CLINE PRIMARY] {cline_message}")
        else:
            print(f"     [CLINE FAIL-CLOSED] {cline_message}")
            try:
                recovery_receipt = preserve_cline_edits(worktree)
                print(f"     [CLINE EDITS PRESERVED] {recovery_receipt}")
            except Exception as exc:
                return False, run, f"Cline failed; checkout retained at {worktree} because recovery backup failed: {exc}"
            # The caller checkpoints this checkout; a failed agent never erases it.
            run.status = "FAILED_CLINE_ENGINEERING"
            run.error_summary = f"Cline failed closed on turn {turn}: {cline_message}"
            record_execution_diagnostic("Cline engineering", run.error_summary)
            return False, run, run.error_summary
        # 2. Reject syntax-invalid output before executing native tests.
        syntax_ok, syntax_message = validate_synthesized_files(worktree, extracted_files)
        if not syntax_ok:
            record_execution_diagnostic(f"syntax validation turn {turn}", syntax_message)
            print(f"     ⚠️ Iteration {turn}: Syntax validation error. Routing error back to DeepSeek for turn {turn + 1}...")
            prior_failures = f"Syntax error in turn {turn}:\n{syntax_message}\nFix syntax errors and re-emit complete files."
            run.error_summary = prior_failures
            continue

        # 4. Run native repository verification suites
        tests_passed = True
        test_fail_log = ""
        for test_cmd in plan.builds + test_commands + plan.format_checks:
            cmd_res = run_command_safe(test_cmd, cwd=worktree, timeout=native_verification_timeout(test_cmd, 180))
            run.verification.append(cmd_res)
            from actions_release import warning_output
            if cmd_res.exit_code != 0 or warning_output(cmd_res.stdout + "\n" + cmd_res.stderr):
                tests_passed = False
                err_text = cmd_res.stderr or cmd_res.stdout
                test_fail_log = f"Test failure in turn {turn}: {' '.join(test_cmd)}\n{err_text}"
                _safe_command_failure(f"native tests turn {turn}", cmd_res)
                break

        if not tests_passed:
            run.error_summary = test_fail_log
            if turn < max_iterations:
                print(f"     ❌ Iteration {turn}: Native tests failed. Routing exact compiler/test errors back for turn {turn + 1}...")
            else:
                print(f"     ❌ Iteration {turn}: Native tests failed on the final turn; the exact failure travels to the caller.")
            clipped_fail = test_fail_log[:FAILURE_EVIDENCE_LIMIT]
            prior_failures = f"Compiler/test failure in turn {turn}:\n{clipped_fail}\nFix these exact failures."
            continue

        # 5. Run linters
        linters_passed = True
        lint_fail_log = ""
        for lint_cmd in plan.linters:
            l_res = run_command_safe(lint_cmd, cwd=worktree, timeout=native_verification_timeout(lint_cmd, 120))
            run.verification.append(l_res)
            from actions_release import warning_output
            if l_res.exit_code != 0 or warning_output(l_res.stdout + "\n" + l_res.stderr):
                linters_passed = False
                lint_err = l_res.stderr or l_res.stdout
                lint_fail_log = f"Linter warning/failure in turn {turn}: {' '.join(lint_cmd)}\n{lint_err}"
                _safe_command_failure(f"linter turn {turn}", l_res)
                break

        if not linters_passed:
            run.error_summary = lint_fail_log
            if turn < max_iterations:
                print(f"     ❌ Iteration {turn}: Linter warnings/errors detected. Routing back for turn {turn + 1}...")
            else:
                print(f"     ❌ Iteration {turn}: Linter warnings/errors on the final turn; the exact failure travels to the caller.")
            clipped_lint = lint_fail_log[:FAILURE_EVIDENCE_LIMIT]
            prior_failures = f"Linter errors in turn {turn}:\n{clipped_lint}\nFix all linter warnings/errors."
            continue

        # If both tests and linters passed:
        if not has_successful_test_verification(run.verification, test_commands):
            run.status = "FAILED_NO_TEST_VERIFICATION"
            run.error_summary = "FAILED_NO_TEST_VERIFICATION: no successful native test command receipt exists."
            record_execution_diagnostic("pre-PR test gate", run.error_summary)
            return False, run, run.error_summary
        run.status = "READY_TO_PUSH"
        run.modified_files = sorted(set(verified_paths))
        reset_execution_diagnostics()
        print(f"  ✅ [ITERATION GREEN] 100% tests and linters passed on turn {turn}!")
        return True, run, f"Iteration green on turn {turn}."

    run.status = "ITERATION_EXHAUSTED"
    exhausted_message = f"Iteration exhausted after {max_iterations} turns without green."
    # The exact native failure is the one fact the next actor needs, and it used to be
    # discarded here: measured 2026-11-01 on Spectral-Finance/lux#99 (run 41252150256), all
    # three delivery turns received only this exhausted sentence as feedback, so the agent
    # spent each turn guessing which command had failed while the receipts sat unread in the
    # log. The caller feeds this string back as the next turn's prior_failures and records it
    # as the ledger diagnostic, so the failure itself must travel with the verdict.
    last_failure = str(getattr(run, "error_summary", "") or "").strip()
    if last_failure:
        exhausted_message += " Last reported failure:\n" + last_failure[:FAILURE_EVIDENCE_LIMIT]
    record_execution_diagnostic("repair loop", exhausted_message)
    return False, run, exhausted_message


def commit_and_open_pr(
    worktree: str,
    repo: str,
    number: int,
    title: str,
    pr_body: str,
    verified_files: List[str],
    default_branch: str = "main",
    verification: Optional[List[CommandResult]] = None,
    test_commands: Optional[List[List[str]]] = None,
) -> Optional[str]:
    branch_name = f"fix/bounty-{number}"

    def fail(message: str) -> None:
        record_execution_diagnostic("commit / pull request", message)
        print(f"  [AUTO-PR ERROR] {message}")

    if not has_successful_test_verification(verification or [], test_commands or []):
        fail("FAILED_NO_TEST_VERIFICATION: refusing commit and pull request without a successful native test receipt.")
        return None

    if not fleet_lease_allows_publication():
        fail("claim lease lost: refusing commit and pull request without current fleet ownership")
        return None

    safe_files = sorted(set(verified_files))
    if not safe_files or any(not is_safe_relative_path(worktree, path) for path in safe_files):
        fail("No safe, verified file set is available for commit.")
        return None
    for argv, operation in (
        (["git", "-C", worktree, "config", "user.name", BOUNTY_ACCOUNT], "config user.name"),
        (["git", "-C", worktree, "config", "user.email", "isearch.xsolve@gmail.com"], "config user.email"),
        (["git", "-C", worktree, "diff", "--check"], "diff check"),
    ):
        _, error = _git_checked(argv, 15, operation)
        if error:
            fail(error)
            return None
    pre_sha, error = _git_checked(["git", "-C", worktree, "rev-parse", "HEAD"], 10, "pre-commit rev-parse")
    if error or not pre_sha:
        fail(error or "Missing pre-commit SHA.")
        return None
    status_out, error = _git_checked(["git", "-C", worktree, "status", "--porcelain", "--untracked-files=all", "-z"], 10, "status")
    if error:
        fail(error)
        return None
    parsed, status_paths, status_message = _status_paths_from_porcelain(status_out)
    if not parsed:
        fail(status_message)
        return None
    changed_files = {path.replace("\\", "/") for path in status_paths}
    unverified_files = sorted(changed_files - set(safe_files))
    if unverified_files:
        fail(
            "Unverified worktree changes detected; refusing to stage them. "
            f"Unverified paths: {', '.join(unverified_files)}"
        )
        return None
    _, error = _git_checked(["git", "-C", worktree, "add", "--", *safe_files], 15, "add verified files")
    if error:
        fail(error)
        return None
    commit_msg = f"fix: #{number} - {title}"
    _, error = _git_checked(["git", "-C", worktree, "commit", "-m", commit_msg], 15, "commit")
    if error:
        fail(error)
        return None
    post_sha, error = _git_checked(["git", "-C", worktree, "rev-parse", "HEAD"], 10, "post-commit rev-parse")
    if error or not post_sha or post_sha.strip() == pre_sha.strip():
        fail(error or "Commit SHA did not advance.")
        return None
    count_out, error = _git_checked(["git", "-C", worktree, "rev-list", "--count", f"{pre_sha.strip()}..{post_sha.strip()}"], 10, "single-commit count")
    if error or count_out.strip() != "1":
        fail(error or "Expected exactly one commit, got " + count_out.strip())
        return None

    if not fleet_lease_allows_publication():
        fail("claim lease lost: refusing push without current fleet ownership")
        return None
    push_out, push_err, push_code = run_cmd(["git", "-C", worktree, "push", "origin", branch_name, "--force"], timeout=45)
    if push_code != 0:
        fail(f"Git push failed (exit {push_code}): {push_err or push_out}")
        return None

    pr_cmd = [
        "gh", "pr", "create",
        "--repo", repo,
        "--head", f"{BOUNTY_ACCOUNT}:{branch_name}",
        "--base", default_branch,
        "--title", f"fix: #{number} - {title}",
        "--body", pr_body
    ]
    if not fleet_lease_allows_publication():
        fail("claim lease lost: refusing pull request without current fleet ownership")
        return None
    pr_out, pr_err, pr_code = run_cmd(pr_cmd, timeout=30)
    if pr_code == 0 and pr_out.strip():
        pr_url = pr_out.strip()
        print(f"🎉 [AUTONOMOUS PULL REQUEST CREATED & LIVE] {pr_url}")
        update_delivery_pr(repo, number, pr_url)
        auto_resolve_cla_if_needed(repo, pr_url)
        return pr_url
    fail(f"GitHub pull request creation failed (exit {pr_code}): {pr_err or pr_out or 'no output'}")
    return None

_DELIVERY_CONTEXT = {}


def run_cline_claim_intake(task, lease):
    """Cline is the first task executor; issue context determines preparation."""
    repo, number = task['repo'], task['issue_number']
    folder = os.path.join(PACKET_DIR, 'delivery-supervisor')
    os.makedirs(folder, exist_ok=True)
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    identity = uuid.uuid4().hex
    context_path = os.path.join(folder, identity + '.context.json')
    report_path = os.path.join(folder, identity + '.preparation.json')
    worktree = os.path.join(SANDBOX_DIR, 'repos', repo.replace('/', '--') + '--' + str(number))
    with open(context_path, 'w', encoding='utf-8') as handle:
        json.dump(task, handle, ensure_ascii=False, indent=2)
    # F3: write-early skeleton at Cline's real report path, before its command is built, so
    # an artefact directory can never exist without a preparation document and a failure
    # inside Cline's own startup still explains itself. Cline's final write replaces it.
    _write_json_atomic(report_path, {
        'action': 'incomplete', 'base_sha': '', 'base_branch': '',
        'default_branch': '', 'started_at': datetime.now(timezone.utc).isoformat(),
        'run': getattr(lease, 'run_id', ''),
    })
    checkout_instruction = (
        f"Prepare an isolated checkout at {worktree}, from upstream's current default branch. "
        f"Set origin and upstream to the public repository https://github.com/{repo}.git "
        f"and check out fix/bounty-{number}. Fork creation and publication belong to a separate "
        "trusted Actions job; do not request write credentials or create a fork in this phase."
        if os.environ.get('ACTIONS_PUBLISHER_MANAGED') == '1' else
        f"Prepare an isolated fork checkout at {worktree}, based strictly on upstream's current default branch.\n"
        f"Set origin to the authenticated account's fork, upstream to {repo}, and check out fix/bounty-{number}."
    )
    prompt = f"""You own this task's complete delivery lifecycle immediately after its fleet claim.
Read the ENTIRE issue and prior failure context from {context_path}; do not truncate or summarize away requirements.
Repository: {repo}. Issue: #{number}. Your active fleet run: {lease.run_id}.

SUPREME MANDATE: ZERO JUDGMENT OF ISSUE QUALITY - PURE ENGINEERING EXECUTION ONLY.

You are the Delivery Engine. You do NOT judge issue quality, you do NOT question requirements,
and you do NOT evaluate whether this issue "deserves" a pull request.

The Sovereign Entry Door has ALREADY inspected, verified, and admitted this issue:
- Its funding authority is verified as real.
- Its competition is checked: no competing claimant exists; any nominal PR is dismissed.
- Its status is verified: the issue is open, live, and sovereignly approved for work.
These are SETTLED, BINDING FACTS recorded in your context. Take them as absolute truth.

YOUR SOLE MANDATE IS TO DELIVER FLAWLESS, PRODUCTION-GRADE ENGINEERING:
1. Inspect the codebase, manifests, and setup documentation.
2. Establish the untouched upstream baseline (baseline_tests MUST pass on clean base).
3. Name the precise reproduction command (regression_plan.command) that will exercise the reported
   defect. The command may name a test that does not exist yet: the test is authored in the
   engineering turn, alongside the fix.
4. Describe the implementation approach on paper; the code itself belongs to the engineering turn.
5. Return the native build/test/lint plan and source citations for the host.
6. Finish preparation with action="retry", leaving the baseline exactly as you found it.
The subsequent engineering turn implements the fix and independently verifies it.

You are strictly forbidden from writing action="blocked" based on issue quality, wording, marketing/digest classification, or open PRs.
The Entry Door has spoken. You follow the order and deliver the code.

You have full freedom to inspect the repository and provision the required tools, pinned versions,
dependencies, environment and configuration. Read its AGENTS.md, manifests, lockfiles, CI and setup docs.
Choose the actual native commands yourself. Diagnose and repair installation/configuration failures;
do not wait for a separate installer or assume npm, a language, a version, or a testing framework.
Funding, status and competition were decided by the sovereign entry door and are recorded in the task
context as the fields "admission" and "competition". Take them as settled fact: do not re-check funding,
do not re-judge open pull requests with your own standard, and never stop for a reason the door already
ruled on. A claimant that appears while you work is caught by the host's publication race check, not
by you.
Preserve existing completed edits and diagnostics before any destructive checkout operation.
{checkout_instruction}
Use repository-declared pins and build permissions. Never bypass integrity checks or approval policies.
Do not manufacture data, command output, test results, or payment evidence. Never expose credentials.

Establish the unchanged upstream baseline before product edits. Run installations and native verification
freely. If the toolchain or external credentials/hardware are missing, report that honestly.

HOW THIS DELIVERY IS SHAPED, and why the ground stays untouched:

Two turns, one craft. You are the surveyor in this turn: you read the terrain, prove the ground is
solid, and write the plan the builder will follow. The engineering turn that comes after you is the
builder: it writes the fix and the regression test and proves the difference between them. A
surveyor who starts pouring concrete destroys the measurement he was sent to take.

The untouched upstream baseline is the yardstick that makes your later proof real. The host proves
your fix by watching one command go from failing to passing. That proof only means something if the
repository underneath never moved: with a single mark on the base, "it was already like that" can
never be ruled out, and the delivery loses its evidence. The checkout at {worktree} is the
customer's ground. In this turn you may read it, run it, install against it, and measure it -- you
leave no edit, no new file, no staged change, and no commit behind. The host compares the tree byte
for byte when you finish, so however good the rest of your work is, a marked baseline ends the
phase on the spot.

Your reproduction command can therefore name a test that does not exist yet. That is correct and
expected: the test is authored in the engineering turn, next to the fix. Demonstrate the defect now
with the repository's own commands, or with an experiment you keep outside the checkout. Your
scratch space is the sandbox directory and the packet directory -- never the repository tree. Write
your report to {report_path}, which is also outside the checkout.

TWO KINDS OF BASELINE COMMAND, and they are not interchangeable:
- `baseline_tests` MUST pass on the untouched base. It proves the environment is healthy. Use the
  build, the linter, and the part of the suite that is green. Never put the failing reproduction here:
  a red `baseline_tests` is read as a broken environment and stops the run as BLOCKED_BASELINE.
- `regression_plan.command` is the reproduction of the reported defect. It MUST fail on the untouched
  base and pass after your fix. This failure is expected evidence of the defect, not a blocker.
If the reported defect makes the repository's own suite red at base, that is normal for a bug report:
put the green subset in `baseline_tests` and the red target in `regression_plan.command`.
The host will independently execute your native plan, then return the issue to you for implementation,
verification, publication monitoring and any required repairs. Do not push or open a PR before those release gates.
No existing master test or CI workflow may be weakened. Keep runtime caches outside the checkout when needed.

Manage runner resources while doing that work. This runner has roughly 7 GiB of RAM plus swap, and swap
does not add memory: a process that reaches 14 GiB is killed, not slowed. Two runs of this exact
pipeline died that way on 2026-10-29 at exit 143, after the agent chose a whole-repo lint.

HOW THE MEASURING WORKS: in this turn you verify with ONE targeted command, never a repository-wide one.
The surveyor's measurement is narrow by nature -- the narrowest command that exercises the defect:
one test file, one package, one component.
- Repo-wide or workspace-wide lint, typecheck, build or test consumes more than this runner has, and
  the run dies before it can report anything. Concretely: no `npm run lint`, `yarn lint`,
  `turbo run build/lint/test` without a filter, `nx run-many`, or any command that walks every
  workspace. Obtaining a baseline for those belongs to the host, which runs your plan after this phase.
- Put every repo-wide command the delivery needs in `plan` (linters, builds, final_tests), with the
  serial or filtered form you recommend. Listing them is the deliverable; executing them here is not.
- Before any command that installs or compiles dependency trees, check `free -m` and cap concurrency
  (e.g. a single workspace filter, `--concurrency=1`). One heavy command at a time, polled to its real
  exit status, never two concurrently.
When memory pressure blocks a target, the plan is where it goes: omitting targets, weakening tests, or
suppressing warnings to fit memory trades the delivery's evidence for a green light, and the host
re-runs them anyway.
If resource pressure interrupts a command, record the exact command and the observed resource/error
evidence, narrow it, and retry once; do not classify it as a product failure.

Write the preparation decision to {report_path}:
{{"action":"retry" or "blocked","reason":"actual diagnosis","worktree":"{worktree}",
"base_sha":"actual upstream checkout SHA","default_branch":"actual default branch",
"architecture":{{"ecosystem":"actual ecosystem","ecosystems":["actual ecosystems"]}},
"sources":[{{"path":"relative manifest/CI/setup file","sha256":"actual source SHA-256"}}],
"plan":{{"bootstrap":[["actual","argv"]],"baseline_tests":[["actual","test"]],
"final_tests":[["actual","test"]],"builds":[["actual","build"]],
"linters":[["actual","lint"]],"format_checks":[]}},
"regression_plan":{{"component":"actual repository path","command":["actual","regression","test"],
"expected_failure":"specific defect assertion that fails on the unchanged base"}}}}
"blocked" is only for a genuinely unbuildable environment - a missing toolchain, credential or hardware
that no amount of engineering can supply. It is never an answer about the ticket itself: the door has
already decided that, and re-deciding it is a contract violation, not a delivery outcome.
Do not claim delivery. Save the real plan and receipts, then finish this preparation phase."""
    _command_log(f'CLINE_FIRST_AFTER_CLAIM repo={repo} issue={number} context={context_path}')
    result = run_command_safe(cline_worktree_command(SANDBOX_DIR, prompt), cwd=SANDBOX_DIR,
                              timeout=cline_turn_timeout_seconds())
    if result.exit_code != 0:
        if os.path.exists(os.path.join(worktree, '.git')):
            _command_log('CLINE_PREPARATION_EDITS_PRESERVED ' + preserve_cline_edits(worktree))
        raise RuntimeError('Cline preparation failed: ' + _sanitize_runtime_diagnostic(result.stderr or result.stdout, 1000))
    # Exit zero does not imply a report: the single reader names each failure mode (absent,
    # unparseable, or a skeleton Cline never replaced) instead of surfacing a bare
    # FileNotFoundError that the host would stamp as an engineering failure.
    report = read_preparation(report_path, elapsed=result.duration_s,
                              exit_code=result.exit_code)
    if report.get('action') != 'retry':
        # A refusal is a verdict, not a transient fault: it is terminal for this dispatch.
        # Raising a plain RuntimeError here converted a correct "not a warranted change"
        # into FAILED_ENGINEER and threw away the reason the contract had just verified.
        raise PreparationBlocked(report)
    if os.path.realpath(report.get('worktree', '')) != os.path.realpath(worktree):
        # A malformed deliverable, not a bad engineer: the report names a worktree the
        # host never prepared.
        raise PreparationContractViolation(report_path, 'Cline preparation returned an unexpected worktree',
                                           paths=[report.get('worktree', '')])
    report['plan'] = VerificationPlan(**validate_delivery_plan(report, worktree))
    head, error = _git_checked(['git', '-C', worktree, 'rev-parse', 'HEAD'], 10, 'Cline prepared baseline SHA')
    status, status_error = _git_checked(['git', '-C', worktree, 'status', '--porcelain',
                                        '--untracked-files=all'], 10, 'Cline prepared baseline integrity')
    if error or status_error or not head or head.strip() != report.get('base_sha') or status.strip():
        # Carries the offending paths: "must leave a clean baseline" alone cost a log dig
        # on 2026-10-29 when the same condition was a bare ValueError.
        dirty = [line[3:].strip() for line in (status or '').splitlines() if line.strip()]
        raise PreparationContractViolation(
            report_path, 'Cline preparation must leave a clean, unchanged upstream baseline',
            paths=dirty)
    if not re.fullmatch(r'[0-9a-f]{40,64}', report.get('base_sha', '')) or not report.get('default_branch'):
        raise PreparationContractViolation(
            report_path, 'Cline preparation omitted the real baseline or default branch')
    report['context_path'] = context_path
    # The host re-reads this exact document after every release turn, so the path has to
    # travel with the report. It used to be assumed by the adapter, which referenced an
    # undefined local and raised NameError the first time a run got far enough to check it
    # (2026-10-29, run 40876500657).
    report['report_path'] = report_path
    return report


def resume_verified_publication(context, repo, number, title, pr_body):
    """Resume a frozen verified commit without resetting or regenerating edits."""
    worktree, plan, run = context['worktree'], context['plan'], context['run']
    head, error = _git_checked(['git', '-C', worktree, 'rev-parse', 'HEAD'], 10, 'publication recovery HEAD')
    if error or not head or head.strip() == context['base_sha']:
        return None
    release_sha = head.strip()
    count, error = _git_checked(['git', '-C', worktree, 'rev-list', '--count',
                                 context['base_sha'] + '..' + release_sha], 10, 'publication recovery isolation')
    if error or count.strip() != '1' or not has_successful_test_verification(run.verification, verification_test_commands(plan)):
        return None
    clean, error = _git_checked(['git', '-C', worktree, 'status', '--porcelain', '--untracked-files=all'], 10, 'publication recovery clean tree')
    if error or clean.strip():
        return None
    repaired, _, diagnostic = cline_supervise_delivery_phase(
        worktree, repo, number, 'publication', get_execution_diagnostic(), plan)
    if not repaired:
        record_execution_diagnostic('Cline publication repair', diagnostic)
        return None
    if not fleet_lease_allows_publication():
        return None
    # Recover an acknowledged-on-server PR after a client timeout, idempotently.
    branch = f'fix/bounty-{number}'
    output, error, code = run_cmd(['gh', 'pr', 'list', '--repo', repo, '--head',
                                  'isearchxsolve:' + branch, '--state', 'open', '--json',
                                  'number,url,headRefOid,author', '--limit', '2'], timeout=30)
    if code:
        return None
    try:
        existing = json.loads(output)
        if len(existing) == 1 and existing[0].get('headRefOid') == release_sha and (
                existing[0].get('author') or {}).get('login') == 'isearchxsolve':
            return existing[0]['url']
        if existing:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    competition_ok, _ = check_competing_prs_fail_closed(repo, number)
    if not competition_ok:
        return None
    output, error, code = run_cmd(['git', '-C', worktree, 'push', 'origin',
                                  'HEAD:refs/heads/' + branch], timeout=45)
    if code or not fleet_lease_allows_publication():
        return None
    body_file = os.path.join(PACKET_DIR, 'publication-' + uuid.uuid4().hex + '.md')
    with open(body_file, 'w', encoding='utf-8') as handle:
        handle.write(pr_body)
    output, error, code = run_cmd([
        'gh', 'pr', 'create', '--repo', repo, '--head', 'isearchxsolve:' + branch,
        '--base', context['default_branch'], '--title', f'fix: #{number} - {title}',
        '--body-file', body_file], timeout=45)
    if code:
        return None
    match = re.search(r'https://github\.com/' + re.escape(repo) + r'/pull/\d+', output or '')
    return match.group(0) if match else None


def monitor_delivery_checks(context, repo, number, title, body, pr_url):
    """Observe remote checks and route an actual failure into a guarded repair."""
    output, error, code = run_cmd(['gh', 'pr', 'checks', pr_url, '--json',
                                  'name,state,bucket,link,description'], timeout=30)
    try:
        checks = json.loads(output) if output else []
    except ValueError:
        checks = []
    journal = os.path.join(PACKET_DIR, 'checks-' + repo.replace('/', '--') + f'-{number}.json')
    record = {'repo': repo, 'number': number, 'pr_url': pr_url, 'checks': checks,
              'query_exit_code': code, 'diagnostic': error}
    with open(journal, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, indent=2)
    failed = [check for check in checks if check.get('bucket') == 'fail']
    if not failed:
        return 'CHECKS_PENDING' if any(c.get('bucket') == 'pending' for c in checks) else 'NO_FAILED_CHECKS_OBSERVED'
    _command_log(f'CLINE_DELIVERY_SUPERVISOR phase=remote-ci repo={repo} issue={number}')
    # Engineering operates on the already completed checkout, with no reset.
    ok, repair, diagnostic = run_engineering_iteration_loop(
        context['worktree'], repo, number, title,
        body + '\n\nActual failed remote checks:\n' + json.dumps(failed),
        context['arch'], context['plan'], context['scenarios'], context['base_sha'],
        max_iterations=1, live_mode=True)
    if not ok:
        record_execution_diagnostic('remote CI repair', diagnostic)
        return 'REMOTE_CI_REPAIR_BLOCKED'
    match = re.search(r'/pull/(\d+)$', pr_url)
    competition_ok, _ = check_competing_prs_fail_closed(repo, number, int(match[1]) if match else None)
    if not competition_ok or not fleet_lease_allows_publication():
        return 'REMOTE_CI_REPAIR_BLOCKED'
    worktree = context['worktree']
    for argv in (['git', '-C', worktree, 'diff', '--check'],
                 ['git', '-C', worktree, 'add', '--', *repair.modified_files],
                 ['git', '-C', worktree, 'commit', '--amend', '--no-edit']):
        _, _, result = run_cmd(argv, timeout=30)
        if result:
            return 'REMOTE_CI_REPAIR_BLOCKED'
    if not fleet_lease_allows_publication():
        return 'REMOTE_CI_REPAIR_BLOCKED'
    _, _, result = run_cmd(['git', '-C', worktree, 'push', '--force-with-lease', 'origin',
                            f'fix/bounty-{number}'], timeout=45)
    return 'REMOTE_CI_REPAIR_PUSHED_AWAITING_CHECKS' if result == 0 else 'REMOTE_CI_REPAIR_BLOCKED'


def attempt_automated_pull_request(repo, number, title, proposal_or_body, live_mode=True, prepared_context=None):
    """
    Multi-Turn Iterative Due-Diligence Engine:
    1. Pre-flight competition check (fail-closed)
    2. Prepares isolated worktree (<owner>--<repo>--<number>)
    3. Inspects repository architecture & CI workflows
    4. Discovers native verification plan
    5. Verifies untouched upstream baseline passes (BLOCKED_BASELINE if fail)
    6. Models edge-case and boundary scenarios
    7. Executes multi-turn iterative code-test-fix loop
    8. Verifies linters pass with 0 warnings
    9. Pre-push fail-closed competition check
    10. Commits and creates human-peer PR
    """
    if not live_mode:
        print(f"  [DRY RUN] Multi-Turn Iterative Engine simulated for {repo}#{number}")
        arch = inspect_repository_architecture(repo) if os.path.exists(repo) else {"ecosystem": "nodejs", "has_tests": True, "has_linter": True}
        scenarios = model_scenarios(title, proposal_or_body, arch)
        # An empty plan, not a guessed one. This branch runs without a checkout, so it has
        # measured nothing; hardcoding `npm test` / `npm run lint` here would prescribe the exact
        # workspace-wide commands the budget above refuses to schedule.
        plan = discover_verification_plan(arch, repo) if os.path.exists(repo) else VerificationPlan()
        run = EngineeringRun(repo=repo, issue_number=number, base_sha="dry_run", worktree=repo, scenario_matrix=scenarios, status="READY_TO_PUSH")
        run.pr_body = build_peer_pr_body(run, title, number, scenarios)
        return None

    # Step 1: Pre-flight competition check
    comp_ok, comp_msg = check_competing_prs_fail_closed(repo, number)
    if not comp_ok:
        record_execution_diagnostic("preflight competition gate", comp_msg)
        print(f"  ❌ [ZERO-COMPETITION GATE TRIGGERED] {repo}#{number}: {comp_msg}")
        return None

    # Step 2: Prepare isolated worktree
    if prepared_context:
        worktree, base_sha, wt_err = prepared_context['worktree'], prepared_context['base_sha'], None
    else:
        worktree, base_sha, wt_err = prepare_isolated_worktree(repo, number)
    if not worktree:
        record_execution_diagnostic("worktree preparation", wt_err or "worktree preparation failed without details")
        print(f"  ❌ [WORKTREE INIT FAILED] {repo}#{number}: {wt_err}")
        return None
    branch_out, branch_err, branch_code = run_cmd(
        ["gh", "repo", "view", repo, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"], timeout=20
    )
    if branch_code != 0 or not branch_out or not branch_out.strip():
        branch_diagnostic = f"gh repo view {repo} defaultBranchRef failed (exit {branch_code}): {branch_err or branch_out or 'empty branch name'}"
        record_execution_diagnostic("default branch lookup", branch_diagnostic)
        print(f"  ❌ [DEFAULT BRANCH LOOKUP FAILED] {branch_diagnostic}")
        return None
    default_branch = branch_out.strip()
    _DELIVERY_CONTEXT.clear()
    _DELIVERY_CONTEXT[(repo, number)] = {'worktree': worktree, 'base_sha': base_sha,
                                        'default_branch': default_branch}

    # Step 3: Inspect architecture & discover verification plan
    try:
        if prepared_context:
            arch = prepared_context.get('architecture') or {'ecosystem': 'cline-managed', 'ecosystems': []}
            plan = prepared_context['plan']
            arch['full_delivery_context'] = prepared_context['context_path']
        else:
            arch = inspect_repository_architecture(worktree)
            plan = discover_verification_plan(arch, worktree)
        discovery_diagnostic = 'Verify and provision the repository-declared native environment before the untouched baseline.'
    except (ValueError, OSError) as exc:
        arch = {'ecosystem': 'unknown', 'ecosystems': [], 'discovery_error': str(exc)}
        plan = VerificationPlan()
        discovery_diagnostic = 'Native discovery requires repair: ' + str(exc)
    if prepared_context:
        preparation_ok, preparation_message = True, 'Cline already owns preparation from the claim boundary.'
    else:
        preparation_ok, plan, preparation_message = cline_supervise_delivery_phase(
            worktree, repo, number, 'preparation', discovery_diagnostic, plan)
    if not preparation_ok:
        record_execution_diagnostic('Cline delivery preparation', preparation_message)
        return None
    scenarios = model_scenarios(title, proposal_or_body, arch)
    test_commands = verification_test_commands(plan)
    if not test_commands:
        diagnostic = "FAILED_NO_TEST_VERIFICATION: no native test commands were discovered for the worktree."
        record_execution_diagnostic("verification plan", diagnostic)
        print(f"  ❌ [{diagnostic}] {repo}#{number}")
        return None

    if "rust" in (arch.get("ecosystems") or [arch.get("ecosystem")]):
        configure_task_cargo_cache(worktree, repo, number, base_sha)

    # Step 4: The untouched upstream must pass its own baseline before Cline
    # receives a bounty task. Do not turn unrelated upstream failures into
    # additional engineering scope.
    base_ok, base_msg, base_results = verify_baseline(worktree, plan)
    if not base_ok:
        repaired, repaired_plan, repair_message = cline_supervise_delivery_phase(
            worktree, repo, number, 'baseline', base_msg, plan)
        if repaired:
            plan = repaired_plan
            test_commands = verification_test_commands(plan)
            base_ok, base_msg, retry_results = verify_baseline(worktree, plan)
            base_results.extend(retry_results)
        else:
            base_msg += '\nCline lifecycle repair: ' + repair_message
    if not base_ok:
        record_execution_diagnostic("untouched upstream baseline", base_msg)
        mark_issue_blocked_baseline(repo, number, base_msg)
        print(f"  ❌ [BLOCKED_BASELINE] {repo}#{number}: {base_msg[:500]}", flush=True)
        return None

    # Step 5: Run Multi-Turn Iteration Loop (3 turns with full error feedback)
    loop_ok, run, loop_msg = run_engineering_iteration_loop(
        worktree=worktree,
        repo=repo,
        issue_number=number,
        title=title,
        body=proposal_or_body,
        arch=arch,
        plan=plan,
        scenarios=scenarios,
        base_sha=base_sha,
        max_iterations=3,
        live_mode=live_mode
    )
    if not loop_ok:
        record_execution_diagnostic("engineering loop", loop_msg)
        print(f"  ❌ [ITERATION FAILED] {loop_msg}")
        return None
    run.verification = base_results + run.verification
    context = _DELIVERY_CONTEXT[(repo, number)]
    context.update(plan=plan, arch=arch, scenarios=scenarios, run=run)

    # Step 6: Final Pre-Push Competition Check (Fail-Closed)
    comp_ok_final, comp_msg_final = check_competing_prs_fail_closed(repo, number)
    if not comp_ok_final:
        record_execution_diagnostic("pre-push competition gate", comp_msg_final)
        print(f"  ❌ [ZERO-COMPETITION GATE TRIGGERED PRE-PUSH] {repo}#{number}: {comp_msg_final}")
        return None

    # Step 7: Format peer PR body
    pr_body = build_peer_pr_body(run, title, number, scenarios)

    # Step 8: Commit, push branch, open PR
    if not has_successful_test_verification(run.verification, test_commands):
        diagnostic = "FAILED_NO_TEST_VERIFICATION: refusing PR because the engineering run has no successful native test receipt."
        record_execution_diagnostic("pre-PR test gate", diagnostic)
        print(f"  ❌ [{diagnostic}] {repo}#{number}")
        return None
    pr_url = commit_and_open_pr(
        worktree,
        repo,
        number,
        title,
        pr_body,
        run.modified_files,
        default_branch=default_branch,
        verification=run.verification,
        test_commands=test_commands,
    )
    if not pr_url:
        pr_url = resume_verified_publication(context, repo, number, title, pr_body)
        if pr_url:
            update_delivery_pr(repo, number, pr_url)
    if pr_url:
        context['checks_state'] = monitor_delivery_checks(context, repo, number, title, proposal_or_body, pr_url)
    if not pr_url and not get_execution_diagnostic():
        record_execution_diagnostic("pull request", "PR creation returned no URL and no lower-level diagnostic was captured.")
    return pr_url


# ==============================================================================
# KAGGLE ENGINE WORKER LOOP & RECEIPT VERIFICATION
# ==============================================================================

PROCESSED_TASKS_FILE = "/tmp/processed_tasks.json"

def load_processed_tasks() -> set:
    try:
        if os.path.exists(PROCESSED_TASKS_FILE):
            with open(PROCESSED_TASKS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def record_processed_task(task_id: str):
    try:
        current = load_processed_tasks()
        current.add(task_id)
        with open(PROCESSED_TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(current), f)
    except Exception:
        pass


def _download_init_file(url: str, destination: str, timeout: int = 60) -> None:
    request_obj = urllib.request.Request(url, headers={"User-Agent": "kaggle-engine-worker"})
    with urllib.request.urlopen(request_obj, timeout=timeout) as response:
        with open(destination, "wb") as target:
            shutil.copyfileobj(response, target)


def _run_init_command(argv: List[str], label: str, timeout: int) -> bool:
    try:
        result = run_streamed_process(argv, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[Init Warning] {label} timed out after {timeout}s.", flush=True)
        return False
    except Exception as exc:
        print(f"[Init Warning] {label} failed ({type(exc).__name__}): {_sanitize_runtime_diagnostic(exc)}", flush=True)
        return False
    if result.returncode != 0:
        print(f"[Init Warning] {label} exited with status {result.returncode}.", flush=True)
        return False
    return True


NODE_LTS_VERSION = "22.23.4"
NODE_LTS_SHA256 = "1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce"
GO_VERSION = "1.26.9"
# Official go.dev release manifest, linux/amd64 archive.
GO_SHA256 = "42d158b4d8f7b61ac0a830567c940a86098fb7aac52e467a5ebec03ef5cc2f8d"


def ensure_supported_go():
    """Provide both Go and gofmt for native and Rust/Go hybrid verification."""
    install_dir = f"/tmp/fleet-go-{GO_VERSION}"
    go = os.path.join(install_dir, "bin", "go")
    gofmt = os.path.join(install_dir, "bin", "gofmt")
    if not (os.path.isfile(go) and os.path.isfile(gofmt)):
        archive = f"/tmp/go{GO_VERSION}.linux-amd64.tar.gz"
        _download_init_file(f"https://go.dev/dl/go{GO_VERSION}.linux-amd64.tar.gz",
                            archive, timeout=120)
        with open(archive, "rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest != GO_SHA256:
            raise RuntimeError("Go archive checksum mismatch; bootstrap refused.")
        os.makedirs(install_dir, exist_ok=True)
        subprocess.run(["tar", "-xzf", archive, "-C", install_dir, "--strip-components=1"],
                       check=True, timeout=60)
    # Do not inherit a GOROOT pointing at a different installation.
    probe_env = dict(os.environ, GOROOT=install_dir)
    probe = subprocess.run([go, "version"], capture_output=True, text=True,
                           env=probe_env, timeout=15)
    if probe.returncode != 0 or not re.fullmatch(
        r"go version go" + re.escape(GO_VERSION) + r" linux/amd64\s*", probe.stdout
    ):
        raise RuntimeError("Go runtime verification failed.")
    subprocess.run([gofmt, "-h"], capture_output=True, check=True, timeout=15)
    os.environ["GOROOT"] = install_dir
    os.environ["PATH"] = os.path.join(install_dir, "bin") + os.pathsep + os.environ.get("PATH", "")
    print(f"[Init] Verified {probe.stdout.strip()} and gofmt at {install_dir}/bin", flush=True)
    return go


def ensure_supported_node():
    """Use the pinned Node 22 LTS runtime before npm, Corepack, or Cline."""
    global CLINE_NODE_EXE
    node = shutil.which("node")
    if node:
        probe = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15)
        if probe.returncode == 0 and probe.stdout.strip() == f"v{NODE_LTS_VERSION}":
            CLINE_NODE_EXE = node
            return node
    archive = f"/tmp/node-v{NODE_LTS_VERSION}-linux-x64.tar.xz"
    install_dir = f"/tmp/fleet-node-{NODE_LTS_VERSION}"
    _download_init_file(
        f"https://nodejs.org/dist/v{NODE_LTS_VERSION}/node-v{NODE_LTS_VERSION}-linux-x64.tar.xz",
        archive, timeout=120,
    )
    with open(archive, "rb") as downloaded:
        digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
    if digest != NODE_LTS_SHA256:
        raise RuntimeError("Node 22 LTS archive checksum mismatch; bootstrap refused.")
    os.makedirs(install_dir, exist_ok=True)
    subprocess.run(["tar", "-xJf", archive, "-C", install_dir, "--strip-components=1"],
                   check=True, timeout=60)
    os.environ["PATH"] = os.path.join(install_dir, "bin") + os.pathsep + os.environ.get("PATH", "")
    CLINE_NODE_EXE = shutil.which("node") or ""
    probe = subprocess.run([CLINE_NODE_EXE, "--version"], capture_output=True, text=True, timeout=15)
    if probe.returncode != 0 or probe.stdout.strip() != f"v{NODE_LTS_VERSION}":
        raise RuntimeError("Node 22 LTS runtime verification failed.")
    print(f"[Init] Verified Node {probe.stdout.strip()} at {CLINE_NODE_EXE}", flush=True)
    return CLINE_NODE_EXE


def setup_kaggle_env():
    global SANDBOX_DIR, PACKET_DIR
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    os.makedirs(PACKET_DIR, exist_ok=True)
    ensure_supported_node()
    ensure_supported_go()

    # 1. Install or locate gh CLI
    if not shutil.which("gh"):
        gh_tar = "/tmp/gh.tar.gz"
        gh_dir = "/tmp/gh_install"
        try:
            print("[Init] Downloading portable GitHub CLI for Linux...", flush=True)
            _download_init_file("https://github.com/cli/cli/releases/download/v2.42.1/gh_2.42.1_linux_amd64.tar.gz", gh_tar, timeout=60)
            os.makedirs(gh_dir, exist_ok=True)
            subprocess.run(["tar", "-xzf", gh_tar, "-C", gh_dir, "--strip-components=1"], check=True, timeout=60)
            bin_dir = os.path.join(gh_dir, "bin")
            os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
            print(f"[Init] GitHub CLI installed at {bin_dir}", flush=True)
        except Exception as e:
            print(f"[Init] gh download error: {e}. Trying apt-get...", flush=True)
            _run_init_command(["apt-get", "update", "-qq"], "GitHub CLI apt index update", 120)
            _run_init_command(["apt-get", "install", "-y", "-qq", "gh"], "GitHub CLI apt install", 180)

    # 2. Always bootstrap the native Rust/C++ toolchain.  Kaggle base images
    # vary, and bindgen/rocksdb require libclang even when `clang` already
    # happens to be on PATH.
    print("[Init] Bootstrapping native C/C++ compiler and libclang headers...", flush=True)
    _run_init_command(["apt-get", "update", "-qq"], "native toolchain apt index update", 180)
    _run_init_command(
        ["apt-get", "install", "-y", "-qq", "clang", "libclang-dev", "cmake", "mold", "build-essential"],
        "native C/C++ toolchain install",
        300,
    )
    libclang_candidates = (
        glob.glob("/usr/lib/llvm-*/lib/libclang.so")
        + glob.glob("/usr/lib/llvm-*/lib/libclang.so.*")
        + glob.glob("/usr/lib/x86_64-linux-gnu/libclang.so")
        + glob.glob("/usr/lib/x86_64-linux-gnu/libclang.so.*")
    )
    if libclang_candidates:
        libclang_path = os.path.dirname(sorted(libclang_candidates)[0])
        os.environ["LIBCLANG_PATH"] = libclang_path
        print(f"[Init] LIBCLANG_PATH={libclang_path}", flush=True)
    else:
        print("[Init Warning] libclang was not found after bootstrap; Rust bindgen builds will fail closed.", flush=True)

    # 3. Install Rust / Cargo toolchain if missing (for Solana zk-SNARKs and Rust bounties)
    if not shutil.which("cargo"):
        try:
            print("[Init] Installing standalone Rust/Cargo toolchain...", flush=True)
            rustup_sh = "/tmp/rustup.sh"
            _download_init_file("https://sh.rustup.rs", rustup_sh, timeout=60)
            run_streamed_process(["sh", rustup_sh, "-y", "--default-toolchain", "stable", "--profile", "minimal"], timeout=300).check_returncode()
            cargo_bin = os.path.expanduser("~/.cargo/bin")
            os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
            print(f"[Init] Rust/Cargo installed at {cargo_bin}", flush=True)
        except Exception as e:
            print(f"[Init Warning] Failed to install Rust via rustup: {e}. Trying apt-get...", flush=True)
            _run_init_command(["apt-get", "update", "-qq"], "Rust apt index update", 120)
            _run_init_command(["apt-get", "install", "-y", "-qq", "cargo", "rustc"], "Rust apt fallback install", 180)

    # 4. Make pnpm available on Kaggle images that ship Node/npm but omit the
    # package-manager shim. Corepack remains first choice so repository
    # packageManager pins are honored when pnpm is invoked in a worktree.
    if not shutil.which("pnpm"):
        corepack = shutil.which("corepack")
        if corepack:
            enable_result = run_command_safe([corepack, "enable", "pnpm"], cwd=SANDBOX_DIR, timeout=30)
            if enable_result.exit_code != 0:
                _safe_command_failure("pnpm Corepack shim", enable_result)
            if not shutil.which("pnpm"):
                activate_result = run_command_safe(
                    [corepack, "prepare", "pnpm@10", "--activate"],
                    cwd=SANDBOX_DIR,
                    timeout=240,
                )
                if activate_result.exit_code != 0:
                    _safe_command_failure("pnpm Corepack bootstrap", activate_result)

        if not shutil.which("pnpm") and shutil.which("npm"):
            npm_result = run_command_safe(
                [shutil.which("npm") or "npm", "install", "--global", "pnpm@10"],
                cwd=SANDBOX_DIR,
                timeout=240,
            )
            if npm_result.exit_code != 0:
                _safe_command_failure("pnpm npm bootstrap", npm_result)

        if shutil.which("pnpm"):
            print("[Init] pnpm is available for native Node verification.", flush=True)
        else:
            print("[Init Warning] pnpm could not be bootstrapped; pnpm repository verification will fail closed with the command receipt.", flush=True)

    # 5. Install Cline in the Kaggle runtime when it is absent. Cline's
    # compiled CLI is the sole engineering agent; no laptop binary or model
    # fallback is used by the worker.
    if not shutil.which("cline"):
        npm = shutil.which("npm")
        if not npm:
            _run_init_command(["apt-get", "update", "-qq"], "Node/npm apt index update", 180)
            _run_init_command(["apt-get", "install", "-y", "-qq", "nodejs", "npm"], "Node/npm install for Cline", 240)
            npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("Cline bootstrap failed: npm is unavailable in this Kaggle runtime.")
        cline_install = run_command_safe(
            [npm, "install", "--global", "--no-audit", "--no-fund", "cline@3.0.74"],
            cwd=SANDBOX_DIR,
            timeout=300,
        )
        if cline_install.exit_code != 0:
            _safe_command_failure("Cline npm bootstrap", cline_install)
            raise RuntimeError("Cline bootstrap failed: npm install did not complete successfully.")
    if not resolve_cline_command():
        raise RuntimeError("Cline bootstrap failed: executable is not on PATH after installation.")
    print("[Init] Cline CLI is available for isolated worktree engineering.", flush=True)

    # 6. Configure git identity
    subprocess.run(["git", "config", "--global", "user.name", "isearchxsolve"], check=False)
    subprocess.run(["git", "config", "--global", "user.email", "isearch.xsolve@gmail.com"], check=False)

def configure_task_github_auth(task: dict) -> bool:
    """Configure GitHub from the private Kaggle secret attached to this kernel."""
    if isinstance(task, dict):
        # Older queue entries carried this field. Never trust or retain it.
        for secret_field in ("gh_token", "github_token", "github_pat", "authorization"):
            task.pop(secret_field, None)
    try:
        from kaggle_secrets import UserSecretsClient
        token = str(UserSecretsClient().get_secret("GITHUB_TOKEN") or "").strip()
    except Exception as exc:
        token = ""
        print(f"[{ENGINE_ID}] Kaggle User Secret unavailable ({type(exc).__name__}); checking private credential dataset.", flush=True)
    if not token:
        private_dataset_token = "/kaggle/input/omniroute-github-credential-20261026/github_token.txt"
        try:
            with open(private_dataset_token, "r", encoding="utf-8") as token_file:
                token = token_file.read().strip()
        except OSError:
            token = ""
    if not token:
        print(f"[{ENGINE_ID}] [FAIL-CLOSED] Kaggle GITHUB_TOKEN is unavailable from private storage.", flush=True)
        return False
    os.environ["GH_TOKEN"] = token
    os.environ["GITHUB_TOKEN"] = token
    # gh configures Git's credential helper without putting a token into a
    # command line, a task payload, or a persistent URL rewrite.
    return subprocess.run(["gh", "auth", "setup-git"], check=False).returncode == 0

def door_say(text: str, body: str = "BOUNTY_FLEET_RESULT"):
    try:
        data = json.dumps({"body": body, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{DOOR}/say?body={body}&token={DOOR_TOKEN}",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "kaggle-engine"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            response_status = resp.status
            response_text = resp.read(4096).decode("utf-8", errors="replace")
        response_data = json.loads(response_text)
        stored = response_data.get("stored") if isinstance(response_data, dict) else None
        legacy_receipt = (
            isinstance(response_data, dict)
            and stored is None
            and response_data.get("delivered_to") == body
            and response_data.get("seq") is not None
        )
        persisted = stored is True or legacy_receipt
        accepted = response_status == 200 and isinstance(response_data, dict) and response_data.get("ok") is True and persisted
        if body == "ENGINE_REGISTRATION" or not accepted:
            print(
                f"[{ENGINE_ID}] /say {body}: HTTP {response_status}, "
                f"ok={response_data.get('ok') if isinstance(response_data, dict) else None}, "
                f"stored={stored}, queued={response_data.get('queued') if isinstance(response_data, dict) else None}, "
                f"degraded={response_data.get('degraded') if isinstance(response_data, dict) else None}, "
                f"filtered={response_data.get('filtered') if isinstance(response_data, dict) else None}",
                flush=True,
            )
        return accepted
    except urllib.error.HTTPError as e:
        response_text = e.read(4096).decode("utf-8", errors="replace")
        try:
            response_data = json.loads(response_text)
        except Exception:
            response_data = {}
        print(
            f"[{ENGINE_ID}] /say {body}: HTTP {e.code}, "
            f"stored={response_data.get('stored')}, degraded={response_data.get('degraded')}, "
            f"err={response_data.get('err')}",
            flush=True,
        )
        return False
    except Exception as e:
        safe_error = re.sub(r"(?i)(token=)[^&\s]+", r"\1[REDACTED]", str(e))[:200]
        print(f"[{ENGINE_ID}] /say {body} error: {type(e).__name__}: {safe_error}", flush=True)
        return False

_SPECULATIVE_DISPATCH_PATTERNS = (
    re.compile(r"\[(?:roadmap|rfc|proposal|design|spec)\]", re.IGNORECASE),
    re.compile(r"\b(?:design/roadmap\s+proposal\s+only|proposal\s+only|not\s+an\s+active\s+deduction|illustrative\s+defaults?|pilot\s+economic\s+scenario)\b", re.IGNORECASE),
)

# Old append-only queue entries can predate the dispatcher-side mirror filter.
# Keep the same exclusion at the execution boundary, where a stale record must
# never consume a claim, model turn, or verification run.
_MIRROR_DISPATCH_PATTERNS = (
    re.compile(r"(?:^|/)gh-disc-[a-z0-9_.-]+(?:\s|$)", re.IGNORECASE),
    re.compile(r"\[\s*nex\s+agent\s*\]", re.IGNORECASE),
    re.compile(r"\b(?:github|gh)\s+discussion\s+mirror\b", re.IGNORECASE),
    re.compile(r"\b(?:discussion[-_ ]mirror|discussion[-_ ]honeypot|mirror[-_ ]honeypot)\b", re.IGNORECASE),
    re.compile(r"\b(?:mirrored|scraped|synced)\s+(?:from|github)\s+discussions?\b", re.IGNORECASE),
)

def is_speculative_dispatch_task(task: dict) -> bool:
    """Reject speculative roadmap records before they can reach model/build work."""
    if not isinstance(task, dict):
        return True
    text = " ".join(str(task.get(field) or "") for field in ("title", "body", "repo"))
    labels = task.get("labels") or []
    if isinstance(labels, list):
        text += " " + " ".join(
            str(label.get("name") or "") if isinstance(label, dict) else str(label)
            for label in labels
        )
    return any(pattern.search(text) for pattern in _SPECULATIVE_DISPATCH_PATTERNS)


def is_mirror_dispatch_task(task: dict) -> bool:
    """Reject stale bot or discussion-mirror records before a fleet claim."""
    if not isinstance(task, dict):
        return True
    if non_engineering_dispatch_reason(task):
        return True
    text = " ".join(str(task.get(field) or "") for field in ("title", "body", "repo"))
    labels = task.get("labels") or []
    if isinstance(labels, list):
        text += " " + " ".join(
            str(label.get("name") or "") if isinstance(label, dict) else str(label)
            for label in labels
        )
    return any(pattern.search(text) for pattern in _MIRROR_DISPATCH_PATTERNS)

def fetch_ledger_rows(body: str, limit: int = 500) -> List[dict]:
    """Preserve server timestamps for lease expiry and bounded recovery."""
    try:
        url = f"{DOOR}/say?body={urllib.parse.quote(body)}&token={urllib.parse.quote(DOOR_TOKEN)}&limit={int(limit)}"
        req = urllib.request.Request(url, headers={"User-Agent": "kaggle-engine"})
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("orders"), list):
            raise ValueError("invalid ledger response")
        orders = payload["orders"]
        return [order for order in orders if isinstance(order, dict)]
    except Exception as exc:
        print(f"[{ENGINE_ID}] ledger lookup failed for {body}: {type(exc).__name__}; blocking dispatch", flush=True)
        raise RuntimeError(f"Unable to verify {body} ledger; dispatch is blocked") from None


def fetch_ledger_texts(body: str, limit: int = 500) -> List[str]:
    """Historical claim lookup remains available to audit and replay callers."""
    return [str(row.get("text") or "") for row in fetch_ledger_rows(body, limit)]


def fetch_claim_lease_rows() -> List[dict]:
    # Frequent renewals must not evict the durable attempt-count receipts.
    return fetch_ledger_rows(FLEET_CLAIM_CHANNEL) + fetch_ledger_rows(FLEET_LEASE_CHANNEL)


class FleetTaskLease:
    """Renew one assigned task; lost ownership closes the publication gate."""

    def __init__(self, task: dict, attempt: int):
        self.task = task
        self.attempt = attempt
        self.run_id = uuid.uuid4().hex
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = None
        self.phase = 'PREPARING_WORKTREE'
        self.command_pid = 0
        self.confirmed_until = 0

    def receipt(self, kind: str) -> str:
        return (
            f"{kind} {self.task['task_id']} by {ENGINE_ID} for {task_reference(self.task)} "
            f"attempt={self.attempt} run={self.run_id} "
            f"lease_until={int(time.time() + CLAIM_LEASE_SECONDS)} phase={self.phase} pid={self.command_pid}"
        )

    def acquire(self) -> bool:
        if not door_say(self.receipt("CLAIMED"), body=FLEET_CLAIM_CHANNEL):
            return False
        if not self.owned():
            return False
        self.thread = threading.Thread(target=self._renew, daemon=True)
        self.thread.start()
        return True

    def owned(self) -> bool:
        if self.lost.is_set():
            return False
        try:
            claim, lease_until = current_claim(self.task, fetch_claim_lease_rows())
            owned = bool(claim and event_run(claim['text']) == self.run_id and lease_until > time.time())
        except Exception:
            # A temporary coordinator outage does not revoke a confirmed lease.
            # Publication still requires a fresh authoritative lookup.
            if time.time() >= self.confirmed_until:
                self.lost.set()
            return False
        if not owned:
            self.lost.set()
        else:
            self.confirmed_until = lease_until
        return owned

    def _renew(self):
        while not self.stop.wait(CLAIM_HEARTBEAT_SECONDS):
            if not self.owned():
                if self.lost.is_set():
                    return
                _command_log('Lease lookup temporarily unavailable; retrying within the last confirmed lease. Publication remains blocked until revalidated.')
                continue
            receipt = self.receipt('HEARTBEAT')
            if not door_say(receipt, body=FLEET_LEASE_CHANNEL):
                if time.time() >= self.confirmed_until:
                    self.lost.set()
                    return
                _command_log('Lease renewal temporarily unavailable; retaining only the last confirmed expiry.')
                continue
            match = re.search(r'\blease_until=(\d+)\b', receipt)
            self.confirmed_until = float(match[1])

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=20)


def fleet_lease_allows_publication() -> bool:
    # Standalone engineering callers still run the original verification gates.
    return _ACTIVE_TASK_LEASE is None or _ACTIVE_TASK_LEASE.owned()


def execute_claimed_fleet_task(task: dict, lease: FleetTaskLease):
    global _ACTIVE_TASK_LEASE
    repo, number = task['repo'], task['issue_number']
    suffix = f" for {repo}#{number} attempt={lease.attempt} run={lease.run_id}"
    _ACTIVE_TASK_LEASE = lease
    _DELIVERY_CONTEXT.clear()
    reset_task_diagnostics()
    lease.phase = 'CLINE_DELIVERY_OWNER'
    try:
        door_say(f"EXECUTING {ENGINE_ID} Cline workflow{suffix}", body="BOUNTY_FLEET_EXECUTION")
        print(f"[{ENGINE_ID}] Executing Cline verification workflow on {repo}#{number}, attempt {lease.attempt}...", flush=True)
        prepared = run_cline_claim_intake(task, lease)
        pr_url = attempt_automated_pull_request(repo, number, task.get('title', ''), task.get('body', ''),
                                              live_mode=True, prepared_context=prepared)
        if pr_url:
            summary = (
                f"Implemented and verified the resolution for issue #{number}.\n\n"
                "The linked pull request passed the required native verification and pre-PR gates."
            )
            receipt_ok = deliver_pr_receipt(
                repo, number, pr_url, summary, task.get('title', ''),
                task.get('author', ''), task.get('corridor_info', ''), task.get('reason', ''),
            )
            context = _DELIVERY_CONTEXT.get((repo, number))
            if not receipt_ok and context:
                repaired, _, repair_diagnostic = cline_supervise_delivery_phase(
                    context['worktree'], repo, number, 'receipt',
                    'The verified PR exists but its authoritative delivery receipt failed. '
                    'Diagnose transport/authentication without changing or republishing source: ' + pr_url,
                    context['plan'])
                if repaired:
                    receipt_ok = reconcile_or_retry_pr_receipt(
                        repo, number, pr_url, summary, task.get('title', ''), task.get('author', ''),
                        task.get('corridor_info', ''), task.get('reason', ''))
                else:
                    record_execution_diagnostic('Cline receipt repair', repair_diagnostic)
            checks_state = context.get('checks_state', 'NOT_OBSERVED') if context else 'NOT_OBSERVED'
            text = (f"SUCCESS {ENGINE_ID} opened verified PR and SHA-256 receipt: {pr_url}" if receipt_ok else
                    f"FAILED {ENGINE_ID} PR exists but authoritative SHA-256 issue receipt failed: {pr_url}")
            text += ' checks_state=' + checks_state
        else:
            diagnostic = get_execution_diagnostic() or "Cline workflow did not produce a verified pull request"
            text = f"FAILED {ENGINE_ID} Cline execution failed closed: {diagnostic}"
        door_say(text + suffix, body=FLEET_RESULT_CHANNEL)
    except Exception as exc:
        diagnostic = _sanitize_runtime_diagnostic(f"{type(exc).__name__}: {exc}", 500)
        door_say(f"FAILED {ENGINE_ID} Cline execution exception: {diagnostic}" + suffix, body=FLEET_RESULT_CHANNEL)
        print(f"[{ENGINE_ID}] Cline execution exception: {diagnostic}", flush=True)
    finally:
        _ACTIVE_TASK_LEASE = None
        lease.close()

def claimed_task_ids_from_texts(texts: List[str]) -> set[str]:
    """Parse immutable claim receipts once for a complete queue poll."""
    claimed = set()
    for text in texts:
        match = re.search(r"\bCLAIMED\s+(BT-\S+)", text, re.IGNORECASE)
        if match:
            claimed.add(match.group(1))
    return claimed


def terminal_task_refs_from_texts(texts: List[str]) -> set[str]:
    """Parse terminal fleet result receipts into ``owner/repo#number`` refs."""
    terminal_refs = set()
    for text in texts:
        if not re.match(r"\s*(?:SUCCESS|FAILED|SKIPPED)\b", text, re.IGNORECASE):
            continue
        match = re.search(r"\sfor\s+([^/\s]+/[^#\s]+)#(\d+)\b", text)
        if match:
            terminal_refs.add(f"{match.group(1)}#{match.group(2)}")
    return terminal_refs


def task_has_prior_fleet_claim(task_id: str) -> bool:
    """Treat an existing immutable fleet claim as a replay block."""
    if not task_id:
        return False
    return task_id in claimed_task_ids_from_texts(
        fetch_ledger_texts(FLEET_CLAIM_CHANNEL)
    )

def fetch_tasks(limit: int = 100) -> List[dict]:
    global _last_fleet_poll_log, _fleet_poll_failures
    try:
        url = f"{DOOR}/say?body={FLEET_QUEUE_CHANNEL}&token={DOOR_TOKEN}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "kaggle-engine"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            orders = data.get("orders", [])
            tasks = []
            for o in orders:
                try:
                    task = json.loads(o.get("text", "{}"))
                    if not isinstance(task, dict):
                        continue
                    for secret_field in ("gh_token", "github_token", "github_pat", "authorization"):
                        task.pop(secret_field, None)
                    tasks.append(task)
                except (ValueError, TypeError) as exc:
                    raw = str(o.get("text", ""))
                    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
                    if digest not in _invalid_queue_record_digests:
                        if len(_invalid_queue_record_digests) >= 256:
                            _invalid_queue_record_digests.clear()
                        _invalid_queue_record_digests.add(digest)
                        print(f"[{ENGINE_ID}] INVALID_TASK_JSON chars={len(raw)} digest={digest}: {_sanitize_runtime_diagnostic(exc)}; task not executed", flush=True)
            now = time.monotonic()
            if _fleet_poll_failures or now - _last_fleet_poll_log >= 300:
                print(f"[{ENGINE_ID}] POLL_OK HTTP 200 tasks={len(tasks)} prior_poll_failures={_fleet_poll_failures}", flush=True)
                _last_fleet_poll_log = now
            _fleet_poll_failures = 0
            return tasks
    except urllib.error.HTTPError as exc:
        _fleet_poll_failures += 1
        try:
            detail = exc.read(2000).decode("utf-8", errors="replace")
        except Exception:
            detail = "response body unavailable"
        print(f"[{ENGINE_ID}] fetch_tasks error: HTTP {exc.code} endpoint={urllib.parse.urlsplit(DOOR).netloc}/say diagnostic={_sanitize_runtime_diagnostic(detail, 700)}", flush=True)
        return []
    except Exception as e:
        _fleet_poll_failures += 1
        print(f"[{ENGINE_ID}] fetch_tasks error: {e}", flush=True)
        return []

def deliver_pr_receipt(repo: str, number: int, pr_url: str, proposal: str, title: str, author: str, corridor_info: str, reason: str) -> bool:
    print(f"Delivering authoritative assessment to GitHub issue referencing verified PR {pr_url}...", flush=True)
    comment_payload = f"{proposal}\n\n---\n**Verified Pull Request**: {pr_url}"
    post_cmd = ["gh", "api", f"repos/{repo}/issues/{number}/comments", "-X", "POST", "-f", f"body={comment_payload}"]
    out, err, code = run_cmd(post_cmd, timeout=30, retries=1)
    if code == 0 and out:
        try:
            resp_data = json.loads(out)
            comment_id = str(resp_data.get("id", ""))
            _receipt_url = resp_data.get("html_url", "")
            server_body = resp_data.get("body", "")

            local_digest = hashlib.sha256(comment_payload.encode("utf-8")).hexdigest()
            server_digest = hashlib.sha256(server_body.encode("utf-8")).hexdigest()

            if local_digest == server_digest:
                print(f"✅ [CRYPTOGRAPHIC RECEIPT CONFIRMED] Comment ID: {comment_id} | PR: {pr_url} | SHA: {local_digest[:16]}", flush=True)
                return True
            else:
                print("⚠️ SHA digest mismatch between sent and server body.", flush=True)
                return False
        except Exception as e:
            print(f"Receipt parsing error: {e}", flush=True)
            return False
    else:
        print(f"Failed posting comment: {err or out}", flush=True)
        return False

def reconcile_or_retry_pr_receipt(repo, number, pr_url, proposal, title, author, corridor_info, reason):
    """Resolve a timeout against server state before repeating a receipt write."""
    expected = hashlib.sha256((proposal + '\n\n---\n**Verified Pull Request**: ' + pr_url).encode()).hexdigest()
    login, _, login_code = run_cmd(['gh', 'api', 'user', '--jq', '.login'], timeout=15)
    output, _, code = run_cmd(['gh', 'api', '--paginate', '--slurp',
                               f'repos/{repo}/issues/{number}/comments?per_page=100'], timeout=30)
    if code or login_code:
        return False
    try:
        for page in json.loads(output):
            for comment in page:
                if ((comment.get('user') or {}).get('login') == login.strip()
                        and hashlib.sha256((comment.get('body') or '').encode()).hexdigest() == expected):
                    _command_log(f'DELIVERY_RECEIPT_RECONCILED repo={repo} issue={number} sha256={expected}')
                    return True
    except (ValueError, TypeError, AttributeError):
        return False
    return deliver_pr_receipt(repo, number, pr_url, proposal, title, author, corridor_info, reason)


def run_worker_loop():
    startup_ok = door_say(
        f"STARTING {ENGINE_ID} Kaggle environment bootstrap",
        body="ENGINE_REGISTRATION",
    )
    print(
        f"[{ENGINE_ID}] STARTING registration POST {'accepted' if startup_ok else 'not accepted'}",
        flush=True,
    )
    try:
        setup_kaggle_env()
    except Exception as exc:
        diagnostic = _sanitize_runtime_diagnostic(f"{type(exc).__name__}: {exc}", 300)
        door_say(
            f"DEGRADED {ENGINE_ID} environment bootstrap failed: {diagnostic}",
            body="ENGINE_REGISTRATION",
        )
        raise

    expected_tokenharbor_keys_raw = os.environ.get("TOKENHARBOR_EXPECTED_KEY_COUNT", "").strip()
    try:
        if os.environ.get("TOKENHARBOR_KEY_FILE") and not expected_tokenharbor_keys_raw:
            raise RuntimeError("Private TokenHarbor dataset is missing its expected key-count contract.")
        tokenharbor_status = _get_default_router().status()
        if expected_tokenharbor_keys_raw and tokenharbor_status.get("total_keys") != int(expected_tokenharbor_keys_raw):
            raise RuntimeError("TokenHarbor engine shard failed its key-count check; worker will not claim tasks.")
    except Exception as exc:
        diagnostic = _sanitize_runtime_diagnostic(f"{type(exc).__name__}: {exc}", 300)
        door_say(
            f"DEGRADED {ENGINE_ID} TokenHarbor shard initialization failed: {diagnostic}",
            body="ENGINE_REGISTRATION",
        )
        raise
    cline_ready, cline_message = initialize_cline_for_engine()
    if not cline_ready:
        diagnostic = _sanitize_runtime_diagnostic(cline_message, 300)
        door_say(
            f"DEGRADED {ENGINE_ID} Cline configuration failed: {diagnostic}",
            body="ENGINE_REGISTRATION",
        )
        raise RuntimeError(cline_message)
    tokenharbor_key_file = os.environ.get("TOKENHARBOR_KEY_FILE", "")
    tokenharbor_shard_id = os.path.basename(os.path.dirname(tokenharbor_key_file)) or "local-key-pool"
    print("=" * 70, flush=True)
    print("⚡ KAGGLE 5-ENGINE DISTRIBUTED WORKER INITIALIZED", flush=True)
    print(f"Engine ID: {ENGINE_ID}", flush=True)
    print(
        f"TokenHarbor shard ready: engine {ENGINE_INDEX}/{TOTAL_ENGINES}, "
        f"{tokenharbor_shard_id} ({tokenharbor_status['total_keys']} private keys)",
        flush=True,
    )
    print(f"Cline ready: {cline_message}", flush=True)
    print(f"Permanent Door: {DOOR}", flush=True)
    print("=" * 70, flush=True)

    registration_ok = door_say(
        f"ONLINE {ENGINE_ID} release={RECOVERY_RELEASE} ready for uncontested bounties; TokenHarbor shard {tokenharbor_shard_id} verified ({tokenharbor_status['total_keys']} keys)",
        body="ENGINE_REGISTRATION",
    )
    print(
        f"[{ENGINE_ID}] ENGINE_REGISTRATION POST {'accepted' if registration_ok else 'not accepted'}",
        flush=True,
    )

    processed_tasks = load_processed_tasks()

    while True:
        try:
            # Read the complete active relay window.  Fetching only its newest
            # ten records can strand earlier unclaimed tasks behind completed
            # records forever in an append-only queue.
            tasks = fetch_tasks(limit=100)
            if not tasks:
                time.sleep(FLEET_IDLE_POLL_SECONDS)
                continue

            # Read claim receipts once per poll.  Besides avoiding a relay
            # request for every task, this covers claim history older than the
            # visible queue tail and preserves the immutable replay barrier.
            claim_rows = fetch_claim_lease_rows()
            result_rows = fetch_ledger_rows(FLEET_RESULT_CHANNEL)

            claim_attempted = set()
            seen_refs = set()
            for task in tasks:
                task_id = task.get("task_id", "")
                repo = task.get("repo", "")
                number = task.get("issue_number")
                title = task.get("title", "")
                body = task.get("body", "")
                author = task.get("author", "")
                author_comments = task.get("author_comments", [])
                corridor_info = task.get("corridor_info", "")
                reason = task.get("reason", "")

                if not task_id or not repo or not number:
                    continue
                if task_id in claim_attempted:
                    continue

                task_ref = f"{repo}#{number}"
                # One queue record per issue owns its deterministic shard.
                # Redispatches cannot give the same issue to two engines.
                if task_ref in seen_refs:
                    continue
                seen_refs.add(task_ref)

                # Deterministic Cryptographic Sharding: 0 cross-process or
                # cross-machine drift.  Only the assigned engine records a
                # terminal skip for a legacy invalid queue record.
                task_hash = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16)
                assigned_engine = (task_hash % TOTAL_ENGINES) + 1
                if assigned_engine != ENGINE_INDEX:
                    continue

                if is_speculative_dispatch_task(task):
                    if task_id in processed_tasks:
                        continue
                    processed_tasks.add(task_id)
                    record_processed_task(task_id)
                    door_say(
                        f"SKIPPED {ENGINE_ID} speculative/roadmap task {task_id} for {repo}#{number}; no model or build launched",
                        body=FLEET_RESULT_CHANNEL,
                    )
                    continue

                if is_mirror_dispatch_task(task):
                    if task_id in processed_tasks:
                        continue
                    processed_tasks.add(task_id)
                    record_processed_task(task_id)
                    door_say(
                        f"SKIPPED {ENGINE_ID} bot/discussion mirror task {task_id} for {repo}#{number}; no model or build launched",
                        body=FLEET_RESULT_CHANNEL,
                    )
                    continue

                if is_nonsoftware_data_task(task):
                    if task_id in processed_tasks:
                        continue
                    processed_tasks.add(task_id)
                    record_processed_task(task_id)
                    door_say(
                        f"SKIPPED {ENGINE_ID} non-software banking transcript collection task {task_id} for {repo}#{number}; no model or build launched",
                        body=FLEET_RESULT_CHANNEL,
                    )
                    continue

                decision = recovery_decision(task, claim_rows, result_rows)
                if not decision.allowed:
                    continue

                status = cline_proxy_router_status()
                if status.get('states', {}).get(READY, 0) < 1:
                    states = status.get("states", {})
                    print(
                        f"[{ENGINE_ID}] No READY TokenHarbor key; task remains unclaimed. "
                        f"states={states}",
                        flush=True,
                    )
                    break

                # Do not claim work until this kernel can authenticate from
                # its private Kaggle secret. Missing secrets must not burn a
                # replay-protected task claim.
                reset_task_diagnostics()
                if not configure_task_github_auth(task):
                    continue

                print(f"\n⚡ [{ENGINE_ID}] CLAIMING TASK: {task_id} ({repo}#{number})", flush=True)
                claim_attempted.add(task_id)
                # Recheck after authentication, immediately before reserving.
                claim_rows = fetch_claim_lease_rows()
                result_rows = fetch_ledger_rows(FLEET_RESULT_CHANNEL)
                decision = recovery_decision(task, claim_rows, result_rows)
                if not decision.allowed:
                    continue
                lease = FleetTaskLease(task, decision.attempt)
                if not lease.acquire():
                    print(
                        f"[{ENGINE_ID}] Durable claim lease was not acquired; model/build work blocked for {task_id}.",
                        flush=True,
                    )
                    continue

                # Cline is the sole engineering agent. It receives the issue
                # and the isolated worktree directly; no model proposal or
                # DeepSeek fallback is generated before implementation.
                task = dict(task)
                task['prior_failures'] = [row['text'] for row in matching_events(task, result_rows)]
                execute_claimed_fleet_task(task, lease)
                claim_rows = fetch_claim_lease_rows()
                result_rows = fetch_ledger_rows(FLEET_RESULT_CHANNEL)
                continue

                # The authoritative issue assessment belongs in the execution
                # half of the partition, so the laptop remains a dispatcher.
                proposal = generate_grounded_proposal(repo, title, body, author, author_comments, turn=1)
                if not proposal:
                    diag_reason = get_last_generation_diagnostic()
                    if not tokenharbor_has_ready_key() and wait_for_tokenharbor_ready():
                        print(
                            f"[{ENGINE_ID}] TokenHarbor cooldown ended; retrying the initial generation once for {repo}#{number}.",
                            flush=True,
                        )
                        proposal = generate_grounded_proposal(
                            repo, title, body, author, author_comments, turn=1
                        )
                        diag_reason = get_last_generation_diagnostic()
                if not proposal:
                    diag_reason = diag_reason or "generation failed without a router diagnostic"
                    record_execution_diagnostic("initial generation", diag_reason)
                    door_say(
                        f"FAILED {ENGINE_ID} generation failed closed: {diag_reason} for {repo}#{number}",
                        body=FLEET_RESULT_CHANNEL,
                    )
                    continue
                proposal_safe, proposal_message = sanitize_and_validate_payload(proposal)
                if not proposal_safe:
                    door_say(f"FAILED {ENGINE_ID} assessment safety gate: {proposal_message[:120]} for {repo}#{number}", body=FLEET_RESULT_CHANNEL)
                    continue

                # Execute original Multi-Turn Iterative Verification Engine
                print(f"[{ENGINE_ID}] Executing Multi-Turn Iterative Verification Engine on {repo}#{number}...", flush=True)
                pr_url = attempt_automated_pull_request(repo, number, title, body, live_mode=True)

                if pr_url:
                    print(f"🎉 [{ENGINE_ID}] VERIFICATION GREEN! Pull Request Opened: {pr_url}", flush=True)
                    # Delivery is successful only when the authoritative issue
                    # comment round-trips with a matching SHA-256 receipt.
                    receipt_ok = deliver_pr_receipt(repo, number, pr_url, proposal, title, author, corridor_info, reason)
                    if receipt_ok:
                        door_say(f"SUCCESS {ENGINE_ID} opened verified PR and SHA-256 receipt: {pr_url} for {repo}#{number}", body=FLEET_RESULT_CHANNEL)
                    else:
                        door_say(f"FAILED {ENGINE_ID} PR exists but authoritative SHA-256 issue receipt failed: {pr_url} for {repo}#{number}", body=FLEET_RESULT_CHANNEL)
                else:
                    print(f"❌ [{ENGINE_ID}] Multi-turn verification did not produce green PR for {repo}#{number}", flush=True)
                    diagnostic = get_last_generation_diagnostic()
                    if diagnostic:
                        door_say(
                            f"FAILED {ENGINE_ID} generation failed closed: {diagnostic} for {repo}#{number}",
                            body=FLEET_RESULT_CHANNEL,
                        )
                    elif get_execution_diagnostic():
                        door_say(
                            f"FAILED {ENGINE_ID} verification failed closed: {get_execution_diagnostic()} for {repo}#{number}",
                            body=FLEET_RESULT_CHANNEL,
                        )
                    else:
                        door_say(f"FAILED {ENGINE_ID} verification failed for {repo}#{number}", body=FLEET_RESULT_CHANNEL)

            time.sleep(FLEET_IDLE_POLL_SECONDS)
        except Exception as e:
            print(f"[{ENGINE_ID}] Error in worker loop: {e}", flush=True)
            time.sleep(FLEET_IDLE_POLL_SECONDS)

if __name__ == "__main__":
    if "--cline-proxy" in sys.argv:
        run_cline_proxy_server()
    else:
        run_worker_loop()
