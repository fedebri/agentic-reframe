"""Version 2 CLI: validate, run, review, evaluate, compile, and rehearse."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from openai import APIError

from .evals import evaluate_run
from .reports import compile_reports
from .review import apply_review, export_review
from .tutorial import run_tutorial
from .workflow import run_exercise, validate_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Validate all configured inputs")
    validate.add_argument("--config", type=Path, default=Path("config/project.yaml"))

    frame = commands.add_parser(
        "frame", help="Create an independent human framing worksheet"
    )
    frame.add_argument("--exercise", default="frame_challenge")
    frame.add_argument("--author", required=True)
    frame.add_argument("--out", type=Path, required=True)

    run = commands.add_parser("run", help="Prepare or resume one exercise")
    run.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    run.add_argument("--exercise", required=True)
    run.add_argument("--out", type=Path)
    run.add_argument("--evidence", type=Path, action="append", default=[])
    run.add_argument("--context-claim", action="append", default=[])
    run.add_argument("--human-frame", type=Path)
    run.add_argument("--critic", action="store_true")
    run.add_argument("--live", action="store_true")
    run.add_argument("--budget-usd", type=Decimal)
    run.add_argument("--retry-failed", action="store_true")

    review = commands.add_parser("review", help="Export or apply human decisions")
    mode = review.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=Path, help="Completed model run to review")
    mode.add_argument("--apply", type=Path, help="Edited review worksheet to apply")
    review.add_argument("--out", type=Path)
    review.add_argument("--reviewer")
    review.add_argument("--evidence", type=Path, action="append", default=[])

    evaluate = commands.add_parser("eval", help="Evaluate one saved run")
    evaluate.add_argument("--run", type=Path, required=True)
    evaluate.add_argument("--out", type=Path, required=True)
    evaluate.add_argument("--assessment", type=Path)

    compile_command = commands.add_parser(
        "compile", help="Compile evidence-qualified reports"
    )
    compile_command.add_argument("--ledger", type=Path, required=True)
    compile_command.add_argument("--out", type=Path, required=True)

    tutorial = commands.add_parser(
        "tutorial", help="Run an isolated, zero-cost fictional rehearsal"
    )
    tutorial.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    tutorial.add_argument("--out", type=Path, required=True)

    try:
        args = parser.parse_args(argv)
    except InvalidOperation:
        parser.error("--budget-usd must be a decimal amount, for example 0.10")

    try:
        if args.command == "frame":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x", encoding="utf-8") as stream:
                yaml.safe_dump(
                    {
                        "author_id": args.author,
                        "exercise_id": args.exercise,
                        "framing": "",
                        "observations": [],
                        "assumptions": [],
                        "alternative_frame": "",
                        "open_questions": [],
                    },
                    stream,
                    sort_keys=False,
                )
            print(f"Complete your interpretation before using AI: {args.out.resolve()}")
        elif args.command == "validate":
            config = validate_project(args.config)
            print(
                f"Validated {config.project.name} {config.project.version}: "
                f"{len(config.exercises)} exercises"
            )
        elif args.command == "run":
            directory = run_exercise(
                args.config,
                args.exercise,
                args.out,
                args.evidence,
                args.critic,
                args.live,
                args.budget_usd,
                args.retry_failed,
                context_claim_ids=args.context_claim,
                human_frame_path=args.human_frame,
            )
            print(f"Run directory: {directory}")
        elif args.command == "review":
            if args.run is not None:
                if args.out is None or not args.reviewer:
                    raise ValueError("Review export requires --out and --reviewer")
                worksheet = export_review(
                    args.run, args.out, args.reviewer, args.evidence
                )
                print(f"Review worksheet: {worksheet}")
            else:
                print(f"Review receipt: {apply_review(args.apply)}")
        elif args.command == "eval":
            print(f"Eval report: {evaluate_run(args.run, args.out, args.assessment)}")
        elif args.command == "compile":
            print(f"Report snapshot: {compile_reports(args.ledger, args.out)}")
        else:
            print(f"Tutorial: {run_tutorial(args.config, args.out)}")
    except APIError as error:
        parser.exit(
            2,
            f"OpenAI request failed: {type(error).__name__}; "
            f"HTTP {getattr(error, 'status_code', 'unavailable')}; "
            f"request ID {getattr(error, 'request_id', 'unavailable')}\n",
        )
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        parser.exit(2, f"{args.command} failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
