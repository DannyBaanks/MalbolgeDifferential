# Corpus

Programs used for comparison. Small on purpose: the point is to find where
implementations disagree, and a handful of well-understood programs does
that better than a million generated ones nobody can reason about.

| Program | Source | What it exercises |
|---|---|---|
| `hello_world.mb` | canonical, widely published (Wikipedia, esolangs.org) | output, termination; halts inside its own code |

Programs that read input are deliberately absent so far. They do not
terminate under implementations without a step limit, so every comparison
involving them is INCONCLUSIVE until that is handled — see
`findings/D4_loading_is_not_specified.md`.
