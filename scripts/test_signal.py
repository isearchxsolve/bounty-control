import bounty_admission as ba

tests = [
    'I will pay $250 for this bug fix',
    'The login button crashes when clicked',
    'Fix the race condition in the report composer',
    'Payment gateway integration issue',
    'UI is broken on mobile',
    'Payment gateway timeout',
    'Login fails with timeout error',
    'App crashes on startup',
    'Random discussion about architecture',
    'just chatting',
]
for text in tests:
    matches = ba.HARD.findall(text.lower())
    evidence = ba.engineering_evidence(text, text)
    signal = ba.engineering_signal(evidence)
    units = evidence.get('evidence_units', [])
    for u in units:
        print(f'  "{text}" -> HARD={matches} unit_qualified={u["qualified"]} signal={signal}')