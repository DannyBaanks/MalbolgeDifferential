# SPDX-License-Identifier: MIT
"""Render a comparison so a divergence can be investigated, not just announced.

A verdict on its own is close to useless: `DIVERGENCE` tells you to go and look
at three JSON files. So the report carries what each backend said, what could
not be compared and why, and — when they disagree — the actual values side by
side.

The `INCONCLUSIVE` case gets the most room, because it is the one people
misread. It does not mean "something is broken". It means the backends did not
answer the same question, and the report has to say which one dropped out.
"""
from __future__ import annotations

from typing import Sequence

from .compare import Comparison, Verdict
from .contract import Outcome

STATUS_MARK = {"OK": "PASS", "TIMEOUT": "TIMEOUT", "INVALID": "INVALID", "ERROR": "ERROR"}


def _preview(raw: bytes, limit: int = 40) -> str:
    """Show output as text when it is text, and as hex when it is not."""
    if not raw:
        return "(empty)"
    head = raw[:limit]
    if all(32 <= b < 127 or b in (9, 10, 13) for b in head):
        text = head.decode("ascii").replace("\n", "\\n").replace("\r", "\\r")
        return f'"{text}"' + ("…" if len(raw) > limit else "")
    return head.hex(" ") + ("…" if len(raw) > limit else "")


def render(program: str, outcomes: Sequence[Outcome], comparison: Comparison) -> str:
    width = max((len(o.backend) for o in outcomes), default=8) + 2
    lines = [
        "Malbolge Differential Test",
        "",
        f"Program: {program}",
        "",
    ]

    for o in outcomes:
        mark = STATUS_MARK.get(o.status, o.status)
        detail = []
        if o.steps is not None:
            detail.append(f"{o.steps} steps")
        if o.output:
            detail.append(f"{len(o.output)} bytes out")
        if o.error:
            detail.append(o.error[:60])
        suffix = f"   ({', '.join(detail)})" if detail else ""
        lines.append(f"  {o.backend + ':':<{width}} {mark}{suffix}")

    lines.append("")

    # What was actually compared, field by field.
    compared = [f for f in ("output", "halted", "steps")
                if f not in comparison.not_compared]
    for name in compared:
        differing = next((d for d in comparison.differences if d.field == name), None)
        if differing is None:
            lines.append(f"  {name + ':':<{width}} identical")
        else:
            lines.append(f"  {name + ':':<{width}} DIFFERS ({differing.kind})")

    for name in comparison.not_compared:
        lines.append(f"  {name + ':':<{width}} not comparable "
                     f"(fewer than two backends report it)")

    lines.append("")
    lines.append(f"RESULT: {comparison.verdict.value}")

    if comparison.verdict is Verdict.DIVERGENCE:
        lines.append("")
        for d in comparison.differences:
            lines.append(f"  {d.field} — {d.kind}")
            for backend, value in d.values.items():
                shown = _preview(value) if isinstance(value, bytes) else value
                lines.append(f"      {backend + ':':<{width}} {shown}")
            if d.detail:
                lines.append(f"      note: {d.detail}")
            lines.append("")

    if comparison.reasons:
        lines.append("")
        lines.append("Why this is not a clean comparison:")
        for reason in comparison.reasons:
            lines.append(f"  - {reason}")

    if comparison.verdict is Verdict.INCONCLUSIVE:
        lines.append("")
        lines.append("  INCONCLUSIVE is not a failure. It means the backends did not")
        lines.append("  answer the same question, so their outputs cannot be compared.")

    return "\n".join(lines)
