# Downstream timeouts

## Symptoms
Errors name a dependency: read timeouts, connection resets, circuit breaker open, HTTP 503 or 504
from an upstream client. Latency on the calling service tracks the dependency's latency.

## Diagnose
Find the first service in the call chain that became slow. Check that dependency's own error rate,
saturation and recent deploys. Retries from callers can multiply load on a struggling dependency.

## Mitigate
Fix the failing dependency first. Scaling or restarting the caller rarely helps and can add retry
load. Confirm circuit breakers are open and fallbacks are serving. If the dependency is external,
degrade the feature and contact the vendor.

## Verify
Dependency latency returns to baseline, circuit breakers close, and caller error rate recovers.
