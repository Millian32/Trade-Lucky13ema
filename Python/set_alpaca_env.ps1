$apiKey = Read-Host -Prompt "Enter ALPACA_API_KEY"
$apiSecret = Read-Host -Prompt "Enter ALPACA_API_SECRET"

$env:ALPACA_API_KEY = $apiKey
$env:ALPACA_API_SECRET = $apiSecret

[Environment]::SetEnvironmentVariable("ALPACA_API_KEY", $apiKey, "User")
[Environment]::SetEnvironmentVariable("ALPACA_API_SECRET", $apiSecret, "User")

Write-Host "Set ALPACA_API_KEY and ALPACA_API_SECRET for this session and persisted at User scope." -ForegroundColor Green
