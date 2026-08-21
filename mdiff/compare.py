# SPDX-License-Identifier: MIT
"""Compare backend outcomes without turning every difference into a bug.

Three verdicts, because two are not enough:

    CONSISTENT     the backends that could answer, agreed
    DIVERGENCE     they could answer, and disagreed
    INCONCLUSIVE   too few could answer to tell

The third exists because most of what goes wrong in differential testing is not
a semantic difference. A runtime hit its step limit; another has no limit. One
refused to load the program. A field is unavailable in one implementation. None
of those is evidence that two interpreters disagree about Malbolge, and
reporting them as such trains people to ignore the tool.

Output differences carry an extra label. A runtime that writes bytes through a
UTF-8 encoder emits two bytes where one that writes raw emits one, for anything
>= 128. The values agree; the streams do not. That is `kind="encoding"`, and it
is worth separating from `kind="value"`, where the program genuinely printed
something else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from .contract import COMPARABLE_FIELDS, Outcome


class Verdict(str, Enum):
    CONSISTENT = "CONSISTENT"
    DIVERGENCE = "DIVERGENCE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class Difference:
    field: str
    kind: str                      # "value" | "encoding"
    values: dict[str, Any]         # backend -> what it reported
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Comparison:
    verdict: Verdict
    backends: tuple[str, ...]
    differences: list[Difference] = field(default_factory=list)
    not_compared: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "backends": list(self.backends),
            "differences": [
                {"field": d.field, "kind": d.kind, "values": _jsonable(d.values),
                 "detail": d.detail}
                for d in self.differences
            ],
            "not_compared": self.not_compared,
            "reasons": self.reasons,
        }


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in values.items()}


def _utf8_of_latin1(raw: bytes) -> bytes:
    """What `raw` becomes if each byte is treated as a code point and encoded."""
    return raw.decode("latin-1").encode("utf-8")


def _classify_output(values: dict[str, bytes]) -> tuple[str, str]:
    """Tell an encoding artefact apart from a real difference in what was printed.

    Returns (kind, detail).
    """
    distinct = list(dict.fromkeys(values.values()))
    if len(distinct) < 2:
        return "value", ""

    # If one candidate is exactly the UTF-8 re-encoding of another, the
    # interpreters agree on the bytes the program produced and disagree only on
    # how they were written out.
    for shorter in distinct:
        for longer in distinct:
            if shorter is longer:
                continue
            if _utf8_of_latin1(shorter) == longer:
                return "encoding", (
                    f"one backend wrote {len(longer)} bytes where another wrote "
                    f"{len(shorter)}: the longer stream is the UTF-8 encoding of the "
                    f"shorter one, so the values agree and the byte streams do not")
    return "value", ""


def compare(outcomes: Sequence[Outcome]) -> Comparison:
    """Compare outcomes for one program across backends."""
    names = tuple(o.backend for o in outcomes)

    answered = [o for o in outcomes if o.answered()]
    reasons: list[str] = []

    # -- can we compare at all? ---------------------------------------------
    non_ok = [o for o in outcomes if not o.answered()]
    for o in non_ok:
        if o.status == "TIMEOUT":
            reasons.append(
                f"{o.backend}: timeout — it never finished, so it did not disagree")
        elif o.status == "INVALID":
            reasons.append(
                f"{o.backend}: refused to load the program ({o.error or 'invalid'}) — "
                "says nothing about semantics")
        else:
            reasons.append(f"{o.backend}: {o.status} ({o.error or 'no detail'})")

    if len(answered) < 2:
        reasons.append(
            f"only {len(answered)} backend(s) produced an answer; at least 2 are "
            "needed to compare")
        return Comparison(Verdict.INCONCLUSIVE, names, [], _uncomparable(outcomes),
                          reasons)

    # -- compare field by field ---------------------------------------------
    differences: list[Difference] = []
    not_compared: list[str] = []

    for name in COMPARABLE_FIELDS:
        reporting = {o.backend: getattr(o, name)
                     for o in answered
                     if o.can_report(name) and getattr(o, name) is not None}
        if len(reporting) < 2:
            not_compared.append(name)
            continue
        if len(set(_hashable(v) for v in reporting.values())) == 1:
            continue

        if name == "output":
            kind, detail = _classify_output(reporting)
        else:
            kind, detail = "value", ""
        differences.append(Difference(name, kind, dict(reporting), detail))

    verdict = Verdict.DIVERGENCE if differences else Verdict.CONSISTENT

    # A backend that could not answer leaves the agreement of the rest standing,
    # but the reader should know it did not take part.
    if non_ok and verdict is Verdict.CONSISTENT:
        verdict = Verdict.INCONCLUSIVE

    return Comparison(verdict, names, differences, not_compared, reasons)


def _hashable(value: Any) -> Any:
    return value


def _uncomparable(outcomes: Iterable[Outcome]) -> list[str]:
    return [name for name in COMPARABLE_FIELDS
            if sum(1 for o in outcomes if o.can_report(name)) < 2]
