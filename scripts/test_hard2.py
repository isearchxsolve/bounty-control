import bounty_admission as ba
print('HARD pattern:', ba.HARD.pattern[:200])
print()
tests = [
    'I will pay $250 for this bug fix',
    'The login button crashes when clicked',
    'Fix the race condition in the report composer',
    'Payment gateway integration issue',
    'UI is broken on mobile',
    'Payment gateway timeout',
    'Login fails with timeout error',
    'App crashes on startup',
    'Login fails with timeout error',
]
for text in tests:
    matches = ba.HARD.findall(text.lower())
    print(f'  "{text}" -> HARD matches: {matches}')