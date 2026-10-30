import subprocess, json
result = subprocess.run(['gh', 'run', 'view', '40741288844', '--json', 'status,conclusion'], capture_output=True, text=True)
print(result.stdout.strip())
if result.stderr:
    print('STDERR:', result.stderr[:200])