import bounty_admission as ba

print('Current HARD pattern:')
print(ba.HARD.pattern)
print()

test_cases = [
    'I will pay $250 for this bug fix',
    'The login button crashes when clicked',
    'Fix the race condition in the report composer',
    'Payment gateway integration issue',
    'UI is broken on mobile',
    'Payment gateway timeout',
    'Login fails with timeout error',
]

for text in test_cases:
    matches = ba.HARD.findall(text.lower())
    print(f'  "{text}" -> HARD matches: {matches}')