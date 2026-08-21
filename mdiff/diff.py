# SPDX-License-Identifier: MIT
"""Run one program on every configured backend and compare the results.

    python -m mdiff.diff corpus/hello_world.mb

Backends are declared in a JSON file rather than hardcoded, because this repo
contains no interpreters: it points at whatever you have built. See
`backends.example.json`.

Every run writes its evidence to disk — outcomes, comparison, and enough
provenance to repeat it — because a divergence you cannot reproduce is an
anecdote.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .backends import Backend, run as run_backend
from .compare import Verdict, compare
from .contract import Outcome
from .report import render

DEFAULT_CONFIG = "backends.json"


def load_backends(path: Path) -> list[Backend]:
    if not path.exists():
        raise SystemExit(
            f"no backend configuration at {path}\n"
            f"copy backends.example.json to {path.name} and set the paths for "
            "the interpreters you have built")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Backend(name=b["name"], kind=b["kind"], path=b["path"])
            for b in data["backends"] if b.get("enabled", True)]


def write_evidence(directory: Path, program: Path, program_text: str,
                   outcomes: list[Outcome], comparison, stdin: str,
                   max_steps: int, timeout: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{program.stem}.{stamp}.json"
    target.write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "program": {
            "path": str(program),
            "bytes": len(program_text),
            "sha256": hashlib.sha256(program_text.encode("latin-1")).hexdigest(),
        },
        "conditions": {"stdin": stdin, "max_steps": max_steps, "timeout_s": timeout},
        "outcomes": [o.to_dict() for o in outcomes],
        "comparison": comparison.to_dict(),
    }, indent=2), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mdiff", description="Run one Malbolge program on several independent "
                                  "implementations and compare what they do.")
    parser.add_argument("program", help="path to a Malbolge program")
    parser.add_argument("--backends", default=DEFAULT_CONFIG,
                        help=f"backend configuration (default: {DEFAULT_CONFIG})")
    parser.add_argument("--stdin", default="", help="input to feed the program")
    parser.add_argument("--max-steps", type=int, default=1_000_000,
                        help="step limit for backends that support one")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="wall-clock limit per backend, in seconds")
    parser.add_argument("--evidence", default="evidence",
                        help="directory for the evidence file")
    parser.add_argument("--no-evidence", action="store_true",
                        help="do not write an evidence file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    program_path = Path(args.program)
    if not program_path.is_file():
        raise SystemExit(f"no such program: {program_path}")

    # latin-1 keeps every byte addressable; Malbolge source is bytes, not text.
    program_text = program_path.read_bytes().decode("latin-1").strip()

    backends = load_backends(Path(args.backends))
    if len(backends) < 2:
        raise SystemExit("at least two backends are needed to compare anything")

    outcomes = [
        run_backend(b, program_text, stdin=args.stdin,
                    max_steps=args.max_steps, timeout=args.timeout)
        for b in backends
    ]
    comparison = compare(outcomes)

    evidence_path = None
    if not args.no_evidence:
        evidence_path = write_evidence(
            Path(args.evidence), program_path, program_text, outcomes, comparison,
            args.stdin, args.max_steps, args.timeout)

    if args.json:
        print(json.dumps({
            "program": str(program_path),
            "outcomes": [o.to_dict() for o in outcomes],
            "comparison": comparison.to_dict(),
            "evidence": str(evidence_path) if evidence_path else None,
        }, indent=2))
    else:
        print(render(program_path.name, outcomes, comparison))
        if evidence_path:
            print(f"\nEvidence: {evidence_path}")

    # DIVERGENCE is the only exit code that means "look at this".
    # INCONCLUSIVE is a normal outcome, not an error.
    return 1 if comparison.verdict is Verdict.DIVERGENCE else 0


if __name__ == "__main__":
    sys.exit(main())
