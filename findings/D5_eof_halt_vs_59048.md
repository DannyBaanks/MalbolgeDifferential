# D5 — EOF: halt vs. a=59048

2026-09-11, four backends: engine-ipc (Malbolge-Engine), oracle-python,
rust-cli (malbolge-rs), rustbolge-cli (Rustbolge 0.1.0).

Program: `MALPAD/evidence/m2_state/truth_machine.mal` (254 bytes), which reads
one byte with `/` and branches on it.

## Observation

| stdin | engine | rustbolge | oracle | rust |
|---|---|---|---|---|
| `"0"` | HALT, 136 steps, out `0` | HALT, 136 steps, out `0` | HALT, 136 steps, out `0` | HALT, out `0` |
| `""` (EOF on first `/`) | HALT, 128 steps | HALT, 128 steps | **TIMEOUT (≥1M steps)** | HALT |

With real input the four implementations agree exactly, including steps and
final registers. With EOF, the vm.c lineage (engine, rustbolge) and
malbolge-rs treat `/` with no input as termination; the oracle follows
Appendix C and continues with `a = 59048`, so the program never halts.

The verifier sees this as `INCONCLUSIVE`, not `DIVERGENCE`: the oracle did not
finish, so it did not strictly disagree. A program that reads past EOF and
then halts on a bounded path would show it as a full divergence.

## Interpretation

Same family as D4: the spec (`exec` over pre-loaded memory, Appendix C) gives
an EOF value, but CLI loaders feeding stdin cannot distinguish "EOF value"
from "no more bytes", so most implementations halt instead. Both behaviours
are defensible; they are not the same machine.

## Evidence

- `evidence/truth_machine.20260911T185900053098Z.json` (stdin `0`) — CONSISTENT
- `evidence/truth_machine.20260911T185548Z.json` (stdin empty) — INCONCLUSIVE
