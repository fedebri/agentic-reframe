"""Fully typed version 2 project configuration."""

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectInfo(ConfigRecord):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: Literal["2.0.0"]


class PathsConfig(ConfigRecord):
    brief: Path
    outputs: Path
    ledger: Path


class WorkflowConfig(ConfigRecord):
    analyst_prompt: Path
    critic_prompt: Path
    critic_policy: Literal["disabled", "requested", "always"] = "requested"


class ModelConfig(ConfigRecord):
    name: str = Field(min_length=1)
    reasoning_effort: (
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    timeout_seconds: float = Field(gt=0, le=300)
    max_retries: int = Field(ge=0, le=2)
    max_input_bytes: int = Field(gt=0, le=200_000)
    max_input_tokens: int = Field(gt=0, le=100_000)
    max_output_tokens: int = Field(gt=0, le=20_000)
    input_usd_per_million: Decimal = Field(gt=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(gt=0, allow_inf_nan=False)


class ExerciseConfig(ConfigRecord):
    id: str = Field(min_length=1)
    order: int = Field(gt=0)
    source: Path
    produces: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def matching_filename(self) -> Self:
        prefix = self.source.name.split("_", 1)[0]
        if self.source.suffix != ".md" or not prefix.isdecimal():
            raise ValueError(f"Exercise {self.id}: expected N_name.md source")
        if int(prefix) != self.order:
            raise ValueError(f"Exercise {self.id}: order and filename disagree")
        return self


class ProjectConfig(ConfigRecord):
    project: ProjectInfo
    paths: PathsConfig
    workflow: WorkflowConfig
    model: ModelConfig
    exercises: list[ExerciseConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ordered_exercises(self) -> Self:
        ids = [exercise.id for exercise in self.exercises]
        orders = [exercise.order for exercise in self.exercises]
        if len(ids) != len(set(ids)):
            raise ValueError("Exercise IDs must be unique")
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("Exercises must be listed in contiguous numeric order")
        return self

    def exercise(self, exercise_id: str) -> ExerciseConfig:
        for exercise in self.exercises:
            if exercise.id == exercise_id:
                return exercise
        raise ValueError(f"Unknown exercise: {exercise_id}")


def load_config(path: Path) -> ProjectConfig:
    """Load and strictly validate the complete configuration file."""
    return ProjectConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
