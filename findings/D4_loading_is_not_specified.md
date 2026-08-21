# D4 — the three backends do not load the same program

**Found:** 2026-08-20, on the first real comparison this harness ran.
**Status:** captured, not resolved. Nothing has been "fixed" to make the
implementations agree.

---

## What was observed

Program: `cat-wikipedia.mb` (70 bytes after stripping the trailing CRLF),
stdin empty, step limit 200 000, wall timeout 8 s.

| Backend | Status | Steps | Output |
|---|---|---|---|
| Malbolge-Engine (C) | `OK`, halted | **34** | none |
| oracle (Python) | `TIMEOUT` | 200 000 | none |
| malbolge-rs (Rust) | `TIMEOUT` | not exposed | **6.8 MB** of `c2 a8` |

Three implementations, three different behaviours, same input.

## Why: loading is not part of the specification

The Malbolge semantics everyone cites — Iizawa (2005) Appendix C — is exactly
this signature:

```c
void exec( unsigned short *mem )
```

**It receives memory already loaded.** The paper says nothing about how the
program gets into `mem`: not the fill, not whitespace, not validation. Every
implementation had to decide for itself, and they decided differently.

| Backend | Fills memory past the program | Skips whitespace | Validates opcodes at load |
|---|---|---|---|
| reference `malbolge.c` | `mem[i] = op(mem[i-1], mem[i-2])` | — | — |
| malbolge-rs | inherited from the reference | **yes** (`is_whitespace → continue`) | **yes** (must decode to `ji*p</vo`) |
| oracle | *was* zero-filled; corrected on 2026-08-20 to the reference rule | no | no |
| Malbolge-Engine | lazy block fill (`ensure_filled`) | not yet checked | not yet checked |

Three consequences, each enough on its own to make two runtimes execute
different machines from the same file:

1. **The fill.** A program occupying 70 of 59 049 cells runs into the tail the
   moment it steps past its own code. Zeroed tail and filled tail are different
   programs.
2. **Whitespace.** Skipping it shifts every subsequent cell. A single space
   inside the source and two implementations are no longer running the same
   thing.
3. **Validation at load.** Rejecting a source whose characters do not decode to
   instructions turns a program that another runtime executes happily into a
   load error.

## What this is not

**It is not a divergence in Malbolge semantics.** All three may well implement
`exec` identically; they were never given the same `mem` to execute.

That distinction is the reason this harness reports `INCONCLUSIVE` as a verdict
in its own right. A comparison of execution semantics is meaningless until the
loaded state is known to match — and until then, "they disagree" is not a
finding, it is a mismeasurement.

## What was fixed, and what was not

**Fixed:** the oracle zero-filled memory past the program while its comment
attributed that choice to Appendix C. The paper takes no such position. It now
implements the reference fill, with tests pinning it
(`MemoryFillTests`, `malbolge-oracle` commit of 2026-08-20).

That was a real bug and it changed the result: before the fix the oracle halted
at 34 steps like the Engine; after it, it runs on like malbolge-rs. The
agreement it previously showed was a coincidence of two different mistakes.

**Not fixed, deliberately:** nothing else. Whitespace handling and load-time
validation differ between implementations and stay as they are until it is
decided which behaviour is the reference one — which is a question about the
language, not about any of these programs.

## Open questions

1. ~~Does `cat-wikipedia.mb` contain internal whitespace?~~ **Answered: yes,
   eight characters** — CR/LF pairs at offsets 36, 41, 48 and beyond). So
   malbolge-rs loads **62** cells where the oracle loads **70**, and everything
   from offset 36 onwards sits at a different address in the two machines.
   The two runtimes are not executing the same program at all, which makes the
   comparison of their behaviour meaningless rather than informative.
2. Does Malbolge-Engine fill its tail equivalently? It uses a lazy block scheme
   (`ensure_filled`) whose boundary behaviour has not been checked against the
   reference rule.
3. Why does the oracle print nothing where malbolge-rs prints continuously,
   when both now run past the program? Two runtimes that both fail to terminate
   are not thereby in agreement.

## Reproducing

```sh
python -m mdiff.diff cat-wikipedia.mb --stdin "" --max-steps 200000 --timeout 8
```

Backends, versions and commands are recorded in the evidence written by that
run.
