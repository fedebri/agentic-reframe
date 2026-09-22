"""Validate inputs, demonstrate provenance, or prepare/run one reasoning agent."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from openai import APIError

from .config import DemoPaths, load_config
from .demo import run_demo
from .framing import run_framing
from .inputs import load_inputs
from .orchestrator import run_first_pass


def main(argv: list[str] | None = None) -> int:
    """Validate inputs and display their inventory, or exit with a clear error."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check and list configured inputs")
    validate.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    validate.add_argument(
        "--brief", type=Path, help="Override the brief; relative to the project root"
    )
    demo = commands.add_parser(
        "provenance-demo", help="Append a fictional claim history"
    )
    demo.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    first_pass = commands.add_parser("first-pass", help="Preview or run exercise 1")
    first_pass.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    first_pass.add_argument("--brief", type=Path, help="Brief relative to project root")
    first_pass.add_argument("--live", action="store_true", help="Send inputs to OpenAI")
    first_pass.add_argument(
        "--budget-usd", type=Decimal, help="Approved per-run USD budget"
    )
    framing = commands.add_parser("frame", help="Continue a reviewed first pass")
    framing.add_argument("--config", type=Path, default=Path("config/project.yaml"))
    framing.add_argument("--from-first-pass", type=Path, required=True)
    framing.add_argument("--review", type=Path, required=True, help="Bound review JSON")
    framing.add_argument("--live", action="store_true", help="Send inputs to OpenAI")
    framing.add_argument("--budget-usd", type=Decimal, help="Total new-call USD budget")
    try:
        args = parser.parse_args(argv)
    except InvalidOperation:
        parser.error("--budget-usd must be a decimal amount, for example 0.10")
    config_path = args.config.resolve()
    # The repository contract places configuration at <project>/config/project.yaml.
    project_root = config_path.parent.parent
    if args.command in {"first-pass", "frame"}:
        try:
            if args.command == "first-pass":
                run_first_pass(config_path, args.brief, args.live, args.budget_usd)
            else:
                run_framing(
                    config_path,
                    args.from_first_pass,
                    args.review,
                    args.live,
                    args.budget_usd,
                )
        except APIError as error:
            parser.exit(
                2,
                f"OpenAI request failed: {type(error).__name__}; "
                f"HTTP {getattr(error, 'status_code', 'unavailable')}; "
                f"request ID {getattr(error, 'request_id', 'unavailable')}. "
                "See the printed run log and status for completed stages.\n",
            )
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            parser.exit(2, f"{args.command.capitalize()} run failed: {error}\n")
        return 0
    if args.command == "provenance-demo":
        try:
            settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            paths = DemoPaths.model_validate(settings["paths"]["outputs"])
            run_demo(project_root / paths.graph, project_root / paths.logs)
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            parser.exit(
                2, f"Provenance demonstration failed ({config_path}): {error}\n"
            )
        return 0
    try:
        config = load_config(config_path)
        inventory = load_inputs(config, project_root, args.brief)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.exit(2, f"Input validation failed ({config_path}): {error}\n")

    print("Input validation passed (file/schema checks only; no agents executed).")
    print(f"Project root: {project_root}")
    print(f"Config: {config_path}")
    print(f"Brief: {inventory.brief.path}")
    print(f"\nAgents ({len(inventory.agents)}):")
    for agent_id, document in inventory.agents.items():
        role = "synthesis" if agent_id == config.agents.synthesis.id else "reasoning"
        print(f"  {agent_id} [{role}]: {document.path}")
    print(f"\nExercises ({len(inventory.exercises)}, numeric order):")
    for exercise in sorted(config.exercise_registry, key=lambda item: item.order):
        print(
            f"  {exercise.order:2}. {exercise.id}: "
            f"{inventory.exercises[exercise.id].path}"
        )
    print("\nOptional HTML/PDF source material is not required or loaded.")
    print("Review the brief's substance before any future live model run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
