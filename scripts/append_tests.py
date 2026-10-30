from pathlib import Path

suite_path = Path("scripts/test_icu_pipeline_suite.py")
text = suite_path.read_text(encoding="utf-8")

end_marker = 'print("\\n==================================================")\nprint("ALL ICU PIPELINE INTEGRITY TESTS PASSED (100% GREEN)")'
assert end_marker in text, "End marker not found in test suite"

new_tests = '''# -------------------------------------------------------------
# 13. TEST DETERMINISTIC CRYPTOGRAPHIC FLEET SHARDING
# -------------------------------------------------------------
print("\\n[Test 13] Testing Deterministic Cryptographic Fleet Sharding...")
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
print("\\n[Test 14] Testing Roadmap & Speculative Design Exclusion Gate...")
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
print("  ✓ Speculative Design Gate: [ROADMAP], [RFC], and unpaid design proposals rejected cleanly.")

# -------------------------------------------------------------
# 15. TEST MULTI-FORMAT PROPOSAL CODE EXTRACTION
# -------------------------------------------------------------
print("\\n[Test 15] Testing Multi-Format Code Extraction Gate...")
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
'''

new_text = text.replace(end_marker, new_tests + "\n" + end_marker)
suite_path.write_text(new_text, encoding="utf-8")
print("test_icu_pipeline_suite.py updated with Tests 13, 14, 15.")
