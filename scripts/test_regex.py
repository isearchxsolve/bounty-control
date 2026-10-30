import re

pattern = r'###[^\n]*?[\(`]+\s*([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)\s*[\)`]+'

test_cases = [
    "### Production Source (`src/core/parser.js`)",
    "### Production Source `src/core/parser.js`",
    "### Production Source (src/core/parser.js)",
    "### `src/core/parser.js`",
    "### (src/core/parser.js)"
]

for t in test_cases:
    m = re.search(pattern, t)
    print(t, "-->", m.group(1) if m else "FAIL")
