"""Extract declared change intent with Claude, guided by the schema contract.

The system prompt is assembled at runtime from the contract's sections (name,
description, id_column) so the model can map ticket/diff language onto the right
sections without any customer-specific term being hardcoded in this file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from anthropic import Anthropic, APIError

from schema.contract_models import SchemaContract
from .diff_reader import DiffHunk


MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048


class AIExtractionError(RuntimeError):
    """Raised when intent extraction fails (config, API, or response parsing)."""


@dataclass
class IntentSummary:
    """Structured, contract-mapped summary of what a change declares.

    Each declared item is a dict of the form
    ``{"section": str, "row_hint": str, "confidence": "clear" | "unclear"}``.
    """

    declared_additions: list[dict] = field(default_factory=list)
    declared_removals: list[dict] = field(default_factory=list)
    declared_modifications: list[dict] = field(default_factory=list)
    affected_sections: list[str] = field(default_factory=list)
    raw_summary: str = ""


class AIExtractor:
    """Wraps the Anthropic Claude API for contract-driven intent extraction."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise AIExtractionError(
                "Missing required environment variable: ANTHROPIC_API_KEY"
            )
        self.model = model
        self._client = Anthropic(api_key=self.api_key)

    def extract_intent(
        self,
        jira_text: str,
        diff_hunks: list[DiffHunk],
        contract: SchemaContract,
    ) -> IntentSummary:
        """Extract a contract-mapped :class:`IntentSummary` from ticket + diff."""

        system_prompt = self._build_system_prompt(contract)
        user_prompt = self._build_user_prompt(jira_text, diff_hunks)

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except APIError as exc:
            raise AIExtractionError(
                f"Anthropic API call failed: {exc}"
            ) from exc

        raw_text = self._response_text(response)
        payload = self._parse_json(raw_text)
        return self._to_summary(payload)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt(contract: SchemaContract) -> str:
        section_lines = []
        for section in contract.sections:
            description = section.description.strip() or "(no description provided)"
            section_lines.append(
                f"- name: {section.name}\n"
                f"  id_column: {section.id_column}\n"
                f"  meaning: {description}"
            )
        sections_block = "\n".join(section_lines)
        valid_sections = ", ".join(section.name for section in contract.sections)

        return (
            "You extract the DECLARED configuration-change intent from a Jira "
            "ticket and an optional code diff. You are working with a config "
            f"described by the schema contract '{contract.contract_name}'.\n\n"
            "The configuration is organized into these sections. Map the "
            "ticket's language onto these section names using their meaning:\n"
            f"{sections_block}\n\n"
            "Rules:\n"
            "1. Only extract what is EXPLICITLY stated. Never infer, assume, or "
            "invent changes that are not clearly described.\n"
            "2. Map every change to one of these section names exactly: "
            f"{valid_sections}. If you cannot confidently map a change to a "
            "section, set its section to null and its confidence to \"unclear\".\n"
            "3. If a change is ambiguous or only implied, mark its confidence as "
            "\"unclear\". Otherwise use \"clear\".\n"
            "4. Respond with JSON ONLY. No prose, no markdown fences, no comments.\n\n"
            "Output exactly this JSON shape:\n"
            "{\n"
            '  "declared_additions": [ {"section": string|null, "row_hint": string, "confidence": "clear"|"unclear"} ],\n'
            '  "declared_removals": [ {"section": string|null, "row_hint": string, "confidence": "clear"|"unclear"} ],\n'
            '  "declared_modifications": [ {"section": string|null, "row_hint": string, "confidence": "clear"|"unclear"} ],\n'
            '  "affected_sections": [ string ],\n'
            '  "raw_summary": string\n'
            "}"
        )

    @staticmethod
    def _build_user_prompt(jira_text: str, diff_hunks: list[DiffHunk]) -> str:
        diff_block_lines: list[str] = []
        for index, hunk in enumerate(diff_hunks, start=1):
            diff_block_lines.append(f"Hunk {index} (file: {hunk.filename}):")
            for line in hunk.removed_lines:
                diff_block_lines.append(f"  - {line}")
            for line in hunk.added_lines:
                diff_block_lines.append(f"  + {line}")
        diff_block = "\n".join(diff_block_lines) or "(no diff provided)"

        return (
            "JIRA TICKET TEXT:\n"
            f"{jira_text or '(no ticket text provided)'}\n\n"
            "DIFF HUNKS:\n"
            f"{diff_block}\n\n"
            "Extract the declared intent as JSON following the system rules."
        )

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _response_text(response) -> str:
        parts = [
            block.text
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        text = "".join(parts).strip()
        if not text:
            raise AIExtractionError("Anthropic response contained no text content")
        return text

    @staticmethod
    def _parse_json(raw_text: str) -> dict:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # The model occasionally wraps JSON in prose or code fences; recover
            # the outermost JSON object before giving up.
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw_text[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise AIExtractionError(
                        f"Could not parse JSON from model response: {exc}"
                    ) from exc
            raise AIExtractionError(
                "Model response did not contain a JSON object"
            )

    @staticmethod
    def _to_summary(payload: dict) -> IntentSummary:
        if not isinstance(payload, dict):
            raise AIExtractionError("Model response JSON was not an object")
        return IntentSummary(
            declared_additions=payload.get("declared_additions", []) or [],
            declared_removals=payload.get("declared_removals", []) or [],
            declared_modifications=payload.get("declared_modifications", []) or [],
            affected_sections=payload.get("affected_sections", []) or [],
            raw_summary=payload.get("raw_summary", "") or "",
        )
