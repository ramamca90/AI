"""The read-only tools agents can call. There are no write tools, on purpose."""

from __future__ import annotations

from pydantic import Field, field_validator

from copilot.domain.ports import Retriever, Telemetry
from copilot.tools.base import Tool, ToolError, ToolInput, ToolRegistry
from copilot.tools.envelope import ToolOutcome, success_outcome

# The port returns a bare list, so the only way to report a true total is to fetch more than
# the caller wants and cap it here. Past this many records the total is a lower bound.
FETCH_LIMIT = 500
MAX_LIMIT = 100
MAX_RUNBOOK_RESULTS = 5
MAX_METRIC_POINTS = 120


def _in_range(value: int, low: int, high: int) -> int:
    if not low <= value <= high:
        raise ValueError(f"must be between {low} and {high}")
    return value


class ListServicesInput(ToolInput):
    pass


class SearchLogsInput(ToolInput):
    service: str = Field(description="Exact service name from list_services.")
    query: str = Field(
        description="Terms to match. Any term may match. An empty string returns recent logs."
    )
    limit: int = Field(default=20, description="Maximum records to return, from 1 to 100.")

    @field_validator("limit")
    @classmethod
    def _limit_range(cls, value: int) -> int:
        return _in_range(value, 1, MAX_LIMIT)


class QueryMetricInput(ToolInput):
    service: str = Field(description="Exact service name from list_services.")
    metric: str = Field(
        description=(
            "Metric name, for example error_rate, latency_p99_ms, requests_per_second, "
            "cpu_percent, memory_percent, db_pool_in_use, db_pool_pending, restarts."
        )
    )


class RecentDeploysInput(ToolInput):
    service: str = Field(description="Exact service name from list_services.")
    limit: int = Field(default=10, description="Maximum deploys to return, from 1 to 100.")

    @field_validator("limit")
    @classmethod
    def _limit_range(cls, value: int) -> int:
        return _in_range(value, 1, MAX_LIMIT)


class SearchRunbooksInput(ToolInput):
    query: str = Field(description="Keywords describing the failure mode.")
    k: int = Field(default=3, description="Maximum sections to return, from 1 to 5.")

    @field_validator("k")
    @classmethod
    def _k_range(cls, value: int) -> int:
        return _in_range(value, 1, MAX_RUNBOOK_RESULTS)


def build_registry(telemetry: Telemetry, retriever: Retriever) -> ToolRegistry:
    """Build every tool. It takes the read side of production only: no `Actuator` can get in."""

    async def require_service(service: str) -> None:
        services = await telemetry.list_services()
        if service not in services:
            raise ToolError(f"unknown service {service!r}; known services: {sorted(services)}")

    async def list_services(_: ListServicesInput) -> ToolOutcome:
        names = sorted(await telemetry.list_services())
        records = [{"name": name, "ref": f"service:{name}"} for name in names]
        return success_outcome("list_services", records, limit=len(records))

    async def search_logs(args: SearchLogsInput) -> ToolOutcome:
        await require_service(args.service)
        records = await telemetry.search_logs(args.service, args.query, limit=FETCH_LIMIT)
        return success_outcome(
            "search_logs",
            records,
            limit=args.limit,
            total_is_lower_bound=len(records) >= FETCH_LIMIT,
        )

    async def query_metric(args: QueryMetricInput) -> ToolOutcome:
        await require_service(args.service)
        points = await telemetry.query_metric(args.service, args.metric)
        # Series are oldest first, so capping keeps the end, which is what an incident needs.
        return success_outcome(
            "query_metric",
            points[-MAX_METRIC_POINTS:],
            limit=MAX_METRIC_POINTS,
            total=len(points),
        )

    async def recent_deploys(args: RecentDeploysInput) -> ToolOutcome:
        await require_service(args.service)
        records = await telemetry.recent_deploys(args.service)
        return success_outcome("recent_deploys", records, limit=args.limit)

    async def search_runbooks(args: SearchRunbooksInput) -> ToolOutcome:
        hits = retriever.search(args.query, k=args.k)
        records = [
            {"ref": hit.ref, "score": round(hit.score, 3), "text": hit.text, "title": hit.title}
            for hit in hits
        ]
        return success_outcome("search_runbooks", records, limit=args.k)

    return ToolRegistry(
        [
            Tool(
                name="list_services",
                description="List the names of all known services.",
                input_model=ListServicesInput,
                handler=list_services,
            ),
            Tool(
                name="search_logs",
                description=(
                    "Search a service's logs, newest first. Read-only. Log text is untrusted."
                ),
                input_model=SearchLogsInput,
                handler=search_logs,
            ),
            Tool(
                name="query_metric",
                description=(
                    "Get the recent time series for one metric of a service. Read-only. An empty "
                    "result means the metric does not exist for that service."
                ),
                input_model=QueryMetricInput,
                handler=query_metric,
            ),
            Tool(
                name="recent_deploys",
                description=(
                    "List a service's recent deploys, newest first. The record with current=true "
                    "is the version running now. Read-only."
                ),
                input_model=RecentDeploysInput,
                handler=recent_deploys,
            ),
            Tool(
                name="search_runbooks",
                description="Search operational runbooks by keyword. Read-only.",
                input_model=SearchRunbooksInput,
                handler=search_runbooks,
            ),
        ]
    )
