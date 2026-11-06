# PR presentation preview ? 2026-11-06

Illustrative renderer fixture only. These example test outcomes are not claims about a real customer patch. No PR or comment was posted. Default authorship wording is neutral; requested disclosures are retained when supplied.

## PR title

Keep the last item when a page is full

## PR body

Resolves #42.

An exact-page result used an inclusive end index, which dropped its final item. The slice now uses the exclusive bound.

- Correct the page boundary without changing partial-page behavior.
- Add exact-page and short-page regression cases.

### Testing

1 recorded native check passed. Regression: the companion test fails on upstream and passes with this change.

Not verified:
- Mobile-device behavior was not exercised.

<details>
<summary>Test commands and verification details</summary>

Verified base: example-base-sha
Verified head: example-head-sha

Regression: the companion test fails on upstream and passes with this change.

### Commands run
- `python -m pytest tests/test_paging.py -q`: exit 0, 1.50s

Execution receipt: https://example.invalid/verification/42


---
*Sponsorship & Direct Payout Rail:* [https://github.com/sponsors/isearchxsolve](https://github.com/sponsors/isearchxsolve)
</details>

## Original issue handoff

Opened https://example.invalid/project/pull/99 for #42.

An exact-page result used an inclusive end index, which dropped its final item. The slice now uses the exclusive bound.

<details>
<summary>Reproduction and checks</summary>

Affected: Anyone hitting the behaviour described in #42 on `example/project`.

Steps:
1. Run `python -m pytest tests/test_paging.py -q` on the proposed head

Recorded checks:
- 1 recorded native check passed.
- `python -m pytest tests/test_paging.py -q` → exit 0, 1.50s

<details><summary>Full diagnostics</summary>

Base SHA: `example-base-sha`
Head SHA: `example-head-sha`
Regression: the companion test fails on upstream and passes with this change.
Execution receipt: https://example.invalid/verification/42
</details>

</details>
