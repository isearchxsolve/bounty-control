# Query lanes: what renders, what does not

`scripts/bounty_queries.json` has five lanes. **Two** of them reach the agent directly
(`founder` and `programs`), covering both wounded founder issues and live platform escrow.

| Lane | Rendered into TASK.md | Used by |
| --- | --- | --- |
| `founder` | **yes** (`render_founder_roster`) | the agent door |
| `programs` | **yes** (`render_founder_roster`) | the agent door (platform escrow bots: Algora, BountyHub, Polar) |
| `normal` | no | retired static loop; kept for tests and the non-agent path |
| `startup` | no | same |
| `priority_discovery` | no | `PRIORITY_DISCOVERY_QUERIES`, popped out of the lane map at import |

Consequences worth stating plainly:

- The rendered roster combines `founder` and `programs` (104 total queries), ordered by
  evidence tier (Tier 0 platform commenters first, then amount-anchored, then surface
  labels, with founder vocabulary veins as reserve).
- De-duplication must be **within a lane only**.
- In addition, code runs an automated pre-sweep across top Tier-0 platform queries to populate
  `search-leads.json` in the scout's worktree, handing real candidates directly to the agent.

`python scripts/query_quality_audit.py` scores the whole file and exits non-zero on a
duplicate, a missing `is:` qualifier, a rotted date anchor, or an ordering inversion in the
rendered lane. It does not judge whether a query is *good*; that stays with the model.
