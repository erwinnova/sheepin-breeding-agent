# Sheepin Breeding Agent - deploy to Cloud Run

param(
  [string]$Project = "sheepin-breeding-agent",
  [string]$Region  = "asia-southeast2",
  [int]$MinInstances = 1
)
$Service = "sheepin-breeding-agent"
gcloud config set project $Project | Out-Null

foreach ($f in @("app.py", "agent.py", "backend_stub.py", "tools.json", "system_prompt.txt", "static\index.html", "static\compare.html", "Dockerfile")) {
  if (-not (Test-Path $f)) { Write-Error "Missing $f - run this from the breeding_agent folder."; exit 1 }
}
if (-not (Test-Path "results_baseten.json")) {
  Write-Host "results_baseten.json not found: /compare will be empty. Run the tests first if you want it in the demo." -ForegroundColor Yellow
}

# max-instances 1: each visitor's demo herd lives in this one process's memory.
gcloud run deploy $Service --source . --region $Region --allow-unauthenticated `
  --memory 512Mi --cpu 1 --min-instances $MinInstances --max-instances 1 --concurrency 40 --timeout 300 `
  --set-env-vars "PROVIDER=baseten,AGENT_TZ=Asia/Jakarta,SESSION_TTL_H=6" `
  --set-secrets "BASETEN_API_KEY=baseten-api-key:latest" --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "Deploy failed - see the Cloud Build log link above."; exit 1 }

$url = gcloud run services describe $Service --region $Region --format="value(status.url)"
Write-Host "`nURL: $url" -ForegroundColor Green

Write-Host "`n== Smoke test"
$h = @{ "X-Session-Id" = "smoke-test" }
try {
  $herd = Invoke-RestMethod "$url/api/herd" -Headers $h
  Write-Host ("herd ok: {0} animals" -f $herd.ternak.Count)
  $body = @{ session_id = "smoke-test"; text = "Ada yang perlu diperhatikan hari ini?" } | ConvertTo-Json
  $chat = Invoke-RestMethod "$url/api/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 120
  Write-Host ("chat ok ({0}): {1}" -f $chat.model, $chat.reply)
  Invoke-RestMethod "$url/api/reset" -Method Post -Headers $h | Out-Null
} catch {
  Write-Host "Smoke test failed: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Logs: gcloud run services logs read $Service --region $Region --limit 50"
}