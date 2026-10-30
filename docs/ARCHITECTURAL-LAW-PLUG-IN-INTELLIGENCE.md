# THE ARCHITECTURAL SIGNAL (Baba, 2026-10-30)

> "Whenever you fall in the trap of hand-rolling, endlessly iterating for weeks, you know you are
> trying to hardcode intelligence in static code. You need to plug in intelligence."

## The signal
Long iteration on the same problem, with the fix living in more code each time, is not a sign that
the code needs one more rule. It is the sign that a *judgement* has been written as static code and
is being patched forever instead of delegated.

Symptoms, all seen in this pipeline:
- a rule refuses thousands of real items and each patch adds a narrower rule (11,840 refusals from
  one offer regex);
- a list grows every week because reality keeps producing cases the list did not anticipate
  (74 static search expressions);
- the same behaviour is chased through flags, environment variables and prompt wording, each change
  fixing one case and breaking another (the agent door: `--system`, `--json`, `--thinking`);
- the code says what to think rather than what to check.

## The law
1. **Intelligence is delegated, never encoded.** Choice, reading, interpretation and repair belong
   to a model with tools. Code holds only what a model cannot be trusted with: facts and gates.
2. **Code verifies; it does not judge.** Every claim an agent makes is checked against the source
   (does the issue exist, is it open, does the quoted sentence appear literally, does the quote
   name an amount). A failed check is a named refusal, never an edit to the agent's answer.
3. **When a fix requires teaching the code a new case, stop.** That is the signal to give the agent
   the tool it lacks, not to add the case.
4. **Iteration count is a diagnostic.** If the same lane has been patched repeatedly without
   changing the underlying decision-maker, the decision-maker is wrong, not the patches.
5. **Facts are not intelligence.** Environment truths (the shell is PowerShell, the gateway is on
   127.0.0.1:8099, the worktree is a git repo) belong in the prompt or config. Judgement about what
   to search, which issues pay, and how to fix a refused row does not.
6. **Plumbing is allowed to be code.** Installing a tool, starting a proxy, rotating a key and
   writing a receipt are infrastructure. The test is simple: does this line decide *what is true or
   worth doing*? If yes, it belongs to the agent.

## Applied to this repository (2026-10-30)
- Static search expressions and the offer regex: the refusals they caused are the reason the agent
  door exists. The agent searches; `verify_rows` and the intake gates decide admission.
- The agent door is given a worktree and a task, not a script of steps.
- `quote_states_an_amount()` and `quote_is_present()` stay in code: they are checks, not judgement.
- Every door failure (no keys, no Cline, no rows) is a named reason and discovery continues.
