# Database connection pool exhaustion

## Symptoms
Application logs show HikariCP errors such as "Connection is not available, request timed out".
Requests queue, p99 latency climbs to the pool checkout timeout, and in-use connections sit at
the pool maximum with pending threads above zero.

## Diagnose
Check whether demand or a leak fills the pool. If requests per second rose in step with in-use
connections and the database has headroom, this is a capacity problem. If in-use connections stay
at the maximum after traffic falls, or grow without a traffic increase, suspect a connection leak
or a slow query holding connections.

## Mitigate capacity pressure
Scale the service out. Each replica adds its own pool, so check that total connections stay under
the database max_connections limit: replicas times pool size should remain below about 80 percent
of it. Do not raise pool size first, because that only moves the queue to the database.

## Mitigate a leak
Restart the service to release leaked connections, one replica at a time. This buys time only.
Enable leak detection and open a follow-up for the code path that fails to close connections.

## Verify
Pending threads return to zero and in-use connections stop hitting the maximum. Timeouts disappear
from the logs.
