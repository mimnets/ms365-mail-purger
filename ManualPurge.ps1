<#
.SYNOPSIS
    Manually purge emails from primary + archive mailbox, 10 at a time.
    Run this from your LOCAL Windows PowerShell (not Docker).
#>

param(
    [string]$UserEmail = "monir.it@vclbd.net",
    [string]$DateFrom = "2026-01-01",
    [string]$DateTo = "2026-12-31",
    [int]$BatchSize = 10
)

# Step 1: Connect
Write-Host "Connecting to Exchange Online..." -ForegroundColor Cyan
Connect-ExchangeOnline -UserPrincipalName $UserEmail

# Step 2: Split date range into weekly chunks
$start = [DateTime]::ParseExact($DateFrom, "yyyy-MM-dd", $null)
$end   = [DateTime]::ParseExact($DateTo,   "yyyy-MM-dd", $null)
$totalFound = 0
$totalDeleted = 0

while ($start -lt $end) {
    $chunkEnd = $start.AddDays(7)
    if ($chunkEnd -gt $end) { $chunkEnd = $end }

    $dateFilter = "received:$($start.ToString('MM/dd/yyyy'))..$($chunkEnd.ToString('MM/dd/yyyy'))"
    $searchName = "ManualPurge_$(Get-Date -Format 'yyyyMMddHHmmssfff')"

    Write-Host "`n--- Searching $($start.ToString('yyyy-MM-dd')) to $($chunkEnd.ToString('yyyy-MM-dd')) ---" -ForegroundColor Yellow

    # Create and start compliance search (covers primary + archive)
    New-ComplianceSearch -Name $searchName -ExchangeLocation $UserEmail -ContentMatchQuery $dateFilter | Out-Null
    Start-ComplianceSearch -Identity $searchName | Out-Null

    # Wait for completion
    do {
        Start-Sleep -Seconds 3
        $status = Get-ComplianceSearch -Identity $searchName
        Write-Host "." -NoNewline
    } while ($status.Status -eq "InProgress")

    $itemCount = [int]$status.Items
    $totalFound += $itemCount
    Write-Host "`nFound $itemCount items (total: $totalFound)" -ForegroundColor Green

    if ($itemCount -eq 0) {
        $start = $chunkEnd.AddDays(1)
        continue
    }

    # Purge 10 at a time
    $actions = [math]::Ceiling($itemCount / $BatchSize)
    for ($i = 0; $i -lt $actions; $i++) {
        $actionName = "ManualPurge_Action_$(Get-Date -Format 'yyyyMMddHHmmssfff')"
        Write-Host "  Purge action $($i+1)/$actions..." -ForegroundColor Gray

        New-ComplianceSearchAction -SearchName $searchName -Purge -PurgeType SoftDelete -Force | Out-Null

        do {
            Start-Sleep -Seconds 3
            $actionStatus = Get-ComplianceSearchAction -Identity $actionName
            Write-Host "." -NoNewline
        } while ($actionStatus.Status -eq "InProgress")

        $batchDeleted = [math]::Min(10, $itemCount - ($i * 10))
        $totalDeleted += $batchDeleted
        Write-Host "`n  Deleted $batchDeleted (total: $totalDeleted)" -ForegroundColor Green

        Start-Sleep -Seconds 2
    }

    # Clean up search
    Remove-ComplianceSearch -Identity $searchName -Confirm:$false -ErrorAction SilentlyContinue

    $start = $chunkEnd.AddDays(1)
}

Write-Host "`n=== COMPLETE ===" -ForegroundColor Cyan
Write-Host "Total found: $totalFound" -ForegroundColor Yellow
Write-Host "Total deleted: $totalDeleted" -ForegroundColor Green

Disconnect-ExchangeOnline -Confirm:$false
