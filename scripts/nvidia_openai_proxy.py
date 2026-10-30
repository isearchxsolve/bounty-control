"""OpenAI-compatible endpoint in front of the NVIDIA NIM key pool.

Cline speaks the OpenAI wire protocol; NIM does too, but Cline needs one stable base URL and a
key that never changes, while the real pool rotates and retires revoked keys. This proxy is that
stable face: Cline points at http://127.0.0.1:8099/v1 with any placeholder key and every request
is served by whichever NVIDIA key is healthy.

Same contract as the engine's gateway, so both paths measure the same brain.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nvidia_router import DEFAULT_MODEL, NvidiaRouter  # noqa: E402

ROUTER = NvidiaRouter(model=os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL))


def _sse_frames(completion: dict, model: str) -> bytes:
    """Encode a whole OpenAI completion as the delta frames a streaming client expects.

    Measured failure: sending the completion object as one frame makes Cline report
    'Model returned empty response', because a streaming reader looks at choices[].delta and
    finds no content there. Content, tool calls and the terminator are therefore all emitted.
    """
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    chunk_id = completion.get("id") or "chatcmpl-nvidia-proxy"
    created = completion.get("created")

    def frame(document: dict) -> bytes:
        return b"data: " + json.dumps(document).encode("utf-8") + b"\n\n"

    def chunk(delta: dict, finish=None) -> dict:
        return {"id": chunk_id, "object": "chat.completion.chunk", "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    frames = [frame(chunk({"role": "assistant"}))]
    content = message.get("content")
    if content:
        frames.append(frame(chunk({"content": content})))
    tool_calls = message.get("tool_calls")
    if tool_calls:
        indexed = []
        for position, call in enumerate(tool_calls):
            entry = dict(call)
            entry["index"] = position
            indexed.append(entry)
        frames.append(frame(chunk({"tool_calls": indexed})))
    finish = choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop")
    frames.append(frame(chunk({}, finish)))
    frames.append(b"data: [DONE]\n\n")
    return b"".join(frames)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout clean for the request receipts
        return

    def _json(self, status: int, document: dict) -> None:
        body = json.dumps(document).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json(200, {"object": "list", "data": [
                {"id": ROUTER.model, "object": "model", "owned_by": "nvidia"}]})
            return
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._json(200, {"ok": True, **ROUTER.status()})
            return
        self._json(404, {"error": {"message": f"no route {self.path}"}})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": {"message": f"no route {self.path}"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError) as exc:
            self._json(400, {"error": {"message": f"unreadable request: {exc}"}})
            return

        # Cline asks for a stream; the router answers whole completions and the client side
        # re-streams them, exactly as the engine gateway already does.
        asked_stream = bool(payload.get("stream"))
        ok, completion, model, error = ROUTER.chat_completion(payload, timeout=600)
        if not ok:
            # A failed brain must be visible to the agent, never a silent empty success.
            self._json(502, {"error": {"message": error, "type": "nvidia_pool_exhausted"}})
            return

        completion.setdefault("model", model)
        if not asked_stream:
            self._json(200, completion)
            return

        body = _sse_frames(completion, model)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    port = int(os.environ.get("NVIDIA_PROXY_PORT", "8099"))
    if not ROUTER._slots:
        print("NO_KEYS: set NVIDIA_KEYS_JSON or NVIDIA_API_KEY before starting", flush=True)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"NVIDIA_PROXY up on http://127.0.0.1:{port}/v1 model={ROUTER.model} "
          f"keys={len(ROUTER._slots)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
