# Query lanes: what renders, what does not

`scripts/bounty_queries.json` has five lanes. Only **one** of them reaches the agent today,
and pretending otherwise has already cost a round of confusion.

| Lane | Rendered into TASK.md | Used by |
| --- | --- | --- |
| `founder` | **yes** (`render_founder_roster`) | the agent door |
| `normal` | no | retired static loop; kept for tests and the non-agent path |
| `startup` | no | same |
| `programs` | no | same |
| `priority_discovery` | no | `PRIORITY_DISCOVERY_QUERIES`, popped out of the lane map at import |

Consequences worth stating plainly:

- Editing a non-founder lane does not change what the agent searches. Measured 2026-11-06:
  a widening added queries across four lanes and only the founder half ever ran.
- De-duplication must therefore be **within a lane only**. Deleting a founder query because
  `normal` already holds the same text removes coverage the agent can see, while the `normal`
  copy reaches nobody.
- The founder lane is rendered in two blocks: evidence-bearing queries first (a platform
  commenter, a printed amount, a label/org surface), then vocabulary veins as explicit
  reserve. The split uses `query_quality_audit.tier()`, so the brief and the audit cannot
  disagree about which half is which.

`python scripts/query_quality_audit.py` scores the whole file and exits non-zero on a
duplicate, a missing `is:` qualifier, a rotted date anchor, or an ordering inversion in the
rendered lane. It does not judge whether a query is *good*; that stays with the model.
