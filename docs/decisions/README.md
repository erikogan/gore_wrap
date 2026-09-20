# Decision Docs

A **decision doc** is the durable, human-facing record of a piece of work: what
was built, and — more importantly — **the design decisions made along the way and
why**. It is written when the work is finished (or nearly so).

It is deliberately different from the other two artifacts under
`docs/superpowers/`:

| Artifact | Audience | Lifespan | Answers |
| -------- | -------- | -------- | ------- |
| `superpowers/specs/` (design spec) | the implementer, before coding | throwaway once built | "what are we going to build?" |
| `superpowers/plans/` (implementation plan) | the implementer, task-by-task | throwaway once built | "what are the exact steps?" |
| `decisions/` (this) | a future engineer touching this area | **durable** | "what exists, and why is it shaped this way?" |

Specs and plans are scaffolding — they capture intent and steps at a moment in
time and go stale the instant code merges. A decision doc is the opposite: it is
written to be read long after the branch is gone, by someone who needs the
*reasoning* (the forks we hit, the options we rejected, the invariants that must
hold) without archaeology through PRs and Slack.

## When to write one

Write a decision doc when finishing any non-trivial feature or change that
involved real design choices — especially where the choice isn't obvious from
the code alone (an architectural fork, a rejected alternative, a load-bearing
invariant, an accepted deviation from a design). Skip it for mechanical or
self-evident changes.

## Format

Keep it concise and skimmable — decisions over prose. Use these sections, in
this order:

### Title

`# Decision Doc: <feature name>` — one line.

### Header

A bullet list of metadata, each entry prefixed with a bolded label. Include
what applies; omit what doesn't.

```markdown
- **Date:** YYYY-MM-DD
- **Status:** Implemented / In review / Rolled out / Rolled back
- **Superseded by:** [`YYYY-MM-DD-slug.md`](YYYY-MM-DD-slug.md) — in part: one
  sentence naming the decisions that no longer hold, and any that still do.
  Add this to an older doc when a later one reverses a decision in it; the
  rest of the older doc is left as written. See "Keeping older docs current".
- **PR:** [org/repo#NNNN](https://github.com/…)
- **Companion:** [org/other-repo#NNNN](https://github.com/…) — one sentence
  on how it relates. Use this when the feature spans more than one repo (its
  own decision doc lives there; this is just the pointer).
- **Jira:** [TICKET-123](https://…) — under epic [EPIC-456](https://…) (Epic name)
- **Figma:** [File / node](https://…)
- **Test Plan:** [Google Doc](https://…)
```

### `## What was built`

A short paragraph explaining the shape of the thing that landed. That's all —
no file inventory.

Earlier versions of this template asked for a `Moving parts:` list of paths
and their roles. Don't write one. It duplicates what the diff already shows,
goes stale the moment a file is renamed or split, and adds nothing a future
reader needs from a document whose whole point is preserved *reasoning*
rather than an index of touched paths. Name a specific file in the body where
the reasoning genuinely attaches to it — an invariant a particular guard
enforces, say — not as a roll-call.

### `## Key decisions`

The heart of the doc. One numbered subsection per decision:

```markdown
### 1. <Short imperative title>

- **Decision:** what we did (one sentence, tight).
- **Why:** the reasoning. If this was a product/UX call rather than an
  engineering one, tag the decider in parentheses at the end, e.g.
  `(Decided by Erik.)` or `(Product call by Erik.)`
- **Alternatives rejected:** briefly, and why each was rejected.
```

Other bullet labels to use where they apply — pick the ones that fit; don't
force every decision to have all of them:

- **Trade-off:** — the cost we accepted by picking this option.
- **Accepted deviation:** — where the implementation intentionally diverges
  from a design or spec, and why we're comfortable with it.
- **Correction during build:** — where reality contradicted an assumption in
  the plan/spec and we adjusted mid-flight.
- **Removed after review:** — code that shipped in an earlier draft of the PR
  but was cut after a review pass; record so the reasoning isn't lost.
- **Why keep ___:** — for decisions that kept an existing thing that a
  reader might expect to see removed.

### `## Incidental fixes`

Bugs fixed in **pre-existing or otherwise unrelated code** that this work
happened to touch along the way — a stale off-by-one in a tuple two lines
above the one you were editing, a cosmetic slip in a neighboring helper, a
real defect in a module you had to open to unblock yourself. One bullet each,
file:line plus what was wrong and the fix, e.g.:

```markdown
- **`store/state_store.py`, `CONTRACT_ALLOWED_FIELDS`** — the continuation
  line was over-indented by one column (pre-existing, unrelated to this
  change); fixed while adding a new field to the same tuple.
```

**Explicitly excludes** bugs found and fixed in the feature's own new code
during its own development or review — that's normal iteration (write, test,
find a problem, fix it before merge), not an incidental finding, and belongs
nowhere in this doc. This section is only for defects in code that predates
or sits outside the feature being built. Skip the section entirely if there's
nothing that qualifies — don't force an empty header.

### `## Invariants (must keep holding)`

The properties that must keep holding — what would break if a future change
violated them. One bullet per invariant, with a bolded lead-in sentence:

```markdown
- **Bucket only when eligible.** The experiment is bucketed *only* when the
  user actually has a next-unviewed citation. A change that buckets before
  confirming eligibility breaks the "both arms would have seen a ping"
  measurement invariant.
```

### `## Accepted deviations / known gaps`

Bullets for places where the implementation intentionally differs from the
design, or where a real risk was identified and consciously decided against
fixing (not tracked as future work — see Scope/deferred for that). Prefer
collecting these here rather than scattering them across Key decisions — but
it's fine to cross-reference a decision when the deviation is a direct
consequence of it (e.g. "see decision 7").

### `## Scope / deferred`

Bullets with bold lead-in labels for what was explicitly left out, what's
intended as follow-up work, and what carried over unchanged from prior work:

```markdown
- **Deferred:** profile page and homepage placement (stretch — the cascade
  already supports both page types).
- **Unchanged:** the `Mentions::CitationPing` model and the A/B experiment
  config (both previously deployed).
```

## Keeping older docs current

A decision doc describes the work as it shipped and is left that way. Two
things can still change an older doc.

**Pointers.** When a new doc reverses a decision in an older one, or removes
the mechanism it describes, add a `Superseded by` line to the older doc's
header, linking to the new doc, in the same commit. Say "in part:" when only
some decisions are affected, and name which no longer hold and which still do.
Use one bullet per superseding doc. A renamed signature or a reworded label is
not a reversal. The older doc's body is left as written.

**Corrections.** If an older doc stated something that was wrong when it was
written, as opposed to something that later stopped being true, fix it in
place, in timeless wording. A correction is not a pointer and has no forward
link.

## Exemplar

See [`2026-07-31-gore-wrap-spinoff.md`](2026-07-31-gore-wrap-spinoff.md), which
uses every section above.

## Naming

`docs/decisions/YYYY-MM-DD-<feature-slug>.md` — the date is the header's
`Date:`, so the filename and the header always agree. Files sit directly under
`decisions/` here.

The convention this template came from groups them under a team or
product-area subdirectory (e.g. `voluntary_churn/`, `autotest-engagement/`),
because a flat directory gets unwieldy fast once more than a couple of teams
are writing these. Worth adopting in this repo at the point it has more than
one area writing docs; it does not yet, and nesting a single file buys
nothing.
