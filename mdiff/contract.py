# SPDX-License-Identifier: MIT
"""What every backend must produce, and what it is allowed to omit.

The shape is deliberately close to the JSONL protocol that Malbolge-Engine
already speaks, because inventing a second vocabulary for the same idea would
be the main way this project could go wrong.

The field that carries the most weight is `unavailable`. Backends differ in how
much they can see: an interpreter that prints and exits cannot report a step
count, and pretending otherwise — with a zero, or a guess — would poison every
comparison downstream. Saying "I cannot answer that" is a first-class result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Fields a comparison may look at. Anything outside this is provenance.
COMPARABLE_FIELDS = ("output", "halted", "steps", "a", "c", "d")

#: Statuses, matching Malbolge-Engine's protocol.
#:   OK       — the program halted on its own
#:   INVALID  — the program could not be loaded
#:   TIMEOUT  — a step or wall-clock limit was reached
#:   ERROR    — the backend itself failed
STATUSES = ("OK", "INVALID", "TIMEOUT", "ERROR")


@dataclass(frozen=True, slots=True)
class Outcome:
    """One backend's answer for one program."""

    backend: str
    output: bytes
    halted: bool
    status: str
    steps: int | None = None
    a: int | None = None
    c: int | None = None
    d: int | None = None
    error: str | None = None

    #: Names of COMPARABLE_FIELDS this backend structurally cannot report.
    #: Distinct from a field that is simply None for this run.
    unavailable: tuple[str, ...] = ()

    #: Free-form record of how this was produced: command, version, hashes.
    provenance: dict[str, Any] = field(default_factory=dict)

    def can_report(self, name: str) -> bool:
        return name not in self.unavailable

    def answered(self) -> bool:
        """Did this backend actually execute the program to a conclusion?

        A load failure or a backend crash is not an answer about semantics, and
        must not be compared against one.
        """
        return self.status == "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "status": self.status,
            "output_hex": self.output.hex(),
            "output_len": len(self.output),
            "halted": self.halted,
            "steps": self.steps,
            "a": self.a, "c": self.c, "d": self.d,
            "error": self.error,
            "unavailable": list(self.unavailable),
            "provenance": self.provenance,
        }
