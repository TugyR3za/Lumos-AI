"""What counts as a real hit.

BM25 does the ranking, here and everywhere else in Lumos. This module only decides
what is worth searching for and what is worth keeping, which BM25 cannot decide for
itself. Two rules.

**A word that means nothing cannot tell one note from another.** "Who do we call
when the radiators go cold?" is a question about radiators. It is not a question
about "do" — and yet BM25 will rank a note on library fines above the heating note,
because that note is short and happens to say "do". BM25 is not wrong to: in a
folder of thirty notes "do" appears in a handful of them, so it carries real
statistical weight while carrying no meaning at all. Frequency cannot tell those
apart. A list must, so the function words are dropped before the search.

Unless they are all there is: "Where is the will?" is a question about a will, and a
query with nothing but function words in it means them literally. That fallback is
also what keeps the list honest about being English-only — a Farsi or Polish query
contains no word on it, so nothing is taken away.

**A hit has to hold its own next to the best hit for its query.** BM25 scores are
not comparable between queries — they depend on the words, the corpus, and the
length of the note — so the floor is a fraction of the best score for *this* query
rather than a number that means anything on its own. And a hit that scored zero
matched nothing informative at all; it is never relevant, whatever the floor says.
"""

from __future__ import annotations

import re
from typing import Any

# English function words. Deliberately missing: "can", "will", "own" and the months —
# each is a perfectly good noun in a family's notes ("where is the will?"), and a
# stopword list has no business swallowing a word someone might be asking about.
STOPWORDS = frozenset(
    """
    a about after again all also am an and any are as at be because been before being
    below between both but by cannot could did do does doing done down during each few
    for from further get gets getting got had has have having he her here hers herself
    him himself his how i if in into is it its itself just me more most much my myself
    no nor not now of off on once only or other otherwise our ours ourselves out over
    same she should so some such than that the their theirs them themselves then there
    these they this those through to too under until up very was we were what when
    where which while who whom why with would you your yours yourself yourselves
    s t
    """.split()  # noqa: SIM905 — a list of 120 quoted words is not more readable than this
)
# "s" and "t" are there because the tokenizer splits on the apostrophe: "Mum's" becomes
# "mum" and "s", and so does "Sam's" — which is how a question about Mum's birthday came
# back with Sam's swimming lesson attached. A possessive is not a word two things share.


def search_terms(query: str, *, literal_when_empty: bool = True) -> list[str]:
    """The words in ``query`` worth searching for, in order.

    Everything but the function words — or, if that is nothing, the words themselves,
    because a question made only of them may be asking about one of them.

    ``literal_when_empty`` is what note search wants and memory search does not. A
    question with nothing but function words in it is usually not a question at all
    ("how are you?"), and the cost of taking it literally is not the same on both
    sides: a stray note is a card nobody reads, while a stray memory is a private
    fact about this family volunteered to whichever provider answers, for nothing.
    Notes keep the benefit of the doubt. Memories do not get to be guessed at.
    """
    terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    meaningful = [term for term in terms if term.casefold() not in STOPWORDS]
    if meaningful:
        return meaningful
    return terms if literal_when_empty else []


def above_floor(rows: list[dict[str, Any]], floor: float) -> list[dict[str, Any]]:
    """The hits worth keeping: those scoring at least ``floor`` of the best one.

    ``floor`` is a fraction, not a score, because a score means nothing across
    queries. Zero disables it and hands back what BM25 ranked, junk and all.
    """
    if not rows or floor <= 0:
        return rows
    best = max(float(row["score"]) for row in rows)
    return [
        row
        for row in rows
        if float(row["score"]) > 0 and float(row["score"]) >= best * floor
    ]
