"""FastAPI application exposing the multi-contract reconciliation engine.

Different teams register their own schema contracts and reconcile against them.
Nothing about any particular customer's config is hardcoded here -- the contract
drives parsing, diffing, integrity, and decisions.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import asdict, replace

import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from typing import Literal

from schema.contract_models import SchemaContract
from schema.contract_loader import load_contract, validate_contract
from parser.generic_parser import parse_file
from intent.ai_extractor import AIExtractor, AIExtractionError, IntentSummary
from intent.diff_reader import extract_csv_changes, parse_git_diff
from intent.jira_reader import (
    JiraConfigError,
    JiraFetchError,
    JiraReader,
    extract_raw_text,
)
from agent.reconciler import Reconciler
from agent.snapshot import (
    SnapshotError,
    list_snapshots,
    load_decisions,
    load_snapshot,
    record_decision,
    save_snapshot,
)
from api import contract_store
from api import creation_store
from api.creation_serializers import result_to_dict, session_to_dict
from creation.creation_pipeline import finalize_creation, run_creation
from creation.input_collector import HumanInputValidationError, apply_human_inputs


API_VERSION = "0.1.0"

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("config_reconciler.api")


# ---------------------------------------------------------------------------
# Structured errors
# ---------------------------------------------------------------------------

_STATUS_BY_CODE = {
    "CONTRACT_INVALID": 400,
    "CONTRACT_NOT_FOUND": 404,
    "PARSE_ERROR": 400,
    "JIRA_FETCH_FAILED": 502,
    "DIFF_PARSE_ERROR": 400,
    "AI_EXTRACTION_FAILED": 502,
    "RECONCILE_FAILED": 500,
    "SNAPSHOT_NOT_FOUND": 404,
    "CREATION_SESSION_NOT_FOUND": 404,
    "GAP_ANALYSIS_FAILED": 400,
    "PLAN_INVALID": 400,
    "REREVIEW_REJECTED": 422,
    "HUMAN_INPUT_INVALID": 400,
    "INTERNAL_ERROR": 500,
}

_MESSAGE_BY_CODE = {
    "CONTRACT_INVALID": "The schema contract is invalid",
    "CONTRACT_NOT_FOUND": "The requested contract was not found",
    "PARSE_ERROR": "A config file could not be parsed",
    "JIRA_FETCH_FAILED": "Failed to fetch the Jira ticket",
    "DIFF_PARSE_ERROR": "The diff could not be parsed",
    "AI_EXTRACTION_FAILED": "AI intent extraction failed",
    "RECONCILE_FAILED": "Reconciliation failed",
    "SNAPSHOT_NOT_FOUND": "The requested snapshot was not found",
    "CREATION_SESSION_NOT_FOUND": "The creation session was not found",
    "GAP_ANALYSIS_FAILED": "Gap analysis failed",
    "PLAN_INVALID": "The merge plan is invalid",
    "REREVIEW_REJECTED": "Re-review rejected the merged output",
    "HUMAN_INPUT_INVALID": "Human input validation failed",
    "INTERNAL_ERROR": "An unexpected error occurred",
}


class APIException(Exception):
    """Domain error carrying a structured error code and detail."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = _STATUS_BY_CODE.get(code, 500)


app = FastAPI(title="Config Reconciler", version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(code: str, detail: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": _MESSAGE_BY_CODE.get(code, "Error"),
            "detail": detail,
            "code": code,
        },
    )


@app.exception_handler(APIException)
async def handle_api_exception(_: Request, exc: APIException) -> JSONResponse:
    if exc.status >= 500:
        logger.error("APIException %s: %s", exc.code, exc.detail)
        traceback.print_exc(file=sys.stderr)
    return _error_response(exc.code, exc.detail, exc.status)


@app.exception_handler(Exception)
async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc)
    traceback.print_exc(file=sys.stderr)
    return _error_response("INTERNAL_ERROR", str(exc), 500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_contract_text(yaml_text: str) -> SchemaContract:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise APIException("CONTRACT_INVALID", f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise APIException("CONTRACT_INVALID", "Contract must be a YAML mapping")
    try:
        return SchemaContract.model_validate(data)
    except ValidationError as exc:
        raise APIException("CONTRACT_INVALID", str(exc)) from exc


def _load_registered_contract(name: str, version: str | None = None) -> SchemaContract:
    path = contract_store.get_contract(name, version)
    if path is None:
        raise APIException(
            "CONTRACT_NOT_FOUND",
            f"No contract registered under name '{name}'"
            + (f" version '{version}'" if version else ""),
        )
    try:
        return load_contract(path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured error
        raise APIException(
            "CONTRACT_INVALID", f"Stored contract '{name}' is invalid: {exc}"
        ) from exc


async def _read_upload(upload: UploadFile) -> str:
    raw = await upload.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise APIException(
            "PARSE_ERROR",
            f"File '{upload.filename}' is not valid UTF-8 text",
        ) from exc


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": API_VERSION}


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@app.post("/contracts")
async def upload_contract(file: UploadFile = File(...)) -> dict:
    yaml_text = await _read_upload(file)
    contract = _parse_contract_text(yaml_text)
    warnings = validate_contract(contract)
    path = contract_store.save_contract(
        contract.contract_name, contract.version, yaml_text
    )
    return {
        "name": contract.contract_name,
        "version": contract.version,
        "section_count": len(contract.sections),
        "warnings": warnings,
        "stored_at": str(path),
    }


@app.get("/contracts")
async def get_contracts() -> list[dict]:
    return [
        {
            "name": item["name"],
            "version": item["version"],
            "section_count": item["section_count"],
        }
        for item in contract_store.list_contracts()
    ]


@app.get("/contracts/{name}")
async def get_contract_structure(name: str) -> dict:
    contract = _load_registered_contract(name)
    return contract.model_dump()


@app.post("/contracts/{name}/validate")
async def validate_registered_contract(name: str) -> dict:
    contract = _load_registered_contract(name)
    return {
        "name": contract.contract_name,
        "version": contract.version,
        "warnings": validate_contract(contract),
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@app.post("/reconcile")
async def reconcile(
    contract_name: str = Form(...),
    jira_ticket_id: str | None = Form(None),
    diff_text: str | None = Form(None),
    base_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
) -> dict:
    contract = _load_registered_contract(contract_name)

    base_text = await _read_upload(base_file)
    new_text = await _read_upload(new_file)

    # Validate that both files parse against the contract up front so we can
    # surface a clean PARSE_ERROR rather than a generic reconcile failure.
    try:
        parse_file(base_text, contract)
        parse_file(new_text, contract)
    except Exception as exc:  # noqa: BLE001
        raise APIException("PARSE_ERROR", f"Failed to parse config file: {exc}") from exc

    diff_hunks = []
    declared_changes = []
    if diff_text:
        try:
            diff_hunks = parse_git_diff(diff_text)
            declared_changes = extract_csv_changes(diff_hunks, contract)
        except Exception as exc:  # noqa: BLE001
            raise APIException("DIFF_PARSE_ERROR", str(exc)) from exc

    # Diff-only mode: with no ticket and no diff, intent is empty and every
    # change is undeclared (so it escalates / blocks rather than auto-applies).
    intent = IntentSummary()
    if jira_ticket_id:
        try:
            ticket = JiraReader().fetch_ticket(jira_ticket_id)
            jira_text = extract_raw_text(ticket)
        except (JiraConfigError, JiraFetchError) as exc:
            raise APIException("JIRA_FETCH_FAILED", str(exc)) from exc
        try:
            intent = AIExtractor().extract_intent(jira_text, diff_hunks, contract)
        except AIExtractionError as exc:
            raise APIException("AI_EXTRACTION_FAILED", str(exc)) from exc

    try:
        report = Reconciler().reconcile(
            base_text, new_text, intent, declared_changes, contract
        )
    except Exception as exc:  # noqa: BLE001
        raise APIException("RECONCILE_FAILED", str(exc)) from exc

    try:
        save_snapshot(report, base_text)
    except SnapshotError as exc:
        # Persisting is best-effort; do not fail the request, but log it.
        logger.error("Failed to persist snapshot: %s", exc)

    return asdict(report)


# ---------------------------------------------------------------------------
# Snapshots & decisions
# ---------------------------------------------------------------------------


@app.get("/snapshots")
async def get_snapshots() -> list[dict]:
    return list_snapshots()


@app.get("/snapshots/{deployment_id}")
async def get_snapshot(deployment_id: str) -> dict:
    try:
        report, base_text = load_snapshot(deployment_id)
    except SnapshotError as exc:
        raise APIException("SNAPSHOT_NOT_FOUND", str(exc)) from exc
    return {
        "deployment_id": deployment_id,
        "report": asdict(report),
        "base_text": base_text,
        "decisions": load_decisions(deployment_id),
    }


class ApplyAction(BaseModel):
    action: Literal["approve", "reject"]


@app.post("/apply/{deployment_id}/{finding_id}")
async def apply_decision(
    deployment_id: str,
    finding_id: str,
    body: ApplyAction,
) -> dict:
    try:
        report, _ = load_snapshot(deployment_id)
    except SnapshotError as exc:
        raise APIException("SNAPSHOT_NOT_FOUND", str(exc)) from exc

    if not any(finding.finding_id == finding_id for finding in report.findings):
        raise APIException(
            "SNAPSHOT_NOT_FOUND",
            f"Finding '{finding_id}' not found in snapshot '{deployment_id}'",
        )

    try:
        record = record_decision(deployment_id, finding_id, body.action)
    except SnapshotError as exc:
        raise APIException("SNAPSHOT_NOT_FOUND", str(exc)) from exc

    return {"deployment_id": deployment_id, **record}


# ---------------------------------------------------------------------------
# Creation pipeline
# ---------------------------------------------------------------------------


class HumanInputsBody(BaseModel):
    inputs: dict[str, dict[str, str]]


class FinalizeBody(BaseModel):
    approvals: list[str]


@app.post("/create/analyze")
async def analyze_creation(
    contract_name: str = Form(...),
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
    jira_ticket_id: str | None = Form(None),
    diff_text: str | None = Form(None),
) -> dict:
    contract = _load_registered_contract(contract_name)

    old_text = await _read_upload(old_file)
    new_text = await _read_upload(new_file)

    try:
        parse_file(old_text, contract)
        parse_file(new_text, contract)
    except Exception as exc:  # noqa: BLE001
        raise APIException("GAP_ANALYSIS_FAILED", f"Failed to parse config: {exc}") from exc

    jira_intent = None
    diff_changes = None
    diff_hunks = []
    if diff_text:
        try:
            diff_hunks = parse_git_diff(diff_text)
            diff_changes = extract_csv_changes(diff_hunks, contract)
        except Exception as exc:  # noqa: BLE001
            raise APIException("DIFF_PARSE_ERROR", str(exc)) from exc

    if jira_ticket_id:
        try:
            ticket = JiraReader().fetch_ticket(jira_ticket_id)
            jira_text = extract_raw_text(ticket)
        except (JiraConfigError, JiraFetchError) as exc:
            raise APIException("JIRA_FETCH_FAILED", str(exc)) from exc
        try:
            jira_intent = AIExtractor().extract_intent(
                jira_text, diff_hunks if diff_text else [], contract
            )
        except AIExtractionError as exc:
            raise APIException("AI_EXTRACTION_FAILED", str(exc)) from exc

    try:
        session = run_creation(
            old_text,
            new_text,
            contract,
            jira_intent=jira_intent,
            diff_changes=diff_changes,
        )
    except Exception as exc:  # noqa: BLE001
        raise APIException("GAP_ANALYSIS_FAILED", str(exc)) from exc

    creation_store.save_session(session)
    return session_to_dict(session)


@app.post("/create/{session_id}/inputs")
async def submit_creation_inputs(session_id: str, body: HumanInputsBody) -> dict:
    stored = creation_store.get_session(session_id)
    if stored is None:
        raise APIException(
            "CREATION_SESSION_NOT_FOUND",
            f"No creation session '{session_id}'",
        )

    session = stored.session
    if session.state == "BLOCKED":
        raise APIException("PLAN_INVALID", "Session is blocked and cannot accept input")

    try:
        updated = apply_human_inputs(session.plan, body.inputs, session.contract)
    except HumanInputValidationError as exc:
        raise APIException("HUMAN_INPUT_INVALID", str(exc)) from exc

    session = replace(
        session,
        plan=updated,
        state=(
            "AWAITING_APPROVAL"
            if not updated.human_inputs_needed
            else "AWAITING_HUMAN_INPUT"
        ),
    )
    creation_store.update_session(session)
    creation_store.set_submitted_inputs(session_id, body.inputs)
    return session_to_dict(session)


@app.post("/create/{session_id}/finalize")
async def finalize_creation_endpoint(
    session_id: str,
    body: FinalizeBody,
) -> dict:
    stored = creation_store.get_session(session_id)
    if stored is None:
        raise APIException(
            "CREATION_SESSION_NOT_FOUND",
            f"No creation session '{session_id}'",
        )

    session = stored.session
    if session.state == "BLOCKED":
        raise APIException("PLAN_INVALID", "Session is blocked")

    result = finalize_creation(
        session,
        human_inputs=stored.submitted_inputs or None,
        approvals=set(body.approvals),
    )

    creation_store.set_result(session_id, result)

    download_url = None
    if result.verdict == "ACCEPTED":
        download_url = f"/create/{session_id}/download"

    return result_to_dict(result, download_url=download_url)


@app.get("/create/{session_id}/download")
async def download_merged(session_id: str):
    from fastapi.responses import PlainTextResponse

    stored = creation_store.get_session(session_id)
    if stored is None or stored.result is None:
        raise APIException(
            "CREATION_SESSION_NOT_FOUND",
            f"No creation session '{session_id}'",
        )

    if stored.result.verdict != "ACCEPTED" or not stored.result.merged_text:
        raise APIException(
            "REREVIEW_REJECTED",
            "Merged file is only available for ACCEPTED sessions",
        )

    return PlainTextResponse(
        content=stored.result.merged_text,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}-merged.cfg"'
        },
    )
