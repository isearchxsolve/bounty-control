from pathlib import Path

robust_func = '''def extract_files_from_proposal(proposal: str) -> List[Tuple[str, str]]:
    """
    Parses code blocks and file paths from grounded implementation deliverables.
    Supports markdown headers (###), file labels (**File:**), and inline source comments.
    """
    extracted = []
    # 1. Match section headers: ### Header (`path`) or ### Header `path` or ### Header (path)
    sections = re.split(r'\\n(?=### )', proposal)
    for sec in sections:
        header_match = re.search(r'###[^\\n]*?[\\(`]+\\s*([a-zA-Z0-9_\\-\\./\\\\]+\\.[a-zA-Z0-9]+)\\s*[\\)`]+', sec)
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

    return extracted'''

for p in [Path("scripts/autonomous_icu_pipeline.py"), Path("scripts/kaggle_engine_worker.py")]:
    text = p.read_text(encoding="utf-8")
    start = text.find("def extract_files_from_proposal(proposal: str) -> List[Tuple[str, str]]:")
    end = text.find("def validate_synthesized_files(work_dir: str", start)
    assert start != -1 and end != -1, f"Function boundaries not found in {p}"
    new_text = text[:start] + robust_func + "\n\n" + text[end:]
    p.write_text(new_text, encoding="utf-8")
    print(f"Updated {p}")
