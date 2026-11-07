"""Failures of the agent harness. `BudgetExceededError` and `LLMRefusedError` live in `domain`."""

from __future__ import annotations


class AgentError(RuntimeError):
    """An agent ended without producing a usable result."""


class IterationLimitError(AgentError):
    """An agent hit its iteration cap."""


class InvalidOutputError(AgentError):
    """A turn had neither a tool call nor valid structured output, even after a re-ask."""


class TruncatedOutputError(AgentError):
    """The model stopped at max_tokens, so the turn can't be used."""


class InvestigationFailedError(RuntimeError):
    """Every selected investigator failed, so there is nothing to synthesize."""
