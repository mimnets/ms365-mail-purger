<#
.SYNOPSIS
    Purge emails from a user's mailbox (primary + in-place archive) using
    Microsoft Purview compliance search and purge actions.
.DESCRIPTION
    Called by the Python backend via pwsh subprocess.
    Splits date range into weekly chunks, searches matching emails,
    and purges them in batches of 10 per compliance action.
    Outputs machine-readable progress lines for Python to parse.
#>

param(
    [string]$AppId,
    [string]$CertPath,
    [string]$CertPass,
    [string]$Organization,
    [string]$Email,
    [string]$DateFrom,
    [string]$DateTo,
    [string]$JobId
)

$ErrorActionPreference = "Stop"

try {
    # ── Connect to Exchange Online Protection ──────────────────────────────
    Import-Module ExchangeOnlineManagement -ErrorAction Stop

    $secPass = ConvertTo-SecureString -String $CertPass -AsPlainText -Force

    Write-Output "STATUS|Connecting to $Organization"
    try {
        Connect-IPPSSession `
            -AppId $AppId `
            -CertificateFilePath $CertPath `
            -CertificatePassword $secPass `
            -Organization $Organization `
            -ErrorAction Stop
    } catch {
        Write-Output "STATUS|REST mode failed, trying RPS mode..."
        Connect-IPPSSession `
            -AppId $AppId `
            -CertificateFilePath $CertPath `
            -CertificatePassword $secPass `
            -Organization $Organization `
            -UseRPSSession `
            -ErrorAction Stop
    }

    Write-Output "STATUS|Connected"

    # ── Parse dates ────────────────────────────────────────────────────────
    $startDate = [DateTime]::ParseExact($DateFrom, "yyyy-MM-dd", $null)
    $endDate   = [DateTime]::ParseExact($DateTo,   "yyyy-MM-dd", $null)

    $totalDeleted   = 0
    $totalFound     = 0
    $searchNames    = @()   # track for cleanup
    $actionNames    = @()   # track for cleanup

    # ── Loop through weekly chunks ─────────────────────────────────────────
    while ($startDate -lt $endDate) {
        $chunkEnd = $startDate.AddDays(7)
        if ($chunkEnd -gt $endDate) { $chunkEnd = $endDate }

        $ts = Get-Date -Format "yyyyMMddHHmmssfff"
        $searchName = "MP_${JobId}_${ts}"

        Write-Output "CHUNK|$($startDate.ToString('yyyy-MM-dd'))|$($chunkEnd.ToString('yyyy-MM-dd'))"

        # ── Create compliance search ───────────────────────────────────
        $dateFilter = "received:$($startDate.ToString('MM/dd/yyyy'))..$($chunkEnd.ToString('MM/dd/yyyy'))"
        Write-Output "STATUS|Creating compliance search: $searchName"

        New-ComplianceSearch `
            -Name $searchName `
            -ExchangeLocation $Email `
            -ContentMatchQuery $dateFilter `
            -AllowNotFoundExchangeLocationsEnabled $false `
            -ErrorAction Stop | Out-Null

        $searchNames += $searchName
        Start-ComplianceSearch -Identity $searchName -ErrorAction Stop | Out-Null

        # ── Wait for search to complete ───────────────────────────────
        $searchWait = 0
        do {
            Start-Sleep -Seconds 5
            $searchStatus = Get-ComplianceSearch -Identity $searchName -ErrorAction Stop
            $searchWait++
            if ($searchWait -gt 180) { throw "Compliance search timed out after 15 minutes: $searchName" }
        } while ($searchStatus.Status -eq "InProgress")

        if ($searchStatus.Status -eq "Failed") {
            Write-Output "ERROR|Search failed: $($searchStatus.Errors)"
            continue
        }

        $itemCount = [int]$searchStatus.Items
        $totalFound += $itemCount
        Write-Output "FOUND|$itemCount"

        if ($itemCount -eq 0) {
            $startDate = $chunkEnd.AddDays(1)
            continue
        }

        # ── Purge actions (10 items each) ─────────────────────────────
        $numActions = [math]::Ceiling($itemCount / 10)
        Write-Output "STATUS|Purging $itemCount items in $numActions action(s)"

        for ($i = 0; $i -lt $numActions; $i++) {
            # Check if job was stopped (Python will set a flag file)
            $stopFile = "/tmp/stop_${JobId}.flag"
            if (Test-Path $stopFile) {
                Write-Output "STATUS|Stop requested, breaking"
                break
            }

            $actionTs = Get-Date -Format "yyyyMMddHHmmssfff"
            $actionName = "MP_${JobId}_Purge_${actionTs}"

            Write-Output "STATUS|Purge action $($i+1)/$numActions"

            New-ComplianceSearchAction `
                -SearchName $searchName `
                -Purge `
                -PurgeType SoftDelete `
                -Force `
                -ErrorAction Stop | Out-Null

            $actionNames += $actionName

            # ── Wait for purge to complete ────────────────────────────
            $actionWait = 0
            do {
                Start-Sleep -Seconds 5
                $actionStatus = Get-ComplianceSearchAction -Identity $actionName -ErrorAction SilentlyContinue
                $actionWait++
                if ($actionWait -gt 180) { throw "Purge action timed out after 15 minutes: $actionName" }
            } while ($actionStatus -and $actionStatus.Status -eq "InProgress")

            if (-not $actionStatus) {
                Write-Output "ERROR|Purge action $actionName not found after creation"
                continue
            }

            if ($actionStatus.Status -eq "Failed") {
                Write-Output "ERROR|Purge failed: $($actionStatus.Errors)"
                continue
            }

            $batchDeleted = [math]::Min(10, $itemCount - ($i * 10))
            $totalDeleted += $batchDeleted
            Write-Output "DELETED|$totalDeleted"

            # Small delay between actions to avoid rate limits
            Start-Sleep -Seconds 2
        }

        # Check for stop flag after loop
        $stopFile = "/tmp/stop_${JobId}.flag"
        if (Test-Path $stopFile) {
            Write-Output "STATUS|Job stopped by user"
            break
        }

        $startDate = $chunkEnd.AddDays(1)
    }

    # ── Clean up compliance artifacts ──────────────────────────────────────
    Write-Output "STATUS|Cleaning up compliance artifacts"
    foreach ($aName in $actionNames) {
        try {
            Remove-ComplianceSearchAction -Identity $aName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        } catch { }
    }
    foreach ($sName in $searchNames) {
        try {
            Remove-ComplianceSearch -Identity $sName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        } catch { }
    }

    Write-Output "DONE|$totalDeleted|$totalFound"

} catch {
    $errMsg = ($_ | Out-String).Trim() -replace "`n"," | " -replace "`r",""
    Write-Output "FATAL|$errMsg"
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        $edMsg = $_.ErrorDetails.Message -replace "`n"," | " -replace "`r",""
        Write-Output "FATAL|STACK: $edMsg"
    }
    exit 1
} finally {
    try {
        Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    } catch { }
}
