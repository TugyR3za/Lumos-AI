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
from dataclasses import dataclass
from pathlib import Path

from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container
from lumos.providers.echo import EchoProvider
from lumos.schemas import ChatResponse

EVAL_DIR = Path(__file__).parent
DEFAULT_NOTES = EVAL_DIR / "notes"
DEFAULT_QUESTIONS = EVAL_DIR / "questions.json"


class NoModel(RuntimeError):
    """Raised rather than reporting answer numbers a canned reply produced."""


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    question: str
    needs_note: str  # the one note that holds the answer
    answer_contains: tuple[str, ...]  # any one of these present = the fact arrived
    kind: str  # "linked": BM25 should miss it — "direct": BM25 should find it


@dataclass(frozen=True, slots=True)
class Retrieval:
    question: Question
    seeds: tuple[str, ...]  # notes BM25 found
    linked: tuple[str, ...]  # notes the graph added behind them
    linked_chars: int

    @property
    def seed_hit(self) -> bool:
        return self.question.needs_note in self.seeds

    @property
    def linked_hit(self) -> bool:
        return self.question.needs_note in self.linked

    @property
    def context_hit(self) -> bool:
        return self.seed_hit or self.linked_hit

    @property
    def rescued(self) -> bool:
        """The graph put a note in front of the model that BM25 could not find."""
        return self.linked_hit and not self.seed_hit

    @property
    def fair(self) -> bool:
        """The question tests what it claims to. A `linked` question BM25 answers on
        its own proves nothing about the graph, and a `direct` one it cannot answer
        is a broken control — either way the corpus is at fault, not the code."""
        return self.seed_hit == (self.question.kind == "direct")

    @property
    def noise(self) -> int:
        """Linked notes that were not the one needed — the cost of the expansion."""
        return len(self.linked) - (1 if self.linked_hit else 0)


@dataclass(frozen=True, slots=True)
class Answer:
    question: Question
    retrieval: Retrieval
    off: ChatResponse
    on: ChatResponse

    @staticmethod
    def _carries(response: ChatResponse, question: Question) -> bool:
        answer = response.answer.casefold()
        return any(token.casefold() in answer for token in question.answer_contains)

    @property
    def off_hit(self) -> bool:
        return self._carries(self.off, self.question)

    @property
    def on_hit(self) -> bool:
        return self._carries(self.on, self.question)

    @property
    def rescued(self) -> bool:
        """The expansion turned a miss into an answer. This is "did it improve"."""
        return self.on_hit and not self.off_hit

    @property
    def regressed(self) -> bool:
        """The expansion cost us an answer we already had. This is the noise."""
        return self.off_hit and not self.on_hit

    @property
    def cites_the_note(self) -> bool:
        """The answer names the file it leaned on, as the system prompt asks it to.
        The filename, not the subject: an answer about the boiler says "boiler"
        whether or not it read boiler.md, so only "boiler.md" counts as telling."""
        needed = self.question.needs_note.casefold()
        return needed in self.on.answer.casefold() or Path(needed).name in self.on.answer.casefold()

    @property
    def silent(self) -> bool:
        """The answer came out of a linked note, and nothing said so: not a citation
        card (those are search hits only, by design) and not a word in the answer.
        The note steered the reply and the reader has no way to know."""
        return self.on_hit and self.retrieval.rescued and not self.cites_the_note


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        Question(
            id=item["id"],
            question=item["question"],
            needs_note=item["needs_note"],
            answer_contains=tuple(item["answer_contains"]),
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
) -> list[Answer]:
    """Ask each question twice, once of each Lumos. Raises NoModel if the echo
    fallback is what replies: it never reads the context, so every canary would be
    missing and the eval would report a real model's failure at finding them."""
    provider = await answering_provider(off)
    if provider == EchoProvider.name:
        raise NoModel(
            "The echo fallback answered, which means no model is configured. Echo never "
            "reads the notes it is given, so every question would score zero and the "
            "report would blame the graph for it. Configure a provider in .env "
            "(LUMOS_OLLAMA_API_KEY, or LUMOS_CLOUD_API_KEY) and run this again."
        )

    answers = []
    for retrieval in retrievals:
        question = retrieval.question
        replies = [
            await container.agent.chat(
                user_message=question.question,
                conversation_id=None,  # every question starts clean: no history to lean on
                route="auto",
                use_notes=True,
                use_web=False,
            )
            for container in (off, on)
        ]
        answers.append(
            Answer(question=question, retrieval=retrieval, off=replies[0], on=replies[1])
        )
    return answers
