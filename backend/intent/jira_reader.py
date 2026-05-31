"""Read change intent from a Jira ticket.

Credentials and the Jira base URL are read from the environment so nothing is
baked into the code. There is no mock/offline mode: if Jira is unreachable or
misconfigured, a descriptive exception is raised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from jira import JIRA
from jira.exceptions import JIRAError


class JiraConfigError(RuntimeError):
    """Raised when required Jira configuration is missing from the environment."""


class JiraFetchError(RuntimeError):
    """Raised when a ticket cannot be fetched from Jira."""


@dataclass
class JiraTicket:
    """A minimal, source-agnostic view of a Jira ticket."""

    ticket_id: str
    summary: str
    description: str
    comments: list[str] = field(default_factory=list)


class JiraReader:
    """Thin wrapper around the Jira client that reads config from the environment.

    Required environment variables:

    * ``JIRA_URL``      - base URL of the Jira instance
    * ``JIRA_EMAIL``    - account email used for basic auth
    * ``JIRA_API_TOKEN``- API token used for basic auth
    """

    def __init__(
        self,
        url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self.url = url or os.getenv("JIRA_URL")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")

        missing = [
            name
            for name, value in (
                ("JIRA_URL", self.url),
                ("JIRA_EMAIL", self.email),
                ("JIRA_API_TOKEN", self.api_token),
            )
            if not value
        ]
        if missing:
            raise JiraConfigError(
                "Missing required Jira environment variables: "
                + ", ".join(missing)
            )

        try:
            self._client = JIRA(
                server=self.url,
                basic_auth=(self.email, self.api_token),
            )
        except JIRAError as exc:
            raise JiraFetchError(
                f"Failed to connect to Jira at {self.url}: {exc.text or exc}"
            ) from exc

    def fetch_ticket(self, ticket_id: str) -> JiraTicket:
        """Fetch a single ticket and return a :class:`JiraTicket`."""

        try:
            issue = self._client.issue(ticket_id)
        except JIRAError as exc:
            raise JiraFetchError(
                f"Failed to fetch Jira ticket '{ticket_id}': {exc.text or exc}"
            ) from exc

        fields = issue.fields
        comments = [
            comment.body
            for comment in getattr(getattr(fields, "comment", None), "comments", [])
            if getattr(comment, "body", None)
        ]

        return JiraTicket(
            ticket_id=ticket_id,
            summary=fields.summary or "",
            description=fields.description or "",
            comments=comments,
        )


def extract_raw_text(ticket: JiraTicket) -> str:
    """Flatten a ticket's summary, description, and comments into one string."""

    parts: list[str] = [f"Summary: {ticket.summary}"]
    if ticket.description:
        parts.append(f"Description:\n{ticket.description}")
    for index, comment in enumerate(ticket.comments, start=1):
        parts.append(f"Comment {index}:\n{comment}")
    return "\n\n".join(parts)
