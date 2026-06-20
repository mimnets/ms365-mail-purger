<#
.SYNOPSIS
    Delete emails via Microsoft Graph PowerShell (interactive admin login).
    No compliance module, no certificates — just sign in as admin.
#>

param(
    [string]$UserEmail = "s.islam@assurerworks.com",
    [string]$DateFrom = "2024-11-01",
    [string]$DateTo = "2024-11-30"
)

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "Target: $UserEmail" -ForegroundColor Cyan
Write-Host "Range:  $DateFrom to $DateTo" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install module if needed
$mod = Get-Module -Name Microsoft.Graph.Users.Actions -ListAvailable -ErrorAction SilentlyContinue
if (-not $mod) {
    Write-Host "Installing Microsoft Graph module..." -ForegroundColor Yellow
    Install-Module Microsoft.Graph -Force -AllowClobber -Scope CurrentUser -ErrorAction SilentlyContinue
}

# Step 2: Connect (sign in as admin)
Write-Host "Step 1: Sign in as admin (monir.it@vclbd.net)" -ForegroundColor Yellow
Write-Host "A browser window will open..." -ForegroundColor Yellow
Connect-MgGraph -Scopes "Mail.ReadWrite.All", "User.Read.All"
Write-Host "Connected!" -ForegroundColor Green

# Step 3: Delete in batches of 10
$totalDeleted = 0
$skip = 0
Write-Host "Searching and deleting emails..." -ForegroundColor Yellow

do {
    $uri = "https://graph.microsoft.com/v1.0/users/$UserEmail/messages?`$filter=receivedDateTime ge ${DateFrom}T00:00:00Z and receivedDateTime le ${DateTo}T23:59:59Z&`$top=10&`$select=id,subject,receivedDateTime&`$skip=$skip"
    $msgs = Invoke-MgGraphRequest -Uri $uri -Method GET
    $count = $msgs.value.Count

    foreach ($msg in $msgs.value) {
        try {
            Invoke-MgGraphRequest -Uri "https://graph.microsoft.com/v1.0/users/$UserEmail/messages/$($msg.id)" -Method DELETE -ErrorAction Stop
            $totalDeleted++
            Write-Host "  ✅ $totalDeleted) $($msg.subject)" -ForegroundColor Green
        } catch {
            Write-Host "  ❌ $($msg.subject) - $($_.Exception.Message)" -ForegroundColor Red
        }
        Start-Sleep -Milliseconds 200
    }
    
    if ($count -gt 0) {
        Write-Host "Batch done - $totalDeleted deleted so far" -ForegroundColor Yellow
    }
    $skip += 10
} while ($count -eq 10)

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "DONE! $totalDeleted emails deleted from $UserEmail" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Cyan

Disconnect-MgGraph -ErrorAction SilentlyContinue
