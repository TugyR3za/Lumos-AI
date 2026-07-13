"""Which BM25 hits are real (v0.4).

Two rules, and the second only works because the score was fixed: bm25() is negative
and more negative the better, so squashing it through 1/(1+|rank|) had inverted it —
the note that answered the question scored 0.12 and a filler note that matched
nothing but "the" scored 1.0. Ordering came from the SQL so nothing looked broken,
but no floor can be built on a number that means the opposite of itself.
"""

from pathlib import Path

import pytest

from lumos.memory.database import Database
from lumos.retrieval.relevance import above_floor, search_terms
from lumos.retrieval.service import RetrievalService

# The eval corpus in miniature: one note that answers the question, and a handful of
# short, irrelevant ones that BM25 will happily rank because they say "do" and "the".
FILLER = {
    "filler/library.md": "Books back by the Saturday. Ten pence a day, and they do not forget.",
    "filler/photos.md": "The box in the loft, unsorted since we moved. Someone said to scan them.",
    "filler/telly.md": "The remote eats batteries. The good one hides behind the cushion.",
    "filler/shopping.md": "Milk, bread, the good coffee. Nobody eats the olives but we buy them.",
}
HEATING = "The upstairs radiators go cold on a winter evening and the whole place warms slowly."
COLD = "Who do we call when the radiators go cold?"


def build(root: Path, notes: dict[str, str], *, score_floor: float = 0.35) -> RetrievalService:
    root.mkdir(parents=True, exist_ok=True)
    database = Database(root / "lumos.db")
    database.initialize()
    for index, (path, text) in enumerate(notes.items()):
        database.replace_document(
            path=path, title=path, sha256=path, mtime_ns=index, chunks=[text]
        )
    return RetrievalService(database, score_floor=score_floor)


def paths(rows) -> list[str]:
    return [str(row["path"]) for row in rows]


def test_a_word_that_means_nothing_is_not_searched_for():
    # The question is about radiators. It is not about "do", and BM25 cannot tell.
    assert search_terms(COLD) == ["call", "radiators", "go", "cold"]


def test_a_word_someone_might_be_asking_about_is_never_a_stopword():
    # The trap a stopword list sets for itself. Strip "will" out as a modal verb and
    # a family can never find their will again, so it is not on the list at all.
    assert search_terms("Where is the will?") == ["will"]
    assert search_terms("Can we afford it?") == ["Can", "afford"]


def test_a_question_made_only_of_function_words_means_them_literally():
    assert search_terms("What about it?") == ["What", "about", "it"]


def test_a_query_in_another_language_is_left_alone():
    # The list is English. Nothing in a Farsi question is on it, so nothing is taken.
    assert search_terms("چای ارل گری") == ["چای", "ارل", "گری"]


def test_the_score_rises_with_relevance(tmp_path: Path):
    retrieval = build(tmp_path, {"house/heating.md": HEATING, **FILLER}, score_floor=0.0)

    rows = retrieval.search_notes(COLD, limit=5)

    # It used to be exactly the other way round, and silently.
    assert paths(rows)[0] == "house/heating.md"
    assert float(rows[0]["score"]) == max(float(row["score"]) for row in rows)


def test_filler_notes_do_not_become_sources(tmp_path: Path):
    # The state of things this slice was opened for: four of the five source cards on
    # the eval corpus were notes about library fines and where the remote lives.
    retrieval = build(tmp_path, {"house/heating.md": HEATING, **FILLER})

    rows = retrieval.search_notes(COLD, limit=5)

    assert paths(rows) == ["house/heating.md"]


def test_the_floor_drops_a_hit_that_barely_matched(tmp_path: Path):
    # Both notes hold a word the question actually asked for, so the search terms
    # cannot separate them: only the score can. The shopping list is about the good
    # coffee; the telly note merely says "good".
    retrieval = build(tmp_path, {"house/heating.md": HEATING, **FILLER})

    kept = paths(retrieval.search_notes("Where is the good coffee?", limit=5))
    unfiltered = paths(build(tmp_path / "raw", FILLER, score_floor=0.0)
                       .search_notes("Where is the good coffee?", limit=5))

    assert "filler/telly.md" in unfiltered  # BM25 ranked it: it says "good"
    assert kept == ["filler/shopping.md"]  # the floor knows it was not about coffee


def test_the_floor_only_ever_removes(tmp_path: Path):
    notes = {"house/heating.md": HEATING, **FILLER}
    unfiltered = build(tmp_path / "a", notes, score_floor=0.0)
    filtered = build(tmp_path / "b", notes, score_floor=0.35)

    all_hits = paths(unfiltered.search_notes(COLD, limit=5))
    kept = paths(filtered.search_notes(COLD, limit=5))

    # No note appears that the search had not already ranked, so the seeds the graph
    # expands from can only be a subset of the seeds it had — and a question that
    # used to reach its answer still reaches it.
    assert set(kept) <= set(all_hits)
    assert kept == [path for path in all_hits if path in kept]  # and in the same order


def test_a_search_that_finds_nothing_stays_empty(tmp_path: Path):
    retrieval = build(tmp_path, {"house/heating.md": HEATING})

    assert retrieval.search_notes("xylophone", limit=5) == []


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ([], []),
        ([0.0, 0.0], []),  # matched nothing informative: never relevant, floor or no floor
        ([10.0, 6.0, 4.0, 0.0], [10.0, 6.0]),
        ([10.0, 4.0, 6.0], [10.0, 6.0]),  # whatever the order, the best sets the bar
    ],
)
def test_the_floor_is_a_fraction_of_the_best_hit(scores, expected):
    # A fraction and not a number, because a BM25 score means nothing across queries.
    rows = [{"score": score} for score in scores]

    assert [row["score"] for row in above_floor(rows, 0.5)] == expected


def test_a_zero_floor_hands_back_everything_bm25_ranked():
    rows = [{"score": 10.0}, {"score": 0.0}]

    assert above_floor(rows, 0.0) == rows  # the escape hatch, junk and all
