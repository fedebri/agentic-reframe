"""One OpenAI Responses integration with explicit budget reservation and retries."""

import time
from collections.abc import Callable
from decimal import Decimal
from typing import TypeVar

from openai import APIConnectionError, APIStatusError, OpenAI

from .config import ModelSettings
from .schemas import AgentResponse

ResponseT = TypeVar("ResponseT", bound=AgentResponse)


def generate_response(
    client: OpenAI,
    request: dict,
    settings: ModelSettings,
    budget_usd: Decimal,
    record: Callable[..., None],
    *,
    response_model: type[ResponseT],
) -> ResponseT:
    """Count the exact request, reserve retry costs, then validate a response.

    SDK retries must be disabled on the supplied client. Unknown failed-attempt
    usage consumes a full reservation. Rates are configured estimates, not a
    provider-side billing cap. Invalid content/refusals are not retried.
    """
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
    total_reservation = per_attempt * (settings.max_retries + 1)
    record(
        "budget_checked",
        input_tokens=input_tokens,
        reserved_usd=str(total_reservation),
        budget_usd=str(budget_usd),
    )
    if total_reservation > budget_usd:
        raise ValueError(
            f"Maximum estimated cost including retries is ${total_reservation}; "
            f"budget is ${budget_usd}. No generation request sent."
        )
    for attempt in range(1, settings.max_retries + 2):
        record("attempt_started", attempt=attempt, reserved_usd=str(per_attempt))
        started = time.monotonic()
        try:
            response = client.responses.create(
                **request,
                max_output_tokens=settings.max_output_tokens,
                store=False,
                service_tier="default",
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
                usage=None,
                reserved_usd=str(per_attempt),
                warning="Usage unknown; retain full attempt reservation.",
            )
            if not retry:
                raise
            # A single short bounded retry; avoid SDK retries multiplying attempts.
            time.sleep(1)
            continue

        usage = response.usage.model_dump() if response.usage is not None else None
        estimated_cost = None
        if response.usage is not None:
            estimated_cost = str(
                (
                    response.usage.input_tokens * settings.input_usd_per_million
                    + response.usage.output_tokens * settings.output_usd_per_million
                )
                / Decimal(1_000_000)
            )
        # Save usage/status before parsing, including incomplete or malformed output.
        # Do not persist the full API response: it can contain reasoning items.
        record(
            "response_received",
            attempt=attempt,
            response_id=response.id,
            request_id=response._request_id,
            model=response.model,
            response_status=response.status,
            usage=usage,
            estimated_cost_usd=estimated_cost,
            elapsed_seconds=time.monotonic() - started,
        )
        if response.status != "completed":
            raise ValueError(
                f"Response {response.id} is {response.status}; not accepted"
            )
        if any(
            part.type == "refusal"
            for item in response.output
            if item.type == "message"
            for part in item.content
        ):
            raise ValueError(f"Response {response.id} was refused; not accepted")
        result = response_model.model_validate_json(response.output_text)
        for claim in result.takeaways:
            if set(claim.evidence_refs) != {"brief"}:
                raise ValueError(
                    f"Claim {claim.takeaway_id}: only brief is assigned evidence"
                )
        return result
    raise AssertionError("Unreachable: bounded attempts must return or raise")
