<#
.SYNOPSIS
    SMASS scheduled backup wrapper (for Windows Task Scheduler).

.DESCRIPTION
    调用 scripts/db_backup.ps1 生成一致性备份，然后按保留策略清理旧文件。
    本脚本**不会自行创建计划任务**——注册任务需要显式授权，见
    docs/SMASS_R15_Backup_Restore_Report.md 的部署说明。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\db_backup_scheduled.ps1 -RetentionDays 14
#>
[CmdletBinding()]
param(
    [int]$RetentionDays = 14,
    [string]$OutputDir = 'E:\PythonWeb\_smass_db_backup'
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$logDir = Join-Path $ProjectRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$logFile = Join-Path $logDir 'db_backup.log'

function Write-Log($message) {
    $line = "[{0}] {1}" -f (Get-Date).ToString('s'), $message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "scheduled backup start"

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'db_backup.ps1') -OutputDir $OutputDir
$code = $LASTEXITCODE
Write-Log ("db_backup exit={0}" -f $code)

if ($code -ne 0) {
    Write-Log "backup FAILED, skip retention"
    exit $code
}

# ---- retention: 只删除输出目录内的 .sql/.meta.json，且超出保留期 ----
$cutoff = (Get-Date).AddDays(-$RetentionDays)
$removed = 0
Get-ChildItem -Path $OutputDir -File |
    Where-Object { $_.LastWriteTime -lt $cutoff -and ($_.Extension -eq '.sql' -or $_.Name -like '*.meta.json') } |
    ForEach-Object {
        try {
            Remove-Item $_.FullName -Force -ErrorAction Stop
            $removed++
        }
        catch {
            Write-Log ("retention skip: {0}" -f $_.Name)
        }
    }

Write-Log ("retention removed={0} keep_days={1}" -f $removed, $RetentionDays)
Write-Log "scheduled backup done"
exit 0