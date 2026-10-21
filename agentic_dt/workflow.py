"""One exercise engine for preparation, model calls, critique, and resume."""

import json
import os
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import yaml
from openai import OpenAI

from .config import ModelConfig, ProjectConfig, load_config
from .graph import replay
from .inquiry import write_comparison
from .model import generate_structured
from .schemas import (
    AnalystResponse,
    CriticResponse,
    FrozenSource,
    HumanFrame,
    LogEvent,
    ModelSnapshot,
    PassageAnalystResponse,
    RunManifest,
)
from .sources import (
    file_sha256,
    freeze_source,
    index_passages,
    indexed_sources,
    validate_citations,
)


def validate_project(config_path: Path) -> ProjectConfig:
    """Validate configuration and every required repository input."""
    config_path = config_path.resolve()
    root = config_path.parent.parent
    config = load_config(config_path)
    required = [
        config.paths.brief,
        config.workflow.analyst_prompt,
        config.workflow.critic_prompt,
        *(exercise.source for exercise in config.exercises),
    ]
    for relative in required:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"Required file is missing: {path}")
        path.read_text(encoding="utf-8")
    return config


def _freeze_with_digest(path: Path, prefix: str, max_bytes: int) -> FrozenSource:
    provisional = freeze_source(path, prefix, max_bytes)
    return FrozenSource(
        source_id=f"{prefix}:{provisional.content_sha256[:12]}",
        source_path=provisional.source_path,
        content=provisional.content,
        content_sha256=provisional.content_sha256,
    )


def _critic_enabled(config: ProjectConfig, requested: bool) -> bool:
    policy = config.workflow.critic_policy
    if requested and policy == "disabled":
        raise ValueError("Critic is disabled by project configuration")
    return policy == "always" or (policy == "requested" and requested)


def _prepare_manifest(
    config_path: Path,
    exercise_id: str,
    run_directory: Path,
    evidence_paths: list[Path],
    critic_requested: bool,
    ledger_path_override: Path | None,
    context_claim_ids: list[str] | None,
    human_frame_path: Path | None,
) -> RunManifest:
    config_path = config_path.resolve()
    root = config_path.parent.parent
    config = validate_project(config_path)
    exercise = config.exercise(exercise_id)
    manifest_path = run_directory / "input_manifest.json"
    selected = [str((root / path).resolve()) for path in evidence_paths]
    enabled = _critic_enabled(config, critic_requested)

    if manifest_path.exists():
        manifest = RunManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.exercise_id != exercise_id:
            raise ValueError("Existing run belongs to a different exercise")
        if manifest.selected_evidence_paths != selected:
            raise ValueError("Existing run has a different evidence selection")
        if manifest.critic_enabled != enabled:
            raise ValueError("Existing run has a different critic policy")
        if human_frame_path is not None and (
            manifest.human_frame is None
            or file_sha256(root / human_frame_path)
            != manifest.human_frame.content_sha256
        ):
            raise ValueError("Independent human frame changed; prepare a new run")
        if [claim.claim_id for claim in manifest.approved_context] != (
            context_claim_ids or []
        ):
            raise ValueError("Existing run has a different prior-claim selection")
        if ledger_path_override is not None and manifest.ledger_path != str(
            ledger_path_override.resolve()
        ):
            raise ValueError("Existing run belongs to a different ledger")
        return manifest

    if exercise_id == "frame_challenge" and human_frame_path is None:
        raise ValueError(
            "Record your independent interpretation with 'frame', then supply "
            "--human-frame before preparing a framing run"
        )
    human_frame = (
        _freeze_with_digest(
            root / human_frame_path, "human-frame", config.model.max_input_bytes
        )
        if human_frame_path is not None
        else None
    )
    if human_frame is not None:
        interpretation = HumanFrame.model_validate(yaml.safe_load(human_frame.content))
        if interpretation.exercise_id != exercise_id:
            raise ValueError("Independent human frame belongs to a different exercise")

    brief = _freeze_with_digest(
        root / config.paths.brief, "brief", config.model.max_input_bytes
    )
    assigned = [brief]
    for index, selected_path in enumerate(selected, start=1):
        path = Path(selected_path)
        assigned.append(
            _freeze_with_digest(
                path,
                f"evidence:{index}:{path.stem}",
                config.model.max_input_bytes,
            )
        )
    exercise_source = _freeze_with_digest(
        root / exercise.source,
        f"method:{exercise.id}",
        config.model.max_input_bytes,
    )
    analyst_prompt = _freeze_with_digest(
        root / config.workflow.analyst_prompt,
        "prompt:analyst",
        config.model.max_input_bytes,
    )
    critic_prompt = (
        _freeze_with_digest(
            root / config.workflow.critic_prompt,
            "prompt:critic",
            config.model.max_input_bytes,
        )
        if enabled
        else None
    )
    ledger_path = (
        ledger_path_override.resolve()
        if ledger_path_override is not None
        else (root / config.paths.ledger).resolve()
    )
    state = replay(ledger_path)
    context_by_id = {claim.claim_id: claim for claim in state.context_claims()}
    selected_context_ids = context_claim_ids or []
    if len(selected_context_ids) != len(set(selected_context_ids)):
        raise ValueError("Prior context claim IDs must be distinct")
    unknown_context = set(selected_context_ids) - set(context_by_id)
    if unknown_context:
        raise ValueError(
            f"Prior context is not reviewed and usable: {sorted(unknown_context)}"
        )
    assigned_ids = {source.source_id for source in assigned}
    for claim_id in selected_context_ids:
        for source_id in context_by_id[claim_id].evidence_refs:
            if source_id not in assigned_ids:
                assigned.append(state.evidence[source_id])
                assigned_ids.add(source_id)
    model = ModelSnapshot(
        name=config.model.name,
        reasoning_effort=config.model.reasoning_effort,
        timeout_seconds=config.model.timeout_seconds,
        max_retries=config.model.max_retries,
        max_input_bytes=config.model.max_input_bytes,
        max_input_tokens=config.model.max_input_tokens,
        max_output_tokens=config.model.max_output_tokens,
        input_usd_per_million=str(config.model.input_usd_per_million),
        output_usd_per_million=str(config.model.output_usd_per_million),
    )
    manifest = RunManifest(
        schema_version=2,
        run_id=f"{exercise.id}-{uuid4().hex}",
        created_at=datetime.now(timezone.utc),
        exercise_id=exercise.id,
        exercise_order=exercise.order,
        deliverables=exercise.produces,
        critic_enabled=enabled,
        selected_evidence_paths=selected,
        sources=assigned,
        exercise_source=exercise_source,
        approved_context=[context_by_id[claim_id] for claim_id in selected_context_ids],
        analyst_prompt=analyst_prompt,
        critic_prompt=critic_prompt,
        model=model,
        ledger_path=str(ledger_path),
        human_frame=human_frame,
        citation_format="passage_ids",
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (run_directory / "status.json").write_text(
        json.dumps({"state": "prepared", "run_id": manifest.run_id}, indent=2),
        encoding="utf-8",
    )
    return manifest


def _analyst_request(manifest: RunManifest) -> dict:
    passage_ids = manifest.citation_format == "passage_ids"
    response_model = PassageAnalystResponse if passage_ids else AnalystResponse
    schema = response_model.model_json_schema()
    schema["properties"]["exercise_id"] = {
        "type": "string",
        "const": manifest.exercise_id,
    }
    claim_name = "PassageClaimDraft" if passage_ids else "ClaimDraft"
    claim = schema["$defs"][claim_name]["properties"]
    schema["$defs"][claim_name]["required"] = list(claim)
    for field in claim.values():
        field.pop("default", None)
    claim["citations"]["minItems"] = 1
    claim["deliverable"] = {
        "type": "string",
        "enum": manifest.deliverables,
    }
    claim["evidence_refs"]["items"] = {
        "type": "string",
        "enum": [source.source_id for source in manifest.sources],
    }
    if manifest.approved_context:
        claim["derived_from"]["items"] = {
            "type": "string",
            "enum": [context.claim_id for context in manifest.approved_context],
        }
    else:
        claim["derived_from"]["maxItems"] = 0
    citation_name = "PassageReference" if passage_ids else "EvidenceCitation"
    schema["$defs"][citation_name]["properties"]["source_id"] = {
        "type": "string",
        "enum": [source.source_id for source in manifest.sources],
    }
    payload = {
        "sources": (
            indexed_sources(manifest.sources)
            if passage_ids
            else [source.model_dump() for source in manifest.sources]
        ),
        "reviewed_prior_claims": [
            claim.model_dump() for claim in manifest.approved_context
        ],
    }
    request = {
        "model": manifest.model.name,
        "instructions": (
            manifest.analyst_prompt.content
            + "\n\nEXERCISE METHOD:\n"
            + manifest.exercise_source.content
            + "\n\nRequired deliverables: "
            + ", ".join(manifest.deliverables)
        ),
        "input": [{"role": "user", "content": json.dumps(payload)}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "design_research_analysis",
                "strict": True,
                "schema": schema,
            }
        },
    }
    if manifest.model.reasoning_effort is not None:
        request["reasoning"] = {"effort": manifest.model.reasoning_effort}
    if len(json.dumps(request).encode()) > manifest.model.max_input_bytes:
        raise ValueError("Analyst request exceeds the configured byte limit")
    return request


def _critic_request(
    manifest: RunManifest,
    response: AnalystResponse,
    *,
    compact_citations: bool = True,
) -> dict:
    if manifest.critic_prompt is None:
        raise ValueError("Critic context was not assigned")
    schema = CriticResponse.model_json_schema()
    schema["required"] = list(schema["properties"])
    for field in schema["properties"].values():
        field.pop("default", None)
    schema["properties"]["exercise_id"] = {
        "type": "string",
        "const": manifest.exercise_id,
    }
    payload = {
        "sources": (
            indexed_sources(manifest.sources)
            if manifest.citation_format == "passage_ids"
            else [source.model_dump() for source in manifest.sources]
        ),
        "reviewed_prior_claims": [
            claim.model_dump() for claim in manifest.approved_context
        ],
        "analyst_response": response.model_dump(),
    }
    # Every source passage is already included above; avoid repeating its full
    # quotation in each analyst claim that refers to it.
    if compact_citations and manifest.citation_format == "passage_ids":
        passages = {
            source.source_id: {
                (citation.start_line, citation.end_line): passage_id
                for passage_id, citation in index_passages(source).items()
            }
            for source in manifest.sources
        }
        for claim in payload["analyst_response"]["claims"]:
            claim["citations"] = [
                {
                    "source_id": citation["source_id"],
                    "passage_id": passages[citation["source_id"]][
                        (citation["start_line"], citation["end_line"])
                    ],
                }
                for citation in claim["citations"]
            ]
        # The saved request identifies its wire format independently of old
        # manifests, so retries retain requests already sent to the service.
        payload["citation_format"] = "passage_ids"
    request = {
        "model": manifest.model.name,
        "instructions": (
            manifest.critic_prompt.content
            + "\n\nEXERCISE METHOD:\n"
            + manifest.exercise_source.content
        ),
        "input": [{"role": "user", "content": json.dumps(payload)}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "design_research_critique",
                "strict": True,
                "schema": schema,
            }
        },
    }
    if manifest.model.reasoning_effort is not None:
        request["reasoning"] = {"effort": manifest.model.reasoning_effort}
    if len(json.dumps(request).encode()) > manifest.model.max_input_bytes:
        raise ValueError("Critic request exceeds the configured byte limit")
    return request


def _validate_analysis(manifest: RunManifest, response: AnalystResponse) -> None:
    if response.exercise_id != manifest.exercise_id:
        raise ValueError("Analyst returned the wrong exercise ID")
    assigned_evidence = {source.source_id for source in manifest.sources}
    sources = {source.source_id: source for source in manifest.sources}
    assigned_context = {claim.claim_id for claim in manifest.approved_context}
    for claim in response.claims:
        if claim.deliverable not in manifest.deliverables:
            raise ValueError(f"Unknown deliverable: {claim.deliverable}")
        if set(claim.evidence_refs) - assigned_evidence:
            raise ValueError(f"Claim {claim.local_id}: unassigned evidence")
        if not claim.citations or {c.source_id for c in claim.citations} != set(
            claim.evidence_refs
        ):
            raise ValueError(
                f"Claim {claim.local_id}: cite exact passages for each source"
            )
        validate_citations(claim.citations, sources)
        if set(claim.derived_from) - assigned_context:
            raise ValueError(f"Claim {claim.local_id}: unassigned prior claim")
    covered = {claim.deliverable for claim in response.claims}
    missing = set(manifest.deliverables) - covered
    if missing:
        raise ValueError(f"Analyst omitted deliverables: {sorted(missing)}")


def _validate_critique(
    manifest: RunManifest,
    analysis: AnalystResponse,
    critique: CriticResponse,
) -> None:
    if critique.exercise_id != manifest.exercise_id:
        raise ValueError("Critic returned the wrong exercise ID")
    if critique.next_action == "request_evidence" and not (
        critique.next_question and critique.next_question.strip()
    ):
        raise ValueError("A request for evidence must name one research question")
    claim_ids = {claim.local_id for claim in analysis.claims}
    evidence_ids = {source.source_id for source in manifest.sources}
    for issue in critique.issues:
        if issue.claim_id is not None and issue.claim_id not in claim_ids:
            raise ValueError(f"Critic referenced unknown claim {issue.claim_id}")
        if set(issue.evidence_refs) - evidence_ids:
            raise ValueError("Critic referenced unassigned evidence")


def run_exercise(
    config_path: Path,
    exercise_id: str,
    output: Path | None,
    evidence_paths: list[Path],
    critic: bool,
    live: bool,
    budget_usd: Decimal | None,
    retry_failed: bool = False,
    *,
    client: OpenAI | None = None,
    ledger_path_override: Path | None = None,
    context_claim_ids: list[str] | None = None,
    human_frame_path: Path | None = None,
) -> Path:
    """Prepare or resume one scoped run; model outputs never write the ledger."""
    config_path = config_path.resolve()
    root = config_path.parent.parent
    config = load_config(config_path)
    run_directory = (
        output.resolve()
        if output is not None
        else root / config.paths.outputs / "runs" / f"{exercise_id}-{uuid4().hex}"
    )
    manifest = _prepare_manifest(
        config_path,
        exercise_id,
        run_directory,
        evidence_paths,
        critic,
        ledger_path_override,
        context_claim_ids,
        human_frame_path,
    )
    manifest_path = run_directory / "input_manifest.json"
    manifest_hash = file_sha256(manifest_path)
    log_path = run_directory / "run_events.jsonl"
    logs = (
        [json.loads(line) for line in log_path.read_text().splitlines()]
        if log_path.exists()
        else []
    )
    current_step = "orchestrator"

    def record(event_type: str, **details) -> None:
        event = LogEvent(
            run_id=manifest.run_id,
            timestamp=datetime.now(timezone.utc),
            step=current_step,
            event_type=event_type,
            manifest_sha256=manifest_hash,
            details=details,
        )
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
        logs.append(event.model_dump(mode="json"))

    if logs and any(event["manifest_sha256"] != manifest_hash for event in logs):
        raise ValueError("Frozen input manifest changed; cannot resume")
    if not logs:
        record("prepared", critic_enabled=manifest.critic_enabled)

    analyst_request = _analyst_request(manifest)
    analyst_request_path = run_directory / "analyst_request.json"
    request_text = json.dumps(analyst_request, indent=2)
    if (
        analyst_request_path.exists()
        and analyst_request_path.read_text() != request_text
    ):
        raise ValueError("Saved analyst request changed; cannot resume")
    analyst_request_path.write_text(request_text, encoding="utf-8")

    if not live:
        return run_directory
    if budget_usd is None or not budget_usd.is_finite() or budget_usd <= 0:
        raise ValueError("Live execution requires a positive finite budget")

    reservations = sum(
        Decimal(event["details"]["reserved_usd"])
        for event in logs
        if event["event_type"] == "budget_checked"
        and event["details"].get("reservation_accepted")
    )
    if budget_usd < reservations:
        raise ValueError(f"Budget is below existing reservations ${reservations}")
    remaining = budget_usd - reservations
    status_path = run_directory / "status.json"
    analyst_path = run_directory / "analyst_response.json"
    critic_path = run_directory / "critic_response.json"

    def load_saved(path: Path, model_type, step: str):
        saved = [
            event
            for event in logs
            if event["event_type"] == "response_saved" and event["step"] == step
        ]
        if not path.exists():
            return None
        if not saved or file_sha256(path) != saved[-1]["details"]["sha256"]:
            raise ValueError(f"{step}: uncheckpointed or changed response")
        return model_type.model_validate_json(path.read_bytes())

    analysis = load_saved(analyst_path, AnalystResponse, "analyst")
    critique = load_saved(critic_path, CriticResponse, "critic")
    if analysis is not None and (not manifest.critic_enabled or critique is not None):
        previous = json.loads(status_path.read_text(encoding="utf-8"))
        state = replay(Path(manifest.ledger_path))
        recovered_state = (
            "completed"
            if manifest.run_id in state.completed_runs
            else "awaiting_review"
        )
        if previous["state"] != recovered_state:
            status_path.write_text(
                json.dumps({"state": recovered_state, "run_id": manifest.run_id}),
                encoding="utf-8",
            )
            record("status_recovered", state=recovered_state)
        write_comparison(manifest, analysis, critique, run_directory / "comparison.md")
        return run_directory

    current_context = {
        claim.claim_id: claim
        for claim in replay(Path(manifest.ledger_path)).context_claims()
    }
    if any(
        current_context.get(claim.claim_id) != claim
        for claim in manifest.approved_context
    ):
        raise ValueError("Assigned prior claims changed; prepare a fresh run")

    own_client = client is None
    if own_client and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is not set")
    settings = ModelConfig.model_validate(manifest.model.model_dump())
    status_path.write_text(
        json.dumps({"state": "running", "run_id": manifest.run_id}, indent=2),
        encoding="utf-8",
    )
    try:
        with (
            OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                max_retries=0,
                timeout=settings.timeout_seconds,
            )
            if own_client
            else nullcontext(client)
        ) as active_client:
            if analysis is None:
                current_step = "analyst"
                unfinished = any(
                    event["step"] == current_step
                    and event["event_type"] == "attempt_started"
                    for event in logs
                )
                if unfinished and not retry_failed:
                    raise ValueError(
                        "Analyst has an unfinished attempt; inspect the log and use "
                        "--retry-failed to authorize another paid call"
                    )
                draft = generate_structured(
                    active_client,
                    analyst_request,
                    settings,
                    remaining,
                    record,
                    PassageAnalystResponse
                    if manifest.citation_format == "passage_ids"
                    else AnalystResponse,
                )
                if isinstance(draft, PassageAnalystResponse):
                    draft_path = run_directory / "analyst_draft.json"
                    draft_path.write_text(
                        draft.model_dump_json(indent=2), encoding="utf-8"
                    )
                    record("draft_saved", sha256=file_sha256(draft_path))
                    passages = {
                        source.source_id: index_passages(source)
                        for source in manifest.sources
                    }
                    resolved_claims = []
                    for claim in draft.claims:
                        citations = []
                        for reference in claim.citations:
                            try:
                                citations.append(
                                    passages[reference.source_id][reference.passage_id]
                                )
                            except KeyError as error:
                                raise ValueError(
                                    f"Claim {claim.local_id}: unknown passage "
                                    f"{reference.source_id}/{reference.passage_id}"
                                ) from error
                        resolved_claims.append(
                            {
                                **claim.model_dump(exclude={"citations"}),
                                "citations": citations,
                            }
                        )
                    analysis = AnalystResponse.model_validate(
                        {**draft.model_dump(), "claims": resolved_claims}
                    )
                else:
                    analysis = draft
                _validate_analysis(manifest, analysis)
                analyst_path.write_text(
                    analysis.model_dump_json(indent=2), encoding="utf-8"
                )
                record("response_saved", sha256=file_sha256(analyst_path))
                reservations = sum(
                    Decimal(event["details"]["reserved_usd"])
                    for event in logs
                    if event["event_type"] == "budget_checked"
                    and event["details"].get("reservation_accepted")
                )
                remaining = budget_usd - reservations

            if manifest.critic_enabled and critique is None:
                current_step = "critic"
                critic_request_path = run_directory / "critic_request.json"
                compact_citations = True
                if critic_request_path.exists():
                    saved_request = json.loads(critic_request_path.read_text())
                    saved_input = json.loads(saved_request["input"][0]["content"])
                    compact_citations = (
                        saved_input.get("citation_format") == "passage_ids"
                    )
                critic_request = _critic_request(
                    manifest, analysis, compact_citations=compact_citations
                )
                critic_text = json.dumps(critic_request, indent=2)
                if (
                    critic_request_path.exists()
                    and critic_request_path.read_text() != critic_text
                ):
                    raise ValueError("Saved critic request changed; cannot resume")
                critic_request_path.write_text(critic_text, encoding="utf-8")
                unfinished = any(
                    event["step"] == current_step
                    and event["event_type"] == "attempt_started"
                    for event in logs
                )
                if unfinished and not retry_failed:
                    raise ValueError(
                        "Critic has an unfinished attempt; inspect the log and use "
                        "--retry-failed to authorize another paid call"
                    )
                critique = generate_structured(
                    active_client,
                    critic_request,
                    settings,
                    remaining,
                    record,
                    CriticResponse,
                )
                _validate_critique(manifest, analysis, critique)
                critic_path.write_text(
                    critique.model_dump_json(indent=2), encoding="utf-8"
                )
                record("response_saved", sha256=file_sha256(critic_path))

        current_step = "orchestrator"
        write_comparison(manifest, analysis, critique, run_directory / "comparison.md")
        status_path.write_text(
            json.dumps(
                {"state": "awaiting_review", "run_id": manifest.run_id}, indent=2
            ),
            encoding="utf-8",
        )
        record("awaiting_review")
        if critique is not None and critique.next_action == "request_evidence":
            record("evidence_requested", question=critique.next_question)
    except (Exception, KeyboardInterrupt) as error:
        current_step = "orchestrator"
        record("failed", error_type=type(error).__name__)
        status_path.write_text(
            json.dumps(
                {
                    "state": "failed",
                    "run_id": manifest.run_id,
                    "error_type": type(error).__name__,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise
    return run_directory
