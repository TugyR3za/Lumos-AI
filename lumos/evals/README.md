# Graph V1 eval

Does graph expansion actually help, does the answer come out the other end, and what
does it cost?

```bash
make eval            # retrieval only — no model, no cost, about a second
make eval-answers    # also ask the configured model, three runs a question
```

Both build a scratch database from `evals/notes` in a temp directory. Your notes and
your `lumos.db` are never touched.

## What it measures

**Retrieval** (always). For each question, did *every* note the answer needs reach the
model's context — with BM25 alone, and then with the graph expanding it? Deterministic,
free, and where the honest signal is: if the right notes never arrive, nothing
downstream can save the answer.

**Answers** (`--answers`). The notes arrived, but did the model *use* them, did it join
facts across them, did the extra context *distract* it, and did it say where the answer
came from?

Four things make that second tier believable, and each was learned the hard way.

**Canaries.** Every fact carries a token the model cannot produce unless it really read
the note — a surname, a code, a figure — so the answer tier is decided by string
comparison, not by an LLM judge.

**Folding.** Canaries are matched after normalising, because a model writes
`SALTMARSH‑42` with a non-breaking hyphen and `19 °C` where the note said nineteen
degrees. Three correct answers were being scored as misses, and the next change made
would have "fixed" them and taken the credit.

**Repeats.** Every question is asked `--repeat` times of each arm, and scored as a
*rate*. At temperature a model answers the same prompt differently: two baselines taken
minutes apart, with nothing changed between them, disagreed by two multi-note questions
out of six. Compare two prompts once and you are comparing two coin flips. It is also
what "reliably" means.

**No tools.** `search_notes` is held out. Leave it on the table and the model fetches a
missing note itself, quietly answering the question the expansion was meant to answer —
and the prompt takes the credit for the tool's work.

If the echo fallback replies, the eval refuses to report answer numbers at all: echo
never reads its context, so every canary would be missing and the graph would take the
blame for a machine with no model on it.

**What none of it measures:** whether the answer was any *good*. Tone, clarity and
judgement need a person — read the transcripts in `results/`, not just the totals.

## The corpus

32 notes under `evals/notes`. Five small clusters of linked notes (heating, car, family,
money, garden), three standalone notes, and **14 unlinked filler notes** whose whole job
is to be irrelevant. The filler is not padding: with 18 notes, BM25's top-5 was a third
of the corpus, so junk seeds from unrelated clusters got in and dragged their own links
along — the eval scored the graph at 4 rescues out of 13. On a realistic 32-note vault
the same code scores 13. **A corpus too small to be indifferent will libel its retriever.**

The link structure is deliberate: some facts sit one link *forward* of the seed
(`heating → boiler`), one sits *backward* (`compost → allotment`), and two hubs exist to
be avoided — `wifi` shares only the `#house` tag with `heating`, and `passports` shares
only the unresolved `[[Consulate]]` mention with `school-run`. Neither may ever be
traversed.

## The question format

```json
{
  "id": "heating-service-and-warmth",
  "question": "Who services the radiators, and how warm is the place kept?",
  "needs_notes": ["house/boiler.md", "house/thermostat.md"],
  "answer_contains": [["Kavanagh"], ["19 degrees", "nineteen degrees"]],
  "kind": "linked"
}
```

- `needs_notes` — every note the answer needs. **More than one is a multi-note question**,
  the hard shape: reaching a note is necessary and no longer sufficient, because the model
  still has to carry a fact out of each and join them.
- `answer_contains` — a list of *facts*, each a list of acceptable spellings. **All** the
  facts must appear; **any** spelling will do. Half of a two-note answer is not an answer.
- `kind` — `linked` means BM25 alone cannot supply every note, so the graph must.
  `direct` means it can; those are the control, and expansion must not lose them.

The eval **checks that premise instead of trusting it**. A `linked` question BM25 can
already answer whole is reported as a corpus fault and proves nothing; a `direct` one it
comes up short on is a broken control. `tests/test_eval_corpus.py` fails on either — the
shortest path to an eval that reports a triumph while measuring nothing.

## What to review

1. **`rescued`** — questions the graph put the needed notes in front of the model for, that
   BM25 could not. The whole case for the feature.
2. **`short of a note`** — the context never got there. Missed retrieval; look at the seeds.
3. **`NOISY (off beats on)`** — answerable *before* expansion, not after. The extra notes
   distracted the model. This one must stay at zero.
4. **`MULTI-NOTE`** — the rate at which every fact survives a question spanning two notes.
   This is the reliability number v0.3 is about.
5. **`SILENT`** — leaned on a linked note and never named it. Linked notes are deliberately
   *not* citations (they were never search hits), so a silent one shapes a reply with nothing
   the reader can see.
6. **`LEAKED`** — quoted our own `[NOTE n]` scaffolding at the reader.
7. **The transcripts**, with your own eyes, for everything the numbers cannot say.

## What it found

**Retrieval** (30 questions, 32 notes, deterministic):

| | BM25 alone | BM25 + graph |
|---|---|---|
| every needed note reached the model | 12/30 (40%) | **30/30 (100%)** |
| …of the 6 multi-note questions | 1/6 | **6/6** |

Eighteen rescues, no control lost, 2.3 notes and ~410 characters of context a question
against a hard ceiling of 2,400.

**Answers** (gpt-oss:120b, 180 calls a side, 3 runs a question), across the v0.3 context
and prompt change:

| | before | after |
|---|---|---|
| **multi-note** — every fact, out of several notes at once | 83% | **100%** |
| all facts present, expansion on | 97% | **99%** |
| all facts present, expansion off | 40% | 40% |
| **LEAKED** — quoted `[NOTE n]` at the reader | 43% | **0%** |
| **SILENT** — leaned on a linked note, never named it | 5 of 17 | **0 of 18** |
| **NOISY** — expansion cost an answer it had | 0 | **0** |

The `off` arm is the control and it does not move: no prompt can conjure a note that never
reached the context. Everything gained was gained by *using* the linked notes better.

Three defects this eval turned up rather than assumed. The expansion once broke ties between
linked notes *alphabetically*, dropping a note its own top seed pointed straight at. 43% of
answers quoted the prompt's own `[NOTE n]` headers at a reader who has never seen the prompt.
And the eval itself was scoring typography — three correct answers marked wrong for a
non-breaking hyphen and a degree sign, which the next change made would have "fixed" and
taken the credit for.

An eval whose numbers only ever go up is not measuring anything. The run that costs you
something is the one doing its job.
