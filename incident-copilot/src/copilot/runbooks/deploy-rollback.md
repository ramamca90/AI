# Deploy rollback

## When to use
A release correlates with a new error class or a jump in error rate. Check that the error first
appears after the deploy finished and that the affected code path changed in that release. A
rollback is the default mitigation for a bad deploy: restore service first, then fix forward.

## Confirm the bad release
Compare error rate and p99 latency for the 15 minutes before and after the deploy timestamp.
Look for stack traces that only exist on the new version. If errors started before the deploy,
the release is probably not the cause and a rollback will not help.

## Choose the target
Roll back to the last version that ran healthy under normal traffic, usually the previous
release. Do not choose a version older than the newest schema migration it can read. Check that
the target is not the version already running.

## Verify
After rollback, error rate should return to the pre-deploy baseline within 5 minutes. Confirm
that the new stack traces have stopped. Keep the failed version blocked in the pipeline until a
fix ships.
