# malbolge-differential

**Run the same Malbolge program on independent implementations and see exactly
where they agree.**

```console
$ python -m mdiff.diff corpus/hello_world.mb

Malbolge Differential Test

Program: hello_world.mb

  engine:  PASS   (40 steps, 12 bytes out)
  oracle:  PASS   (40 steps, 12 bytes out)
  rust:    PASS   (12 bytes out)

  output:  identical
  halted:  identical
  steps:   identical
  a:       not comparable (fewer than two backends report it)
  c:       not comparable (fewer than two backends report it)
  d:       not comparable (fewer than two backends report it)

RESULT: CONSISTENT
```

**This repository contains no Malbolge interpreter.** It points at whichever
ones you have built and compares what they do. Each backend runs the program
itself; nothing goes through anything else.

## Why

Malbolge implementations disagree in ways that are invisible until you put them
side by side. Not on hello-world — on what happens at EOF, on the state after a
halt, on **how the program gets into memory in the first place**.

That last one turned out to be the interesting part. See
[`findings/D4_loading_is_not_specified.md`](findings/D4_loading_is_not_specified.md):
the semantics everyone cites, Iizawa (2005) Appendix C, is
`void exec( unsigned short *mem )` — it receives memory **already loaded** and
says nothing about how. So every implementation decided for itself, and they
decided differently: one fills the tail of memory, one zeroed it, one skips
whitespace in the source and one does not. Programs that step past their own
last cell are not running the same machine.

That was found on the first real comparison this harness ran, and it produced a
fix in one of the backends.

## Three verdicts, not two

```
CONSISTENT     the backends that could answer, agreed
DIVERGENCE     they could answer, and disagreed
INCONCLUSIVE   too few could answer to tell
```

The third exists because most of what goes wrong in differential testing is not
a semantic difference. A runtime hit its step limit; another has no limit. One
refused to load the program. A field is unavailable in one implementation.
Reporting any of that as a divergence teaches people to ignore the tool.

Two more things it refuses to do:

**It never fabricates a field.** An interpreter that prints and exits cannot
report a step count. That is recorded as unavailable, not as zero, and fields
fewer than two backends can report are left out of the comparison entirely.

**It separates encoding from semantics.** A runtime writing bytes through a
UTF-8 encoder emits two bytes where one writing raw emits one, for anything
≥ 128. The machines agree; the streams do not. That is reported as
`kind="encoding"`, apart from a genuine difference in what was printed.

## Setup

```sh
cp backends.example.json backends.json     # then edit the paths
python -m mdiff.diff corpus/hello_world.mb
```

Three kinds of backend are supported, matching how each implementation exposes
itself:

| kind | For | Reports |
|---|---|---|
| `engine-ipc` | an interpreter speaking JSONL over stdin/stdout | status, steps, output |
| `oracle-python` | a directory containing `oracle.py` | the full machine state |
| `rust-cli` | a CLI taking a file path | stdout and termination |

Adding a fourth is a function in `mdiff/backends.py` that returns an `Outcome`
and declares what it cannot report.

## Evidence

Every run writes a JSON file with each backend's outcome, the comparison, the
program hash and the conditions — because a divergence you cannot reproduce is
an anecdote. `--no-evidence` turns it off.

Exit code is `1` only for `DIVERGENCE`. `INCONCLUSIVE` exits `0`: it is a normal
result, not an error.

## Tests

```sh
python -m pytest tests/ -v
```

They cover the comparator, which is where the judgement lives: what counts as
agreement when one backend cannot report a field, why a timeout is inconclusive
rather than divergent, and how a UTF-8 artefact is told apart from a real
difference in output.

## Licence

MIT. See [`LICENSE`](LICENSE).

The interpreters this harness drives are separate projects with their own
licences and are not included here.
