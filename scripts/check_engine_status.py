import subprocess, json

result = subprocess.run(['gh', 'run', 'view', '40746023790', '--json', 'status,conclusion'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print('STDERR:', result.stderr[:200])