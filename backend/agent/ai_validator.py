"""Secondary, AI-assisted validation of individual findings.

The validator uses the contract's column ``data_type`` hints to look for genuine
data anomalies (malformed IPs, out-of-range or colliding ports, invalid enum
values) and asks Claude for a conservative note. It only *adds* a note -- it
never overrides the deterministic decision produced by the reconciler.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field

from anthropic import Anthropic, APIError

from schema.contract_models import SchemaContract
from schema.contract_loader import get_section


MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024
_MAX_PORT = 65535


class AIValidationError(RuntimeError):
    """Raised when validation cannot run (config, API, or response parsing)."""


@dataclass
class ValidationNote:
    """An advisory note attached to a finding. Never changes the decision."""

    finding_id: str
    note: str
    confidence: str  # high | medium | low
    flags: list[str] = field(default_factory=list)


class AIValidator:
    """Wraps Claude to produce conservative, type-aware validation notes."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise AIValidationError(
                "Missing required environment variable: ANTHROPIC_API_KEY"
            )
        self.model = model
        self._client = Anthropic(api_key=self.api_key)

    def validate_finding(
        self,
        finding,
        section_context: list[dict],
        contract: SchemaContract,
    ) -> ValidationNote:
        """Validate one finding's row against contract data-type constraints."""

        section_def = get_section(contract, finding.section)
        if section_def is None:
            raise AIValidationError(
                f"Section '{finding.section}' is not declared in the contract"
            )

        row = finding.new_value if isinstance(finding.new_value, dict) else {}
        local_flags = _local_flags(row, section_def, section_context or [])
        constraints = _describe_constraints(section_def)

        system_prompt = (
            "You are a conservative configuration data validator. You are given "
            "a single changed row, the column type constraints for its section, "
            "and any anomalies already detected by deterministic checks.\n"
            "Flag ONLY genuine data anomalies (malformed values, out-of-range "
            "ports, port collisions, invalid enum values, suspicious IPs). If the "
            "data looks valid, say so plainly and do not invent problems.\n"
            "Respond with JSON ONLY, no prose or markdown fences, in the shape:\n"
            '{ "note": string, "confidence": "high"|"medium"|"low", "flags": [string] }'
        )
        user_prompt = (
            f"Section: {finding.section}\n"
            f"Change type: {finding.change_type}\n"
            f"Column constraints:\n{constraints}\n\n"
            f"Changed row: {json.dumps(row)}\n\n"
            f"Deterministic anomalies already found: {json.dumps(local_flags)}\n\n"
            "Provide your conservative validation note as JSON."
        )

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except APIError as exc:
            raise AIValidationError(f"Anthropic API call failed: {exc}") from exc

        payload = _parse_json(_response_text(response))

        ai_flags = payload.get("flags", []) or []
        merged_flags = list(dict.fromkeys([*local_flags, *ai_flags]))
        return ValidationNote(
            finding_id=finding.finding_id,
            note=str(payload.get("note", "")),
            confidence=str(payload.get("confidence", "low")),
            flags=merged_flags,
        )


# ---------------------------------------------------------------------------
# Deterministic, contract-data-type-driven checks
# ---------------------------------------------------------------------------


def _local_flags(
    row: dict,
    section_def,
    section_context: list[dict],
) -> list[str]:
    flags: list[str] = []

    for column in section_def.columns:
        value = row.get(column.name)
        if value in (None, ""):
            continue

        if column.data_type == "ip":
            if not _is_valid_ip(value):
                flags.append(f"{column.name}='{value}' is not a valid IP address")

        elif column.data_type == "port":
            port = _as_int(value)
            if port is None or not (0 <= port <= _MAX_PORT):
                flags.append(
                    f"{column.name}='{value}' is not a valid port (0-{_MAX_PORT})"
                )
            elif _port_collision(
                column.name, value, row, section_context, section_def.id_column
            ):
                flags.append(
                    f"{column.name}='{value}' collides with another row in the section"
                )

        elif column.data_type == "enum":
            allowed = column.enum_values or []
            if value not in allowed:
                flags.append(
                    f"{column.name}='{value}' is not in allowed values {allowed}"
                )

    return flags


def _describe_constraints(section_def) -> str:
    lines: list[str] = []
    for column in section_def.columns:
        line = f"- {column.name}: type={column.data_type}"
        if column.data_type == "enum" and column.enum_values:
            line += f", allowed={column.enum_values}"
        if column.data_type == "port":
            line += f", range=0-{_MAX_PORT}"
        lines.append(line)
    return "\n".join(lines)


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        # Accept CIDR / subnet notation as well.
        try:
            ipaddress.ip_network(value, strict=False)
            return True
        except ValueError:
            return False


def _as_int(value: str):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _port_collision(
    column_name: str,
    value,
    row: dict,
    section_context: list[dict],
    id_column: str,
) -> bool:
    """True if another row in the section uses the same port value.

    The row's own identity (per the contract's ``id_column``) is excluded so a
    row does not collide with itself when it appears in ``section_context``.
    """

    own_id = row.get(id_column)
    for other in section_context:
        if other is row:
            continue
        if own_id is not None and other.get(id_column) == own_id:
            continue
        if other.get(column_name) == value:
            return True
    return False


# ---------------------------------------------------------------------------
# Response parsing (shared shape with the intent extractor)
# ---------------------------------------------------------------------------


def _response_text(response) -> str:
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    text = "".join(parts).strip()
    if not text:
        raise AIValidationError("Anthropic response contained no text content")
    return text


def _parse_json(raw_text: str) -> dict:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw_text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AIValidationError(
                    f"Could not parse JSON from model response: {exc}"
                ) from exc
        raise AIValidationError("Model response did not contain a JSON object")
