"""Pins the search queries against cp1252 mojibake, which fails silently.

A GitHub label query either matches the label exactly or returns zero results, and a
zero-result query looks identical in the log to a query for a rare label. On 2026-10-29 the
two highest-yield funded-label queries in ``bounty_queries.json`` were stored as the cp1252
misreading of their own UTF-8 bytes: ``\\u00f0\\u0178\\u2019\\u017d`` instead of the gem-stone
emoji, and ``\\u00f0\\u0178\\u2019\\u00b0`` instead of the money-bag emoji. The file was
valid JSON, every suite passed, and the dispatch loop simply reported one fewer candidate
lane, so the only trace was ``normal.raw`` staying small while ``label:bounty`` alone
reported 4,916 open issues.

The measured difference, read live from the search API through a request built in Python
so no shell re-encoding could flatter the result:

    label:"<gem stone> Bounty"   583 open issues   (correct bytes)
    label:"<mojibake> Bounty"      0 open issues   (what the runner actually sent)

These tests therefore assert on the decoded code points of the query strings, never on how
they render in a terminal, because a Windows console re-encodes them on the way out and
displays the correct emoji for the broken string.
"""
import json
import pathlib
import unittest

QUERIES = pathlib.Path(__file__).with_name("bounty_queries.json")

# cp1252 mojibake always begins with one of these pairs: a lead byte mapped to a letter,
# or the UTF-8 continuation prefix read as a Latin-1 letter.
MOJIBAKE_PREFIXES = ("\u00f0\u0178", "\u00e2\u0080")


def strings(value):
    """Every string inside the parsed query file, in document order."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class QueryEncodingTests(unittest.TestCase):
    def setUp(self):
        self.queries = json.loads(QUERIES.read_text(encoding="utf-8"))
        self.all_strings = list(strings(self.queries))

    def test_no_query_carries_mojibake(self):
        for text in self.all_strings:
            for prefix in MOJIBAKE_PREFIXES:
                with self.subTest(prefix=prefix, query=text[:40]):
                    self.assertNotIn(prefix, text)

    def test_the_funded_label_queries_name_a_real_label(self):
        labels = [text for text in self.all_strings
                  if text.startswith('label:"') and "Bounty" in text]
        self.assertTrue(labels, "the funded-label queries disappeared")
        code_points = {text[7] for text in labels}
        self.assertEqual(code_points, {"\U0001f48e", "\U0001f4b0"})

    def test_every_lane_still_declares_queries(self):
        for lane in ("priority_discovery", "normal", "startup", "founder"):
            with self.subTest(lane=lane):
                self.assertTrue(self.queries.get(lane), lane)


if __name__ == "__main__":
    unittest.main()
