# Sheepin Breeding Agent - Google Cloud setup
param(
  [string]$Project = "sheepin-breeding-agent",   # globally unique, 6-30 chars; change if taken
  [string]$Region  = "asia-southeast2",
  [string]$Billing = "",
  [string]$Organization = "",                    # numeric org id (gcloud organizations list); empty = no organization
  [string]$EnvFile = "..\.env"                  # BASETEN_API_KEY is read from here if present
)

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step "Project $Project"
$state = gcloud projects describe $Project --format="value(lifecycleState)" 2>$null
if ($state -eq "DELETE_REQUESTED") {
  Write-Host "Project $Project is pending deletion (deleted within the last 30 days)." -ForegroundColor Red
  Write-Host "Restore it:   gcloud projects undelete $Project"
  Write-Host "or use a new id:  .\setup_gcp.ps1 -Project $Project-2 ..."
  exit 1
}
if (-not $state) {
  if ($Organization) { gcloud projects create $Project --name="Sheepin Breeding Agent" --organization=$Organization }
  else { gcloud projects create $Project --name="Sheepin Breeding Agent" }
  if ($LASTEXITCODE -ne 0) { Write-Error "Could not create project (id taken by someone else?). Pick another -Project id."; exit 1 }
}
gcloud config set project $Project | Out-Null

Step "Billing"
if ($Billing) {
  gcloud billing projects link $Project --billing-account=$Billing
  if ($LASTEXITCODE -ne 0) { Write-Error "Linking billing failed - see the message above."; exit 1 }
}
else { Write-Host "No -Billing given. Make sure billing is linked in the console, or Cloud Build will fail." -ForegroundColor Yellow }

Step "Enable APIs (1-2 minutes)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
if ($LASTEXITCODE -ne 0) { Write-Error "Enabling APIs failed (billing not linked?)."; exit 1 }

Step "Baseten API key -> Secret Manager"
$plain = $null
foreach ($p in @(".env", $EnvFile)) {
  if (Test-Path $p) {
    $line = Get-Content $p -Encoding UTF8 | Where-Object { $_ -match '^\s*(export\s+)?BASETEN_API_KEY\s*=' } | Select-Object -First 1
    if ($line) { $plain = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'"); Write-Host "Using BASETEN_API_KEY from $p"; break }
  }
}
if (-not $plain) {
  $sec = Read-Host -AsSecureString "Paste BASETEN_API_KEY (input hidden)"
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
}
$tmp = [IO.Path]::GetTempFileName()
[IO.File]::WriteAllText($tmp, $plain)          # no trailing newline (piping would add CRLF and break the key)
gcloud secrets describe baseten-api-key --format="value(name)" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { gcloud secrets create baseten-api-key --data-file="$tmp" --replication-policy=automatic }
else { gcloud secrets versions add baseten-api-key --data-file="$tmp" }
Remove-Item $tmp -Force
$plain = $null

Step "Permissions for the runtime/build service account"
$PN = gcloud projects describe $Project --format="value(projectNumber)"
$SA = "$PN-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding baseten-api-key --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" | Out-Null
gcloud projects add-iam-policy-binding $Project --member="serviceAccount:$SA" --role="roles/run.builder" --condition=None | Out-Null

Write-Host "`nSetup done. Next: .\deploy.ps1 -Project $Project" -ForegroundColor Green