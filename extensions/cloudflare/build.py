"""Stage an allowlisted Workers bundle from the same repository."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def build(destination: Path = HERE / "dist", *, fixture: bool = False) -> None:
    """Copy source and public resources; no real brief, evidence, runs, or secrets."""
    sources = [
        *ROOT.joinpath("agentic_dt").glob("*.py"),
        *ROOT.joinpath("extensions/web").glob("*.py"),
        ROOT / "extensions/web/schema.sql",
        ROOT / "extensions/web/interpretations.yaml",
        *ROOT.joinpath("extensions/web/templates").glob("*.html"),
        *ROOT.joinpath("extensions/web/static").glob("*"),
        ROOT / "config/project.yaml",
        ROOT / "agents/analyst.md",
        ROOT / "agents/critic.md",
        *ROOT.joinpath("exercises").glob("[0-9]*.md"),
        HERE / "__init__.py",
        HERE / "snapshots.py",
        HERE / "runtime.py",
        HERE / "entry.py",
        HERE / "runner.py",
    ]
    if fixture:
        sources.append(ROOT / "tests/workers/fixture.py")
    expected = {path.relative_to(ROOT) for path in sources}
    expected.add(Path("docs/brief.md"))
    stale = {
        path.relative_to(destination)
        for path in destination.rglob("*")
        if path.is_file() and path.relative_to(destination) not in expected
    }
    if stale:
        raise ValueError(
            "Unexpected files in build directory; inspect before publishing: "
            f"{sorted(stale)}"
        )
    for source in sources:
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    destination.joinpath("docs").mkdir(exist_ok=True)
    destination.joinpath("docs/brief.md").write_text(
        "# Deployment scaffold\n\nEach tester supplies a private challenge brief.\n"
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixture"]:
        build(HERE / "dist-fixture", fixture=True)
    elif sys.argv[1:]:
        raise SystemExit("Usage: python build.py [--fixture]")
    else:
        build()
