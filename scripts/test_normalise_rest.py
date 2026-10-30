import sys
sys.path.append('scripts')
import urllib.parse
import subprocess
import json
import re

q = urllib.parse.quote('commenter:algora-pbc "$100" is:issue is:open is:public archived:false')
cmd = ['gh', 'api', f'/search/issues?q={q}&per_page=10', '--jq', '.items']
out = subprocess.check_output(cmd)
raw_items = json.loads(out)

print(f"Raw items fetched from GitHub REST API: {len(raw_items)}")

normalized = []
for it in raw_items:
    # 1. repo
    repo = None
    if isinstance(it.get("repository"), dict):
        repo = it.get("repository", {}).get("nameWithOwner")
    elif it.get("repository_url"):
        repo = "/".join(it["repository_url"].split("/")[-2:])
    elif it.get("html_url"):
        m = re.match(r"https?://github\.com/([^/]+/[^/]+)/", it["html_url"])
        if m:
            repo = m.group(1)
            
    # 2. commentsCount
    comments_cnt = it.get("commentsCount", it.get("comments", 0))
    it["commentsCount"] = comments_cnt
    
    # 3. authorAssociation
    if "authorAssociation" not in it:
        it["authorAssociation"] = it.get("author_association", "NONE")
        
    # 4. author
    if "author" not in it:
        it["author"] = it.get("user") or {}
        
    # 5. createdAt
    if "createdAt" not in it:
        it["createdAt"] = it.get("created_at", "")
        
    # Set repository
    it["repository"] = {"nameWithOwner": repo}
    
    print(f"  [{repo}#{it.get('number')}] (Author: {it.get('author', {}).get('login')}, Assoc: {it.get('authorAssociation')}, Comments: {comments_cnt}) {it.get('title')}")
    normalized.append(it)

print(f"\nSuccessfully normalized {len(normalized)} items!")
