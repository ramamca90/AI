# Certificate expiry

## Symptoms
TLS handshake failures appear suddenly across clients at a round time, with errors such as
"certificate has expired" or "x509: certificate has expired or is not yet valid". Traffic drops
to zero on the affected listener with no deploy nearby.

## Diagnose
Check the expiry date of the certificate actually served by the endpoint, not the one in the
secret store. Look for a failed renewal job or a load balancer that was not reloaded after
renewal.

## Mitigate
Renew or reissue the certificate, install it, and reload the listener. A rollback will not help,
since the failure comes from time passing and not from code. A restart helps only when the service
holds an old certificate in memory.

## Verify
A handshake from outside the network shows the new expiry date, and error rate returns to
baseline. Add expiry monitoring with alerts at 30 and 7 days.
