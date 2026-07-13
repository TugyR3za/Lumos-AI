"""The eval's retrieval tier, pinned as a regression guard.

This is not a substitute for running the eval — it cannot tell you whether an
answer got better, and it never asks a model. It says the graph still puts the
right notes in front of one, so a refactor that quietly unplugs the expansion
cannot pass as green. It also guards the corpus, which is the easier thing to
break: a question BM25 can already answer proves nothing about the graph, and a
suite full of them would report a triumph while measuring nothing.
"""

import pytest

from evals.harness import (
    DEFAULT_NOTES,
    Retrieval,
    build_pair,
    evaluate_retrieval,
    load_questions,
    normalise,
)


def test_a_fact_counts_however_the_model_types_it():
    # Every one of these is a real answer gpt-oss:120b gave, scored as a miss by a
    # raw substring match. A typographic hyphen and a degree sign were costing the
    # eval three questions, and the next change made would have taken the credit.
    assert normalise("SALTMARSH‑42") == normalise("SALTMARSH-42")
    assert normalise("19 degrees") in normalise("The Hive holds the place at 19 °C.")
    assert normalise("50 minutes") in normalise("Bake for 50 minutes.")
    assert normalise("mill-lane.md") in normalise("Booked through mill‑lane.md.")
    # And it still refuses what is genuinely absent.
    assert normalise("Kavanagh") not in normalise("Call the plumber.")


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> list[Retrieval]:
    database = tmp_path_factory.mktemp("eval") / "eval.db"
    off, on = build_pair(DEFAULT_NOTES, database)
    return evaluate_retrieval(off, on, load_questions())


def test_every_question_tests_what_it_claims(results: list[Retrieval]):
    # A `linked` question BM25 can already answer whole is not evidence for the
    # graph, and a `direct` one it comes up short on is a broken control. Either
    # way the eval would be reporting on a corpus, not on the code.
    unfair = {r.question.id: r.question.kind for r in results if not r.fair}

    assert unfair == {}


def test_the_graph_reaches_what_bm25_cannot(results: list[Retrieval]):
    link_only = [r for r in results if r.question.kind == "linked"]

    # Every one of them: each question whose notes BM25 cannot all reach, the graph
    # can. This asserted "at least 11" while the expansion broke its ties on the
    # alphabet and dropped a note its own top seed pointed at — the suite stayed
    # green straight through the defect. A threshold hides what it is set above.
    assert [r.question.id for r in link_only if not r.rescued] == []


def test_multi_note_questions_get_every_note_they_need(results: list[Retrieval]):
    multi = [r for r in results if r.question.multi]

    # The whole point of v0.3: reaching one of the two notes is not an answer.
    assert len(multi) >= 6
    assert [r.question.id for r in multi if not r.complete] == []


def test_the_notes_search_already_found_are_never_lost(results: list[Retrieval]):
    direct = [r for r in results if r.question.kind == "direct"]

    # Expansion appends; it may not displace. Every control still lands whole.
    assert all(r.complete_from_seeds for r in direct)


def test_the_context_ceiling_holds(results: list[Retrieval]):
    assert max(len(r.linked) for r in results) <= 3
    assert max(r.linked_chars for r in results) <= 3 * 800


def test_hubs_are_never_traversed(results: list[Retrieval]):
    # wifi shares only the #house tag with heating; passports shares only the
    # unresolved [[Consulate]] mention with school-run. Both sit two hops away
    # through a node of unbounded degree, and neither may ever be pulled in.
    for result in results:
        if "house/heating.md" in result.seeds:
            assert "house/wifi.md" not in result.linked
        if "family/school-run.md" in result.seeds:
            assert "travel/passports.md" not in result.linked


def test_the_corpus_and_the_questions_agree(results: list[Retrieval]):
    for result in results:
        question = result.question
        assert question.needs_notes, question.id
        for note in question.needs_notes:
            assert (DEFAULT_NOTES / note).exists(), note
        assert question.kind in {"linked", "direct"}
        assert question.answer_contains and all(fact for fact in question.answer_contains)
