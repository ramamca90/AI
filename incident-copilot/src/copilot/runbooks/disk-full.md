# Disk full

## Symptoms
Writes fail with "No space left on device". Databases may turn read-only, log shipping stops, and
health checks can fail. Disk used percent is above 90 and rising.

## Diagnose
Find what is growing: application logs, temp files, WAL or core dumps. Compare the growth rate to
the remaining space to estimate time to full. A sudden burst of logs usually means another
incident is producing errors.

## Mitigate
Remove rotated logs and temp files that are safe to delete. Never delete database data or WAL
files by hand. Restarting a service can release space held by deleted files that are still open.
Expand the volume if the growth is legitimate.

## Verify
Disk used percent falls below 80 and writes succeed. Fix rotation or retention so this does not
recur.
