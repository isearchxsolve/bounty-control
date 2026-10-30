import os
import sys
import re
import json
import time
import imaplib
import smtplib
import sqlite3
import hashlib
import urllib.request
import email
from datetime import datetime, timezone
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Enforce UTF-8 line buffering
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# -------------------------------------------------------------
# 1. CORE CONFIGURATION & CONSTANTS
# -------------------------------------------------------------
BASE_DIR = r"D:\anonym"
SCRATCH_DIR = os.path.join(BASE_DIR, "scratch")
PACKETS_DIR = os.path.join(SCRATCH_DIR, "email_packets")
DB_FILE = os.path.join(SCRATCH_DIR, "email_pipeline.db")
VAULT_DIR = os.path.join(BASE_DIR, "vault")
GMAIL_APP_PW_FILE = os.path.join(VAULT_DIR, "gmail_apppw.txt")
TOKENHARBOR_FLEET_KEYS_FILE = os.path.join(VAULT_DIR, "tokenharbor_keys.json")
TOKENHARBOR_INBOUND_KEYS_FILE = os.path.join(VAULT_DIR, "tokenharbor_inbound_keys.json")
TOKENHARBOR_INBOUND_KEYS_ENV = "TOKENHARBOR_INBOUND_KEYS_JSON"

CLIENT_EMAIL = "isearch.xsolve@gmail.com"
TOKENHARBOR_URL = "https://tokenharbor.ai/v1/chat/completions"
DEFAULT_MODEL = "deepseek-v4.1-flash:free"

os.makedirs(PACKETS_DIR, exist_ok=True)

# -------------------------------------------------------------
# 2. VAULT & CREDENTIAL ACCESS
# -------------------------------------------------------------
def get_gmail_password():
    if not os.path.exists(GMAIL_APP_PW_FILE):
        raise FileNotFoundError(f"Missing Gmail app password at {GMAIL_APP_PW_FILE}")
    with open(GMAIL_APP_PW_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def get_all_tokenharbor_keys():
    keys_json = os.environ.get(TOKENHARBOR_INBOUND_KEYS_ENV, "").strip()
    if keys_json:
        keys = json.loads(keys_json)
    elif os.path.exists(TOKENHARBOR_INBOUND_KEYS_FILE):
        with open(TOKENHARBOR_INBOUND_KEYS_FILE, "r", encoding="utf-8") as f:
            keys = json.load(f)
    else:
        raise RuntimeError(
            "A dedicated inbound TokenHarbor key pool is required; refusing to reuse the fleet pool."
        )

    if isinstance(keys, dict):
        keys = keys.get("keys", keys.get("value", []))
    if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key.strip() for key in keys):
        raise ValueError("Dedicated inbound TokenHarbor credentials must be a non-empty list of keys.")
    keys = [key.strip() for key in keys]
    if len(set(keys)) != len(keys):
        raise ValueError("Dedicated inbound TokenHarbor credentials contain duplicate keys.")

    if os.path.exists(TOKENHARBOR_FLEET_KEYS_FILE):
        with open(TOKENHARBOR_FLEET_KEYS_FILE, "r", encoding="utf-8") as f:
            fleet_doc = json.load(f)
        fleet_keys = fleet_doc if isinstance(fleet_doc, list) else fleet_doc.get("keys", fleet_doc.get("value", []))
        if set(keys).intersection(fleet_keys if isinstance(fleet_keys, list) else []):
            raise RuntimeError("Inbound TokenHarbor credentials overlap the active fleet pool; refusing request.")
    return keys

CURRENT_KEY_IDX = 0
def get_tokenharbor_key():
    global CURRENT_KEY_IDX
    keys = get_all_tokenharbor_keys()
    key = keys[CURRENT_KEY_IDX % len(keys)]
    CURRENT_KEY_IDX += 1
    return key

# -------------------------------------------------------------
# 3. DATABASE STATE & RECEIPT TRACKING
# -------------------------------------------------------------
def init_db(db_path=DB_FILE):
    with sqlite3.connect(db_path, timeout=30) as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("""
        CREATE TABLE IF NOT EXISTS email_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_uid TEXT UNIQUE,
            from_addr TEXT,
            subject TEXT,
            date_str TEXT,
            category TEXT,
            actionable INTEGER,
            reply_draft TEXT,
            sha256_digest TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            delivered_at TIMESTAMP
        );
        """)
        con.commit()

def is_email_processed(msg_uid, db_path=DB_FILE):
    try:
        with sqlite3.connect(db_path, timeout=30) as con:
            cur = con.cursor()
            cur.execute("SELECT status FROM email_events WHERE msg_uid = ?", (msg_uid,))
            row = cur.fetchone()
            if row:
                return True, row[0]
            return False, None
    except Exception:
        return False, None

def record_email_event(msg_uid, from_addr, subject, date_str, category, actionable, reply_draft, sha256_digest, status, db_path=DB_FILE):
    try:
        with sqlite3.connect(db_path, timeout=30) as con:
            cur = con.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO email_events
            (msg_uid, from_addr, subject, date_str, category, actionable, reply_draft, sha256_digest, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (msg_uid, from_addr, subject, date_str, category, 1 if actionable else 0, reply_draft, sha256_digest, status))
            con.commit()
            return True
    except Exception as e:
        print(f"  [DB Event Error] {e}")
        return False

# -------------------------------------------------------------
# 4. CONTENT SECURITY SANITIZER (ZERO LEAKS)
# -------------------------------------------------------------
def sanitize_email_payload(content):
    if not content or len(content.strip()) < 50:
        return False, "Payload empty or too short"

    # Strictly prohibit private bank accounts, UPI handles, private keys, PATs
    leak_patterns = [
        r"\b\d{9,18}\b",                                    # Contiguous bank accounts
        r"\b[A-Z]{4}0[A-Z0-9]{6}\b",                        # IFSC codes
        r"\b[a-zA-Z0-9.\-_]+@(okhdfcbank|okaxis|oksbi|okicici|paytm|ybl|upi|kotak)\b",
        r"\b0x[a-fA-F0-9]{40}\b",                           # EVM address
        r"\bghp_[A-Za-z0-9_]{36}\b",                        # GitHub PAT
        r"\bsk-[a-zA-Z0-9]{20,}\b",                         # OpenAI keys
        r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"          # Private keys
    ]
    for lp in leak_patterns:
        if re.search(lp, content, re.IGNORECASE):
            return False, f"Security violation: matches leak pattern '{lp}'"

    # Formatted card/account numbers (12-19 digits formatted with - or space, excluding ISO dates YYYY-MM-DD)
    formatted_groups = re.finditer(r"\b\d{2,6}(?:[- ]\d{2,6}){2,5}\b", content)
    for fg in formatted_groups:
        matched_str = fg.group(0)
        if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", matched_str):
            continue
        digits_only = re.sub(r"\D", "", matched_str)
        if len(digits_only) >= 12:
            return False, f"Security violation: matches formatted financial account number '{matched_str}'"

    # Prohibit false test verification claims (Supreme Edict)
    falsification_patterns = [
        r"\bverified on our reference environment\b",
        r"\b100% test pass verified\b",
        r"\bwe have isolated this failure on our private reference\b"
    ]
    for fp in falsification_patterns:
        if re.search(fp, content, re.IGNORECASE):
            return False, f"Zero-Manufacture violation: matches false test claim '{fp}'"

    return True, "Payload clean and approved"

# -------------------------------------------------------------
# 5. DEEPSEEK REASONING & RESPONSE SYNTHESIS
# -------------------------------------------------------------
def call_deepseek_chat(messages, max_tokens=1500, temperature=0.2):
    for attempt in range(len(get_all_tokenharbor_keys())):
        api_key = get_tokenharbor_key()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "model": DEFAULT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        req = urllib.request.Request(
            TOKENHARBOR_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0].get("message", {})
                content = choice.get("content")
                if content and isinstance(content, str) and content.strip():
                    return content.strip()
                finish_reason = data.get("choices", [{}])[0].get("finish_reason")
                if finish_reason == "length":
                    print(f"  [DeepSeek Horizon] Response hit max_tokens limit ({max_tokens}); rotating key...")
                    continue
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1)
                continue
            print(f"  [DeepSeek HTTP Error] {e}")
            time.sleep(1)
        except Exception as e:
            print(f"  [DeepSeek Call Error] {e}")
            time.sleep(1)
    return None

def analyze_and_categorize_email(from_addr, subject, body):
    """
    Categorizes inbound email using DeepSeek reasoning:
    - CLIENT_INQUIRY: Real human asking about consulting, architectural fix, or contract terms.
    - GITHUB_BOUNTY_UPDATE: Active notification on an issue/bounty with tangible technical context.
    - FINANCIAL_RECEIPT: Aviva surrender, bank credits, or payment mandate confirmations.
    - EXECUTIVE_OPPORTUNITY: Top-tier recruiter or job alert (CTO, Director AI).
    - NOISE_OR_AUTOMATED: Marketing spam, generic automated notifications, etc.
    """
    system_prompt = (
        "You are an executive triage analyst for Kunal Das (Principal Systems Architect & Technology Leader).\n"
        "Classify the following incoming email into one of these strict categories:\n"
        "1. CLIENT_INQUIRY (Client, founder, or engineer inquiring about software architecture, consulting, or an issue resolution)\n"
        "2. GITHUB_BOUNTY_UPDATE (Direct notification or discussion regarding an active GitHub bug bounty or technical ticket)\n"
        "3. FINANCIAL_RECEIPT (Aviva surrender updates, banking credits, payment mandates, or financial settlement notices)\n"
        "4. EXECUTIVE_OPPORTUNITY (Recruiter outreach or high-tier leadership alerts for CTO, Director AI, or Staff Engineer roles)\n"
        "5. NOISE_OR_AUTOMATED (Newsletters, marketing campaigns, promotions, or generic platform notifications)\n\n"
        "Output ONLY a valid JSON object with keys:\n"
        "{\n"
        '  "category": "CLIENT_INQUIRY" | "GITHUB_BOUNTY_UPDATE" | "FINANCIAL_RECEIPT" | "EXECUTIVE_OPPORTUNITY" | "NOISE_OR_AUTOMATED",\n'
        '  "actionable": true | false,\n'
        '  "summary": "1-2 sentence concise executive summary",\n'
        '  "priority": "HIGH" | "MEDIUM" | "LOW"\n'
        "}"
    )

    user_content = f"From: {from_addr}\nSubject: {subject}\nBody Snippet:\n{body[:2500]}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    raw_resp = call_deepseek_chat(messages, max_tokens=1200, temperature=0.1)
    if not raw_resp:
        return {
            "category": "NOISE_OR_AUTOMATED",
            "actionable": False,
            "summary": "DeepSeek analysis unreachable",
            "priority": "LOW"
        }

    try:
        # Extract JSON from response
        match = re.search(r"\{.*\}", raw_resp, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(raw_resp)
    except Exception:
        return {
            "category": "NOISE_OR_AUTOMATED",
            "actionable": False,
            "summary": "Parsing error on DeepSeek categorization",
            "priority": "LOW"
        }

def synthesize_email_reply(from_addr, subject, body, summary):
    """
    Synthesizes an authoritative, concise, technical email response from Kunal Das
    following Baba's Email Law (written lanes only, no live calls, radical honesty, zero vaporware).
    """
    system_prompt = (
        "You are Kunal Das, Principal Systems Architect (NIT alumnus, 20+ years enterprise systems architecture).\n"
        "Draft a formal, concise, authoritative email reply to the client/inquiry.\n\n"
        "STRICT DOCTRINE:\n"
        "1. Tone: Calm, senior enterprise architect, direct, courteous, peer-to-peer.\n"
        "2. Zero-Manufacture Law: Never claim you ran code on a private reference harness unless evidenced. Provide truthful architectural analysis.\n"
        "3. Written Lane Mandate: State clearly that we operate asynchronously via written technical deliverables and clear milestone specifications (no live discovery phone calls).\n"
        "4. Contact Channel: Sign off strictly as:\n"
        "   Kunal Das\n"
        "   Principal Systems Architect\n"
        "   isearch.xsolve@gmail.com\n"
        "5. NO bank account numbers, IFSC codes, or UPI coordinates in the body.\n"
        "6. Do not include markdown headers (# or ##); format as clean, standard executive email text.\n"
        "7. Output ONLY the email reply text. Do NOT include internal thinking or meta-instructions in your response."
    )

    user_content = (
        f"Inbound Email From: {from_addr}\n"
        f"Subject: {subject}\n"
        f"Executive Summary of Context: {summary}\n"
        f"Inbound Body:\n{body[:3000]}\n\n"
        f"Draft the exact email reply text ready to send:"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    return call_deepseek_chat(messages, max_tokens=2500, temperature=0.3)

# -------------------------------------------------------------
# 6. IMAP & SMTP COMMUNICATOR
# -------------------------------------------------------------
UNREACHABLE_RECIPIENT_PATTERNS = [
    r"@notifications\.github\.com\b",
    r"@reply\.github\.com\b",
    r"@github\.com\b",
    r"\b(?:noreply|no-reply|donotreply|do-not-reply)@",
    r"\b(?:postmaster|mailer-daemon)@",
    r"@(?:linkedin|freelancer|indeed|foundit|swooped|beehiiv)\.com\b",
    r"@store-news\.amazon\.",
    r"@microsoft\.com\b",
    r"@googlemail\.com\b"
]

def is_unreachable_recipient(email_addr):
    if not email_addr:
        return True
    addr = email_addr.strip().lower()
    for pat in UNREACHABLE_RECIPIENT_PATTERNS:
        if re.search(pat, addr, re.IGNORECASE):
            return True
    return False

def decode_mime(s):
    if not s:
        return ""
    dh = decode_header(s)
    res = []
    for text, enc in dh:
        if isinstance(text, bytes):
            res.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            res.append(str(text))
    return "".join(res)

def extract_body_text(msg):
    body = ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="ignore")
                break
        elif ctype == "text/html" and not body:
            payload = part.get_payload(decode=True)
            if payload:
                raw_html = payload.decode("utf-8", errors="ignore")
                clean = re.sub(r"<[^>]+>", " ", raw_html)
                clean = re.sub(r"\s+", " ", clean)
                body = clean
    return body.strip()

def send_smtp_email(to_addr, subject, body_text):
    if is_unreachable_recipient(to_addr):
        return False, f"Address '{to_addr}' is a no-reply robot/postmaster blackhole. Send aborted."

    pw = get_gmail_password()
    msg = MIMEMultipart()
    msg["From"] = f"Kunal Das <{CLIENT_EMAIL}>"
    msg["To"] = to_addr
    msg["Subject"] = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
    try:
        server.login(CLIENT_EMAIL, pw)
        server.sendmail(CLIENT_EMAIL, [to_addr], msg.as_string())
        return True, "Email delivered successfully via SMTP"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            server.quit()
        except Exception:
            pass

# -------------------------------------------------------------
# 7. INBOUND PIPELINE CYCLE
# -------------------------------------------------------------
def run_inbound_cycle(live_mode=False, max_inspect=20):
    init_db()
    pw = get_gmail_password()

    now_utc = datetime.now(timezone.utc)
    print(f"\n=======================================================")
    print(f"[{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}] DEEPSEEK INBOUND & RECEIPT PIPELINE")
    print(f"Standard: Zero-Manufacture, Pre-Post Security Gate, Written Lane Law")
    print(f"Channel: {CLIENT_EMAIL}")
    print(f"Mode: {'LIVE SMTP DISPATCH' if live_mode else 'CANDIDATE PACKET MODE (Safe Preview)'}")
    print(f"=======================================================")

    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=20)
    try:
        m.login(CLIENT_EMAIL, pw)
        m.select("INBOX")
        status, msgs = m.search(None, "ALL")
        if status != "OK" or not msgs or not msgs[0]:
            print("No messages found in INBOX.")
            return

        all_ids = msgs[0].split()
        recent_ids = all_ids[-max_inspect:]
        print(f"Inspecting latest {len(recent_ids)} messages from INBOX...")

        for mid in reversed(recent_ids):
            uid_str = mid.decode()
            already_done, cur_status = is_email_processed(uid_str)
            if already_done:
                continue

            res, data = m.fetch(mid, "(RFC822)")
            if res != "OK" or not data or not data[0]:
                continue

            msg = email.message_from_bytes(data[0][1])
            subj = decode_mime(msg.get("Subject"))
            sender = decode_mime(msg.get("From"))
            date_str = decode_mime(msg.get("Date"))
            body_text = extract_body_text(msg)

            # 0. Immediate Drop of Postmaster, Mailer-Daemon, Delivery Failure Bounces, and Unfunded Academic Testbeds
            if re.search(r"\b(?:postmaster|mailer-daemon)@", sender, re.IGNORECASE) or \
               re.search(r"\b(?:Delivery has failed|Undeliverable|Failure Notice|Mail delivery failed)\b", subj, re.IGNORECASE) or \
               re.search(r"microcredit-agent-testbed|scottonchain", subj + sender, re.IGNORECASE):
                continue
                print(f"🛑 [BOUNCE NOTICE DROPPED] UID {uid_str}: {subj[:60]}")
                record_email_event(uid_str, sender, subj, date_str, "NOISE_OR_AUTOMATED", False, "", "", "BOUNCE_DROPPED")
                continue

            print(f"\n📨 [NEW INBOUND DETECTED] UID: {uid_str}")
            print(f"From: {sender[:50]}")
            print(f"Subject: {subj[:80]}")

            # 1. DeepSeek Triage & Categorization
            triage = analyze_and_categorize_email(sender, subj, body_text)
            category = triage.get("category", "NOISE_OR_AUTOMATED")
            actionable = triage.get("actionable", False)
            summary = triage.get("summary", "")
            priority = triage.get("priority", "LOW")

            print(f"Category: {category} | Priority: {priority} | Actionable: {actionable}")
            print(f"Summary: {summary}")

            # Non-actionable or noise emails are recorded and skipped
            if not actionable or category == "NOISE_OR_AUTOMATED":
                record_email_event(uid_str, sender, subj, date_str, category, False, "", "", "PROCESSED_NO_ACTION")
                continue

            # 2. Financial Receipt Logging
            if category == "FINANCIAL_RECEIPT":
                print(f"💰 [FINANCIAL RECEIPT LOGGED] {summary}")
                packet_path = os.path.join(PACKETS_DIR, f"receipt_{uid_str}.json")
                with open(packet_path, "w", encoding="utf-8") as pf:
                    json.dump({
                        "uid": uid_str,
                        "type": "FINANCIAL_RECEIPT",
                        "sender": sender,
                        "subject": subj,
                        "date": date_str,
                        "summary": summary,
                        "logged_at": datetime.now(timezone.utc).isoformat()
                    }, pf, indent=2)
                record_email_event(uid_str, sender, subj, date_str, category, False, "", "", "RECEIPT_SAVED")
                continue

            # 3. Executive Placement Alert
            if category == "EXECUTIVE_OPPORTUNITY":
                print(f"🎯 [EXECUTIVE OPPORTUNITY DETECTED] {summary}")
                packet_path = os.path.join(PACKETS_DIR, f"exec_opp_{uid_str}.json")
                with open(packet_path, "w", encoding="utf-8") as pf:
                    json.dump({
                        "uid": uid_str,
                        "type": "EXECUTIVE_OPPORTUNITY",
                        "sender": sender,
                        "subject": subj,
                        "date": date_str,
                        "summary": summary,
                        "body_snippet": body_text[:1000],
                        "logged_at": datetime.now(timezone.utc).isoformat()
                    }, pf, indent=2)
                record_email_event(uid_str, sender, subj, date_str, category, False, "", "", "OPPORTUNITY_SAVED")
                continue

            # 4. GitHub Bounty Notification (Informational Tracker - NEVER email notifications@github.com)
            if category == "GITHUB_BOUNTY_UPDATE":
                print(f"📦 [GITHUB BOUNTY UPDATE LOGGED] {summary}")
                packet_path = os.path.join(PACKETS_DIR, f"bounty_{uid_str}.json")
                with open(packet_path, "w", encoding="utf-8") as pf:
                    json.dump({
                        "uid": uid_str,
                        "type": "GITHUB_BOUNTY_UPDATE",
                        "sender": sender,
                        "subject": subj,
                        "date": date_str,
                        "summary": summary,
                        "body_snippet": body_text[:1200],
                        "logged_at": datetime.now(timezone.utc).isoformat()
                    }, pf, indent=2)
                record_email_event(uid_str, sender, subj, date_str, category, False, "", "", "BOUNTY_NOTIFICATION_LOGGED")
                continue

            # 5. Actionable Client Inquiry (Real Human Inbound)
            if category == "CLIENT_INQUIRY":
                match_email = re.search(r"[\w\.-]+@[\w\.-]+", sender)
                to_email = match_email.group(0).lower() if match_email else ""
                if not to_email or is_unreachable_recipient(to_email):
                    print(f"🛑 [AUTOMATED SENDER DROPPED] Sender '{sender}' is not a reachable human. Suppressing engagement.")
                    record_email_event(uid_str, sender, subj, date_str, category, False, "", "", "UNREACHABLE_SUPPRESSED")
                    continue

                print(f"⚡ [CLIENT ENGAGEMENT CANDIDATE] Synthesizing grounded response via DeepSeek...")
                reply_draft = synthesize_email_reply(sender, subj, body_text, summary)
                if not reply_draft:
                    print(f"❌ [ABORTED] DeepSeek response synthesis failed.")
                    continue

                # Content safety check
                is_safe, safety_msg = sanitize_email_payload(reply_draft)
                if not is_safe:
                    print(f"❌ [SECURITY GATE] {safety_msg}. Suppressing response.")
                    record_email_event(uid_str, sender, subj, date_str, category, True, reply_draft, "", "SECURITY_REJECTED")
                    continue

                digest = hashlib.sha256(reply_draft.encode("utf-8")).hexdigest()

                # Generate Candidate Packet
                packet_path = os.path.join(PACKETS_DIR, f"client_inquiry_{uid_str}.json")
                packet = {
                    "uid": uid_str,
                    "sender": sender,
                    "subject": subj,
                    "date": date_str,
                    "category": category,
                    "summary": summary,
                    "reply_draft": reply_draft,
                    "sha256": digest,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                with open(packet_path, "w", encoding="utf-8") as pf:
                    json.dump(packet, pf, indent=2)

                print(f"📦 [CLIENT INQUIRY PACKET SAVED] {packet_path}")
                print("\n--- [REPLY DRAFT PREVIEW] ---")
                print(reply_draft[:800] + ("\n..." if len(reply_draft) > 800 else ""))
                print("--- [END PREVIEW] ---\n")

                if not live_mode:
                    record_email_event(uid_str, sender, subj, date_str, category, True, reply_draft, digest, "PREVIEW_PACKET_CREATED")
                    continue

                # LIVE SMTP ENGAGEMENT TO REAL HUMAN
                ok_send, send_msg = send_smtp_email(to_email, subj, reply_draft)
                if ok_send:
                    print(f"✅ [SMTP DELIVERED] Response sent to {to_email} (SHA-256: {digest[:16]}...)")
                    record_email_event(uid_str, sender, subj, date_str, category, True, reply_draft, digest, "SMTP_DELIVERED")
                else:
                    print(f"❌ [SMTP FAILED] Error sending to {to_email}: {send_msg}")
                    record_email_event(uid_str, sender, subj, date_str, category, True, reply_draft, digest, "SMTP_FAILED")

    finally:
        try:
            m.logout()
        except Exception:
            pass

# -------------------------------------------------------------
# 8. 24/7 DAEMON LOOP
# -------------------------------------------------------------
def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
Usage: python scripts/deepseek_inbound_pipeline.py [OPTIONS]

Options:
  --once    Run a single inbox sweep and exit (default is continuous 24/7 daemon).
  --live    Enable live SMTP transmission (default is Candidate Packet Mode / safe preview).
  --help    Show this help message and exit.
""")
        return

    live_mode = "--live" in sys.argv
    run_once = "--once" in sys.argv
    poll_interval_seconds = 90  # Poll every 90 seconds

    cycle_count = 1
    print("\n" + "=" * 60)
    print("⚡ DEEPSEEK INBOUND EMAIL & RECEIPT PIPELINE - 24/7 DAEMON")
    print(f"Monitored Channel: {CLIENT_EMAIL}")
    print(f"Mode: {'LIVE SMTP ENGAGEMENT' if live_mode else 'CANDIDATE PACKET MODE (Safe Preview)'}")
    print(f"Poll Interval: {poll_interval_seconds}s")
    print("=" * 60 + "\n")

    while True:
        try:
            print(f"\n>>> [STARTING EMAIL SWEEP #{cycle_count}] <<<")
            run_inbound_cycle(live_mode=live_mode)
        except KeyboardInterrupt:
            print("\n[STOPPED] Received keyboard interrupt. Shutting down email daemon gracefully.")
            break
        except Exception as e:
            print(f"\n❌ [EMAIL SWEEP #{cycle_count} ERROR] {e}. Retrying in 60 seconds...")
            time.sleep(60)

        if run_once:
            print("[ONCE MODE] Single sweep completed. Exiting.")
            break

        cycle_count += 1
        print(f"\n⏳ Sweep #{cycle_count - 1} complete. Sleeping {poll_interval_seconds}s before next inbox check...")
        time.sleep(poll_interval_seconds)

if __name__ == "__main__":
    main()
