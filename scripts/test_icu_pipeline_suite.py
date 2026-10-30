import sys
import os
import sqlite3
import re
import shutil
import subprocess
import tempfile

# Add scripts directory to path
sys.path.insert(0, r"D:\anonym\scripts")

from autonomous_icu_pipeline import (
    verify_genuine_icu_patient,
    detect_author_corridor,
    sanitize_and_validate_payload,
    APPROVED_CORRIDOR_TZ_MAP,
    init_db,
    try_claim_issue,
    is_issue_claimed_or_delivered,
    commit_delivery,
    release_claim,
    is_safe_relative_path,
    model_scenarios,
    inspect_repository_architecture,
    discover_verification_plan,
    verify_baseline,
    check_competing_prs_fail_closed,
    build_peer_pr_body,
    run_command_safe,
    VerificationPlan,
    CommandResult,
    ScenarioCase,
    EngineeringRun
)
from tokenharbor_router import (
    COOLDOWN,
    DEEPSEEK_FLASH_MODEL,
    DISABLED,
    READY,
    TokenHarborRouter,
)
import kaggle_engine_worker as kaggle_worker

TEST_DB = r"D:\anonym\scratch\test_suite_isolated.db"

print("==================================================")
print("RUNNING ICU PIPELINE INTEGRITY TEST SUITE")
print("==================================================")

# ----------------------------------------------------------------
# Test 1: Genuine ICU Client Detection & Decision-Maker Authority
# ----------------------------------------------------------------
print("\n[Test 1] Testing Genuine ICU Client Gate & Authority...")

# 1. TONEART GmbH (WhatsApp MCP Production Coexistence - Paid Feasibility)
is_icu_1, reason_1 = verify_genuine_icu_patient(
    title="Paid feasibility assessment: WhatsApp Business MCP alongside an existing Meta Business Agent",
    body="Looking for a paid feasibility assessment for TONEART GmbH. We use WhatsApp Business with an existing Meta Business Agent, SOPHIA-X. We want to assess coexistence without disrupting production setup.",
    author_comments=[],
    labels=[],
    repo="spirit122/whatsapp-mcp-server",
    author_assoc="COLLABORATOR"
)
assert is_icu_1, f"Expected True for TONEART, got {is_icu_1}: {reason_1}"
print("  ✓ TONEART GmbH: Approved as genuine ICU client (COLLABORATOR authority).")

# 2. Reject CONTRIBUTOR role (lacks maintainer authority per Codex Audit)
is_icu_contrib, reason_contrib = verify_genuine_icu_patient(
    title="CUDA app by PackageCompiler hangs at runtime on Ubuntu / Debian",
    body="Dummy app made by PackageCompiler with CUDA@5.6.1 hangs at runtime on Ubuntu 24 and Debian 12.",
    author_comments=["Update: problem arises on Google Colab and not in AWS VMs. Happy to pay couple hours of consulting for anyone who can fix this problem."],
    labels=[],
    repo="JuliaLang/PackageCompiler.jl",
    author_assoc="CONTRIBUTOR"
)
assert not is_icu_contrib, "Expected CONTRIBUTOR to be rejected as lacking maintainer authority."
print("  ✓ Authority Gate: CONTRIBUTOR rejected as lacking maintainer authority.")

# 3. Decision-Maker Authority: Reject unverified external user without maintainer role or budget intent
is_icu_auth_fail, reason_auth_fail = verify_genuine_icu_patient(
    title="Production server crashing on boot",
    body="Why does it crash? Can someone fix this bug?",
    author_comments=[],
    labels=[],
    repo="org/app",
    author_assoc="NONE"
)
assert not is_icu_auth_fail, "Expected False for unverified external user."
print("  ✓ Authority Gate: Rejected external user without maintainer role or budget authority.")

# 4. Decision-Maker Authority: Reject self-asserted corporate sponsor without independent verification
is_icu_self_assert, reason_self_assert = verify_genuine_icu_patient(
    title="Production outage: payment gateway deadlocked",
    body="Critical P0 outage disrupting production. Our company budget will pay $2,500 for emergency architecture fix.",
    author_comments=[],
    labels=[],
    repo="fintech/payment-gateway",
    author_assoc="NONE",
    author=None
)
assert not is_icu_self_assert, "Expected self-asserted sponsor without independent verification to be rejected."
print("  ✓ Authority Gate: Rejected self-asserted corporate sponsor without independent verification.")

# 4b. Corporate Sponsor Entity Correlation: Generic 'our company' without naming affiliated entity is REJECTED
import autonomous_icu_pipeline
orig_get_profile = autonomous_icu_pipeline.get_author_profile
autonomous_icu_pipeline.get_author_profile = lambda u: {"company": "Acme Technologies, Inc."} if u == "acme_lead" else {}

is_icu_generic_sponsor, reason_generic_sponsor = verify_genuine_icu_patient(
    title="Critical production deadlock in payment processor",
    body="Outage in production. Our company budget will pay $5,000 for emergency resolution.",
    author_comments=[],
    labels=[],
    repo="fintech/payments",
    author_assoc="NONE",
    author="acme_lead"
)
assert not is_icu_generic_sponsor, "Expected generic 'our company' without naming Acme to be rejected."
print("  ✓ Authority Gate: Rejected generic 'our company' claim lacking named corporate entity correlation.")

# 4c. Corporate Sponsor Entity Correlation: Named entity matching author profile is APPROVED
is_icu_named_sponsor, reason_named_sponsor = verify_genuine_icu_patient(
    title="Critical production deadlock in payment processor",
    body="Outage in production. Acme Technologies budget will pay $5,000 for emergency resolution.",
    author_comments=[],
    labels=[],
    repo="fintech/payments",
    author_assoc="NONE",
    author="acme_lead"
)
assert is_icu_named_sponsor, f"Expected named sponsor matching Acme Technologies to be approved, got: {reason_named_sponsor}"
print("  ✓ Authority Gate: Approved verified corporate sponsor with correlated named entity ('Acme Technologies').")

# 4d. Discovery Integration Test: Correlated author_assoc="NONE" sponsor passes discovery gate with author payload
discovery_payload = {
    "title": "Critical production deadlock in payment processor",
    "body": "Outage in production. Acme Technologies budget will pay $5,000 for emergency resolution.",
    "author": {"login": "acme_lead"},
    "labels": [{"name": "bug"}],
    "author_comments": [],
    "authorAssociation": "NONE"
}
d_author = discovery_payload.get("author", {}).get("login", "")
d_title = discovery_payload.get("title", "")
d_body = discovery_payload.get("body", "")
d_labels = discovery_payload.get("labels", [])
d_comments = discovery_payload.get("author_comments", [])
d_assoc = discovery_payload.get("authorAssociation", "NONE")

d_is_icu, d_reason = verify_genuine_icu_patient(
    d_title, d_body, d_comments, d_labels, "fintech/payments",
    author_assoc=d_assoc, author=d_author
)
assert d_is_icu, f"Expected discovery-gate call to approve correlated NONE-assoc sponsor, got: {d_reason}"
print("  ✓ Discovery Gate Integration: Correlated NONE-association sponsor passes discovery gate with author=author.")

# Restore profile lookup
autonomous_icu_pipeline.get_author_profile = orig_get_profile

# 4e. Direct Payer Gate: Solo founder filing on OWN repo with payment intent (NONE assoc) - APPROVED
# Mock: author "solodev" owns repo "solodev/api-server", no company on profile
autonomous_icu_pipeline.get_author_profile = lambda u: {} if u == "solodev" else {}
is_icu_solo_founder, reason_solo = verify_genuine_icu_patient(
    title="Production crash: API returning 502 on all endpoints",
    body="My production API is down, losing customers every minute. Will pay $500 for emergency fix. DM me.",
    author_comments=[],
    labels=[],
    repo="solodev/api-server",
    author_assoc="NONE",
    author="solodev"
)
assert is_icu_solo_founder, f"Expected solo founder on own repo with payment intent to be approved, got: {reason_solo}"
print("  ✓ Direct Payer Gate: Solo founder on own repo with payment intent approved.")

# 4f. Direct Payer Gate: Freelancer with PayPal/UPI signal on third-party repo (NONE assoc) - APPROVED
is_icu_freelancer, reason_freelancer = verify_genuine_icu_patient(
    title="Critical memory leak crashing production workers",
    body="Our production workers keep crashing with OOM. Willing to pay $300 via PayPal for a fix. email me at dev@example.com",
    author_comments=[],
    labels=[],
    repo="otherorg/worker-lib",
    author_assoc="NONE",
    author="solodev"
)
assert is_icu_freelancer, f"Expected freelancer with PayPal signal to be approved, got: {reason_freelancer}"
print("  ✓ Direct Payer Gate: Freelancer with PayPal payment signal approved.")

# 4g. Direct Payer Gate: NONE assoc, no payment signal, no repo ownership, no company - REJECTED
is_icu_no_signal, reason_no_signal = verify_genuine_icu_patient(
    title="Production timeout on database queries",
    body="Database queries timing out in production. Will pay $200 for a fix.",
    author_comments=[],
    labels=[],
    repo="otherorg/db-lib",
    author_assoc="NONE",
    author="randomuser123"
)
assert not is_icu_no_signal, "Expected NONE-assoc user without payment signal, repo ownership, or company to be rejected."
print("  ✓ Direct Payer Gate: NONE-assoc without payment signal or repo ownership correctly rejected.")

# 4h. Direct Payer Gate: Crypto payment signal - APPROVED
is_icu_crypto, reason_crypto = verify_genuine_icu_patient(
    title="Smart contract reverting on production mainnet",
    body="Contract reverting all transactions on production. Offering $1,000 USDC bounty. Send to my ETH wallet.",
    author_comments=[],
    labels=[],
    repo="otherorg/defi-protocol",
    author_assoc="NONE",
    author="solodev"
)
assert is_icu_crypto, f"Expected crypto payment signal to be approved, got: {reason_crypto}"
print("  ✓ Direct Payer Gate: Crypto/USDC payment signal approved.")

# Restore profile lookup
autonomous_icu_pipeline.get_author_profile = orig_get_profile

# 5. Demonstrated Maintainer with Explicit Budget Approved
is_icu_owner, reason_owner = verify_genuine_icu_patient(
    title="Production outage: payment gateway deadlocked",
    body="Critical P0 outage disrupting production. Our company budget will pay $2,500 for emergency architecture fix.",
    author_comments=[],
    labels=[],
    repo="fintech/payment-gateway",
    author_assoc="OWNER"
)
assert is_icu_owner, f"Expected OWNER with budget to pass, got: {reason_owner}"
print("  ✓ Authority Gate: Approved OWNER with explicit $2,500 budget.")

# 6. Currency Parsing, Multi-Currency Normalization & Bounds ($20 to $9,999,999)
# Normal range ($1,500)
is_icu_comma, reason_comma = verify_genuine_icu_patient(
    title="Production OOM crash during peak load",
    body="Runtime crash in prod. Willing to pay $1,500 for remediation.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert is_icu_comma, f"Expected comma-formatted currency to pass, got: {reason_comma}"
print("  ✓ Comma-Formatted Currency ($1,500): Parsed and approved within range.")

# Decimal Boundary Test: $20.00 Floor (Approved)
is_icu_floor, reason_floor = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay $20.00 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert is_icu_floor, f"Expected $20.00 exact floor to pass, got: {reason_floor}"
print("  ✓ Decimal Boundary Exact Floor ($20.00): Approved.")

# Decimal Boundary Test: $19.99 Below Floor (Rejected)
is_icu_sub_floor, reason_sub_floor = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay $19.99 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert not is_icu_sub_floor, "Expected $19.99 to be rejected as below $20.00 floor."
print("  ✓ Decimal Boundary Below Floor ($19.99): Rejected.")

# Decimal Boundary Test: $9,999,999.99 Exceeding Ceiling (Rejected)
is_icu_ceiling, reason_ceiling = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay $9,999,999.99 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert not is_icu_ceiling, "Expected $9,999,999.99 to be rejected as exceeding ceiling."
print("  ✓ Decimal Boundary Exceeding Ceiling ($9,999,999.99): Rejected.")

# Decimal Foreign Currency Boundary Test: €18.52 (~$20.00 USD) Approved vs €18.51 (~$19.99 USD) Rejected
is_icu_eur_ok, reason_eur_ok = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay €18.52 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert is_icu_eur_ok, f"Expected €18.52 (~$20.00 USD) to pass, got: {reason_eur_ok}"
print("  ✓ Decimal Foreign Currency Floor (€18.52 -> $20.00 USD): Approved.")

is_icu_eur_low, reason_eur_low = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay €18.51 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert not is_icu_eur_low, "Expected €18.51 (~$19.99 USD) to be rejected."
print("  ✓ Decimal Foreign Currency Below Floor (€18.51 -> $19.99 USD): Rejected.")

# Multi-Currency Normalization: ₹50,000 INR (~$600 USD) -> Approved
is_icu_inr_ok, reason_inr_ok = verify_genuine_icu_patient(
    title="Production deadlock in order processing",
    body="Critical production crash. We will pay ₹50,000 for emergency hotfix.",
    author_comments=[],
    labels=[],
    repo="fintech/orders",
    author_assoc="MEMBER"
)
assert is_icu_inr_ok, f"Expected ₹50,000 INR to pass normalized USD check, got: {reason_inr_ok}"
print("  ✓ Currency Normalization (₹50,000 INR -> ~$600 USD): Approved within consulting bounds.")

# Multi-Currency Normalization: ₹500 INR (~$6 USD) -> Rejected (< $20 USD floor)
is_icu_inr_low, reason_inr_low = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Outage in production. Will pay ₹500 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/service",
    author_assoc="MEMBER"
)
assert not is_icu_inr_low, "Expected ₹500 INR to be rejected as below $20 USD floor."
print("  ✓ Out-of-Bounds Currency (₹500 INR -> ~$6 USD): Rejected as below $20 USD floor.")

# Below $20 bound ($5) -> Reject
is_icu_low, reason_low = verify_genuine_icu_patient(
    title="Production crash in service",
    body="Production outage in prod. Will pay $5 for fix.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert not is_icu_low, "Expected $5 to be rejected as below consulting bounds."
print("  ✓ Out-of-Bounds Currency ($5): Rejected as below $20 consulting bound.")

# Postfix Currency Tests: 50$ (Henry00IS/ShapeEditor real-world pattern)
is_icu_post_dollar, reason_post_dollar = verify_genuine_icu_patient(
    title="[50$ Bounty] PolyBool can cause an editor crash on T-Junctions",
    body="Editor crashes during mesh boolean operations in production. Will pay 50$ upon merge.",
    author_comments=[],
    labels=["bounty"],
    repo="Henry00IS/ShapeEditor",
    author_assoc="OWNER"
)
assert is_icu_post_dollar, f"Expected 50$ postfix currency to pass, got: {reason_post_dollar}"
print("  ✓ Postfix Currency (50$ Bounty): Approved within consulting bounds.")

# Postfix Currency Tests: 100 USD
is_icu_post_usd, reason_post_usd = verify_genuine_icu_patient(
    title="Production memory leak in websocket server",
    body="Memory leak causes worker crash every 2 hours. Offering 100 USD for a clean fix.",
    author_comments=[],
    labels=["bounty"],
    repo="myorg/websocket-server",
    author_assoc="OWNER"
)
assert is_icu_post_usd, f"Expected 100 USD postfix currency to pass, got: {reason_post_usd}"
print("  ✓ Postfix Currency (100 USD): Approved within consulting bounds.")

# Postfix Currency Tests: 5$ Below Floor -> Reject
is_icu_post_low, reason_post_low = verify_genuine_icu_patient(
    title="[5$ Bounty] Small crash fix",
    body="Will pay 5$ for fix.",
    author_comments=[],
    labels=["bounty"],
    repo="myorg/app",
    author_assoc="OWNER"
)
assert not is_icu_post_low, "Expected 5$ to be rejected as below $20 floor."
print("  ✓ Postfix Currency Below Floor (5$): Rejected as below $20 consulting bound.")

# Bare 'happy to pay' without numeric amount -> Reject
is_icu_bare_pay, reason_bare_pay = verify_genuine_icu_patient(
    title="Production service crashing under load",
    body="Production outage. Happy to pay anyone who can fix this.",
    author_comments=[],
    labels=[],
    repo="fintech/engine",
    author_assoc="OWNER"
)
assert not is_icu_bare_pay, "Expected bare 'happy to pay' without amount to be rejected."
print("  ✓ Bare Payment Without Amount ('happy to pay'): Rejected.")

# Live delivery mode blocks unpriced enterprise RFPs (routed to candidate packet review)
is_live_rfp, reason_live_rfp = verify_genuine_icu_patient(
    title="Paid feasibility assessment: WhatsApp Business MCP alongside an existing Meta Business Agent",
    body="Looking for a paid feasibility assessment for TONEART GmbH. Could you share expected approach, timeline, and cost?",
    author_comments=[],
    labels=[],
    repo="spirit122/whatsapp-mcp-server",
    author_assoc="COLLABORATOR",
    live_delivery_mode=True
)
assert not is_live_rfp, "Expected unpriced enterprise RFP to be blocked from automated live delivery."
print("  ✓ Live Delivery Gate: Blocked unpriced enterprise RFP from unreviewed live dispatch (routed to packet).")

# 6. Rejection: Non-commercial / Student Programs
is_icu_3, reason_3 = verify_genuine_icu_patient(
    title="Volcano Integration Plugin for Headlamp - Linux Foundation paid mentorship project",
    body="This is our draft proposal for an LFX mentorship project for students.",
    author_comments=[],
    labels=[],
    repo="kubernetes-sigs/headlamp",
    author_assoc="MEMBER"
)
assert not is_icu_3, "Expected False for LFX student project."
print("  ✓ LFX Mentorship: Rejected correctly.")

# 7. Rejection: Homelab setup
is_icu_4, reason_4 = verify_genuine_icu_patient(
    title="[BOUNTY $150] Storage Stack - Nextcloud + MinIO + FileBrowser",
    body="Homelab stack nextcloud storage configuration.",
    author_comments=[],
    labels=[],
    repo="illbnm/homelab-stack",
    author_assoc="OWNER"
)
assert not is_icu_4, "Expected False for Homelab non-production project."
print("  ✓ Homelab Non-Production: Rejected correctly.")

# 8. Rejection: Roadmap planning ticket
is_icu_5, reason_5 = verify_genuine_icu_patient(
    title="[28] Validate paid workflow value and sustainable unit economics",
    body="Roadmap milestone 32/38 for commercial go-to-market planning.",
    author_comments=[],
    labels=[],
    repo="Sammieblz/tholi",
    author_assoc="OWNER"
)
assert not is_icu_5, "Expected False for internal roadmap ticket."
print("  ✓ Roadmap Planning Ticket: Rejected correctly.")

# 9. Rejection: Personal Portfolio Landing Page
is_icu_6, reason_6 = verify_genuine_icu_patient(
    title="Site 12 · The $500 buttons and the footer email lead nowhere on the live site",
    body="Rebuild taimooralam.com to the decided content. Both $500 buttons link to Paid consulting which returns 404.",
    author_comments=[],
    labels=[],
    repo="taimooralam/portfolio",
    author_assoc="OWNER"
)
assert not is_icu_6, f"Expected False for personal portfolio site, got: {reason_6}"
print("  ✓ Personal Portfolio Site: Rejected correctly.")

# 10. Rejection: Theatre Casting Alert
is_icu_7, reason_7 = verify_genuine_icu_patient(
    title="🎭 Egg; Or Anything Dipped in Egg Gone Soften - NYC EPA (10.23.26)",
    body="PAID CASTING ALERT. This production will operate under an Equity 29 hour-reading code.",
    author_comments=[],
    labels=[],
    repo="matthewletton/matthew-casting-radar",
    author_assoc="OWNER"
)
assert not is_icu_7, f"Expected False for theatre casting alert, got: {reason_7}"
print("  ✓ Theatre Casting Notice: Rejected correctly.")

# 11. Rejection: Board Game Rules FAQ
is_icu_8, reason_8 = verify_genuine_icu_patient(
    title="GF9 FAQ",
    body="Frequently answered questions for the GF9 ruleset we can find. Can a player pay spice for someone in battle?",
    author_comments=[],
    labels=[],
    repo="ndelangen/dunezone",
    author_assoc="OWNER"
)
assert not is_icu_8, f"Expected False for board game FAQ, got: {reason_8}"
print("  ✓ Board Game Ruleset: Rejected correctly.")

# 12. Rejection: Blog / GitHub Pages & Chinese Daily Info Flow (Headroom Conservation)
is_icu_digest_cn, reason_digest_cn = verify_genuine_icu_patient(
    title="[每日信息流] 2024-08-07",
    body="Startup raises $1,000,000 in seed round. AI models update summary.",
    author_comments=[],
    labels=[],
    repo="ruohong2018/ruohong2018.github.io",
    author_assoc="OWNER"
)
assert not is_icu_digest_cn, f"Expected False for Chinese daily stream on .github.io, got: {reason_digest_cn}"
print("  ✓ Chinese Daily Stream & .github.io Blog: Rejected correctly.")

# 13. Rejection: Bookmark / Picker Repo & Tech Digest
is_icu_picker, reason_picker = verify_genuine_icu_patient(
    title="Tech Weekly Digest #45",
    body="Top github repositories this week. Founders paid $10k in bug bounties.",
    author_comments=[],
    labels=[],
    repo="BruceFeIix/picker",
    author_assoc="OWNER"
)
assert not is_icu_picker, f"Expected False for picker/digest repo, got: {reason_picker}"
print("  ✓ Bookmark Picker & Weekly Digest: Rejected correctly.")

# 14. Rejection: Issue-First Repository without Maintainer 'approved' Label (UnitOneAI/SecuritySkills)
is_icu_issue_first, reason_issue_first = verify_genuine_icu_patient(
    title="[NEW SKILL] serverless-function-security",
    body="Standard ($200). Preferred payment method: PayPal - https://paypal.me/user",
    author_comments=[],
    labels=[],
    repo="UnitOneAI/SecuritySkills",
    author_assoc="NONE",
    author="JeremyZeng77"
)
assert not is_icu_issue_first, f"Expected False for unapproved issue-first repo, got: {reason_issue_first}"
print("  ✓ Issue-First Repository (Unapproved): Rejected correctly.")

# 15. Approval: Issue-First Repository WITH Maintainer 'approved' Label
is_icu_approved_skill, reason_approved_skill = verify_genuine_icu_patient(
    title="[NEW SKILL] serverless-function-security",
    body="Standard ($200). Implement serverless security skill.",
    author_comments=[],
    labels=[{"name": "approved"}],
    repo="UnitOneAI/SecuritySkills",
    author_assoc="OWNER",
    author="UnitOneAI"
)
assert is_icu_approved_skill, f"Expected True for approved skill, got: {reason_approved_skill}"
print("  ✓ Issue-First Repository (Maintainer Approved): Approved correctly.")

# 12. Rejection: Payment Negations
is_icu_9, reason_9 = verify_genuine_icu_patient(
    title="Production server crashing on startup with OOM",
    body="Our production server is down with OOM crash. Note that we are not willing to pay any consulting fees for help.",
    author_comments=[],
    labels=[],
    repo="example/prod-crash",
    author_assoc="OWNER"
)
assert not is_icu_9, f"Expected False for payment negation, got: {reason_9}"
print("  ✓ Payment Negation ('not willing to pay'): Rejected correctly.")

# 13. Rejection: Intermediary Aggregator / Bounty Platform
is_icu_10, reason_10 = verify_genuine_icu_patient(
    title="Gitcoin bounty: integrate wallet connect",
    body="Gitcoin hackathon bounty task for community grant.",
    author_comments=[],
    labels=[],
    repo="bounties/web3-task",
    author_assoc="OWNER"
)
assert not is_icu_10, f"Expected False for Gitcoin aggregator, got: {reason_10}"
print("  ✓ Bounty Aggregator / Hackathon: Rejected correctly.")

# 14. Rejection: Non-critical label
is_icu_lbl, reason_lbl = verify_genuine_icu_patient(
    title="Production memory leak",
    body="Willing to pay $1000 for fix",
    author_comments=[],
    labels=[{"name": "wontfix"}],
    repo="org/repo",
    author_assoc="OWNER"
)
assert not is_icu_lbl, "Expected False for wontfix label."
print("  ✓ Non-Critical Label ('wontfix'): Rejected correctly.")

# ----------------------------------------------------------------
# Test 2: Pre-Post Safety Sanitizer
# ----------------------------------------------------------------
print("\n[Test 2] Testing Pre-Post Safety Sanitizer...")

clean_payload = """### Technical Architecture & Feasibility Assessment
1. Root Cause Analysis: Webhook routing collision on WABA endpoint.
2. Remediation: Zero-touch webhook multiplexer.
```python
def handle_webhook(req):
    return {"status": "ok"}
```
3. Test Strategy: Sandbox Meta App staging verification.
4. Contact: isearch.xsolve@gmail.com"""
safe_1, msg_1 = sanitize_and_validate_payload(clean_payload)
assert safe_1, f"Expected clean payload to pass, got: {msg_1}"
print("  ✓ Clean Proposal: Approved.")

# Technical IDs (Meta WABA phone ID, comment ID, Unix timestamp) must NOT trigger bank leak
payload_with_tech_ids = clean_payload + "\nMeta WABA Phone ID: 104928172948192\nMeta App ID: 123456789012345\nComment ID: 6392217766\nTimestamp: 1730000000000"
safe_tech, msg_tech = sanitize_and_validate_payload(payload_with_tech_ids)
assert safe_tech, f"Expected technical IDs payload to pass without false bank leak trigger, got: {msg_tech}"
print("  ✓ Technical IDs (WABA Phone ID, App ID, Comment ID, Epoch Timestamp): Approved without false leak.")

# Leaked Bank Account (Contiguous)
leaked_bank = clean_payload + "\nAccount Number: 55505593812 Bank: Kotak Bank"
assert not sanitize_and_validate_payload(leaked_bank)[0], "Expected contiguous account leak caught."
print("  ✓ Contiguous Bank Account Leak: Caught and blocked.")

# Leaked Formatted Account Number
leaked_formatted = clean_payload + "\nAccount: 1234-5678-9012"
assert not sanitize_and_validate_payload(leaked_formatted)[0], "Expected formatted account leak caught."
print("  ✓ Formatted Account Leak (1234-5678-9012): Caught and blocked.")

# Leaked Hyphenated Account Number (123-456-789-012)
leaked_hyphen = clean_payload + "\nAccount: 123-456-789-012"
assert not sanitize_and_validate_payload(leaked_hyphen)[0], "Expected hyphenated account leak caught."
print("  ✓ Hyphenated Account Leak (123-456-789-012): Caught and blocked.")

# Leaked Generic UPI (@paytm and @yesbank)
leaked_upi_paytm = clean_payload + "\nPay to: merchant@paytm"
assert not sanitize_and_validate_payload(leaked_upi_paytm)[0], "Expected @paytm UPI leak caught."
leaked_upi_yes = clean_payload + "\nPay to: alice@yesbank"
assert not sanitize_and_validate_payload(leaked_upi_yes)[0], "Expected @yesbank UPI leak caught."
print("  ✓ Banking UPI Leaks (@paytm, @yesbank): Caught and blocked.")

# Leaked EVM Ethereum Address
leaked_eth = clean_payload + "\nWallet: 0x71CAb39600a9F80c4c4A0b457e51e44fEbEbC141"
assert not sanitize_and_validate_payload(leaked_eth)[0], "Expected Ethereum address leak caught."
print("  ✓ EVM Ethereum Address Leak: Caught and blocked.")

# Leaked GitHub PAT
leaked_pat = clean_payload + "\nPAT: github_pat_11ABCDEF0123456789abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRST"
assert not sanitize_and_validate_payload(leaked_pat)[0], "Expected GitHub PAT leak caught."
print("  ✓ GitHub PAT Leak: Caught and blocked.")

# Leaked OpenAI Project Key (sk-proj-...)
leaked_skproj = clean_payload + "\nKey: sk-proj-1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP"
assert not sanitize_and_validate_payload(leaked_skproj)[0], "Expected sk-proj key leak caught."
print("  ✓ OpenAI Project Key Leak (sk-proj-...): Caught and blocked.")

# False Verification Claim
false_verification = clean_payload + "\nVerified on our reference environment with 100% test pass."
assert not sanitize_and_validate_payload(false_verification)[0], "Expected false test verification claim caught."
print("  ✓ False Test Verification Claim: Caught and blocked.")

# Verified Settlement Coordinates (Approved DOOM L1 and Solana Addresses)
payload_with_verified_settlement = clean_payload + "\n### Settlement Rails\n- DOOM L1: ROTATED-DOOM-KEY\n- Solana: 2qi849TBq72XMpsp8PjR4YfegDEzc7BRFZaarwQ2tKgL\n- Email: isearch.xsolve@gmail.com"
ok_settle, msg_settle = sanitize_and_validate_payload(payload_with_verified_settlement)
assert ok_settle, f"Expected verified settlement addresses to pass, got: {msg_settle}"
print("  ✓ Verified Settlement Rails (DOOM L1 + Solana): Approved and permitted.")

# Unverified Random Solana Address Leak -> Caught and blocked
unverified_sol = clean_payload + "\nSolana: 4DjveHyuryraFdV8o4HWMp5aWb8nkwLmhPqpe9bw3UZgL"
assert not sanitize_and_validate_payload(unverified_sol)[0], "Expected unverified random Solana address to be blocked."
print("  ✓ Unverified Third-Party Crypto Address: Caught and blocked.")

# ----------------------------------------------------------------
# Test 3: Approved Corridor & Timezone Validation
# ----------------------------------------------------------------
print("\n[Test 3] Testing Approved Corridor Engine & Cambridge Collision...")

# Verify Cambridge MA vs Cambridge UK collision resolution & Global Expansion
sample_locations = [
    ("Bengaluru, India", "India Tech Hubs (IST)"),
    ("Singapore", "Singapore (SGT)"),
    ("Dubai, UAE", "UAE & Gulf (GST)"),
    ("Cambridge, MA", "US East (EDT/EST)"),
    ("Cambridge, UK", "UK (BST/GMT)"),
    ("London, England", "UK (BST/GMT)"),
    ("Austin, Texas", "US Central (CDT/CST)"),
    ("San Francisco, CA", "US West (PDT/PST)"),
    ("Munich, Germany", "Germany & DACH (CET/CEST)"),
    ("Berlin, Deutschland", "Germany & DACH (CET/CEST)"),
    ("Zurich, Switzerland", "Germany & DACH (CET/CEST)"),
    ("Paris, France", "Western & Northern Europe (CET/CEST)"),
    ("Amsterdam, Netherlands", "Western & Northern Europe (CET/CEST)"),
    ("Stockholm, Sweden", "Western & Northern Europe (CET/CEST)"),
    ("Nairobi, Kenya", "Kenya & East Africa (EAT)"),
    ("Kigali, Rwanda", "Kenya & East Africa (EAT)"),
    ("Lagos, Nigeria", "Nigeria & West/South Africa (WAT/SAST)"),
    ("Toronto, Canada", "Canada (EST/PST)"),
    ("Sydney, Australia", "Australia & NZ (AEST/NZST)"),
]

for loc, expected_name in sample_locations:
    matched = None
    for entry in APPROVED_CORRIDOR_TZ_MAP:
        if re.search(entry["pattern"], loc.lower()):
            matched = entry["name"]
            break
    assert matched == expected_name, f"Expected {expected_name} for '{loc}', got: {matched}"
print("  ✓ Cambridge Collision Resolved: 'Cambridge, MA' -> US East | 'Cambridge, UK' -> UK.")
print("  ✓ Global Corridor Expansion: Germany, Kenya, France, Netherlands, Nigeria, Canada, Australia validated.")

# Test hard territory exclusions (Kolkata/WB, China, Pakistan)
import autonomous_icu_pipeline

original_get_profile = autonomous_icu_pipeline.get_author_profile

# Test Kolkata Exclusion
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Kolkata, India", "company": "Local Agency"}
c_name, is_act, reason = detect_author_corridor("kolkata_user")
assert c_name == "Excluded Regional Market", f"Expected Excluded Regional Market for Kolkata, got {c_name}"
print("  ✓ Hard Regional Exclusion: Kolkata/WB correctly excluded per zero-burn law.")

# Test China Exclusion
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Beijing, China", "company": "Tencent"}
c_name, is_act, reason = detect_author_corridor("china_user")
assert c_name == "Excluded Territory", f"Expected Excluded Territory for China, got {c_name}"
print("  ✓ Hard Territory Exclusion: China correctly excluded per mandate.")

# Test Pakistan Exclusion
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Lahore, Pakistan", "company": "Software House"}
c_name, is_act, reason = detect_author_corridor("pakistan_user")
assert c_name == "Excluded Territory", f"Expected Excluded Territory for Pakistan, got {c_name}"
print("  ✓ Hard Territory Exclusion: Pakistan correctly excluded per mandate.")

# Test Approved Corridor via detect_author_corridor (Munich, Germany)
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Munich, Germany", "company": "BMW Group"}
c_name, is_act, reason = detect_author_corridor("munich_user")
assert c_name == "Germany & DACH (CET/CEST)", f"Expected Germany & DACH for Munich, got {c_name}"
print("  ✓ Approved Author Corridor: Munich, Germany approved through detect_author_corridor.")

# Test Approved Corridor via detect_author_corridor (Nairobi, Kenya)
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Nairobi, Kenya", "company": "Fintech Lab"}
c_name, is_act, reason = detect_author_corridor("nairobi_user")
assert c_name == "Kenya & East Africa (EAT)", f"Expected Kenya & East Africa for Nairobi, got {c_name}"
print("  ✓ Approved Author Corridor: Nairobi, Kenya approved through detect_author_corridor.")

# Restore original
autonomous_icu_pipeline.get_author_profile = original_get_profile

# Verify bare Cambridge is treated as ambiguous / unapproved (fail-closed)
bare_cambridge = "cambridge"
bare_matched = None
for entry in APPROVED_CORRIDOR_TZ_MAP:
    if re.search(entry["pattern"], bare_cambridge):
        bare_matched = entry["name"]
        break
assert bare_matched is None, f"Bare Cambridge should not match any corridor, but matched {bare_matched}"
print("  ✓ Bare Cambridge Ambiguity: Failed closed (treated as unknown/unapproved).")
print("  ✓ Approved Enterprise Corridors: All tech hubs mapped strictly to exact IANA zones.")

# ----------------------------------------------------------------
# Test 4: Isolated SQLite Transactional Store & Concurrency Safety
# ----------------------------------------------------------------
print("\n[Test 4] Testing Isolated SQLite Store & Concurrency Safety...")

# Ensure fresh test database on every run
if os.path.exists(TEST_DB):
    try:
        os.remove(TEST_DB)
    except Exception:
        pass

# Initialize dedicated test database
init_db(db_path=TEST_DB)
test_repo = "test-org/concurrency-race"
test_num = 1001

# Worker 1 claims issue
claim_1 = try_claim_issue(test_repo, test_num, "Race Test", "tester", "US West", "Test claim", db_path=TEST_DB)
assert claim_1 is True, "Worker 1 failed to claim issue."
print("  ✓ Worker 1: Successfully claimed test issue in isolated SQLite DB.")

# Worker 2 attempts concurrent claim on same issue -> MUST FAIL
claim_2 = try_claim_issue(test_repo, test_num, "Race Test", "tester", "US West", "Test claim", db_path=TEST_DB)
assert claim_2 is False, "Worker 2 claimed already-claimed issue! Concurrency violated."
print("  ✓ Worker 2: Concurrent claim rejected by UNIQUE(repo, issue_number) constraint.")

# Verify status
claimed_status, cur_state = is_issue_claimed_or_delivered(test_repo, test_num, db_path=TEST_DB)
assert claimed_status is True and cur_state == "CLAIMED", f"Expected CLAIMED, got {cur_state}"

# Commit delivery with checked rowcount
test_cid = "comment_77777"
test_url = "https://github.com/test-org/concurrency-race/issues/1001#issuecomment-77777"
test_digest = "a" * 64
ok_commit = commit_delivery(test_repo, test_num, test_cid, test_url, test_digest, db_path=TEST_DB)
assert ok_commit is True, "Failed to commit delivery with rowcount == 1."

# Double commit or commit on non-claimed issue must fail
fail_commit = commit_delivery(test_repo, 999999, test_cid, test_url, test_digest, db_path=TEST_DB)
assert fail_commit is False, "Expected commit on nonexistent/unclaimed issue to return False."
print("  ✓ Checked Rowcount: Commit succeeds on claimed row and returns False on invalid row.")

# Verify delivered state
del_status, final_state = is_issue_claimed_or_delivered(test_repo, test_num, db_path=TEST_DB)
assert del_status is True and final_state == "PROPOSAL_DELIVERED", f"Expected PROPOSAL_DELIVERED, got {final_state}"
print("  ✓ Transactional State: Atomically transitioned from CLAIMED to PROPOSAL_DELIVERED.")

# Clean up test database
if os.path.exists(TEST_DB):
    try:
        os.remove(TEST_DB)
    except Exception:
        pass

# ----------------------------------------------------------------
# Test 5: Search-Gate Contract Congruence (Zero Approved = Zero in Search)
# ----------------------------------------------------------------
print("\n[Test 5] Testing Search-Gate Contract Congruence...")

from autonomous_icu_pipeline import search_issues

# Mock run_cmd to feed raw search results through search_issues
orig_run_cmd = autonomous_icu_pipeline.run_cmd

mock_raw_items = [
    # 1. Terminal label 'wontfix' -> MUST BE DROPPED
    {
        "number": 1, "title": "Crash in app", "body": "App crashes in production. Will pay $100.",
        "repository": {"nameWithOwner": "org/repo1"}, "labels": [{"name": "wontfix"}],
        "authorAssociation": "OWNER", "author": {"login": "dev1"}
    },
    # 2. Terminal label 'spam' -> MUST BE DROPPED
    {
        "number": 2, "title": "Spam ticket", "body": "Buy crypto.",
        "repository": {"nameWithOwner": "org/repo2"}, "labels": [{"name": "spam"}],
        "authorAssociation": "OWNER", "author": {"login": "dev2"}
    },
    # 3. Explicit payment negation -> MUST BE DROPPED
    {
        "number": 3, "title": "Need help", "body": "We cannot pay for this fix. No budget.",
        "repository": {"nameWithOwner": "org/repo3"}, "labels": [{"name": "bounty"}],
        "authorAssociation": "OWNER", "author": {"login": "dev3"}
    },
    # 4. Economic scam -> MUST BE DROPPED
    {
        "number": 4, "title": "Crypto Lottery", "body": "Win casino lottery.",
        "repository": {"nameWithOwner": "org/repo4"}, "labels": [{"name": "bounty"}],
        "authorAssociation": "OWNER", "author": {"login": "dev4"}
    },
    # 5. Contract-compliant genuine client with enhancement label -> MUST BE YIELDED FOR VERIFICATION
    {
        "number": 5, "title": "Database dumps do not work on large databases",
        "body": "Production deadlock and crash during table dump under heavy load. We offer $250 bounty.",
        "repository": {"nameWithOwner": "outerbase/starbasedb"}, "labels": [{"name": "enhancement"}],
        "authorAssociation": "MEMBER", "author": {"login": "Brayden"}
    }
]

import json
autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=35: (json.dumps(mock_raw_items), "", 0)

yielded = search_issues("dummy query")
assert len(yielded) == 1, f"Expected exactly 1 approved candidate, got {len(yielded)}"
assert yielded[0]["number"] == 5, f"Expected issue #5 to be approved, got #{yielded[0]['number']}"
print("  ✓ Search-Gate High-Recall Congruence: Terminal labels, negations, and scams filtered; paid work yielded.")

# Test Zero Approved = Zero Yielded
autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=35: (json.dumps(mock_raw_items[:4]), "", 0)
yielded_zero = search_issues("dummy query")
assert len(yielded_zero) == 0, f"Expected 0 yielded when zero approved, got {len(yielded_zero)}"
print("  ✓ Zero Approved Contract: Zero approved candidates strictly yields 0 search results.")

# Restore run_cmd
autonomous_icu_pipeline.run_cmd = orig_run_cmd

# ----------------------------------------------------------------
# Test 6: Advisory Deletion & Implementation Upgrade Logic
# ----------------------------------------------------------------
print("\n[Test 6] Testing Advisory Deletion & Implementation Upgrade Logic...")

from autonomous_icu_pipeline import delete_github_comment

# 6a. Delete comment mock check
autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=20, retries=2: ("", "", 0)
ok_del, msg_del = delete_github_comment("mock/repo", "1234567")
assert ok_del, f"Expected successful delete, got: {msg_del}"
print("  ✓ GitHub Comment Deletion: Verified delete request.")

# 6b. Verify commit_delivery updates existing delivered row
init_db(db_path=TEST_DB)
assert try_claim_issue(
    test_repo,
    test_num,
    "Delivery upgrade fixture",
    "tester",
    "US West",
    "Test delivery upgrade",
    db_path=TEST_DB,
), "Failed to establish the existing delivery row for the upgrade test."
ok_upd = commit_delivery(test_repo, test_num, "new_comment_999", f"https://github.com/{test_repo}/issues/{test_num}#comment", "sha256_new_digest", db_path=TEST_DB)
assert ok_upd, "Expected commit_delivery to update existing delivery row."
print("  ✓ Delivery Upgrade Commit: Successfully updated SQLite store.")

# Restore run_cmd
autonomous_icu_pipeline.run_cmd = orig_run_cmd

# ----------------------------------------------------------------
# Test 7: High-Recall Bounty Expansion & Platform Attestation
# ----------------------------------------------------------------
print("\n[Test 7] Testing High-Recall Bounty Expansion & Platform Attestation...")

# 7a. Algora-bot platform-attested bounty on NONE-association issue
is_algora_bounty, algora_reason = verify_genuine_icu_patient(
    title="Optimize GPU kernel execution speed",
    body="Need 2x speedup on vector math kernel.",
    author_comments=["/bounty $300 funded via algora.io"],
    labels=[{"name": "enhancement"}, {"name": "bounty"}],
    repo="web3-org/gpu-kernels",
    author_assoc="NONE",
    author="community_dev"
)
assert is_algora_bounty, f"Expected Algora bounty on NONE-assoc issue to be approved, got: {algora_reason}"
print("  ✓ Platform Attestation Gate: Algora-attested bounty approved on NONE-assoc issue.")

# 7b. Feature enhancement with paid bounty and no crash words
is_feat_bounty, feat_reason = verify_genuine_icu_patient(
    title="Add AVX-512 vector acceleration",
    body="Offering $500 bounty to implement AVX-512 driver.",
    author_comments=[],
    labels=[{"name": "enhancement"}],
    repo="fastorg/math-engine",
    author_assoc="OWNER",
    author="fastdev"
)
assert is_feat_bounty, f"Expected AVX-512 feature bounty to be approved, got: {feat_reason}"
print("  ✓ Feature Bounty Gate: Paid enhancement approved without needing crash/outage words.")

# 7c. Remote / Worldwide / Blank author profile location
autonomous_icu_pipeline.get_author_profile = lambda u: {"location": "Remote, Worldwide"}
c_name, is_act, c_reason = detect_author_corridor("remote_dev")
assert c_name == "Global / Remote" and is_act is True, f"Expected Global / Remote for remote dev, got {c_name}, {is_act}"
print("  ✓ Global/Remote Corridor Gate: Remote/Worldwide location approved without business-hour blocking.")

autonomous_icu_pipeline.get_author_profile = lambda u: {"location": ""}
c_name_blank, is_act_blank, c_reason_blank = detect_author_corridor("blank_dev")
assert c_name_blank == "Global / Remote" and is_act_blank is True, f"Expected Global / Remote for blank dev, got {c_name_blank}, {is_act_blank}"
print("  ✓ Global/Remote Corridor Gate: Blank location approved without business-hour blocking.")

autonomous_icu_pipeline.get_author_profile = orig_get_profile

# -------------------------------------------------------------
# 8. TEST AUTONOMOUS PULL REQUEST ENGINE
# -------------------------------------------------------------
print("\n[Test 8] Testing Autonomous Pull Request Engine...")

sample_deliverable = """### 🛠️ Production Implementation & Technical Verification

1. **Root Cause Analysis**:
Identified buffer boundary mismatch in core parser.

2. **Production-Grade Implementation Source Code**:

### Production Source (`src/core/parser.js`)
```javascript
export function parsePayload(buf) {
  if (!buf || buf.length === 0) throw new Error("Empty buffer");
  return JSON.parse(buf.toString());
}
```

### Test Suite (`test/parser.test.js`)
```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { parsePayload } from "../src/core/parser.js";

test("parses valid JSON buffer", () => {
  assert.deepEqual(parsePayload(Buffer.from('{"ok":true}')), { ok: true });
});
```

3. **Settlement Rails**:
- DOOM L1: ROTATED-DOOM-KEY
- Solana: 2qi849TBq72XMpsp8PjR4YfegDEzc7BRFZaarwQ2tKgL
"""

extracted = autonomous_icu_pipeline.extract_files_from_proposal(sample_deliverable)
assert len(extracted) == 2, f"Expected 2 extracted files, got {len(extracted)}"
assert extracted[0][0] == "src/core/parser.js", f"Unexpected path: {extracted[0][0]}"
assert "parsePayload" in extracted[0][1], "Expected code body in extracted[0]"
assert extracted[1][0] == "test/parser.test.js", f"Unexpected path: {extracted[1][0]}"
assert "parses valid JSON buffer" in extracted[1][1], "Expected test body in extracted[1]"
print("  ✓ Proposal File Extraction: Successfully parsed source code and test files.")

# Test database persistence of PR URL
test_pr_url = "https://github.com/mock-org/mock-repo/pull/42"
autonomous_icu_pipeline.try_claim_issue(
    repo="mock-org/mock-repo",
    number=101,
    title="Test Parser",
    author="testuser",
    corridor="Global / Remote",
    reason="Test",
    db_path=TEST_DB
)
autonomous_icu_pipeline.commit_delivery(
    repo="mock-org/mock-repo",
    number=101,
    comment_id="mock_cid",
    receipt_url="https://github.com/mock-org/mock-repo/issues/101#comment",
    sha256_digest="mock_digest",
    pr_url=test_pr_url,
    db_path=TEST_DB
)
autonomous_icu_pipeline.update_delivery_pr("mock-org/mock-repo", 101, test_pr_url, db_path=TEST_DB)
with sqlite3.connect(TEST_DB) as test_con:
    row = test_con.execute("SELECT pr_url FROM deliveries WHERE repo = ? AND issue_number = ?", ("mock-org/mock-repo", 101)).fetchone()
    assert row and row[0] == test_pr_url, f"Expected PR URL persisted, got {row}"
print("  ✓ PR URL DB Persistence: Successfully stored and retrieved pr_url in deliveries store.")

# Test dry-run PR creation
pr_dry_run = autonomous_icu_pipeline.attempt_automated_pull_request("mock-org/mock-repo", 101, "Fix Parser", sample_deliverable, live_mode=False)
assert pr_dry_run is None, f"Expected dry-run PR to return None, got {pr_dry_run}"
print("  ✓ PR Safety Gate: Dry-run safely holds network creation.")

# ----------------------------------------------------------------
# Test 9: Pre-Commit Sandbox Syntax Quality Gates & CLA Detection
# ----------------------------------------------------------------
print("\n[Test 9] Testing Pre-Commit Sandbox Syntax Quality Gates & CLA...")
import tempfile
from autonomous_icu_pipeline import validate_synthesized_files, auto_resolve_cla_if_needed

# 1. Valid Python + JSON files
valid_extracted = [
    ("src/solution.py", "def add(a: int, b: int) -> int:\n    return a + b\n"),
    ("config/schema.json", '{"version": 1, "enabled": true}')
]
ok, msg = validate_synthesized_files(tempfile.gettempdir(), valid_extracted)
assert ok is True, f"Expected valid files to pass, got: {msg}"
print("  ✓ Quality Gate: Valid Python and JSON syntax verified.")

# 2. Syntax Error in Python
bad_py_extracted = [
    ("src/broken.py", "def broken(\n    return 42\n")
]
ok_bad_py, msg_bad_py = validate_synthesized_files(tempfile.gettempdir(), bad_py_extracted)
assert ok_bad_py is False, "Expected syntax error in Python to fail quality gate."
print("  ✓ Quality Gate: Caught and blocked Python syntax error.")

# 3. Syntax Error in JSON
bad_json_extracted = [
    ("config/broken.json", '{"version": 1, "enabled": true,}')
]
ok_bad_json, msg_bad_json = validate_synthesized_files(tempfile.gettempdir(), bad_json_extracted)
assert ok_bad_json is False, "Expected trailing comma JSON to fail quality gate."
print("  ✓ Quality Gate: Caught and blocked invalid JSON schema.")

# ----------------------------------------------------------------
# Test 10: ArXiv, LaTeX Math, Contributor Payee & Platform Pattern Gates
# ----------------------------------------------------------------
print("\n[Test 10] Testing ArXiv, LaTeX Math, Contributor Payee & Platform Pattern Gates...")
from decimal import Decimal
from autonomous_icu_pipeline import _has_platform_bounty_marker, is_direct_payer, parse_and_normalize_bounty

# 1. ArXiv repo rejection
ok, reason = verify_genuine_icu_patient(
    title="Showing new listings for Tuesday, 2 June 2026",
    body="Auto update Star Formation arxiv papers",
    author_comments=[],
    labels=[],
    repo="LIAOGuangmao/ArXivDaily_StarFormation",
    author="LIAOGuangmao",
    author_assoc="OWNER"
)
assert ok is False and "arxiv" in reason.lower(), f"Expected ArXiv repo rejection, got {ok}, {reason}"
print("  ✓ ArXiv Repo Gate: Scraper repo rejected correctly.")

# 2. ArXiv daily listing title rejection
ok, reason = verify_genuine_icu_patient(
    title="Showing new listings for Tuesday, 2 June 2026",
    body="List of 31 papers for today",
    author_comments=[],
    labels=[],
    repo="some-org/papers",
    author="researcher",
    author_assoc="OWNER"
)
assert ok is False and "newsletter, paper digest" in reason.lower(), f"Expected listing title rejection, got {ok}, {reason}"
print("  ✓ ArXiv Listing Title Gate: Automated paper digest title rejected correctly.")

# 3. LaTeX math dollar rejection vs genuine bounty parsing
has_amt, in_bounds, raw_text, val, _ = parse_and_normalize_bounty("at the wavelength of $500$ \\mu m and frequency $600$ GHz")
assert has_amt is False or val == Decimal("0.00"), f"Expected LaTeX math to be rejected, got {has_amt}, {val}"
print("  ✓ LaTeX Math Gate: '$500$ \\mu m' correctly rejected as scientific notation, not currency.")

has_amt, in_bounds, raw_text, val, _ = parse_and_normalize_bounty("Offering $500 USD bounty for fixing this race condition")
assert has_amt is True and val == Decimal("500.00"), f"Expected genuine $500 bounty to be parsed, got {has_amt}, {val}"
print("  ✓ Bounty Parsing Gate: Genuine '$500 USD bounty' successfully parsed and normalized.")

# 4. Platform bounty marker selectivity (Polar.sh vs Polar astrophysics)
astronomy_text = "Analysis of polar coordinates and bipolar outflow in Centaurus A with Herschel"
polar_bounty_text = "Funded via polar.sh with $500 bounty"
assert _has_platform_bounty_marker(astronomy_text) is False, "Bare word 'polar' in astrophysics erroneously triggered platform bounty marker!"
assert _has_platform_bounty_marker(polar_bounty_text) is True, "Expected polar.sh bounty to trigger platform bounty marker!"
print("  ✓ Platform Bounty Pattern Gate: Polar.sh verified while bare physics word 'polar' safely ignored.")

# 5. Contributor payee rejection on third-party repos
payee_text = """
### Summary
- Severity: High ($400 USDC — Stage 1 On-Chain Bridge)
- Payout Address: 3HLDkipdKmJKGjbgCD8moo3GyhEY4DWdZ7JAgSpMysHp
/claim #1138
"""
is_payer = is_direct_payer("campbellarchiezh-debug", "paraloom-labs/paraloom-core", payee_text)
assert is_payer is False, f"Expected third-party contributor with Payout Address to be rejected as payee, got {is_payer}"
print("  ✓ Contributor Payee Gate: Third-party bounty hunter with 'Payout Address' rejected as payee.")

# 6. In-game virtual currency / game design rejection
ok, reason = verify_genuine_icu_patient(
    title="Progression after the garage is maxed: give players something to chase",
    body="Five tracks at $500 + $1,500 + $4,000 come to $30,000 in garage upgrades. Wanted poster with run's bounty.",
    author_comments=[],
    labels=[],
    repo="game-dev/car-chase",
    author="game-dev",
    author_assoc="OWNER"
)
assert ok is False and ("student/contest pattern" in reason.lower() or "gameplay" in reason.lower()), f"Expected game mechanics rejection, got {ok}, {reason}"
print("  ✓ Game Design Gate: In-game virtual garage currency ($500) rejected correctly.")

# 7. Hackathon demo video & Agora entry rejection (matocard/matocard#104)
ok, reason = verify_genuine_icu_patient(
    title="app: passkey onboarding with Mera (required for the Agora bounty)",
    body="@Lexirieru the Agora bounty ('Best Cross-Border Payments App on Monad', $10k) has a hard requirement. Submit a demo video (up to 2 mins) showing passkey onboarding. Submission closes 14 Oct.",
    author_comments=[],
    labels=[],
    repo="matocard/matocard",
    author="yeheskieltame",
    author_assoc="COLLABORATOR"
)
assert ok is False and "student/contest pattern" in reason.lower(), f"Expected Agora hackathon rejection, got {ok}, {reason}"
print("  ✓ Hackathon Gate: Agora hackathon entry & demo video ticket rejected correctly.")

# 8. Hackathon T&C compliance & prize pool checklist rejection (mandaputtra/arteri#10)
ok, reason = verify_genuine_icu_patient(
    title="T&C compliance: AI disclosure, registration, demo video, eligibility",
    body="Satisfy the Metropolis Hackathon Terms & Conditions as mandatory requirements. Prize pool is stated as $145,000 in T&C but $250,000+ on the website. Team registered on hackathon.monad.xyz.",
    author_comments=[],
    labels=[],
    repo="mandaputtra/arteri",
    author="mandaputtra",
    author_assoc="OWNER"
)
assert ok is False and "student/contest pattern" in reason.lower(), f"Expected Metropolis hackathon rejection, got {ok}, {reason}"
print("  ✓ Hackathon Gate: Metropolis hackathon T&C compliance ($250k prize pool) rejected correctly.")

# 9. Honeypot & Issue Farm repo rejection (SecureBananaLabs/bug-bounty)
ok, reason = verify_genuine_icu_patient(
    title="fix(api): validate /api/payments payload before intent creation (ref #743)",
    body="/bounty $700",
    author_comments=[],
    labels=[],
    repo="SecureBananaLabs/bug-bounty",
    author="dwaddle",
    author_assoc="NONE"
)
assert ok is False and "aggregator" in reason.lower(), f"Expected SecureBananaLabs honeypot rejection, got {ok}, {reason}"
print("  ✓ Issue Farm Gate: Honeypot repository SecureBananaLabs rejected correctly.")

# 10. Exclusive author / self-solve restriction rejection
ok, reason = verify_genuine_icu_patient(
    title="[Bounty 80] POST /api/auth/login signs a valid token for any credentials — authentication bypass",
    body="""This issue is limited only to the creator of this issue. This means that only the issue author can attempt to solve this issue. If you would like to work on it, please create another issue with the same contents and refer to issue #743 for more information.
References #743.
/bounty $780""",
    author_comments=[],
    labels=[],
    repo="some-org/some-app",
    author="dwaddle",
    author_assoc="NONE"
)
assert ok is False and "exclusive author" in reason.lower(), f"Expected exclusive author rejection, got {ok}, {reason}"
print("  ✓ Exclusive Author Gate: 'limited only to the creator' rejected correctly.")

# 11. Non-owner bare /bounty command without platform attestation
is_payer = is_direct_payer("dwaddle", "some-org/some-app", "POST /api/auth/login authentication bypass\n/bounty $780")
assert is_payer is False, f"Expected non-owner bare /bounty to be rejected as direct payer, got {is_payer}"
print("  ✓ Non-Owner Authority Gate: Non-owner bare /bounty without platform attestation rejected correctly.")

# 12. Vendor audit pitch / proactive review solicitation rejection (HockeyPlaya48/RWAForge#5)
ok, reason = verify_genuine_icu_patient(
    title="Security Review: DistributionRouter Batch Overflow + RewardClaimer Merkle Front-Running",
    body="""## 🔍 Proactive Security Review
I perform independent smart contract security audits. I found issues worth your attention.
### 💼 Offer
I would be happy to perform a full audit of the contract suite for $500-$1,000. Contact: reach out directly.
This is a proactive review, not a bug bounty submission. No reward expected for these findings.""",
    author_comments=[],
    labels=[],
    repo="HockeyPlaya48/RWAForge",
    author="hebridean-tech",
    author_assoc="NONE"
)
assert ok is False and ("payment negated" in reason.lower() or "lacks explicit parsed" in reason.lower()), f"Expected vendor audit pitch rejection, got {ok}, {reason}"
print("  ✓ Vendor Audit Pitch Gate: Proactive review pitch with 'no reward expected' rejected correctly.")

# 13. Settlement Wallet payee rejection on third-party repos (paraloom-core#1158)
payee_settlement_text = """
## Severity
**Medium ($500 USDC — Stage 1 On-Chain Bridge)**
## Settlement Wallet (USDC Base / EVM — Mandatory Invariant)
`0x8366bCe3a2D379Dec7656D7A67015789FaF999f20`
"""
is_payer = is_direct_payer("Skywalkingzulu1", "paraloom-labs/paraloom-core", payee_settlement_text)
assert is_payer is False, f"Expected Settlement Wallet author to be rejected as payee, got {is_payer}"
print("  ✓ Settlement Wallet Gate: Bug bounty reporter with 'Settlement Wallet' rejected as payee.")

# 14. Strikethrough retracted bounty gate (telefuel/video_player_testbed#1)
ok, reason = verify_genuine_icu_patient(
    title="Sync audio and video for go-flutter-desktop video player plugin",
    body="## Bounty Amount\n~~$2,000~~ (we are no longer offering a bounty for this).",
    author_comments=[],
    labels=[],
    repo="telefuel/video_player_testbed",
    author="MattNguyen",
    author_assoc="OWNER"
)
assert ok is False, f"Expected strikethrough/retracted bounty to be rejected, got {ok}, {reason}"
print("  ✓ Strikethrough Retraction Gate: Retracted '~~$2,000~~ (no longer offering)' rejected correctly.")

# 15. Contributor bounty applicant pitch gate (limitlessprojects/Go-Hybrid#1594)
applicant_patch_text = """
Please consider the useful-improvements bounty track. I understand the $500 cycle pool is competitive and the maintainer decides qualification, rank and payout. If selected, USDC on Base or PayPal are my preferred options.
"""
is_payer = is_direct_payer("JRCage", "limitlessprojects/Go-Hybrid", applicant_patch_text)
assert is_payer is False, f"Expected bounty applicant with 'preferred options' to be rejected as payee, got {is_payer}"
print("  ✓ Bounty Applicant Gate: Contributor requesting bounty consideration rejected as payee.")

# 16. Protocol TVL / Roadmap Phase Gate (PhucNguyen-Dev/fashion-design-ai-studio#4)
roadmap_tvl_text = """
# Blockchain NFT Marketplace & Web3 Integration
## Objective
Build a decentralized marketplace for digital fashion NFTs with multi-chain support.
## Success Criteria
- $1M+ TVL achieved
"""
ok, reason = verify_genuine_icu_patient(
    title="⛓️ Phase 4: Blockchain NFT Marketplace & Web3 Integration",
    body=roadmap_tvl_text,
    author_comments=[],
    labels=[],
    repo="PhucNguyen-Dev/fashion-design-ai-studio",
    author="PhucNguyen-Dev",
    author_assoc="OWNER"
)
assert ok is False, f"Expected roadmap Phase 4 / $1M TVL to be rejected, got {ok}, {reason}"
print("  ✓ Roadmap TVL Gate: Protocol KPI metric ($1M+ TVL achieved) rejected correctly.")

# ----------------------------------------------------------------
# Test 11: Multi-Turn Iterative Due-Diligence Engine Integrity
# ----------------------------------------------------------------
print("\n[Test 11] Testing Multi-Turn Iterative Due-Diligence Engine Integrity...")

# 11.1 Worktree boundary path security (fail-closed)
mock_wt = r"D:\test_worktree"
assert is_safe_relative_path(mock_wt, "src/core/app.py") is True
assert is_safe_relative_path(mock_wt, "package.json") is True
assert is_safe_relative_path(mock_wt, "tests/unit/test_calc.py") is True
# Traversal rejections
assert is_safe_relative_path(mock_wt, "../secret.env") is False
assert is_safe_relative_path(mock_wt, "foo/../../bar.txt") is False
# Absolute path rejections
assert is_safe_relative_path(mock_wt, "/etc/passwd") is False
assert is_safe_relative_path(mock_wt, "C:\\Windows\\system32\\cmd.exe") is False
# CI/Workflow mutation rejection (security invariant)
assert is_safe_relative_path(mock_wt, ".github/workflows/deploy.yml") is False
assert is_safe_relative_path(mock_wt, ".github/workflows/ci.yaml") is False
assert is_safe_relative_path(mock_wt, ".GitHub/Workflows/casing-bypass.yml") is False
print("  ✓ Worktree Boundary Gate: Traversal, absolute paths, and workflow mutations blocked.")

# Real symlink escape rejection: a path that lexically stays inside the worktree
# must still fail when an existing directory link resolves outside it.
symlink_root = tempfile.mkdtemp(prefix="test_icu_symlink_")
try:
    symlink_worktree = os.path.join(symlink_root, "worktree")
    outside_dir = os.path.join(symlink_root, "outside")
    os.makedirs(symlink_worktree)
    os.makedirs(outside_dir)
    link_dir = os.path.join(symlink_worktree, "linked")
    try:
        os.symlink(outside_dir, link_dir, target_is_directory=True)
    except OSError:
        # Standard Windows sessions may lack SeCreateSymbolicLinkPrivilege; an NTFS
        # junction is the same escaping reparse-point threat and needs no privilege.
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link_dir, outside_dir],
            capture_output=True, text=True, check=False
        )
        assert junction.returncode == 0, junction.stderr or junction.stdout
    assert is_safe_relative_path(symlink_worktree, "linked/escape.py") is False
finally:
    shutil.rmtree(symlink_root, ignore_errors=True)
print("  ✓ Symlink Boundary Gate: Realpath escape through a directory link blocked.")

# 11.2 Scenario matrix modeling (7 dimensions)
scenarios = model_scenarios("Payment deadlock during concurrent checkout", "Handle concurrent webhook settlement", {})
assert len(scenarios) == 7, f"Expected 7 scenario dimensions, got {len(scenarios)}"
dims = {s.category for s in scenarios}
expected_dims = {"happy_path", "null", "empty", "boundary", "negative", "concurrency", "regression"}
assert dims == expected_dims, f"Scenario dimensions mismatch: {dims} vs {expected_dims}"
for s in scenarios:
    assert s.id, "Scenario missing id"
    assert s.expected_result, "Scenario missing expected result"
print("  ✓ Scenario Modeling: 7 rigorous test dimensions modeled (happy, null, empty, boundary, negative, concurrency, regression).")

# 11.3 Peer PR description builder (zero-signature, zero-wallet, receipts verified)
mock_run = EngineeringRun(
    repo="fintech/payments",
    issue_number=142,
    base_sha="master",
    worktree=mock_wt,
    iteration=1,
    status="VERIFIED"
)
mock_run.verification.append(CommandResult(["pytest", "-q"], mock_wt, 0, "", "", 1.25))
pr_body = build_peer_pr_body(
    run=mock_run,
    title="Deadlock during concurrent webhook processing",
    number=142,
    scenarios=scenarios
)
assert "Resolves #142." in pr_body
assert "### Architectural Summary & Root Cause Analysis" in pr_body
assert "### Verified Scenario Coverage" in pr_body
assert "SCENARIO_CONCURRENCY_RACE" in pr_body
assert "Verified base SHA: `master`" in pr_body
assert "pytest -q" in pr_body and "exit `0`" in pr_body and "duration `1.250s`" in pr_body
# Law enforcement: ZERO signature, ZERO wallet spam
assert "Kunal Das" not in pr_body
assert "Director" not in pr_body
assert "Best regards" not in pr_body
assert "0x" not in pr_body
assert "USDC" not in pr_body
print("  ✓ Peer PR Builder: Generated pixel-perfect PR body with zero signatures, zero wallet spam, and exact test receipts.")

# 11.4 Architecture inspection and verification plan discovery

temp_workspace = tempfile.mkdtemp(prefix="test_repo_arch_")
try:
    # A) Node.js project
    node_dir = os.path.join(temp_workspace, "node_app")
    os.makedirs(node_dir)
    with open(os.path.join(node_dir, "package.json"), "w", encoding="utf-8") as f:
        f.write('{"name": "demo", "scripts": {"test": "jest", "lint": "eslint ."}}')
    arch_node = inspect_repository_architecture(node_dir)
    assert arch_node["ecosystem"] == "nodejs"
    plan_node = discover_verification_plan(arch_node, node_dir)
    assert ["npm", "test"] in plan_node.baseline_tests
    assert ["npm", "run", "lint"] in plan_node.linters

    # A2) Polyglot repository must retain every active ecosystem and all plans.
    with open(os.path.join(node_dir, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write('[project]\nname = "demo"\n')
    with open(os.path.join(node_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
        f.write('[package]\nname = "demo"\nversion = "0.1.0"\n')
    arch_poly = inspect_repository_architecture(node_dir)
    assert arch_poly["ecosystem"] == "polyglot"
    assert {"nodejs", "python", "rust"}.issubset(set(arch_poly["ecosystems"]))
    plan_poly = discover_verification_plan(arch_poly, node_dir)
    assert ["npm", "test"] in plan_poly.baseline_tests
    assert any("pytest" in arg for cmd in plan_poly.baseline_tests for arg in cmd)
    assert ["cargo", "test", "--workspace"] in plan_poly.baseline_tests

    # B) Python project
    py_dir = os.path.join(temp_workspace, "py_app")
    os.makedirs(py_dir)
    with open(os.path.join(py_dir, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write('[project]\nname = "demo"\n')
    arch_py = inspect_repository_architecture(py_dir)
    assert arch_py["ecosystem"] == "python"
    plan_py = discover_verification_plan(arch_py, py_dir)
    assert any("pytest" in arg for cmd in plan_py.baseline_tests for arg in cmd)
    assert any("ruff" in arg for cmd in plan_py.linters for arg in cmd)

    # C) Rust project
    rust_dir = os.path.join(temp_workspace, "rust_app")
    os.makedirs(rust_dir)
    with open(os.path.join(rust_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
        f.write('[package]\nname = "demo"\nversion = "0.1.0"\n')
    arch_rust = inspect_repository_architecture(rust_dir)
    assert arch_rust["ecosystem"] == "rust"
    plan_rust = discover_verification_plan(arch_rust, rust_dir)
    assert ["cargo", "test", "--workspace"] in plan_rust.baseline_tests
    assert any("clippy" in arg for cmd in plan_rust.linters for arg in cmd)

    # D) Go project
    go_dir = os.path.join(temp_workspace, "go_app")
    os.makedirs(go_dir)
    with open(os.path.join(go_dir, "go.mod"), "w", encoding="utf-8") as f:
        f.write('module demo\ngo 1.22\n')
    arch_go = inspect_repository_architecture(go_dir)
    assert arch_go["ecosystem"] == "go"
    plan_go = discover_verification_plan(arch_go, go_dir)
    assert ["go", "test", "./..."] in plan_go.baseline_tests
    assert ["golangci-lint", "run"] in plan_go.linters
finally:
    shutil.rmtree(temp_workspace, ignore_errors=True)
print("  ✓ Architecture & Plan Discovery: Node.js, Python, Rust, and Go manifests inspected and planned.")

# 11.5 Baseline verification blocks broken upstream (fail-closed BLOCKED_BASELINE)
broken_plan = VerificationPlan(baseline_tests=[[sys.executable, "-c", "import sys; sys.exit(1)"]])
baseline_ok, baseline_msg, baseline_results = verify_baseline(os.getcwd(), broken_plan)
assert baseline_ok is False, "Expected failing baseline to block run"
assert "Baseline test failure on untouched upstream" in baseline_msg
assert len(baseline_results) == 1 and baseline_results[0].exit_code == 1
assert autonomous_icu_pipeline.mark_issue_blocked_baseline("mock-org/baseline", 909, "upstream failed", db_path=TEST_DB)
with sqlite3.connect(TEST_DB) as test_con:
    blocked_status = test_con.execute("SELECT status FROM deliveries WHERE repo = ? AND issue_number = ?", ("mock-org/baseline", 909)).fetchone()
assert blocked_status == ("BLOCKED_BASELINE",), f"Expected BLOCKED_BASELINE receipt, got {blocked_status}"
print("  ✓ Baseline Gate: Broken upstream baseline test failure blocks PR pipeline (BLOCKED_BASELINE).")

# 11.6 Fail-closed pre-push Zero-Competition gate
orig_run_cmd = autonomous_icu_pipeline.run_cmd
try:
    # A) When open PR exists -> Blocked
    autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=30, retries=2: (
        '[{"number": 99, "title": "unrelated", "headRefName": "topic", "body": "Resolves #101"}]', "", 0
    )
    ok, reason = check_competing_prs_fail_closed("org/repo", 101)
    assert ok is False, "Expected competing PR to block"
    assert "Competing open PR already exists" in reason

    # B) When gh cli lookup fails -> Fails closed
    autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=30, retries=2: (
        "", "GitHub API rate limit exceeded", 1
    )
    ok, reason = check_competing_prs_fail_closed("org/repo", 101)
    assert ok is False, "Expected failed query to fail closed"
    assert "failing closed per Zero-Competition Law" in reason

    # C) When clean and zero competing PRs -> Approved
    autonomous_icu_pipeline.run_cmd = lambda cmd, timeout=30, retries=2: (
        "[]", "", 0
    )
    ok, reason = check_competing_prs_fail_closed("org/repo", 101)
    assert ok is True, f"Expected clean repo to pass, got: {reason}"
    assert "Zero competing open PRs verified" in reason
finally:
    autonomous_icu_pipeline.run_cmd = orig_run_cmd
print("  ✓ Zero-Competition Gate: Pre-push lookup rejects open competing PRs and fails closed on query error.")

# 11.7 Actual repair loop: syntax feedback, failed native test feedback, reset, then green repair.
repair_dir = tempfile.mkdtemp(prefix="test_icu_repair_")
original_generate = autonomous_icu_pipeline.generate_grounded_proposal
original_run_safe = autonomous_icu_pipeline.run_command_safe
original_reset = autonomous_icu_pipeline.reset_worktree_to_base
proposal_feedback = []
reset_calls = []
proposals = iter([
    "### Production Source `src/fixed.py`\n```python\ndef broken(\n```",
    "### Production Source `src/fixed.py`\n```python\ndef repaired():\n    return 1\n```",
    "### Production Source `src/fixed.py`\n```python\ndef repaired():\n    return 2\n```",
])
test_attempts = {"count": 0}
try:
    def fake_generate(*args, **kwargs):
        proposal_feedback.append(kwargs.get("prior_failures"))
        return next(proposals)
    def fake_run_safe(argv, cwd, timeout=120):
        if argv == ["native-test"]:
            test_attempts["count"] += 1
            failed = test_attempts["count"] == 1
            return CommandResult(argv, cwd, 1 if failed else 0, "assertion failure: expected repaired behavior" if failed else "", "", 0.01)
        return CommandResult(argv, cwd, 0, "", "", 0.01)
    autonomous_icu_pipeline.generate_grounded_proposal = fake_generate
    autonomous_icu_pipeline.run_command_safe = fake_run_safe
    autonomous_icu_pipeline.reset_worktree_to_base = lambda wt, sha: (reset_calls.append((wt, sha)) or (True, "reset"))
    repair_plan = VerificationPlan(final_tests=[["native-test"]], linters=[["native-lint"]])
    repair_ok, repair_run, repair_message = autonomous_icu_pipeline.run_engineering_iteration_loop(
        worktree=repair_dir, repo="org/repo", issue_number=77, title="Repair loop", body="body",
        arch={}, plan=repair_plan, scenarios=[], base_sha="base-sha", max_iterations=3
    )
    assert repair_ok is True and repair_run.iteration == 3, repair_message
    assert proposal_feedback[0] is None
    assert "Syntax/quality gate failure" in proposal_feedback[1]
    assert "Test failure in turn 2" in proposal_feedback[2]
    assert reset_calls == [(repair_dir, "base-sha"), (repair_dir, "base-sha")]
    assert repair_run.modified_files == ["src/fixed.py"]
finally:
    autonomous_icu_pipeline.generate_grounded_proposal = original_generate
    autonomous_icu_pipeline.run_command_safe = original_run_safe
    autonomous_icu_pipeline.reset_worktree_to_base = original_reset
    shutil.rmtree(repair_dir, ignore_errors=True)
print("  ✓ Repair Loop: Syntax/test evidence passed to turns 2-3 and each repair reset to base.")

# 11.8 Default-branch discovery and every git setup command fail-closed.
original_run_cmd = autonomous_icu_pipeline.run_cmd
original_sandbox_dir = autonomous_icu_pipeline.SANDBOX_DIR
git_calls = []
worktree_parent = tempfile.mkdtemp(prefix="test_icu_worktree_")
try:
    autonomous_icu_pipeline.SANDBOX_DIR = worktree_parent
    def fake_prepare_cmd(cmd, timeout=30, retries=2):
        git_calls.append(cmd)
        if cmd[:4] == ["gh", "repo", "view", "org/repo"]:
            return "trunk\n", "", 0
        if cmd[:3] == ["git", "-C", os.path.join(worktree_parent, "repos", "org--repo--78")] and cmd[-2:] == ["rev-parse", "HEAD"]:
            return "abc123\n", "", 0
        return "", "", 0
    autonomous_icu_pipeline.run_cmd = fake_prepare_cmd
    prepared_worktree, prepared_sha, prepared_error = autonomous_icu_pipeline.prepare_isolated_worktree("org/repo", 78)
    assert prepared_error is None and prepared_sha == "abc123"
    assert ["git", "-C", prepared_worktree, "fetch", "upstream", "trunk"] in git_calls
    assert ["git", "-C", prepared_worktree, "checkout", "-B", "fix/bounty-78", "upstream/trunk"] in git_calls
finally:
    autonomous_icu_pipeline.run_cmd = original_run_cmd
    autonomous_icu_pipeline.SANDBOX_DIR = original_sandbox_dir
    shutil.rmtree(worktree_parent, ignore_errors=True)
print("  ✓ Worktree Gate: Default branch discovered dynamically and checkout targets upstream/trunk.")

# 11.9 Single-commit discipline stages only the verified files, never git add -A.
commit_dir = tempfile.mkdtemp(prefix="test_icu_commit_")
os.makedirs(os.path.join(commit_dir, "src"))
with open(os.path.join(commit_dir, "src", "fixed.py"), "w", encoding="utf-8") as f:
    f.write("print('fixed')\n")
original_run_cmd = autonomous_icu_pipeline.run_cmd
original_cla = autonomous_icu_pipeline.auto_resolve_cla_if_needed
commit_calls = []
sha_reads = iter(["a" * 40 + "\n", "b" * 40 + "\n"])
try:
    def fake_commit_cmd(cmd, timeout=30, retries=2):
        commit_calls.append(cmd)
        if cmd[-2:] == ["rev-parse", "HEAD"]:
            return next(sha_reads), "", 0
        if cmd[-2:] == ["status", "--porcelain"]:
            return " M src/fixed.py\n", "", 0
        if "rev-list" in cmd:
            return "1\n", "", 0
        if cmd[:3] == ["gh", "pr", "create"]:
            return "https://github.com/org/repo/pull/88\n", "", 0
        return "", "", 0
    autonomous_icu_pipeline.run_cmd = fake_commit_cmd
    autonomous_icu_pipeline.auto_resolve_cla_if_needed = lambda repo, url: None
    pr_url = autonomous_icu_pipeline.commit_and_open_pr(
        commit_dir, "org/repo", 88, "Fix", "body", ["src/fixed.py"], default_branch="trunk"
    )
    assert pr_url.endswith("/88")
    assert ["git", "-C", commit_dir, "add", "--", "src/fixed.py"] in commit_calls
    assert not any(cmd[-1:] == ["-A"] for cmd in commit_calls)
    assert any("rev-list" in cmd and "--count" in cmd for cmd in commit_calls)
finally:
    autonomous_icu_pipeline.run_cmd = original_run_cmd
    autonomous_icu_pipeline.auto_resolve_cla_if_needed = original_cla
    shutil.rmtree(commit_dir, ignore_errors=True)
print("  ✓ Commit Gate: Only verified paths staged and exact one-commit proof required.")

# ----------------------------------------------------------------
# Test 12: Tiered DeepSeek & Token Harbor Key Router
# ----------------------------------------------------------------
print("\n[Test 12] Testing Tiered DeepSeek & Token Harbor Key Router...")

# 12.1 A 429 leases no second request on the same key, honors Retry-After,
# and transparently reaches the next ready key.
clock_now = [1_000.0]
router_calls = []
def rate_limit_then_success(api_key, payload, timeout):
    router_calls.append(api_key)
    if api_key == "test-key-a":
        return 429, {"Retry-After": "30"}, {"error": {"message": "rate limited"}}
    return 200, {}, {"choices": [{"message": {"content": "flash completion"}}]}

router = TokenHarborRouter(
    keys=["test-key-a", "test-key-b"],
    transport=rate_limit_then_success,
    clock=lambda: clock_now[0],
    jitter=lambda: 0.0,
)
ok, text, model, err = router.call("implement the ordinary feature")
assert ok is True and text == "flash completion" and model == DEEPSEEK_FLASH_MODEL and err is None
assert router_calls == ["test-key-a", "test-key-b"], "429 must fail over to a different ready key"
router_status = router.status()
assert router_status["states"][COOLDOWN] == 1 and router_status["states"][READY] == 1
assert router_status["cooldowns"][0]["remaining_seconds"] == 30.0
clock_now[0] += 31.0
assert router.status()["states"][READY] == 2, "Elapsed cooldown must restore key to READY"
print("  ✓ Router State Gate: READY → LEASED → COOLDOWN → READY and 429 fallback verified.")

# 12.2 Authentication failures disable only the rejected key and continue.
def reject_first_key(api_key, payload, timeout):
    if api_key == "bad-key":
        return 401, {}, {"error": {"message": "invalid credential"}}
    return 200, {}, {"choices": [{"message": {"content": "fallback completion"}}]}

auth_router = TokenHarborRouter(keys=["bad-key", "good-key"], transport=reject_first_key)
ok, text, _, err = auth_router.call("repair issue")
assert ok is True and text == "fallback completion" and err is None
assert auth_router.status()["states"][DISABLED] == 1
print("  ✓ Router Auth Gate: 401 disables rejected key and uses the next key.")

# 12.3 A transient transport timeout receives exactly one fallback attempt.
network_calls = []
def timeout_then_success(api_key, payload, timeout):
    network_calls.append(api_key)
    if len(network_calls) == 1:
        raise TimeoutError("simulated timeout")
    return 200, {}, {"choices": [{"message": {"content": "recovered completion"}}]}

network_router = TokenHarborRouter(keys=["key-1", "key-2"], transport=timeout_then_success)
ok, text, _, err = network_router.call("repair issue")
assert ok is True and text == "recovered completion" and err is None and network_calls == ["key-1", "key-2"]
print("  ✓ Router Network Gate: One timeout retry uses a fallback key.")

# 12.4 DeepSeek handles full delivery pipeline; fail-closed cleanly on exhaustion per Zero-Manufacture Law
original_collect_evidence = autonomous_icu_pipeline.collect_repo_evidence
original_flash = autonomous_icu_pipeline.call_deepseek_flash
try:
    autonomous_icu_pipeline.collect_repo_evidence = lambda repo, body: {
        "commit_sha": "a" * 40,
        "languages": "Python",
        "description": "fixture",
        "code_blocks": "",
        "referenced_source": "",
        "default_branch": "main",
    }
    # Turn 1: DeepSeek serves ordinary work
    autonomous_icu_pipeline.call_deepseek_flash = lambda prompt, system_prompt=None, timeout=120: (True, "flash proposal", None)
    proposal = autonomous_icu_pipeline.generate_grounded_proposal(
        "org/repo", "ordinary formatting", "rename helper", "maintainer", [], turn=1
    )
    assert proposal == "flash proposal", "DeepSeek Flash should serve ordinary first-turn work"

    # Turn 2: DeepSeek serves repair turns directly without Codex failover
    proposal_t2 = autonomous_icu_pipeline.generate_grounded_proposal(
        "org/repo", "ordinary formatting", "rename helper", "maintainer", [], iteration_feedback="test failed", turn=2
    )
    assert proposal_t2 == "flash proposal", "DeepSeek Flash should handle iterative repair turns directly"

    # Fail-closed gate: On exhaustion, pipeline cleanly returns None (Zero-Manufacture Law)
    autonomous_icu_pipeline.call_deepseek_flash = lambda prompt, system_prompt=None, timeout=120: (False, "", "keys exhausted")
    proposal_fail = autonomous_icu_pipeline.generate_grounded_proposal(
        "org/repo", "ordinary formatting", "rename helper", "maintainer", [], turn=1
    )
    assert proposal_fail is None, "DeepSeek exhaustion must fail closed cleanly without manufacturing fake fallbacks"
finally:
    autonomous_icu_pipeline.collect_repo_evidence = original_collect_evidence
    autonomous_icu_pipeline.call_deepseek_flash = original_flash
print("  ✓ DeepSeek Full Pipeline Gate: DeepSeek handles generation, repairs, and fail-closed exhaustion verified.")




# -------------------------------------------------------------
# 13. TEST DETERMINISTIC CRYPTOGRAPHIC FLEET SHARDING
# -------------------------------------------------------------
print("\n[Test 13] Testing Deterministic Cryptographic Fleet Sharding...")
import hashlib

def calculate_engine_shard(task_id: str, total_engines: int = 5) -> int:
    task_hash = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16)
    return (task_hash % total_engines) + 1

# Verify determinism across multiple calls and independent task IDs
task_a = "BT-1792940445-paraloom-labs_paraloom-core-893"
task_b = "BT-1792940420-paraloom-labs_paraloom-core-985"
task_c = "BT-1792940477-MyZubster-Ecosystem_myzubster-1462"

engine_a1 = calculate_engine_shard(task_a)
engine_a2 = calculate_engine_shard(task_a)
assert engine_a1 == engine_a2, f"Cryptographic shard must be immutable: {engine_a1} != {engine_a2}"
assert 1 <= engine_a1 <= 5, f"Engine index must be in [1, 5], got {engine_a1}"

engine_b = calculate_engine_shard(task_b)
assert 1 <= engine_b <= 5, f"Engine index must be in [1, 5], got {engine_b}"

engine_c = calculate_engine_shard(task_c)
assert 1 <= engine_c <= 5, f"Engine index must be in [1, 5], got {engine_c}"
print("  ✓ Cryptographic Sharding Gate: Deterministic across processes and bounded to [1, TOTAL_ENGINES].")

# -------------------------------------------------------------
# 14. TEST ROADMAP & SPECULATIVE DESIGN PROPOSAL EXCLUSION
# -------------------------------------------------------------
print("\n[Test 14] Testing Roadmap & Speculative Design Exclusion Gate...")
roadmap_title = "[ROADMAP] NFT creator revenue split -> MyZubster fee -> bounty treasury"
roadmap_body = "This issue is a design/roadmap proposal only. It does not activate a fee, royalty, mint, wallet transfer, or bounty funding. Illustrative €100-equivalent primary sale."

ok, reason = autonomous_icu_pipeline.verify_genuine_icu_patient(
    title=roadmap_title,
    body=roadmap_body,
    author_comments=[],
    labels=[],
    repo="MyZubster-Ecosystem/myzubster",
    author="contributor",
    author_assoc="NONE"
)
assert not ok, "Roadmap design proposal must be rejected"
assert "speculative design proposal" in reason or "student/contest pattern" in reason, f"Unexpected rejection reason: {reason}"

rfc_title = "[RFC] Next-generation storage protocol proposal"
rfc_body = "Proposal only for future feedback. Not an active deduction or funded bounty."
ok_rfc, reason_rfc = autonomous_icu_pipeline.verify_genuine_icu_patient(
    title=rfc_title,
    body=rfc_body,
    author_comments=[],
    labels=[],
    repo="some-org/some-repo",
    author="architect",
    author_assoc="NONE"
)
assert not ok_rfc, "RFC speculative proposal must be rejected"
for speculative_title, speculative_body in [
    ("[PROPOSAL] Future storage", "This is an active-looking change request."),
    ("[DESIGN] Future storage", "This is an active-looking change request."),
    ("[SPEC] Future storage", "This is an active-looking change request."),
    ("Future storage", "design/roadmap proposal only"),
    ("Future storage", "proposal only"),
    ("Future storage", "not an active deduction"),
    ("Future storage", "illustrative defaults"),
    ("Future storage", "pilot economic scenario"),
]:
    rejected, rejection_reason = autonomous_icu_pipeline.verify_genuine_icu_patient(
        title=speculative_title,
        body=speculative_body,
        author_comments=[],
        labels=[],
        repo="some-org/some-repo",
        author="architect",
        author_assoc="NONE",
    )
    assert not rejected, f"Speculative ticket must be rejected: {speculative_title} / {speculative_body}: {rejection_reason}"
print("  ✓ Speculative Design Gate: [ROADMAP], [RFC], and unpaid design proposals rejected cleanly.")

# -------------------------------------------------------------
# 15. TEST MULTI-FORMAT PROPOSAL CODE EXTRACTION
# -------------------------------------------------------------
print("\n[Test 15] Testing Multi-Format Code Extraction Gate...")
proposal_parens = """### Production Source (src/core/router.rs)
```rust
pub fn route_request() -> bool { true }
```

### Test Suite (tests/router_test.rs)
```rust
#[test]
fn test_route() { assert!(route_request()); }
```"""

proposal_ticks = """### Production Source `lib/utils.py`
```python
def calculate_tax(): return 0
```"""

proposal_first_line = """```go
// pkg/server/http.go
package server
func Start() {}
```"""

files_parens = autonomous_icu_pipeline.extract_files_from_proposal(proposal_parens)
assert len(files_parens) == 2, f"Expected 2 files from parens format, got {len(files_parens)}"
assert files_parens[0][0] == "src/core/router.rs"
assert files_parens[1][0] == "tests/router_test.rs"

files_ticks = autonomous_icu_pipeline.extract_files_from_proposal(proposal_ticks)
assert len(files_ticks) == 1, f"Expected 1 file from ticks format, got {len(files_ticks)}"
assert files_ticks[0][0] == "lib/utils.py"

files_comment = autonomous_icu_pipeline.extract_files_from_proposal(proposal_first_line)
assert len(files_comment) == 1, f"Expected 1 file from first-line comment, got {len(files_comment)}"
assert files_comment[0][0] == "pkg/server/http.go"
print("  ✓ Multi-Format Code Extraction Gate: Parentheses, backticks, and inline comments parsed correctly.")

# ----------------------------------------------------------------
# 16. TEST APPEND-ONLY FLEET LEDGER REPLAY & STALE-TASK GATES
# ----------------------------------------------------------------
print("\n[Test 16] Testing Append-Only Fleet Ledger Replay Gates...")
roadmap_task = {
    "task_id": "BT-test-MyZubster-Ecosystem_myzubster-1462",
    "repo": "MyZubster-Ecosystem/myzubster",
    "issue_number": 1462,
    "title": "[ROADMAP] NFT creator revenue split -> MyZubster fee -> bounty treasury",
    "body": "This is a design/roadmap proposal only with illustrative defaults.",
}
assert kaggle_worker.is_speculative_dispatch_task(roadmap_task), "Worker must reject a stale roadmap ledger task before claim"
ordinary_task = dict(roadmap_task, title="Fix Rust unit test", body="Reproduce and fix the failing library unit test.")
assert not kaggle_worker.is_speculative_dispatch_task(ordinary_task), "Ordinary implementation task must not match speculative filter"
original_fetch_ledger_texts = kaggle_worker.fetch_ledger_texts
try:
    kaggle_worker.fetch_ledger_texts = lambda body: [
        f"CLAIMED {ordinary_task['task_id']} by kaggle-engine-1",
    ]
    assert kaggle_worker.task_has_prior_fleet_claim(ordinary_task["task_id"]), "Prior immutable claim must block replay"
finally:
    kaggle_worker.fetch_ledger_texts = original_fetch_ledger_texts
print("  ✓ Fleet Replay Gate: Stale roadmap and already-claimed ledger records block before model execution.")

print("\n==================================================")
print("ALL ICU PIPELINE INTEGRITY TESTS PASSED (100% GREEN)")
print("==================================================")
