import actions_dispatch as ad
import inspect

print("=== retry_eligible ===")
print(inspect.getsource(ad.retry_eligible))

print()
print("=== reserve inside dispatch ===")
lines = open("actions_dispatch.py", encoding="utf-8").read().splitlines()
in_reserve = False
for line in lines:
    if "def reserve(old):" in line:
        in_reserve = True
    if in_reserve:
        print(line.rstrip())
        if line.strip() == "return {**(old or {})":
            break