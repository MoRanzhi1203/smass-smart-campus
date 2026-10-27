<#
.SYNOPSIS
    SMASS backup restore drill in an isolated restore database.

.DESCRIPTION
    1. Guard: target db must start with smass_restore_drill_ ; source is smass (read-only).
    2. CREATE target -> IMPORT dump -> verify via scripts/db_verify.py.
    3. DROP target unless -Keep. Never touches smass or other business databases.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\db_restore_drill.ps1 -BackupFile "E:\PythonWeb\_smass_db_backup\smass_db_xxx.sql"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [string]$SourceDatabase = 'smass',
    [string]$MysqlBin = 'D:\mysql-8.0.18-winx64\bin',
    [switch]$Keep
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$PythonExe = 'C:\Users\MSIPC\.conda\envs\smass\python.exe'
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] isolated interpreter missing: $PythonExe" -ForegroundColor Red
    exit 3
}
if (-not (Test-Path $BackupFile)) {
    Write-Host "[ERROR] backup file missing: $BackupFile" -ForegroundColor Red
    exit 3
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$TargetDatabase = "smass_restore_drill_$stamp"

Write-Host "=== guard check ===" -ForegroundColor Cyan
& $PythonExe scripts\db_verify.py --check-target --target $TargetDatabase
if ($LASTEXITCODE -ne 0) {
    Write-Host "[GUARD] target rejected, abort" -ForegroundColor Red
    exit 2
}

$mysqlExe = Join-Path $MysqlBin 'mysql.exe'
if (-not (Test-Path $mysqlExe)) {
    Write-Host "[ERROR] mysql client missing: $mysqlExe" -ForegroundColor Red
    exit 3
}

$cfg = @{ host = 'localhost'; port = '3306'; user = 'root'; password = '' }
$envFile = Join-Path $ProjectRoot '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content -Encoding UTF8 $envFile) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $kv = $t.Split('=', 2)
        if ($kv.Count -ne 2) { continue }
        switch ($kv[0].Trim()) {
            'DB_HOST' { $cfg.host = $kv[1].Trim() }
            'DB_PORT' { $cfg.port = $kv[1].Trim() }
            'DB_USER' { $cfg.user = $kv[1].Trim() }
            'DB_PASSWORD' { $cfg.password = $kv[1].Trim() }
        }
    }
}
if ($env:DB_HOST) { $cfg.host = $env:DB_HOST }
if ($env:DB_PORT) { $cfg.port = $env:DB_PORT }
if ($env:DB_USER) { $cfg.user = $env:DB_USER }
if ($env:DB_PASSWORD) { $cfg.password = $env:DB_PASSWORD }

$cnfPath = Join-Path $env:TEMP ("smass_restore_{0}.cnf" -f $stamp)
$errPath = Join-Path $env:TEMP ("smass_restore_{0}.err" -f $stamp)

@"
[client]
user=$($cfg.user)
password=$($cfg.password)
host=$($cfg.host)
port=$($cfg.port)
default-character-set=utf8
"@ | Set-Content -Path $cnfPath -Encoding ASCII

$created = $false
$verifyExit = 1
try {
    Write-Host ""
    Write-Host "=== create drill db: $TargetDatabase ===" -ForegroundColor Cyan
    $createSql = "CREATE DATABASE ``$TargetDatabase`` DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;"
    $createErr = Join-Path $env:TEMP ("smass_create_{0}.err" -f $stamp)
    $createCmd = '"{0}" --defaults-extra-file="{1}" -e "{2}" 2> "{3}"' -f $mysqlExe, $cnfPath, $createSql, $createErr
    cmd /c $createCmd
    if ($LASTEXITCODE -ne 0) {
        $msg = Get-Content -Raw -Encoding UTF8 $createErr -ErrorAction SilentlyContinue
        Write-Host "[FAIL] create failed: $msg" -ForegroundColor Red
        exit 5
    }
    if (Test-Path $createErr) { Remove-Item -Force $createErr -ErrorAction SilentlyContinue }
    $created = $true
    Write-Host "[OK] drill db created"

    Write-Host ""
    Write-Host "=== import backup ===" -ForegroundColor Cyan
    $importCmd = '"{0}" --defaults-extra-file="{1}" --default-character-set=utf8 {2} < "{3}" 2> "{4}"' -f $mysqlExe, $cnfPath, $TargetDatabase, $BackupFile, $errPath
    cmd /c $importCmd
    $importExit = $LASTEXITCODE
    if (Test-Path $errPath) {
        $err = Get-Content -Raw -Encoding UTF8 $errPath -ErrorAction SilentlyContinue
        if ($err -and $err.Trim()) { Write-Host "[stderr] $($err.Trim())" -ForegroundColor Yellow }
    }
    if ($importExit -ne 0) {
        Write-Host "[FAIL] import failed, exit=$importExit" -ForegroundColor Red
        exit 6
    }
    Write-Host "[OK] import done"

    Write-Host ""
    Write-Host "=== consistency check ($SourceDatabase vs $TargetDatabase) ===" -ForegroundColor Cyan
    & $PythonExe scripts\db_verify.py --source $SourceDatabase --target $TargetDatabase
    $verifyExit = $LASTEXITCODE

    if ($verifyExit -ne 0) {
        Write-Host "[FAIL] restore db differs from source" -ForegroundColor Red
    }
    else {
        Write-Host "[PASS] restore drill ok" -ForegroundColor Green
    }
}
finally {
    if ($created) {
        if ($Keep) {
            Write-Host ""
            Write-Host "[KEEP] drill db kept: $TargetDatabase" -ForegroundColor Yellow
        }
        else {
            Write-Host ""
            Write-Host "=== drop drill db: $TargetDatabase ===" -ForegroundColor Cyan
            if ($TargetDatabase -like 'smass_restore_drill_*') {
                $dropErr = Join-Path $env:TEMP ("smass_drop_{0}.err" -f $stamp)
                $dropCmd = '"{0}" --defaults-extra-file="{1}" -e "DROP DATABASE {2};" 2> "{3}"' -f $mysqlExe, $cnfPath, $TargetDatabase, $dropErr
                cmd /c $dropCmd
                if (Test-Path $dropErr) { Remove-Item -Force $dropErr -ErrorAction SilentlyContinue }

                # 以事实为准：查 information_schema 确认库确实消失，而不是依赖 cmd 退出码
                & $PythonExe scripts\db_verify.py --exists $TargetDatabase | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "[OK] drill db dropped (source $SourceDatabase untouched)" -ForegroundColor Green
                }
                else {
                    Write-Host "[WARN] drill db still exists: $TargetDatabase" -ForegroundColor Yellow
                }
            }
            else {
                Write-Host "[GUARD] refuse DROP: name not matching drill prefix" -ForegroundColor Red
            }
        }
    }
    if (Test-Path $cnfPath) { Remove-Item -Force $cnfPath -ErrorAction SilentlyContinue }
    if (Test-Path $errPath) { Remove-Item -Force $errPath -ErrorAction SilentlyContinue }
}

if ($verifyExit -ne 0) { exit 7 }
exit 0