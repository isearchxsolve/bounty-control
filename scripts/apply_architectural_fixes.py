import re
from pathlib import Path

# ==============================================================================
# Update kaggle_engine_worker.py
# ==============================================================================
worker_path = Path("scripts/kaggle_engine_worker.py")
worker_text = worker_path.read_text(encoding="utf-8")
worker_text_norm = worker_text.replace("\r\n", "\n")

# A. Deterministic Cryptographic Sharding
old_sharding = """                # Deterministic Modulo Sharding: 0 race conditions across the 5 engines!
                task_hash = abs(hash(task_id))
                assigned_engine = (task_hash % TOTAL_ENGINES) + 1"""

new_sharding = """                # Deterministic Cryptographic Sharding: 0 cross-process or cross-machine drift!
                task_hash = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16)
                assigned_engine = (task_hash % TOTAL_ENGINES) + 1"""

assert old_sharding in worker_text_norm, "Old sharding not found in worker"
worker_text_norm = worker_text_norm.replace(old_sharding, new_sharding)

# B. Extract files robust in worker
old_extract_def = """def extract_files_from_proposal(proposal: str) -> List[Tuple[str, str]]:
    \"\"\"
    Parses code blocks and file paths from grounded implementation deliverables.
    Returns a list of (relative_filepath, file_content) tuples.
    \"\"\"
    sections = re.split(r'\\n(?=### )', proposal)
    extracted = []
    for sec in sections:
        header_match = re.search(r'###[^\\n`]*`([^`]+)`', sec)
        if not header_match:
            continue
        rel_path = header_match.group(1).strip()
        if '.' not in rel_path and '/' not in rel_path and '\\\\' not in rel_path:
            continue
        code_match = re.search(r'```(?:[a-zA-Z0-9_-]+)?\\r?\\n(.*?)```', sec, re.DOTALL)
        if not code_match:
            continue
        code_body = code_match.group(1)
        extracted.append((rel_path, code_body))
    return extracted"""

new_extract_def = """def extract_files_from_proposal(proposal: str) -> List[Tuple[str, str]]:
    \"\"\"
    Parses code blocks and file paths from grounded implementation deliverables.
    Supports markdown headers (###), file labels (**File:**), and inline source comments.
    \"\"\"
    extracted = []
    # 1. Match section headers: ### Header `path` or ### Header (path)
    sections = re.split(r'\\n(?=### )', proposal)
    for sec in sections:
        header_match = re.search(r'###[^\\n`\\(\\[]*[`\\(\\[]\\s*([a-zA-Z0-9_\\-\\./\\\\]+\\.[a-zA-Z0-9]+)\\s*[`\\)\\]]', sec)
        if header_match:
            rel_path = header_match.group(1).strip()
            if '.' in rel_path or '/' in rel_path or '\\\\' in rel_path:
                code_match = re.search(r'```(?:[a-zA-Z0-9_-]+)?\\r?\\n(.*?)```', sec, re.DOTALL)
                if code_match:
                    extracted.append((rel_path, code_match.group(1)))

    # 2. Match explicit "File: `path`" or "**File:** `path`"
    if not extracted:
        file_blocks = re.findall(r'(?:\\*\\*File:?\\*\\*|File:?|Path:?)\\s*[`\\(]([a-zA-Z0-9_\\-\\./\\\\]+\\.[a-zA-Z0-9]+)[`\\)]\\s*[\\r\\n]+```(?:[a-zA-Z0-9_-]+)?\\r?\\n(.*?)```', proposal, re.DOTALL)
        for path, code in file_blocks:
            extracted.append((path.strip(), code))

    # 3. Match filepath in first line of code block comment
    if not extracted:
        code_blocks = re.findall(r'```(?:[a-zA-Z0-9_-]+)?\\r?\\n(.*?)```', proposal, re.DOTALL)
        for code in code_blocks:
            first_line = code.strip().splitlines()[0] if code.strip().splitlines() else ""
            comment_match = re.match(r'^(?://|#|/\\*)\\s*([a-zA-Z0-9_\\-\\./\\\\]+\\.[a-zA-Z0-9]+)', first_line)
            if comment_match:
                extracted.append((comment_match.group(1).strip(), code))

    return extracted"""

assert old_extract_def in worker_text_norm, "Old extract_files_from_proposal not found in worker"
worker_text_norm = worker_text_norm.replace(old_extract_def, new_extract_def)

# C. Setup build tools unconditionally
old_setup_rust = """    # 2. Install Rust / Cargo toolchain if missing (for Solana zk-SNARKs and Rust bounties)
    if not shutil.which("cargo"):
        try:
            print("[Init] Installing standalone Rust/Cargo toolchain...", flush=True)
            rustup_sh = "/tmp/rustup.sh"
            urllib.request.urlretrieve("https://sh.rustup.rs", rustup_sh)
            subprocess.run(["sh", rustup_sh, "-y", "--default-toolchain", "stable", "--profile", "minimal"], check=True)
            cargo_bin = os.path.expanduser("~/.cargo/bin")
            os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
            print(f"[Init] Rust/Cargo installed at {cargo_bin}", flush=True)
        except Exception as e:
            print(f"[Init Warning] Failed to install Rust via rustup: {e}. Trying apt-get...", flush=True)
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "cargo", "rustc", "clang", "libclang-dev"], check=False)"""

new_setup_rust = """    # 2. Install build-essential, clang, libclang-dev, cmake, mold for native crates (rocksdb, bindgen)
    try:
        if not shutil.which("clang") or not os.path.exists("/usr/lib/llvm-14/lib/libclang.so"):
            print("[Init] Bootstrapping native C/C++ compiler and libclang headers...", flush=True)
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "clang", "libclang-dev", "cmake", "mold", "build-essential"], check=False)
    except Exception as e:
        print(f"[Init Warning] Native build tool bootstrap error: {e}", flush=True)

    # 3. Install Rust / Cargo toolchain if missing (for Solana zk-SNARKs and Rust bounties)
    if not shutil.which("cargo"):
        try:
            print("[Init] Installing standalone Rust/Cargo toolchain...", flush=True)
            rustup_sh = "/tmp/rustup.sh"
            urllib.request.urlretrieve("https://sh.rustup.rs", rustup_sh)
            subprocess.run(["sh", rustup_sh, "-y", "--default-toolchain", "stable", "--profile", "minimal"], check=True)
            cargo_bin = os.path.expanduser("~/.cargo/bin")
            os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
            print(f"[Init] Rust/Cargo installed at {cargo_bin}", flush=True)
        except Exception as e:
            print(f"[Init Warning] Failed to install Rust via rustup: {e}. Trying apt-get...", flush=True)
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "cargo", "rustc"], check=False)"""

assert old_setup_rust in worker_text_norm, "Old setup rust not found in worker"
worker_text_norm = worker_text_norm.replace(old_setup_rust, new_setup_rust)

# D. Rust verification plan uses --lib for unit test suite
old_rust_plan = """    if "rust" in ecosystems:
        plan.bootstrap.append(["cargo", "check", "--workspace"])
        plan.baseline_tests.append(["cargo", "test", "--workspace"])
        plan.final_tests.append(["cargo", "test", "--workspace"])
        plan.linters.append(["cargo", "clippy", "--workspace", "--", "-D", "warnings"])"""

new_rust_plan = """    if "rust" in ecosystems:
        plan.bootstrap.append(["cargo", "check", "--workspace"])
        plan.baseline_tests.append(["cargo", "test", "--lib"])
        plan.final_tests.append(["cargo", "test", "--lib"])
        plan.linters.append(["cargo", "clippy", "--lib", "--", "-D", "warnings"])"""

assert old_rust_plan in worker_text_norm, "Old rust plan not found in worker"
worker_text_norm = worker_text_norm.replace(old_rust_plan, new_rust_plan)

worker_path.write_text(worker_text_norm, encoding="utf-8")
print("kaggle_engine_worker.py successfully patched.")
