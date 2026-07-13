"""The eval's retrieval tier, pinned as a regression guard.

This is not a substitute for running the eval — it cannot tell you whether an
answer got better, and it never asks a model. It says the graph still puts the
right note in front of one, so a refactor that quietly unplugs the expansion
cannot pass as green. It also guards the corpus, which is the easier thing to
break: a question BM25 can already answer proves nothing about the graph, and a
suite full of them would report a triumph while measuring nothing.
"""


import pytest

from evals.harness import DEFAULT_NOTES, Retrieval, build_pair, evaluate_retrieval, load_questions


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> list[Retrieval]:
    database = tmp_path_factory.mktemp("eval") / "eval.db"
    off, on = build_pair(DEFAULT_NOTES, database)
    return evaluate_retrieval(off, on, load_questions())


def test_every_question_tests_what_it_claims(results: list[Retrieval]):
    # A `linked` question BM25 answers on its own is not evidence for the graph,
    # and a `direct` one it misses is a broken control. Either way the eval would
    # be reporting on a corpus, not on the code.
    unfair = {r.question.id: r.question.kind for r in results if not r.fair}

    assert unfair == {}


def test_the_graph_reaches_what_bm25_cannot(results: list[Retrieval]):
    link_only = [r for r in results if r.question.kind == "linked"]
    rescued = [r for r in link_only if r.rescued]

    # 12 of 13 today. The hold-out is who-insures-the-volvo, which loses its slot
    # under the cap to notes linked from weaker seeds — see evals/README.md.
    assert len(rescued) >= 11, [r.question.id for r in link_only if not r.rescued]


def test_the_notes_search_already_found_are_never_lost(results: list[Retrieval]):
    direct = [r for r in results if r.question.kind == "direct"]

    # Expansion appends; it may not displace. Every control still lands.
    assert all(r.seed_hit for r in direct)


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
        assert (DEFAULT_NOTES / result.question.needs_note).exists(), result.question.needs_note
        assert result.question.kind in {"linked", "direct"}
        assert result.question.answer_contains, result.question.id
