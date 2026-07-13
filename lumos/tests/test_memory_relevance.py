"""Which memories are worth recalling (v0.5).

A small regression harness over a family's memories. It needs no model: memory
recall is BM25 and nothing else, so the whole thing is deterministic and runs in a
second.

The stakes are not the same as they are for notes. A junk note is an ugly card;
nobody is hurt by it. A junk memory is a private fact about this family — an
allergy, a mortgage, where the spare key is — posted to whichever provider answers
a question that had nothing to do with it. And a *missed* memory is worse still: it
is the thing the user turned round and asked Lumos to remember, and Lumos forgot.
So recall is pinned exactly, and precision is pushed only as far as recall allows.
"""

from pathlib import Path

import pytest

from lumos.memory.database import Database

# Twenty of them, the way a family actually accumulates them.
MEMORIES = [
    ("Family pizza night is every Friday", None),
    ("The car insurance renews on 3 March", "insurance"),
    ("Mum's birthday is on 12 November", None),
    ("The bins go out on Thursday night", None),
    ("Reza is allergic to penicillin", "allergy"),
    ("The wifi password is SALTMARSH-42", None),
    ("The boiler is serviced by Kavanagh every 14 months", None),
    ("Sam's swimming lesson is at seven on Saturday", None),
    ("We use the dentist on Fen Road", None),
    ("The spare key is with the neighbour at number 14", None),
    ("Nan does not eat shellfish", None),
    ("The mortgage is with Nationwide", None),
    ("Bedtime for the children is half past seven", None),
    ("The passports were renewed on 2 February", None),
    ("We are vegetarian on weekdays", None),
    ("Dad works from home on Wednesdays", None),
    ("The cat is called Biscuit", None),
    ("Our anniversary is on 8 June", None),
    ("The allotment is plot 12 by the railway", None),
    ("The lawnmower is a Hayter", None),
]

# Each question, and the memory it is actually asking for.
ASKED = [
    ("When is pizza night?", "Family pizza night is every Friday"),
    ("Who services the boiler?", "The boiler is serviced by Kavanagh every 14 months"),
    ("What is Reza allergic to?", "Reza is allergic to penicillin"),
    ("When do the bins go out?", "The bins go out on Thursday night"),
    ("Does Nan eat shellfish?", "Nan does not eat shellfish"),
    ("What is the wifi password?", "The wifi password is SALTMARSH-42"),
    ("When is Mum's birthday?", "Mum's birthday is on 12 November"),
    ("Who is the mortgage with?", "The mortgage is with Nationwide"),
    ("What time do the children go to bed?", "Bedtime for the children is half past seven"),
    ("Who has the spare key?", "The spare key is with the neighbour at number 14"),
    ("What day does Dad work from home?", "Dad works from home on Wednesdays"),
    ("Where is the allotment?", "The allotment is plot 12 by the railway"),
]

# Questions that lean on two memories at once — what a floor is most likely to break.
COMPOUND = [
    (
        "When is pizza night, and who has the spare key?",
        ["Family pizza night is every Friday", "The spare key is with the neighbour at number 14"],
    ),
    (
        "What is Reza allergic to, and does Nan eat shellfish?",
        ["Reza is allergic to penicillin", "Nan does not eat shellfish"],
    ),
    (
        "Who services the boiler, and who is the mortgage with?",
        ["The boiler is serviced by Kavanagh every 14 months", "The mortgage is with Nationwide"],
    ),
]


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Database:
    db = Database(tmp_path_factory.mktemp("mem") / "lumos.db")
    db.initialize()
    for value, key in MEMORIES:
        db.save_memory(value, memory_key=key, source="test")
    return db


def recalled(database: Database, question: str, **kwargs) -> list[str]:
    return [row["value"] for row in database.search_memories(question, limit=4, **kwargs)]


@pytest.mark.parametrize(("question", "expected"), ASKED)
def test_the_memory_that_was_asked_for_is_always_recalled(
    database: Database, question: str, expected: str
):
    # The one thing that must never regress. A memory the user saved and Lumos
    # cannot produce is not a ranking problem, it is a broken promise.
    assert expected in recalled(database, question)


@pytest.mark.parametrize(("question", "expected"), COMPOUND)
def test_a_question_needing_two_memories_gets_both(
    database: Database, question: str, expected: list[str]
):
    assert set(expected) <= set(recalled(database, question))


def test_nothing_else_rides_along(database: Database):
    # It used to take four memories to answer this and three of them were about the
    # mortgage, the cat, and the lawnmower — matched on the word "is", scored at
    # exactly zero by BM25, and posted to the provider all the same.
    assert recalled(database, "What is Reza allergic to?") == ["Reza is allergic to penicillin"]


def test_a_possessive_is_not_a_word_two_memories_share(database: Database):
    # "Mum's" tokenizes to "mum" and "s". So does "Sam's". Which is how a question
    # about Mum's birthday used to come back with Sam's swimming lesson attached.
    assert "Sam's swimming lesson is at seven on Saturday" not in recalled(
        database, "When is Mum's birthday?"
    )


def test_a_word_shared_by_accident_does_not_recall_a_memory(database: Database):
    # The bins go out on Thursday *night*. Pizza night is a different night, and the
    # search terms cannot tell them apart — only the floor can.
    assert recalled(database, "When is pizza night?") == ["Family pizza night is every Friday"]


def test_an_idle_question_recalls_nothing_at_all(database: Database):
    # Nothing but function words: every memory matches, every one scores zero, and
    # not one of them has any business being sent anywhere.
    assert recalled(database, "What about it?") == []
    assert recalled(database, "How are you?") == []


def test_turning_the_floor_off_gives_back_the_old_behaviour(database: Database):
    # The escape hatch. The stopwords still go, because they were never a policy —
    # they were a bug — but nothing is dropped on score.
    loose = recalled(database, "When is pizza night?", score_floor=0.0)

    assert "The bins go out on Thursday night" in loose


def test_barely_anything_rides_along_across_the_whole_set(database: Database):
    # Ask all twelve and count the private facts that went out unasked. It was 38 of
    # the 56 memories recalled; it is now one.
    strays = [
        (question, value)
        for question, expected in ASKED
        for value in recalled(database, question)
        if value != expected
    ]

    # The one that is left is honest, and no rule here can reach it: "what time do
    # the children *go* to bed" and "the bins *go* out on Thursday" share a verb, and
    # both memories match on a single word, so their scores are level and the floor
    # has nothing to cut on. Words alone cannot tell those two apart. Embeddings
    # could; BM25 never will, and pretending otherwise is how a floor starts eating
    # the answers instead of the noise.
    assert len(strays) <= 1, strays


def test_a_query_in_another_language_still_finds_its_memory(tmp_path: Path):
    db = Database(tmp_path / "fa.db")
    db.initialize()
    db.save_memory("چای مورد علاقه رضا ارل گری است", source="test")

    # The stopword list is English; a Farsi question has nothing on it to lose.
    assert db.search_memories("چای ارل گری") != []
