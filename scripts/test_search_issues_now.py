import sys
sys.path.append('scripts')
from autonomous_icu_pipeline import search_issues

res = search_issues('commenter:algora-pbc "$100"', limit=10)
print(f"search_issues returned {len(res)} items:")
for it in res:
    print("  RETAINED:", it.get("repository", {}).get("nameWithOwner"), it.get("number"), it.get("title"))
