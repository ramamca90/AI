"""Simulated production for demos, tests and evals: scenarios, telemetry and an actuator."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from copilot.domain.models import Alert

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class ScenarioNotFoundError(LookupError):
    """No scenario has that name."""


class Scenario(BaseModel):
    """One simulated incident.

    `expected` is the answer key for evals, so it must never reach a prompt. `script` drives
    `ScriptedLLM`. `Alert.scenario` arrives from the webhook, which is why names are checked
    against the scenario directory and never joined onto a path.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    alert: Alert
    services: list[str]
    logs: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    metrics: dict[str, dict[str, list[dict[str, Any]]]] = Field(default_factory=dict)
    deploys: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    expected: dict[str, Any]
    script: dict[str, list[dict[str, Any]]]


def list_scenarios() -> list[str]:
    return sorted(path.stem for path in SCENARIO_DIR.glob("*.json"))


def load_scenario(name: str) -> Scenario:
    if name not in list_scenarios():
        raise ScenarioNotFoundError(f"unknown scenario {name!r}; available: {list_scenarios()}")
    return Scenario.model_validate_json((SCENARIO_DIR / f"{name}.json").read_bytes())


class FixtureTelemetry:
    """Implements `Telemetry` over a scenario. Returns copies, so callers can't alter fixtures."""

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario

    async def search_logs(self, service: str, query: str, limit: int = 50) -> list[dict[str, Any]]:
        terms = [term for term in re.split(r"[\s|,]+", query.lower()) if term]
        matches = [
            dict(record)
            for record in self._scenario.logs.get(service, [])
            if not terms or any(term in str(record.get("message", "")).lower() for term in terms)
        ]
        matches.sort(key=lambda r: (str(r["timestamp"]), str(r["ref"])), reverse=True)
        return matches[:limit]

    async def query_metric(self, service: str, metric: str) -> list[dict[str, Any]]:
        series = self._scenario.metrics.get(service, {}).get(metric, [])
        return [dict(point) for point in series]

    async def recent_deploys(self, service: str) -> list[dict[str, Any]]:
        return [dict(deploy) for deploy in self._scenario.deploys.get(service, [])]

    async def list_services(self) -> list[str]:
        return sorted(self._scenario.services)


class FixtureActuator:
    """Implements `Actuator` in memory. `actions` records what was done, in order."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []

    async def rollback(self, service: str, target_version: str) -> str:
        self.actions.append(
            {"action": "rollback_deploy", "service": service, "target_version": target_version}
        )
        return f"rolled back {service} to {target_version}"

    async def restart(self, service: str) -> str:
        self.actions.append({"action": "restart_service", "service": service})
        return f"restarted {service}"

    async def scale(self, service: str, replicas: int) -> str:
        self.actions.append({"action": "scale_service", "service": service, "replicas": replicas})
        return f"scaled {service} to {replicas} replicas"
