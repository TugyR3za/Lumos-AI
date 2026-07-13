# Graph V1 eval

Does graph expansion actually help, and what does it cost?

```bash
make eval            # retrieval only — no model, no cost, about a second
make eval-answers    # also ask the configured model, twice per question
```

Both build a scratch database from `evals/notes` in a temp directory. Your notes and
your `lumos.db` are never touched.

## What it measures

**Retrieval** (always). For each question, did the note holding the answer reach the
model's context at all — with BM25 alone, and then with the graph expanding it? This is
where the honest signal is. If the right note never arrives, nothing downstream can save
the answer, and the number is exact rather than judged.

**Answers** (`--answers`, two model calls a question). The note arrived, but did the model
*use* it, did the extra context *distract* it, and did it *say* where the answer came from?

Each question plants a **canary**: a token the model cannot produce unless it really read
the note — a surname, a code, a figure, never something it could paraphrase or guess. So
even the answer tier is decided by string comparison rather than by a judge. If the echo
fallback is what replies, the eval refuses to report answer numbers at all: echo never
reads its context, so every canary would be missing and the graph would take the blame.

**What neither tier measures:** whether the answer was any *good*. Tone, clarity and
judgement need a person, which is what the per-question transcript dump in `results/` is
for. Read a few; do not just read the totals.

## The corpus

32 notes under `evals/notes`. Five small clusters of linked notes (heating, car, family,
money, garden), three standalone notes, and **14 unlinked filler notes** that exist purely
to be irrelevant. The filler is not padding: with 18 notes, BM25's top-5 was a third of the
corpus, so junk seeds from unrelated clusters got in and dragged their own links along —
the eval scored the graph at 4 rescues out of 13. On a realistic 32-note vault, the same
code scores 12. **A corpus too small to be indifferent will libel your retriever.**

The link structure is deliberate: some facts sit one link *forward* of the seed
(`heating → boiler`), one sits *backward* (`compost → allotment`), and two hubs exist to be
avoided — `wifi` shares only the `#house` tag with `heating`, and `passports` shares only
the unresolved `[[Consulate]]` mention with `school-run`. Neither may ever be traversed.

## The question format

```json
{
  "id": "radiators-cold-who",
  "question": "Who do we call when the radiators go cold?",
  "needs_note": "house/boiler.md",
  "answer_contains": ["Kavanagh"],
  "kind": "linked"
}
```

- `needs_note` — the one note that holds the answer. The retrieval tier asks whether it arrived.
- `answer_contains` — the canary, any one of which counts. The answer tier asks whether it came out.
- `kind` — `linked` means the question's words are in a note that *links to* `needs_note`, not in
  `needs_note` itself, so BM25 alone should miss it. `direct` means BM25 should find it unaided;
  these are the control, and expansion must not lose them.

The eval **checks that premise instead of trusting it**. A `linked` question BM25 can already
answer is reported as a corpus fault and proves nothing; a `direct` one it cannot answer is a
broken control. `tests/test_eval_corpus.py` fails if any question drifts into either state, which
is the easiest way for an eval to start lying: measuring nothing and reporting a triumph.

## What to review

Read these in order.

1. **`rescued`** — questions the graph put a note in front of the model for, that BM25 could not.
   This is the whole case for the feature. If it is near zero, the graph is not earning its context.
2. **`never reached it`** — the note never arrived by any route. Missed context; look at the seeds.
3. **`NOISY (hit → miss)`** — a question that was answerable *before* expansion and is not after.
   The extra notes distracted the model. This is the one number that must stay at zero.
4. **`SILENT`** — the answer leaned on a linked note and never named it. Linked notes are
   deliberately *not* citations (they were never search hits), so a silent one shaped the reply
   with nothing the reader could see. Expect this to be high; decide whether you can live with it.
5. **The cost line** — notes and characters added per question, against the hard ceiling.
6. **The transcripts** in `results/`, with your own eyes, for anything the numbers cannot say.

## What it found (2026-07-12, 32 notes, 24 questions)

| | BM25 alone | BM25 + graph |
|---|---|---|
| note holding the answer reached the model | 11/24 (46%) | **23/24 (96%)** |

Twelve questions rescued, no control lost, and the expansion cost 2.3 notes and 424 characters
a question against a ceiling of 2,400. The graph is doing what slice 6 claimed.

**One real defect, and the eval is how we know.** `who-insures-the-volvo` is the single miss.
Its top seed is `car/estate.md`, which links *directly* to the note that holds the answer —
and the expansion dropped it. Every candidate ties at one connection, so the tiebreak decides,
and the tiebreak is alphabetical (chosen in slice 6 for determinism): `compost` and
`energy-tariff`, reached from junk seeds ranked 3rd and 4th, take the slots ahead of
`motor-policy`, reached from the seed ranked 1st.

**The expansion throws away BM25's ranking of its own seeds.** A note linked from the best hit
should outrank one linked from the worst. The fix is to carry each seed's rank into
`related_notes` and sort by it before falling back to the slug — a change to ranking, not to
traversal, and its own slice.
