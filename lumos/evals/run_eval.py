"""Graph V1 eval: is the note the model needed reaching it, does the answer come
out the other end, and at what cost?

    python -m evals.run_eval              # retrieval only: no model, no cost, seconds
    python -m evals.run_eval --answers    # also ask a real model, several runs a question

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


def stems(paths: tuple[str, ...], needed: tuple[str, ...]) -> str:
    """Note names, starring any the answer needs wherever it turns up, so a verdict
    can always be read back to the row that produced it."""
    return ",".join(Path(p).stem + ("*" if p in needed else "") for p in paths) or "-"


def report_retrieval(results: list[Retrieval]) -> None:
    total = len(results)
    seeded = [r for r in results if r.complete_from_seeds]
    reached = [r for r in results if r.complete]
    rescued = [r for r in results if r.rescued]
    missed = [r for r in results if not r.complete]
    unfair = [r for r in results if not r.fair]

    print(f"\nRETRIEVAL  ·  {total} questions, no model")
    print("Did every note the answer needs reach the model?\n")
    print(f"  BM25 alone .............. {len(seeded):>2}/{total}  {pct(len(seeded), total)}")
    print(f"  BM25 + graph ............ {len(reached):>2}/{total}  {pct(len(reached), total)}")
    print(f"  rescued by the graph .... {len(rescued):>2}      <- what the expansion bought")
    print(f"  short of a note ......... {len(missed):>2}      {ids(missed)}")

    print("\n  by shape — a multi-note question needs every one of them, not any one:")
    for label, group in (
        ("one note", [r for r in results if not r.question.multi]),
        ("several notes", [r for r in results if r.question.multi]),
    ):
        seeds_ok = sum(1 for r in group if r.complete_from_seeds)
        graph_ok = sum(1 for r in group if r.complete)
        print(f"    {label:<14} BM25 {seeds_ok:>2}/{len(group)}"
              f"    BM25 + graph {graph_ok:>2}/{len(group)}")

    seeds = [len(r.seeds) for r in results]
    counts = [len(r.linked) for r in results]
    chars = [r.linked_chars for r in results]
    expanded = [r for r in results if r.linked]
    useful = [r for r in expanded if set(r.linked) & set(r.question.needs_notes)]

    print("\nCOST  ·  what reached the model, and what the reader is shown")
    # The seeds are the source cards: whatever the search keeps, the user sees.
    print(f"  search hits per question .. {statistics.mean(seeds):.1f} mean, {max(seeds)} max")
    print(f"  cards that earned nothing .. {sum(r.seed_noise for r in results)} of {sum(seeds)}"
          "   (neither the answer nor the note that led to it)")
    print(f"  linked notes per question  {statistics.mean(counts):.1f} mean, {max(counts)} max")
    print(f"  linked notes nobody needed  {sum(r.noise for r in results)} of {sum(counts)}")
    print(f"  extra characters ......... {statistics.mean(chars):,.0f} mean, "
          f"{max(chars):,} max  (ceiling 2,400)")
    print(f"  questions it paid off in ... {len(useful)}/{len(expanded)} that got any")

    if unfair:
        print(f"\nCORPUS FAULTS  ·  {len(unfair)} question(s) do not test what they claim")
        for r in unfair:
            why = "BM25 has them all" if r.complete_from_seeds else "BM25 short of a control"
            print(f"  {r.question.kind:<7} {r.question.id:<30} {why}")

    print("\n  question                       seeds (* = needed)                   linked")
    print("  " + "-" * 104)
    for r in results:
        mark = "RESCUED" if r.rescued else ("seed" if r.complete_from_seeds else "SHORT")
        seeds = stems(r.seeds, r.question.needs_notes)
        linked = stems(r.linked, r.question.needs_notes)
        note = f"  needs {len(r.question.needs_notes)}" if r.question.multi else ""
        print(f"  {r.question.id:<30} {seeds:<36} {linked:<30} {mark}{note}")


def report_answers(answers: list[Answer], provider: str, repeat: int) -> None:
    total = len(answers)
    off_rate = statistics.mean(a.off_rate for a in answers)
    on_rate = statistics.mean(a.on_rate for a in answers)
    improved = [a for a in answers if a.improved]
    worsened = [a for a in answers if a.worsened]
    rescued = [a for a in answers if a.rescued]
    silent = [a for a in answers if a.silent]
    leak = statistics.mean(a.leak_rate for a in answers)

    print(f"\nANSWERS  ·  {provider}, {total * 2 * repeat} calls, tools held out")
    print(f"Every fact the question asked for, over {repeat} runs a question.\n")
    print(f"  all facts present, off ... {off_rate:5.0%} of runs")
    print(f"  all facts present, on .... {on_rate:5.0%} of runs")
    print(f"  IMPROVED  (on beats off) . {len(improved):>2}      {ids(improved)}")
    print(f"  NOISY     (off beats on) . {len(worsened):>2}      {ids(worsened)}")
    print("  SILENT    (leaned on a linked note, mostly did not name it)")
    print(f"            {len(silent):>2} of the {len(rescued)} rescued    {ids(silent)}")
    print("  LEAKED    (quoted our [NOTE n] furniture at the reader)")
    print(f"            {leak:5.0%} of answers")

    multi = [a for a in answers if a.question.multi]
    if multi:
        multi_off = statistics.mean(a.off_rate for a in multi)
        multi_on = statistics.mean(a.on_rate for a in multi)
        print("\n  MULTI-NOTE  ·  every fact, out of several notes at once")
        print(f"    off {multi_off:5.0%}    on {multi_on:5.0%}    ({len(multi)} questions)")
        for a in multi:
            off_k = round(a.off_rate * repeat)
            on_k = round(a.on_rate * repeat)
            print(f"    {a.question.id:<30} off {off_k}/{repeat}   on {on_k}/{repeat}")


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
            f"- needs: {', '.join(f'`{n}`' for n in r.question.needs_notes)} — canaries: "
            + "; ".join(" / ".join(fact) for fact in r.question.answer_contains),
            f"- seeds: {', '.join(f'`{p}`' for p in r.seeds) or '_none_'}",
            f"- linked: {', '.join(f'`{p}`' for p in r.linked) or '_none_'}"
            f" ({r.linked_chars:,} chars)",
            f"- every needed note reached the model: **{'yes' if r.complete else 'NO'}**"
            + (f" — missing {', '.join(r.missing)}" if r.missing else "")
            + (" — rescued by the graph" if r.rescued else ""),
            "",
        ]
        if answer:
            verdict = []
            if answer.improved:
                verdict.append("IMPROVED")
            if answer.worsened:
                verdict.append("NOISY — lost ground the expansion had")
            if answer.silent:
                verdict.append("SILENT — used the linked note, never named it")
            if answer.leak_rate:
                verdict.append("LEAKED — quoted [NOTE n] at the reader")
            lines += [
                f"- facts present: off **{answer.off_rate:.0%}** of runs, "
                f"on **{answer.on_rate:.0%}**"
                + (f" — {'; '.join(verdict)}" if verdict else ""),
                "",
                "<details><summary>expansion OFF (first run)</summary>",
                "",
                "```",
                answer.off[0].answer.strip(),
                "```",
                "",
                "</details>",
                "",
                "<details><summary>expansion ON (first run)</summary>",
                "",
                "```",
                answer.on[0].answer.strip(),
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
    parser.add_argument("--answers", action="store_true", help="also ask the model")
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES, help="corpus to ingest")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS, help="question set")
    parser.add_argument("--repeat", type=int, default=3, help="runs per question per arm")
    parser.add_argument("--report", type=Path, default=None, help="where to write the detail")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    with tempfile.TemporaryDirectory() as scratch:
        off, on = build_pair(args.notes, Path(scratch) / "eval.db", with_providers=args.answers)
        retrievals = evaluate_retrieval(off, on, questions)
        report_retrieval(retrievals)

        answers = None
        if args.answers:
            try:
                answers = asyncio.run(evaluate_answers(off, on, retrievals, repeat=args.repeat))
            except NoModel as exc:
                print(f"\nANSWERS  ·  not run\n  {exc}")
                return 1
            first = answers[0].on[0]
            report_answers(answers, f"{first.provider} · {first.model}", args.repeat)

    report = args.report or (RESULTS / f"graph-v1-{datetime.now():%Y%m%d-%H%M%S}.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, retrievals, answers)
    print(f"\nper-question detail: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
