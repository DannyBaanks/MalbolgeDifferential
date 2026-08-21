# SPDX-License-Identifier: MIT
"""Tests for the comparator.

The comparator is the whole product. Anyone can run three interpreters; the
work is deciding what a difference *means*, and refusing to call something a
divergence when it is a missing field, a timeout, or an artefact of how a
runtime writes bytes.

Three verdicts, and the boundaries between them are what these tests pin:

    CONSISTENT     the backends that can answer, agree
    DIVERGENCE     they can answer, and disagree
    INCONCLUSIVE   not enough of them could answer to tell
"""
from __future__ import annotations

import unittest

from mdiff.contract import Outcome
from mdiff.compare import Verdict, compare


def outcome(backend: str, **kw) -> Outcome:
    base = dict(backend=backend, output=b"", halted=True, steps=None,
                status="OK", a=None, c=None, d=None, error=None,
                unavailable=())
    base.update(kw)
    return Outcome(**base)


class AgreementTests(unittest.TestCase):
    def test_identical_outcomes_are_consistent(self):
        result = compare([
            outcome("oracle", output=b"Hello World!", steps=40),
            outcome("engine", output=b"Hello World!", steps=40),
        ])
        self.assertEqual(result.verdict, Verdict.CONSISTENT)
        self.assertEqual(result.differences, [])

    def test_a_field_only_one_backend_reports_does_not_break_agreement(self):
        """malbolge-rs cannot report steps. That is not a disagreement."""
        result = compare([
            outcome("oracle", output=b"Hello World!", steps=40),
            outcome("rust", output=b"Hello World!", steps=None,
                    unavailable=("steps",)),
        ])
        self.assertEqual(result.verdict, Verdict.CONSISTENT)
        self.assertIn("steps", result.not_compared)

    def test_output_disagreement_is_a_divergence(self):
        result = compare([
            outcome("oracle", output=b"Hello World!"),
            outcome("engine", output=b"Hello world!"),
        ])
        self.assertEqual(result.verdict, Verdict.DIVERGENCE)
        self.assertTrue(any(d.field == "output" for d in result.differences))

    def test_step_disagreement_is_a_divergence(self):
        result = compare([
            outcome("oracle", steps=40),
            outcome("engine", steps=41),
        ])
        self.assertEqual(result.verdict, Verdict.DIVERGENCE)
        self.assertTrue(any(d.field == "steps" for d in result.differences))

    def test_halt_disagreement_is_a_divergence(self):
        result = compare([
            outcome("oracle", halted=True),
            outcome("engine", halted=False),
        ])
        self.assertEqual(result.verdict, Verdict.DIVERGENCE)


class InconclusiveTests(unittest.TestCase):
    """Cases that look like divergences and are not."""

    def test_a_timeout_is_inconclusive_not_a_divergence(self):
        """One runtime stopped at its limit; the other has no limit.

        They did not disagree about anything: one of them never finished
        answering.
        """
        result = compare([
            outcome("oracle", status="TIMEOUT", halted=False, steps=1_000_000),
            outcome("rust", status="TIMEOUT", halted=False, unavailable=("steps",)),
        ])
        self.assertEqual(result.verdict, Verdict.INCONCLUSIVE)
        self.assertTrue(any("timeout" in r.lower() for r in result.reasons))

    def test_one_timeout_and_one_halt_is_inconclusive(self):
        result = compare([
            outcome("oracle", status="OK", halted=True, output=b"hi"),
            outcome("rust", status="TIMEOUT", halted=False, output=b"hi"),
        ])
        self.assertEqual(result.verdict, Verdict.INCONCLUSIVE)

    def test_a_load_error_is_inconclusive_not_a_divergence(self):
        """A program the runtime refused to load says nothing about semantics."""
        result = compare([
            outcome("oracle", status="INVALID", error="invalid character"),
            outcome("engine", status="OK", output=b"x"),
        ])
        self.assertEqual(result.verdict, Verdict.INCONCLUSIVE)

    def test_fewer_than_two_answering_backends_is_inconclusive(self):
        result = compare([outcome("oracle", output=b"hi")])
        self.assertEqual(result.verdict, Verdict.INCONCLUSIVE)

    def test_a_field_no_backend_reports_is_listed_not_compared(self):
        result = compare([
            outcome("rust", output=b"hi", unavailable=("steps", "a", "c", "d")),
            outcome("rust2", output=b"hi", unavailable=("steps", "a", "c", "d")),
        ])
        self.assertEqual(result.verdict, Verdict.CONSISTENT)
        for field in ("steps", "a", "c", "d"):
            self.assertIn(field, result.not_compared)


class EncodingTests(unittest.TestCase):
    """The trap found while probing malbolge-rs.

    A runtime that writes `a as u8 as char` through Rust's print! emits UTF-8:
    two bytes for anything >= 128. One that uses putc emits one byte. They
    agree on the machine and disagree on stdout.
    """

    def test_utf8_vs_raw_bytes_is_reported_as_encoding_not_semantics(self):
        result = compare([
            outcome("engine", output=bytes([0xA8])),
            outcome("rust", output=bytes([0xC2, 0xA8])),
        ])
        self.assertEqual(result.verdict, Verdict.DIVERGENCE)
        difference = next(d for d in result.differences if d.field == "output")
        self.assertEqual(difference.kind, "encoding")
        self.assertIn("utf-8", difference.detail.lower())

    def test_a_genuine_output_difference_is_not_labelled_encoding(self):
        result = compare([
            outcome("engine", output=b"abc"),
            outcome("rust", output=b"abd"),
        ])
        difference = next(d for d in result.differences if d.field == "output")
        self.assertEqual(difference.kind, "value")

    def test_ascii_output_is_never_an_encoding_difference(self):
        """Below 128 UTF-8 is one byte, so the trap cannot apply."""
        result = compare([
            outcome("engine", output=b"Hello"),
            outcome("rust", output=b"Hello"),
        ])
        self.assertEqual(result.verdict, Verdict.CONSISTENT)


class EvidenceTests(unittest.TestCase):
    """A divergence has to be investigable, not just announced."""

    def test_a_difference_names_every_backend_and_its_value(self):
        result = compare([
            outcome("oracle", steps=40),
            outcome("engine", steps=41),
            outcome("rust", steps=None, unavailable=("steps",)),
        ])
        difference = next(d for d in result.differences if d.field == "steps")
        self.assertEqual(difference.values["oracle"], 40)
        self.assertEqual(difference.values["engine"], 41)
        self.assertNotIn("rust", difference.values, "unavailable is not a value")

    def test_the_result_says_which_backends_took_part(self):
        result = compare([outcome("oracle"), outcome("engine")])
        self.assertEqual(sorted(result.backends), ["engine", "oracle"])


if __name__ == "__main__":
    unittest.main()
