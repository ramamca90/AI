<#
.SYNOPSIS
  End-to-end walkthrough through the gateway: register -> login -> order
  (with idempotent retry) -> async notification -> cancel.
.EXAMPLE
  ./scripts/demo.ps1                                   # local docker compose
  ./scripts/demo.ps1 -BaseUrl https://gateway.<env>.azurecontainerapps.io
#>
param([string]$BaseUrl = "http://localhost:8080")

$ErrorActionPreference = "Stop"
$correlation = "demo-" + [guid]::NewGuid().ToString("N").Substring(0, 12)
$email = "demo+" + (Get-Random) + "@example.com"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Call($method, $path, $body = $null, $headers = @{}) {
    $headers["X-Correlation-ID"] = $correlation
    $params = @{ Method = $method; Uri = "$BaseUrl$path"; Headers = $headers; ContentType = "application/json" }
    if ($null -ne $body) { $params.Body = ($body | ConvertTo-Json -Depth 5) }
    $resp = Invoke-WebRequest @params -UseBasicParsing
    Write-Host ("    {0} {1} -> {2}" -f $method, $path, $resp.StatusCode) -ForegroundColor DarkGray
    return ($resp.Content | ConvertFrom-Json)
}

Write-Host "Correlation id for this run: $correlation (search it in logs / App Insights)" -ForegroundColor Yellow

Step "Gateway health"
Call GET "/healthz" | Format-List

Step "Register $email"
$user = Call POST "/v1/auth/register" @{ email = $email; full_name = "Demo User"; password = "a-very-long-password-123" }
$user | Format-List id, email, roles

Step "Login"
$token = (Call POST "/v1/auth/token" @{ email = $email; password = "a-very-long-password-123" }).access_token
$auth = @{ Authorization = "Bearer $token" }

Step "Place an order with Idempotency-Key"
$order = @{ currency = "USD"; items = @(
    @{ sku = "KB-01"; name = "Mechanical keyboard"; quantity = 1; unit_price = "89.99" },
    @{ sku = "MS-01"; name = "Wireless mouse"; quantity = 2; unit_price = "24.50" }
) }
$key = "checkout-" + [guid]::NewGuid().ToString("N")
$first = Call POST "/v1/orders" $order (@{ Authorization = "Bearer $token"; "Idempotency-Key" = $key })
$first | Format-List id, status, total_amount, currency

Step "Retry the same request (simulated network retry) - must NOT create a second order"
$retry = Call POST "/v1/orders" $order (@{ Authorization = "Bearer $token"; "Idempotency-Key" = $key })
Write-Host ("    same order id: {0}" -f ($retry.id -eq $first.id)) -ForegroundColor Green

Step "Wait for the event to flow orders -> outbox -> bus -> notification-service"
Start-Sleep -Seconds 3
(Call GET "/v1/notifications" $null $auth).items | Format-Table title, message -AutoSize

Step "Cancel the order"
Call POST "/v1/orders/$($first.id)/cancel" @{ reason = "Changed my mind" } $auth | Format-List id, status
Start-Sleep -Seconds 3
$n = Call GET "/v1/notifications" $null $auth
Write-Host ("    notifications: {0} total, {1} unread" -f $n.total, $n.unread) -ForegroundColor Green

Step "Error contract (RFC 7807) - unauthenticated call"
try { Call GET "/v1/orders" | Out-Null } catch { $_.ErrorDetails.Message | ConvertFrom-Json | Format-List }
