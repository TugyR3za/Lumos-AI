"""Graph V1 eval: is the note the model needed actually reaching it, and at what cost?

    python -m evals.run_eval              # retrieval only: no model, no cost, seconds
    python -m evals.run_eval --answers    # also ask a real model, twice per question

Everything is built in a scratch database from the corpus in evals/notes, so your
own notes and your own lumos.db are never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
from datetime import datetime
from pathlib import Path

from evals.harness import (
    DEFAULT_NOTES,
    DEFAULT_QUESTIONS,
    Answer,
    NoModel,
    Retrieval,
    build_pair,
    evaluate_answers,
    evaluate_retrieval,
    load_questions,
)

RESULTS = Path(__file__).parent / "results"


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:4.0f}%" if whole else "   -"


def ids(results: list[Retrieval] | list[Answer]) -> str:
    return ", ".join(r.question.id for r in results) or "-"


def stems(paths: tuple[str, ...], needed: str) -> str:
    """Note names, starring the one that holds the answer wherever it turns up, so
    a verdict can always be read back to the row that produced it."""
    return ",".join(Path(p).stem + ("*" if p == needed else "") for p in paths) or "-"


def report_retrieval(results: list[Retrieval]) -> None:
    total = len(results)
    seeded = [r for r in results if r.seed_hit]
    reached = [r for r in results if r.context_hit]
    rescued = [r for r in results if r.rescued]
    missed = [r for r in results if not r.context_hit]
    unfair = [r for r in results if not r.fair]

    print(f"\nRETRIEVAL  ·  {total} questions, no model")
    print("Did the note holding the answer reach the model at all?\n")
    print(f"  BM25 alone .............. {len(seeded):>2}/{total}  {pct(len(seeded), total)}")
    print(f"  BM25 + graph ............ {len(reached):>2}/{total}  {pct(len(reached), total)}")
    print(f"  rescued by the graph .... {len(rescued):>2}      <- what the expansion bought")
    print(f"  never reached it ........ {len(missed):>2}      {ids(missed)}")

    print("\n  by design of the question:")
    for kind, blurb in (("linked", "BM25 should miss"), ("direct", "BM25 should find")):
        group = [r for r in results if r.question.kind == kind]
        found = sum(1 for r in group if r.context_hit)
        print(f"    {kind} ({blurb}) {found:>3}/{len(group)} reached")

    counts = [len(r.linked) for r in results]
    chars = [r.linked_chars for r in results]
    expanded = [r for r in results if r.linked]
    useful = [r for r in expanded if r.linked_hit]

    print("\nCOST  ·  what the expansion put in the prompt")
    print(f"  linked notes per question  {statistics.mean(counts):.1f} mean, {max(counts)} max")
    print(f"  extra characters ......... {statistics.mean(chars):,.0f} mean, "
          f"{max(chars):,} max  (ceiling 2,400)")
    print(f"  notes added that were not the one needed  "
          f"{sum(r.noise for r in results)} of {sum(counts)}")
    print(f"  questions it paid off in ................ {len(useful)}/{len(expanded)} that got any")

    if unfair:
        print(f"\nCORPUS FAULTS  ·  {len(unfair)} question(s) do not test what they claim")
        for r in unfair:
            why = "BM25 already finds it" if r.seed_hit else "BM25 misses it even as a control"
            print(f"  {r.question.kind:<7} {r.question.id:<28} {why}")

    print("\n  question                       seeds (* = holds the answer)          linked")
    print("  " + "-" * 100)
    for r in results:
        mark = "RESCUED" if r.rescued else ("seed" if r.seed_hit else "MISS")
        seeds = stems(r.seeds, r.question.needs_note)
        linked = stems(r.linked, r.question.needs_note)
        print(f"  {r.question.id:<30} {seeds:<36} {linked:<30} {mark}")


def report_answers(answers: list[Answer], provider: str) -> None:
    total = len(answers)
    off_hits = [a for a in answers if a.off_hit]
    on_hits = [a for a in answers if a.on_hit]
    rescued = [a for a in answers if a.rescued]
    regressed = [a for a in answers if a.regressed]
    silent = [a for a in answers if a.silent]

    print(f"\nANSWERS  ·  {provider}, {total * 2} calls")
    print("Did the fact actually come out the other end?\n")
    print(f"  fact in the answer, off ... {len(off_hits):>2}/{total}  {pct(len(off_hits), total)}")
    print(f"  fact in the answer, on .... {len(on_hits):>2}/{total}  {pct(len(on_hits), total)}")
    print(f"  IMPROVED  (miss -> hit) ... {len(rescued):>2}      {ids(rescued)}")
    print(f"  NOISY     (hit -> miss) ... {len(regressed):>2}      {ids(regressed)}")
    print("  SILENT    (used a linked note, never named it)")
    print(f"            {len(silent):>2} of the {len(rescued)} rescued    {ids(silent)}")


def write_report(path: Path, retrievals: list[Retrieval], answers: list[Answer] | None) -> None:
    lines = [f"# Graph V1 eval — {datetime.now():%Y-%m-%d %H:%M}", ""]
    by_id = {a.question.id: a for a in answers or []}

    for r in retrievals:
        answer = by_id.get(r.question.id)
        lines += [
            f"## {r.question.id}  ({r.question.kind})",
            "",
            f"**{r.question.question}**",
            "",
            f"- needs: `{r.question.needs_note}` — canary: {', '.join(r.question.answer_contains)}",
            f"- seeds: {', '.join(f'`{p}`' for p in r.seeds) or '_none_'}",
            f"- linked: {', '.join(f'`{p}`' for p in r.linked) or '_none_'}"
            f" ({r.linked_chars:,} chars)",
            f"- reached the model: **{'yes' if r.context_hit else 'NO'}**"
            + (" — rescued by the graph" if r.rescued else ""),
            "",
        ]
        if answer:
            verdict = []
            if answer.rescued:
                verdict.append("IMPROVED")
            if answer.regressed:
                verdict.append("NOISY — lost an answer it had")
            if answer.silent:
                verdict.append("SILENT — used the linked note, never named it")
            lines += [
                f"- fact in answer: off **{'yes' if answer.off_hit else 'no'}**, "
                f"on **{'yes' if answer.on_hit else 'no'}**"
                + (f" — {'; '.join(verdict)}" if verdict else ""),
                "",
                "<details><summary>expansion OFF</summary>",
                "",
                "```",
                answer.off.answer.strip(),
                "```",
                "",
                "</details>",
                "",
                "<details><summary>expansion ON</summary>",
                "",
                "```",
                answer.on.answer.strip(),
                "```",
                "",
                "</details>",
                "",
            ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--answers", action="store_true", help="also ask the model (2 calls per question)"
    )
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES, help="corpus to ingest")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS, help="question set")
    parser.add_argument("--report", type=Path, default=None, help="where to write the detail")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    with tempfile.TemporaryDirectory() as scratch:
        off, on = build_pair(
            args.notes, Path(scratch) / "eval.db", with_providers=args.answers
        )
        retrievals = evaluate_retrieval(off, on, questions)
        report_retrieval(retrievals)

        answers = None
        if args.answers:
            try:
                answers = asyncio.run(evaluate_answers(off, on, retrievals))
            except NoModel as exc:
                print(f"\nANSWERS  ·  not run\n  {exc}")
                return 1
            report_answers(answers, f"{answers[0].on.provider} · {answers[0].on.model}")

    report = args.report or (RESULTS / f"graph-v1-{datetime.now():%Y%m%d-%H%M%S}.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, retrievals, answers)
    print(f"\nper-question detail: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
