import subprocess
result = subprocess.run(["gh", "run", "view", "40746023790", "--log"], capture_output=True, text=True)
print(result.stdout[-10000:])
if result.stderr:
    print("STDERR:", result.stderr[:500])

