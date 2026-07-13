"""The machinery behind the Graph V1 eval. Measures; never prints.

Two tiers, because they answer different questions and cost different things.

**Retrieval** is deterministic, free, and needs no model: for each question, did
the note holding the answer reach the model's context at all — with BM25 alone,
and then with the graph expanding it? This is where the honest signal is. If the
graph does not put the right note in front of the model, nothing downstream can
save it, and the number is exact rather than judged.

**Answers** cost two model calls a question and only exist because the first tier
cannot see the last mile: the note arrived, but did the model *use* it, did the
extra context *distract* it, and did it *say* where the answer came from? Each is
read off a planted canary — a token the model cannot produce without having read
the note — so even this tier is decided by string comparison, not by a judge.

What neither tier measures: whether the answer was any good. Style, tone, and
helpfulness need a human, and the report exists to be read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container
from lumos.providers.echo import EchoProvider
from lumos.schemas import ChatResponse
from lumos.tools.registry import ToolRegistry

EVAL_DIR = Path(__file__).parent
DEFAULT_NOTES = EVAL_DIR / "notes"
DEFAULT_QUESTIONS = EVAL_DIR / "questions.json"


class NoModel(RuntimeError):
    """Raised rather than reporting answer numbers a canned reply produced."""


_SEPARATORS = re.compile(r"[\s-]+")

# The context's own headers, quoted back at the reader as though they meant something.
_SCAFFOLDING = re.compile(r"[\[【]\s*(linked\s+)?note\s*\d", re.IGNORECASE)


# A model types a fact in whatever hyphen and space its prose calls for.
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))
_SPACES = str.maketrans(dict.fromkeys("    ", " "))


def normalise(text: str) -> str:
    """Fold the ways a model can write a fact without changing it.

    A reply that says SALTMARSH‑42 with a non-breaking hyphen, or 19 °C where the
    note said nineteen degrees, has answered the question. Matching the raw string
    scores that as a miss — and then hands the credit for "fixing" it to whatever
    we happened to change next. The degree sign is folded to the word because that
    is what it is; everything else here is punctuation the model chose, not content.
    """
    folded = text.casefold().translate(_DASHES).translate(_SPACES).replace("°", " degrees ")
    return re.sub(r"\s+", " ", folded)


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    question: str
    needs_notes: tuple[str, ...]  # every note the answer needs; more than one is the hard case
    answer_contains: tuple[tuple[str, ...], ...]  # every fact, each with its spellings
    kind: str  # "linked": BM25 cannot supply them all — "direct": it can

    @property
    def multi(self) -> bool:
        """Spans several notes. Not a third kind — just the shape that hurts."""
        return len(self.needs_notes) > 1


@dataclass(frozen=True, slots=True)
class Retrieval:
    question: Question
    seeds: tuple[str, ...]  # notes BM25 found
    linked: tuple[str, ...]  # notes the graph added behind them
    linked_chars: int

    @property
    def reached(self) -> set[str]:
        return {note for note in self.question.needs_notes if note in self.seeds + self.linked}

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(note for note in self.question.needs_notes if note not in self.reached)

    @property
    def complete(self) -> bool:
        """Every note the answer needs reached the model. For a one-note question this
        is the old bar; for a multi-note one it is necessary and no longer sufficient,
        since the model still has to carry a fact out of each and join them."""
        return not self.missing

    @property
    def complete_from_seeds(self) -> bool:
        return all(note in self.seeds for note in self.question.needs_notes)

    @property
    def rescued(self) -> bool:
        """The graph completed a question BM25 could not."""
        return self.complete and not self.complete_from_seeds

    @property
    def fair(self) -> bool:
        """The question tests what it claims to. A `linked` question BM25 can already
        answer whole proves nothing about the graph, and a `direct` one it cannot is a
        broken control — either way the corpus is at fault, not the code."""
        return self.complete_from_seeds == (self.question.kind == "direct")

    @property
    def noise(self) -> int:
        """Linked notes nobody needed — the cost of the expansion."""
        return len(set(self.linked) - set(self.question.needs_notes))


@dataclass(frozen=True, slots=True)
class Answer:
    """One question, asked of each Lumos several times over.

    A model answers the same prompt differently twice running. Ask it once and the
    difference between two prompts is mostly the difference between two coin flips:
    the first two baselines of this eval disagreed by two questions out of six with
    nothing changed between them at all. Reliability is a rate, so it is measured as
    one, and a change has to move the rate to count as having moved anything.
    """

    question: Question
    retrieval: Retrieval
    off: tuple[ChatResponse, ...]
    on: tuple[ChatResponse, ...]

    @property
    def off_rate(self) -> float:
        return sum(self._carries(r, self.question) for r in self.off) / len(self.off)

    @property
    def on_rate(self) -> float:
        return sum(self._carries(r, self.question) for r in self.on) / len(self.on)

    @property
    def off_hit(self) -> bool:
        """Answered it more often than not."""
        return self.off_rate > 0.5

    @property
    def on_hit(self) -> bool:
        return self.on_rate > 0.5

    @property
    def improved(self) -> bool:
        return self.on_rate > self.off_rate

    @property
    def worsened(self) -> bool:
        return self.on_rate < self.off_rate

    @property
    def leak_rate(self) -> float:
        """How often the answer quotes the context's own headers back at the reader."""
        return sum(bool(_SCAFFOLDING.search(r.answer)) for r in self.on) / len(self.on)

    @property
    def cite_rate(self) -> float:
        """How often it names a note it could only have got the answer from."""
        if not self.leaned_on:
            return 1.0
        named = sum(any(self._cites(r, n) for n in self.leaned_on) for r in self.on)
        return named / len(self.on)

    @staticmethod
    def _carries(response: ChatResponse, question: Question) -> bool:
        """Every fact the question asked for, in any of its spellings. A multi-note
        answer that produces one fact and drops the other has not answered it.

        Matched twice: as written, and again with the separators taken out, because
        07700 900 412 and 07700900412 are the same phone number and only one of them
        is in the corpus."""
        answer = normalise(response.answer)
        tight = _SEPARATORS.sub("", answer)
        return all(
            any(
                normalise(spelling) in answer
                or _SEPARATORS.sub("", normalise(spelling)) in tight
                for spelling in fact
            )
            for fact in question.answer_contains
        )

    @property
    def rescued(self) -> bool:
        """The expansion turned a miss into an answer. This is "did it improve"."""
        return self.on_hit and not self.off_hit

    @property
    def regressed(self) -> bool:
        """The expansion cost us an answer we already had. This is the noise."""
        return self.off_hit and not self.on_hit

    @property
    def leaned_on(self) -> tuple[str, ...]:
        """The notes the answer needed that only the graph supplied."""
        return tuple(n for n in self.question.needs_notes if n in self.retrieval.linked)

    @staticmethod
    def _cites(response: ChatResponse, note: str) -> bool:
        """The answer names the file, as the system prompt asks it to. The filename,
        not the subject: an answer about the boiler says "boiler" whether or not it
        read boiler.md, so only "boiler.md" counts as telling."""
        answer = normalise(response.answer)
        return normalise(note) in answer or normalise(Path(note).name) in answer

    @property
    def silent(self) -> bool:
        """It leaned on a linked note and mostly did not say so — no citation card
        (those are search hits only, by design) and no word in the answer either.
        The note steered the reply and the reader has no way to know."""
        return self.on_hit and self.retrieval.rescued and self.cite_rate <= 0.5


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        Question(
            id=item["id"],
            question=item["question"],
            needs_notes=tuple(item["needs_notes"]),
            answer_contains=tuple(tuple(fact) for fact in item["answer_contains"]),
            kind=item["kind"],
        )
        for item in payload["questions"]
    ]


def _settings(notes: Path, database: Path, *, expand: bool, with_providers: bool) -> Settings:
    # The corpus, the database, and the graph flags are the eval's to decide; the
    # provider is the user's, and is left exactly as their environment configures
    # it. Web search is off — this measures the notes folder, nothing else.
    providers = {} if with_providers else {"ollama_enabled": False, "cloud_enabled": False}
    return Settings(
        database_path=database,
        notes_path=notes,
        ingest_notes_on_startup=False,
        web_search_provider="disabled",
        graph_enabled=True,
        graph_expand_retrieval=expand,
        **providers,
    )


def build_pair(
    notes: Path, database: Path, *, with_providers: bool = False
) -> tuple[LumosContainer, LumosContainer]:
    """Two Lumos instances over one freshly ingested corpus, alike but for the
    expansion. Everything the comparison must hold equal is literally the same
    database file, so nothing but the flag can explain a difference."""
    off = build_container(_settings(notes, database, expand=False, with_providers=with_providers))
    on = build_container(_settings(notes, database, expand=True, with_providers=with_providers))
    for container in (off, on):
        # Tools are held out. The variable under test is the context Lumos assembles
        # *before* the model speaks; leaving search_notes on the table would let the
        # model fetch a missing note itself and quietly answer the question the
        # expansion was meant to answer, crediting the prompt for the tool's work.
        container.agent.tools = ToolRegistry()
    off.settings.ensure_directories()
    off.ingestor.ingest_all()
    return off, on


def evaluate_retrieval(
    off: LumosContainer, on: LumosContainer, questions: list[Question]
) -> list[Retrieval]:
    results = []
    for question in questions:
        # One search, shared: search_notes is untouched by the graph, so asking
        # twice could only introduce a difference the expansion is not to blame for.
        seeds = off.retrieval.search_notes(question.question, off.settings.retrieval_top_k)
        linked = on.retrieval.linked_notes(seeds)
        results.append(
            Retrieval(
                question=question,
                seeds=tuple(dict.fromkeys(str(row["path"]) for row in seeds)),
                linked=tuple(note.path for note in linked),
                linked_chars=sum(len(note.content) for note in linked),
            )
        )
    return results


async def answering_provider(container: LumosContainer) -> str:
    """Who actually answers here — asked, not assumed. A throwaway turn, because
    provider status reports what is configured and this reports what replies."""
    response = await container.agent.chat(
        user_message="ping", conversation_id=None, route="auto", use_notes=False, use_web=False
    )
    return response.provider


async def evaluate_answers(
    off: LumosContainer,
    on: LumosContainer,
    retrievals: list[Retrieval],
    *,
    repeat: int = 3,
) -> list[Answer]:
    """Ask each question of each Lumos, ``repeat`` times over.

    Once is not a measurement. The model answers the same prompt differently on
    consecutive runs, so a single pass compares two prompts by comparing two coin
    flips. Raises NoModel if the echo fallback is what replies: it never reads the
    context, so every canary would be missing and the graph would take the blame.
    """
    provider = await answering_provider(off)
    if provider == EchoProvider.name:
        raise NoModel(
            "The echo fallback answered, which means no model is configured. Echo never "
            "reads the notes it is given, so every question would score zero and the "
            "report would blame the graph for it. Configure a provider in .env "
            "(LUMOS_OLLAMA_API_KEY, or LUMOS_CLOUD_API_KEY) and run this again."
        )

    async def ask(container: LumosContainer, question: str) -> ChatResponse:
        return await container.agent.chat(
            user_message=question,
            conversation_id=None,  # every run starts clean: no history to lean on
            route="auto",
            use_notes=True,
            use_web=False,
        )

    answers = []
    for retrieval in retrievals:
        question = retrieval.question
        answers.append(
            Answer(
                question=question,
                retrieval=retrieval,
                off=tuple([await ask(off, question.question) for _ in range(repeat)]),
                on=tuple([await ask(on, question.question) for _ in range(repeat)]),
            )
        )
    return answers
