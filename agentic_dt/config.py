"""Validate the input configuration used by the input inventory command.

Later-stage settings remain outside these models until their runtime exists.
"""

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AgentConfig(BaseModel):
    """An explicitly registered role and its Markdown profile."""

    id: Identifier
    profile: Path


class AgentsConfig(BaseModel):
    """Reasoning roles and the separate synthesis role."""

    reasoning: list[AgentConfig] = Field(min_length=1)
    synthesis: AgentConfig

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [agent.id for agent in [*self.reasoning, self.synthesis]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"agents contains duplicate IDs: {ids}")
        return self


class ExerciseConfig(BaseModel):
    """A canonical Markdown exercise with an explicit numeric order."""

    id: Identifier
    order: int = Field(strict=True, gt=0)
    source: Path

    @model_validator(mode="after")
    def matching_filename(self) -> Self:
        prefix = self.source.name.split("_", 1)[0]
        if self.source.suffix != ".md" or not prefix.isdecimal():
            raise ValueError(
                f"exercise {self.id}: expected N_name.md source, got {self.source}"
            )
        if int(prefix) != self.order:
            raise ValueError(
                f"exercise {self.id}: order {self.order} disagrees with "
                f"filename {self.source}"
            )
        return self


class InputPaths(BaseModel):
    """Primary challenge input; other paths belong to later packages."""

    brief: Path


class DemoPaths(BaseModel):
    """Configured roots for isolated demonstration histories and logs."""

    graph: Path
    logs: Path


class ModelSettings(BaseModel):
    """One provider/model and explicit limits for the first paid experiment."""

    model: Literal["gpt-4.1-mini-2025-04-14"]
    timeout_seconds: float = Field(gt=0, le=300)
    max_retries: int = Field(strict=True, ge=0, le=1)
    max_input_bytes: int = Field(strict=True, gt=0, le=100_000)
    max_input_tokens: int = Field(strict=True, gt=0, le=30_000)
    max_output_tokens: int = Field(strict=True, ge=512, le=8_000)
    input_usd_per_million: Decimal = Field(gt=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(gt=0, allow_inf_nan=False)


class FirstPassPaths(DemoPaths):
    """Output roots needed for the single-agent run; graph remains untouched."""

    exercises: Path


class ProjectConfig(BaseModel):
    """The subset of project.yaml needed to validate the input inventory."""

    paths: InputPaths
    agents: AgentsConfig
    exercise_registry: list[ExerciseConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_exercises(self) -> Self:
        for field in ("id", "order"):
            values = [getattr(exercise, field) for exercise in self.exercise_registry]
            if len(values) != len(set(values)):
                raise ValueError(
                    f"exercise_registry contains duplicate {field}: {values}"
                )
        return self


def load_config(path: Path) -> ProjectConfig:
    """Read YAML safely and validate fields used by the input inventory."""
    return ProjectConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
