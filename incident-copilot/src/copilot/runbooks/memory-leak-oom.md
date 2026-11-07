# Memory leak and OOM kills

## Symptoms
Containers restart with exit code 137 or OOMKilled. Memory climbs steadily and resets at each
restart in a sawtooth pattern. Garbage collection time rises before each kill, and heap errors such
as OutOfMemoryError may appear in logs.

## Diagnose
Separate a leak from undersized limits. A leak grows with work done and never levels off, while a
limit that is too small fails soon after startup at a stable level. Check whether growth started
with a deploy, a config change or a new traffic pattern. Capture a heap dump before restarting if
the pod is still responsive.

## Mitigate
Restart the service to clear the leaked memory. This buys hours, not a fix. If a recent release
introduced the growth, roll back instead. Adding replicas spreads load and only slows the leak.

## Verify
Memory drops to its normal baseline and restart counts stop rising. Keep watching the growth slope
for at least an hour, and open a follow-up to fix the leak.
