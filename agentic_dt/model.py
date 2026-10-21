"""One structured Responses API boundary with explicit budget and retry control."""

import time
from collections.abc import Callable
from decimal import Decimal
from typing import TypeVar

from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel

from .config import ModelConfig

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def generate_structured(
    client: OpenAI,
    request: dict,
    settings: ModelConfig,
    budget_usd: Decimal,
    record: Callable[..., None],
    response_model: type[ResponseT],
) -> ResponseT:
    """Reserve the worst-case call cost, retry transient failures, and validate."""
    count = client.responses.input_tokens.count(**request)
    input_tokens = count.input_tokens
    if input_tokens > settings.max_input_tokens:
        raise ValueError(
            f"Input has {input_tokens} tokens; limit is {settings.max_input_tokens}"
        )
    per_attempt = (
        input_tokens * settings.input_usd_per_million
        + settings.max_output_tokens * settings.output_usd_per_million
    ) / Decimal(1_000_000)
    reservation = per_attempt * (settings.max_retries + 1)
    record(
        "budget_checked",
        input_tokens=input_tokens,
        reserved_usd=str(reservation),
        approved_budget_usd=str(budget_usd),
        reservation_accepted=reservation <= budget_usd,
    )
    if reservation > budget_usd:
        raise ValueError(
            f"Maximum estimated cost is ${reservation}; budget is ${budget_usd}"
        )

    for attempt in range(1, settings.max_retries + 2):
        record("attempt_started", attempt=attempt, reserved_usd=str(per_attempt))
        started = time.monotonic()
        try:
            response = client.responses.create(
                **request,
                max_output_tokens=settings.max_output_tokens,
                store=False,
            )
        except (APIConnectionError, APIStatusError) as error:
            status = getattr(error, "status_code", None)
            retryable = isinstance(error, APIConnectionError) or (
                status in {408, 409, 429} or (status is not None and status >= 500)
            )
            retry = retryable and attempt <= settings.max_retries
            record(
                "retry_warning" if retry else "api_failed",
                attempt=attempt,
                error_type=type(error).__name__,
                status_code=status,
                request_id=getattr(error, "request_id", None),
                elapsed_seconds=time.monotonic() - started,
                warning="Usage is unknown; the attempt reservation remains charged.",
            )
            if not retry:
                raise
            time.sleep(1)
            continue

        usage = response.usage.model_dump() if response.usage is not None else None
        record(
            "response_received",
            attempt=attempt,
            response_id=response.id,
            request_id=response._request_id,
            model=response.model,
            response_status=response.status,
            usage=usage,
            elapsed_seconds=time.monotonic() - started,
        )
        if response.status != "completed":
            raise ValueError(f"Response {response.id} is {response.status}")
        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise ValueError(f"Response {response.id} was refused")
        return response_model.model_validate_json(response.output_text)
    raise AssertionError("Bounded attempts must return or raise")
