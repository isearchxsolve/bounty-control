"""Set the Worker origin to a live, receipt-verified local fleet ledger tunnel."""
import argparse
import email.parser
import email.policy
import hashlib
import json
from pathlib import Path
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = "c95d86ef4985346cae29bcd4dbfc67af"
BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/omniroute-relay"
RELAY_TOKEN = "GOLD24"


def api_headers():
    config = tomllib.loads(Path("C:/Users/Admin/AppData/Roaming/xdg.config/.wrangler/config/default.toml").read_text())
    return {"Authorization": "Bearer " + config["oauth_token"]}


def request_json(url, headers=None, data=None):
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; fleet-origin-rotator/1.0)"}
    request_headers.update(headers or {})
    payload = None if data is None else json.dumps(data, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=payload, headers=request_headers, method="GET" if data is None else "POST")
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def get_live(headers):
    with urllib.request.urlopen(urllib.request.Request(BASE + "/settings", headers=headers), timeout=30) as response:
        settings = json.load(response)["result"]
    with urllib.request.urlopen(urllib.request.Request(BASE, headers=headers), timeout=30) as response:
        content_type, raw = response.headers["Content-Type"], response.read()
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + raw)
    files = {}
    for part in message.iter_parts():
        name = part.get_filename() or part.get_param("name", header="content-disposition")
        if name:
            files[name] = part.get_payload(decode=True)
    return settings, files


def normalized_bindings(bindings):
    return [binding for binding in bindings if binding.get("name") != "FLEET_RELAY_ORIGIN"]


def check_origin(origin):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise RuntimeError("origin must be a bare HTTPS URL")
    normalized = f"https://{parsed.netloc}"
    health = request_json(normalized + "/fleet/health?token=" + urllib.parse.quote(RELAY_TOKEN, safe=""))
    if health.get("ready") is not True or health.get("service") != "fleet-local-ledger" or health.get("storage") != "sqlite":
        raise RuntimeError("candidate tunnel does not reach a healthy SQLite fleet relay")
    return normalized


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="bare HTTPS origin from the verified live tunnel")
    parser.add_argument("--fresh-epoch", action="store_true",
                        help="route a documented fresh SQLite epoch while retaining the old DO as an archive")
    args = parser.parse_args()
    origin = check_origin(args.origin)

    receipt_path = ROOT / "scratch/fleet_local_cutover_receipt.json"
    if not receipt_path.is_file():
        raise RuntimeError("a verified fleet cutover receipt is required before enabling fleet routing")
    cutover = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected_mode = "fresh_epoch" if args.fresh_epoch else "migrated"
    if cutover.get("passed") is not True or cutover.get("mode") != expected_mode:
        raise RuntimeError(f"cutover receipt must confirm mode={expected_mode}")
    if args.fresh_epoch and (cutover.get("stale_snapshot_replayed") is not False
                             or cutover.get("historical_reconciliation") != "pending_after_cloudflare_daily_reset"):
        raise RuntimeError("fresh-epoch receipt does not preserve the historical reconciliation boundary")

    receipt = json.loads((ROOT / "scratch/relay_patch_verification/v10_output/relay_syntax_receipt.json").read_text())
    if receipt.get("passed") is not True:
        raise RuntimeError("Kaggle verification receipt is not fully green")
    repair = ROOT / "scratch/relay_coordinator_repair"
    checks = {item["module"]: item for item in receipt["checks"]}
    source_hashes = {}
    for name in ("film_vault.js", "web_job_coordinator.js", "worker.js"):
        path = repair / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if name not in checks or checks[name].get("exit_code") != 0 or actual != checks[name].get("sha256"):
            raise RuntimeError(f"Kaggle source receipt mismatch: {name}")
        source_hashes[name] = actual

    headers = api_headers()
    settings, live_files = get_live(headers)
    for name, expected in source_hashes.items():
        if name not in live_files or hashlib.sha256(live_files[name]).hexdigest() != expected:
            raise RuntimeError(f"live Worker source differs from verified artifact: {name}")
    recorded = json.loads((ROOT / "scratch/cloudflare_worker_settings.json").read_text())["result"]
    if normalized_bindings(settings.get("bindings", [])) != recorded.get("bindings", []):
        raise RuntimeError("non-origin Worker bindings differ from the recorded baseline")

    origin_bindings = [binding for binding in settings.get("bindings", []) if binding.get("name") == "FLEET_RELAY_ORIGIN"]
    old_origin = origin_bindings[0].get("text") if origin_bindings else None
    if old_origin == origin:
        edge = request_json("https://omniroute-relay.omniroute-fleet-kd.workers.dev/fleet/health?token=" + RELAY_TOKEN)
        if edge.get("ready") is not True:
            raise RuntimeError("Worker is configured for this origin but edge health did not pass")
        result = {"success": True, "changed": False, "origin": origin, "edge_ready": True,
                  "data_mode": expected_mode, "historical_reconciliation": cutover.get("historical_reconciliation")}
        (ROOT / "scratch/fleet_origin_update_receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return

    bindings = []
    for binding in settings.get("bindings", []):
        if binding["type"] in ("secret_text", "secret_key") or binding.get("name") == "FLEET_RELAY_ORIGIN":
            continue
        if binding["type"] == "durable_object_namespace":
            bindings.append({key: binding[key] for key in ("type", "name", "class_name", "script_name", "environment") if key in binding})
        else:
            bindings.append(binding)
    bindings.append({"type": "plain_text", "name": "FLEET_RELAY_ORIGIN", "text": origin})
    metadata = {
        "main_module": "worker.js", "bindings": bindings,
        "keep_bindings": ["secret_text", "secret_key"],
        "compatibility_date": settings["compatibility_date"],
        "compatibility_flags": settings.get("compatibility_flags", []),
        "usage_model": settings.get("usage_model", "standard"),
        "logpush": settings.get("logpush", False),
        "tail_consumers": settings.get("tail_consumers", []),
        "tags": settings.get("tags", []),
        "annotations": {"workers/message": "3.5.0 fleet local SQLite origin rotation"},
    }
    boundary = "fleet-origin-" + uuid.uuid4().hex
    parts = []
    def add(name, data, content_type, filename=None):
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        parts.append((f"--{boundary}\r\n{disposition}\r\nContent-Type: {content_type}\r\n\r\n").encode() + data + b"\r\n")
    add("metadata", json.dumps(metadata).encode(), "application/json")
    for path in sorted(repair.glob("*.js")):
        if path.name not in checks:
            raise RuntimeError(f"source is absent from Kaggle verification receipt: {path.name}")
        add(path.name, path.read_bytes(), "application/javascript+module", path.name)
    payload = b"".join(parts) + f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(BASE, data=payload, method="PUT", headers={
        **headers, "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            deployed = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare rejected origin update with HTTP {error.code}: {detail}") from None
    if not deployed.get("success"):
        raise RuntimeError("Cloudflare rejected the verified Worker upload")

    after_settings, after_files = get_live(headers)
    if normalized_bindings(after_settings.get("bindings", [])) != recorded.get("bindings", []):
        raise RuntimeError("non-origin Worker bindings changed during origin update")
    configured = [binding for binding in after_settings.get("bindings", []) if binding.get("name") == "FLEET_RELAY_ORIGIN"]
    if len(configured) != 1 or configured[0].get("text") != origin:
        raise RuntimeError("FLEET_RELAY_ORIGIN was not confirmed in live Worker settings")
    for name, expected in source_hashes.items():
        if hashlib.sha256(after_files[name]).hexdigest() != expected:
            raise RuntimeError(f"deployed Worker source hash mismatch: {name}")

    edge = request_json("https://omniroute-relay.omniroute-fleet-kd.workers.dev/fleet/health?token=" + RELAY_TOKEN)
    if edge.get("ready") is not True:
        raise RuntimeError("edge-to-tunnel fleet health did not pass after origin update")
    result = {"success": True, "changed": True, "deployment_id": deployed.get("result", {}).get("deployment_id"),
              "origin": origin, "edge_ready": True,
              "data_mode": expected_mode, "historical_reconciliation": cutover.get("historical_reconciliation"),
              "preserved_bindings": [binding["name"] for binding in after_settings.get("bindings", [])],
              "source_sha256": source_hashes}
    (ROOT / "scratch/fleet_origin_update_receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
