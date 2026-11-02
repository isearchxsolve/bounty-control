"""Read-only access receipts using the exact credential supplied to a publisher job."""
import argparse
import json
import os
import subprocess


def observe(endpoint):
    done = subprocess.run(['gh', 'api', '--include', endpoint], capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=45)
    header, _, body = done.stdout.replace('\r\n', '\n').partition('\n\n')
    headers = {}
    for line in header.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.lower()] = value.strip()
    try:
        document = json.loads(body)
    except ValueError:
        document = {}
    return {'success': done.returncode == 0, 'http': header.splitlines()[0] if header else None,
            'oauth_scopes': headers.get('x-oauth-scopes'),
            'accepted_permissions': headers.get('x-accepted-github-permissions'),
            'request_id': headers.get('x-github-request-id')}, document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--expect-policy', choices=['all', 'collaborators_only'])
    parser.add_argument('--expect-push', choices=['true', 'false'])
    args = parser.parse_args()
    credential = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
    kind = ('fine-grained PAT' if credential.startswith('github_pat_') else
            'classic PAT' if credential.startswith('ghp_') else
            'installation token' if credential.startswith('ghs_') else 'other or CLI stored credential')
    auth, user = observe('user')
    repository, metadata = observe('repos/' + args.repo)
    pulls, rows = observe('repos/' + args.repo + '/pulls?per_page=1')
    checks = []
    if args.expect_policy:
        checks.append(metadata.get('pull_request_creation_policy') == args.expect_policy)
    if args.expect_push:
        checks.append(metadata.get('permissions', {}).get('push') is (args.expect_push == 'true'))
    print(json.dumps({'credential_kind': kind, 'authentication': auth, 'login': user.get('login'),
                      'repository_access': repository, 'repository': metadata.get('full_name'),
                      'has_pull_requests': metadata.get('has_pull_requests'),
                      'pull_request_creation_policy': metadata.get('pull_request_creation_policy'),
                      'viewer_permissions': metadata.get('permissions'),
                      'pulls_read_access': pulls, 'pulls_read_is_array': isinstance(rows, list),
                      'expected_facts_passed': all(checks) if checks else None,
                      'writes_performed': False}, indent=2))
    return 0 if auth['success'] and repository['success'] and pulls['success'] and all(checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
