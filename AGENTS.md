

## 85. THE ARCHITECTURAL SIGNAL: STOP HARDCODING INTELLIGENCE (Baba 2026-10-30, standing law)

> "Whenever you fall in the trap of hand-rolling, endlessly iterating for weeks, you know you are
> trying to hardcode intelligence in static code. You need to plug in intelligence."

- **The signal:** the same problem keeps needing patches; each fix adds a narrower rule, a longer
  list, another flag, or more prompt wording. That is a judgement encoded as static code.
- **The law:** delegate choice, reading, interpretation and repair to a model with tools. Keep in
  code only facts and gates: does the issue exist, is it open, does the quoted sentence appear
  literally, does the quote name an amount, is the repo alive, is capacity left.
- **The test for any line:** does it decide what is true or worth doing? Then it belongs to the
  agent. Does it only check a claim or move a byte? Then it belongs in code.
- **Do not teach the code a new case.** Give the agent the missing tool and let it correct itself
  from gate feedback.
- Full statement and the audit that produced it: `docs/ARCHITECTURAL-LAW-PLUG-IN-INTELLIGENCE.md`.

## 86. RESUME AFTER REPAIR (Baba 2026-11-03, standing instruction)

- After fixing a pipeline or live E2E failure, resume from the failed stage using its retained journal and real artifacts.
- Preserve completed evidence, original task identities, publication ownership, dispatch generations, and bounded attempt history. Never reset counters or create duplicate work to obtain a green run.
- Revalidate factual prerequisites before reuse. If a checkpoint is missing, incomplete, or stale, repeat only the earliest stage whose evidence is no longer valid and continue downstream.
- Do not restart unrestricted discovery or the entire E2E campaign when a valid later checkpoint exists. Record the source run and repair revision for every continuation.
- Keep the suite contract and release gates intact; a reused checkpoint is not a fabricated successful test receipt.
