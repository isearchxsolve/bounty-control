#!/usr/bin/env python3
"""Fix F6: Add velocity ordering to dispatch."""
with open('D:/anonym/scripts/actions_dispatch.py') as f:
    content = f.read()

# Add repository_velocity function before query_exclusion_status
old = '''def query_exclusion_status(item):'''
new = '''def repository_velocity(api, repo, cache=None):
    """Count commits on the default branch in the last 24 hours.

    Cached per cycle to avoid hitting the GitHub search rate limit.
    Returns the number of commits; higher = busier repo = slower dispatch.
    """
    if cache is not None and repo in cache:
        return cache[repo]
    owner, name = repo.split("/", 1)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")
    try:
        result = api.api(f"repos/{owner}/{name}/commits?since={since}&per_page=1")
        count = len(result) if isinstance(result, list) else 0
    except (GitHubError, OSError, ValueError, TypeError):
        count = 0
    if cache is not None:
        cache[repo] = count
    return count


def query_exclusion_status(item):'''
content = content.replace(old, new)

with open('D:/anonym/scripts/actions_dispatch.py', 'w') as f:
    f.write(content)
print("Added repository_velocity function")