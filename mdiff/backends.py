# SPDX-License-Identifier: MIT
"""Adapters: one per implementation, each running Malbolge on its own.

The point of the project is that no backend goes through another. Python does
not interpret anything here; it starts three independent runtimes and collects
what each says.

Every adapter is responsible for declaring what it *cannot* report, so the
comparator can leave those fields out instead of reading a missing value as a
disagreement.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .contract import Outcome

DEFAULT_MAX_STEPS = 1_000_000
DEFAULT_TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class Backend:
    """Where an implementation lives. Nothing about how it works."""
    name: str
    kind: str          # "engine-ipc" | "oracle-python" | "rust-cli"
    path: str          # binary, or directory containing oracle.py


# --------------------------------------------------------------------------
# Malbolge-Engine — speaks JSONL over stdin/stdout
# --------------------------------------------------------------------------

def run_engine_ipc(backend: Backend, program: str, stdin: str = "",
                   max_steps: int = DEFAULT_MAX_STEPS,
                   timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Drive the IPC server through one request and shut it down.

    One process per program rather than a long-lived server: a run that never
    terminates would otherwise poison every request after it, and correctness
    matters more here than the cost of a spawn.
    """
    request = {"id": 1, "op": "run", "program": program, "steps": max_steps}
    if stdin:
        request["input"] = stdin
    payload = json.dumps(request) + "\n" + json.dumps({"id": 2, "op": "quit"}) + "\n"

    started = time.perf_counter()
    try:
        proc = subprocess.run([backend.path], input=payload, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Outcome(backend=backend.name, output=b"", halted=False,
                       status="TIMEOUT", error=f"no reply within {timeout}s",
                       unavailable=("a", "c", "d"),
                       provenance={"command": [backend.path], "kind": backend.kind})
    elapsed = time.perf_counter() - started

    reply = None
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == 1:
            reply = message
            break

    provenance = {"command": [backend.path], "kind": backend.kind,
                  "wall_s": round(elapsed, 4), "raw_reply": reply}

    if reply is None:
        return Outcome(backend=backend.name, output=b"", halted=False,
                       status="ERROR", error="no reply for the run request",
                       unavailable=("a", "c", "d"), provenance=provenance)

    status = reply.get("status", "ERROR")
    return Outcome(
        backend=backend.name,
        output=(reply.get("output") or "").encode("utf-8"),
        halted=status == "OK",
        status=status,
        steps=reply.get("steps"),
        error=reply.get("error"),
        # The IPC protocol reports status, steps and output; not the registers.
        unavailable=("a", "c", "d"),
        provenance=provenance,
    )


# --------------------------------------------------------------------------
# The oracle — a Python module, imported rather than spawned
# --------------------------------------------------------------------------

def run_oracle(backend: Backend, program: str, stdin: str = "",
               max_steps: int = DEFAULT_MAX_STEPS,
               timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Import the oracle from its own directory and run it in-process.

    It is a control, not a service: it has a step limit of its own and cannot
    hang, so there is nothing to isolate it from.
    """
    import sys

    directory = str(Path(backend.path).resolve())
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import oracle as oracle_module  # noqa: PLC0415

    machine = oracle_module.Oracle()
    machine.load_ascii(program)
    # Always declare the input, including when it is empty. "No input
    # configured" and "the input is empty" are different states in this
    # backend, and only the second is what a comparison against a CLI running
    # with closed stdin actually means.
    machine.provide_input(stdin)

    started = time.perf_counter()
    result = machine.run(max_steps=max_steps)
    elapsed = time.perf_counter() - started

    status = "OK" if result.halted else "TIMEOUT"
    return Outcome(
        backend=backend.name,
        output=result.output.encode("latin-1", errors="replace"),
        halted=result.halted,
        status=status,
        steps=result.steps,
        a=result.a, c=result.c, d=result.d,
        provenance={"kind": backend.kind, "module": directory,
                    "wall_s": round(elapsed, 4),
                    "halt_reason": result.halt_reason},
    )


# --------------------------------------------------------------------------
# malbolge-rs — a CLI that only prints
# --------------------------------------------------------------------------

#: The interpreter reports load failures on stdout and exits 0, so the only way
#: to tell "the program printed this" from "the interpreter refused" is the text.
RUST_LOAD_FAILURE = b"Could not initialize memory."


def run_rust_cli(backend: Backend, program: str, stdin: str = "",
                 max_steps: int = DEFAULT_MAX_STEPS,
                 timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Run the Rust CLI on a temporary file and collect what it prints.

    Three of its behaviours shape this adapter, all established by measurement:

    - it has no step limit, so a program that loops must be killed, and output
      has to be collected while it runs rather than after;
    - it reports load failures on stdout with exit code 0;
    - it writes output through Rust's `print!`, which emits UTF-8, so bytes
      >= 128 come out as two bytes. That is left as-is here and labelled by the
      comparator; rewriting it in the adapter would hide a real difference
      between implementations.
    """
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".mb", delete=False,
                                     encoding="latin-1") as handle:
        handle.write(program)
        program_path = handle.name

    proc = subprocess.Popen([backend.path, program_path],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    collected = bytearray()

    def drain() -> None:
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            collected.extend(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    started = time.perf_counter()
    proc.stdin.write(stdin.encode("latin-1"))
    proc.stdin.close()

    try:
        proc.wait(timeout=timeout)
        terminated = True
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        terminated = False
    elapsed = time.perf_counter() - started
    reader.join(timeout=1.0)
    Path(program_path).unlink(missing_ok=True)

    output = bytes(collected)
    provenance = {"command": [backend.path, "<program>"], "kind": backend.kind,
                  "wall_s": round(elapsed, 4), "exit_code": proc.returncode,
                  "note": "step limit not supported by this backend"}

    if output.startswith(RUST_LOAD_FAILURE):
        return Outcome(backend=backend.name, output=b"", halted=False,
                       status="INVALID",
                       error=output.decode("utf-8", "replace").strip(),
                       unavailable=("steps", "a", "c", "d"), provenance=provenance)

    if not terminated:
        return Outcome(backend=backend.name, output=output, halted=False,
                       status="TIMEOUT",
                       error=f"still running after {timeout}s (no step limit)",
                       unavailable=("steps", "a", "c", "d"), provenance=provenance)

    return Outcome(backend=backend.name, output=output, halted=True, status="OK",
                   unavailable=("steps", "a", "c", "d"), provenance=provenance)


# --------------------------------------------------------------------------
# Rustbolge — a CLI that reports the full machine state as JSON on stderr
# --------------------------------------------------------------------------

def _run_reporter_cli(command: list[str], backend: Backend, program: str,
                      stdin: str, max_steps: int, timeout: float) -> Outcome:
    """Shared driver for the "reporter" CLIs (rustbolge, swiftbolge, javolge).

    They all speak the same protocol: a program file + step limit as
    arguments, raw bytes on stdout (with one framing newline), and a JSON
    report on stderr (`--json`) with steps/status/final a-c-d. So one parser
    serves all three; only the invoked command differs.
    """
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".mal", delete=False,
                                     encoding="latin-1", newline="") as handle:
        handle.write(program)
        program_path = handle.name

    command = list(command) + [program_path, str(max_steps), "--json"]
    started = time.perf_counter()
    proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        raw_out, raw_err = proc.communicate(stdin.encode("latin-1"),
                                            timeout=timeout)
        wall_timeout = False
    except subprocess.TimeoutExpired:
        proc.kill()
        raw_out, raw_err = proc.communicate()
        wall_timeout = True
    elapsed = time.perf_counter() - started
    Path(program_path).unlink(missing_ok=True)

    stderr_text = raw_err.decode("utf-8", "replace")
    provenance = {"command": command + ["<program>", str(max_steps), "--json"],
                  "kind": backend.kind, "wall_s": round(elapsed, 4),
                  "exit_code": proc.returncode,
                  "note": "stdout newline framing stripped (1 trailing LF)"}

    if proc.returncode == 2 and "invalid character" in stderr_text:
        return Outcome(backend=backend.name, output=b"", halted=False,
                       status="INVALID",
                       error=stderr_text.strip().splitlines()[-1],
                       unavailable=("steps", "a", "c", "d"),
                       provenance=provenance)

    report = None
    for line in stderr_text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                report = json.loads(line)
            except json.JSONDecodeError:
                pass

    # Strip exactly one trailing newline framing (see docstring).
    output = bytes(raw_out)
    if output.endswith(b"\r\n"):
        output = output[:-2]
    elif output.endswith(b"\n"):
        output = output[:-1]

    if wall_timeout:
        return Outcome(backend=backend.name, output=output, halted=False,
                       status="TIMEOUT",
                       error=f"wall-clock timeout after {timeout}s",
                       unavailable=("steps", "a", "c", "d"),
                       provenance=provenance)

    if report is None:
        return Outcome(backend=backend.name, output=output, halted=False,
                       status="ERROR",
                       error="no JSON report on stderr: " + stderr_text.strip(),
                       unavailable=("steps", "a", "c", "d"),
                       provenance=provenance)

    provenance["halt_reason"] = report.get("halt_reason")
    status = "OK" if report.get("status") == "HALTED" else "TIMEOUT"
    final = report.get("final") or {}
    return Outcome(backend=backend.name, output=output,
                   halted=status == "OK", status=status,
                   steps=report.get("steps"),
                   a=final.get("a"), c=final.get("c"), d=final.get("d"),
                   provenance=provenance)


def run_rustbolge_cli(backend: Backend, program: str, stdin: str = "",
                      max_steps: int = DEFAULT_MAX_STEPS,
                      timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Rustbolge / Swiftbolge: single executable, report-on-stderr CLI."""
    return _run_reporter_cli([backend.path], backend, program, stdin,
                             max_steps, timeout)


def run_javolge_cli(backend: Backend, program: str, stdin: str = "",
                    max_steps: int = DEFAULT_MAX_STEPS,
                    timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Javolge: a JVM class reached via classpath (no self-contained binary)."""
    return _run_reporter_cli(
        ["java", "-cp", backend.path, "com.dannybaanks.javolge.Main"],
        backend, program, stdin, max_steps, timeout)


def run_cobolge_cli(backend: Backend, program: str, stdin: str = "",
                    max_steps: int = DEFAULT_MAX_STEPS,
                    timeout: float = DEFAULT_TIMEOUT_S) -> Outcome:
    """Cobolge: GnuCOBOL 3.2 Malbolge engine, reporter CLI protocol."""
    return _run_reporter_cli([backend.path], backend, program, stdin,
                             max_steps, timeout)


RUNNERS = {
    "engine-ipc": run_engine_ipc,
    "oracle-python": run_oracle,
    "rust-cli": run_rust_cli,
    "rustbolge-cli": run_rustbolge_cli,
    "javolge-cli": run_javolge_cli,
    "cobolge-cli": run_cobolge_cli,
}


def run(backend: Backend, program: str, **kw) -> Outcome:
    runner = RUNNERS.get(backend.kind)
    if runner is None:
        raise ValueError(f"unknown backend kind: {backend.kind}")
    outcome = runner(backend, program, **kw)
    outcome.provenance.setdefault(
        "program_sha256", hashlib.sha256(program.encode("latin-1")).hexdigest())
    return outcome
