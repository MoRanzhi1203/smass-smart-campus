<#
.SYNOPSIS
    SMASS 数据库一致性备份（mysqldump）。

.DESCRIPTION
    - 只备份白名单内的开发库（默认 smass），不触碰同实例其他业务库；
    - 凭据从 .env / 环境变量读取，写入临时 --defaults-extra-file，
      不出现在命令行与日志中，用完即删；
    - 使用 --single-transaction 保证 InnoDB 一致性快照，不锁表；
    - 备份文件落在项目外目录，已排除 Git。

    实现说明：不使用 Start-Process —— PowerShell 5.1 在环境中存在大小写不同的
    同名变量（NO_PROXY / no_proxy）时会抛 ArgumentException。
    改用 cmd /c 做字节级重定向。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\db_backup.ps1
#>
[CmdletBinding()]
param(
    [string]$Database = 'smass',
    [string]$OutputDir = 'E:\PythonWeb\_smass_db_backup',
    [string]$MysqlBin = 'D:\mysql-8.0.18-winx64\bin'
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$AllowedSources = @('smass')
if ($AllowedSources -notcontains $Database) {
    Write-Host "[GUARD] refuse: $Database not in backup whitelist" -ForegroundColor Red
    exit 2
}

$dumpExe = Join-Path $MysqlBin 'mysqldump.exe'
if (-not (Test-Path $dumpExe)) {
    Write-Host "[ERROR] mysqldump not found: $dumpExe" -ForegroundColor Red
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

if (-not $cfg.password) {
    Write-Host "[ERROR] no db password (check .env or DB_PASSWORD)" -ForegroundColor Red
    exit 4
}

if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupFile = Join-Path $OutputDir ("smass_db_{0}.sql" -f $stamp)
$cnfPath = Join-Path $env:TEMP ("smass_dump_{0}.cnf" -f $stamp)
$errPath = Join-Path $env:TEMP ("smass_dump_{0}.err" -f $stamp)

@"
[client]
user=$($cfg.user)
password=$($cfg.password)
host=$($cfg.host)
port=$($cfg.port)
default-character-set=utf8
"@ | Set-Content -Path $cnfPath -Encoding ASCII

try {
    Write-Host "=== mysqldump ===" -ForegroundColor Cyan
    Write-Host ("source db : {0}" -f $Database)
    Write-Host ("output    : {0}" -f $backupFile)

    $cmdLine = '"{0}" --defaults-extra-file="{1}" --single-transaction --quick --routines --triggers --events --hex-blob --set-gtid-purged=OFF --no-tablespaces --default-character-set=utf8 {2} > "{3}" 2> "{4}"' -f $dumpExe, $cnfPath, $Database, $backupFile, $errPath

    cmd /c $cmdLine
    $exitCode = $LASTEXITCODE
    Write-Host ("mysqldump exit code : {0}" -f $exitCode)

    if (Test-Path $errPath) {
        $err = Get-Content -Raw -Encoding UTF8 $errPath -ErrorAction SilentlyContinue
        if ($err -and $err.Trim()) { Write-Host "[stderr] $($err.Trim())" -ForegroundColor Yellow }
    }

    if ($exitCode -ne 0) {
        Write-Host "[FAIL] mysqldump failed, exit=$exitCode" -ForegroundColor Red
        exit 5
    }

    if (-not (Test-Path $backupFile)) {
        Write-Host "[FAIL] backup file not created" -ForegroundColor Red
        exit 6
    }

    $size = (Get-Item $backupFile).Length
    $createCount = (Select-String -Path $backupFile -Pattern '^CREATE TABLE' -AllMatches).Count
    $insertCount = (Select-String -Path $backupFile -Pattern '^INSERT INTO' -AllMatches).Count

    Write-Host "=== verify ===" -ForegroundColor Cyan
    Write-Host ("size          : {0:N0} bytes" -f $size)
    Write-Host ("CREATE TABLE  : {0}" -f $createCount)
    Write-Host ("INSERT INTO   : {0}" -f $insertCount)

    if ($size -lt 4096) {
        Write-Host "[FAIL] backup too small" -ForegroundColor Red
        exit 7
    }
    if ($createCount -lt 26) {
        Write-Host "[FAIL] CREATE TABLE count < 26 (actual $createCount)" -ForegroundColor Red
        exit 8
    }

    $metaFile = [System.IO.Path]::ChangeExtension($backupFile, '.meta.json')
    $dumpVersion = (& $dumpExe --version) -join ' '
    [ordered]@{
        database     = $Database
        created_at   = (Get-Date).ToString('o')
        bytes        = $size
        create_table = $createCount
        insert_into  = $insertCount
        mysqldump    = $dumpVersion
        host         = $cfg.host
        port         = $cfg.port
        user         = $cfg.user
    } | ConvertTo-Json | Set-Content -Path $metaFile -Encoding UTF8

    Write-Host ""
    Write-Host "[PASS] backup done: $backupFile" -ForegroundColor Green
    Write-Host "       meta: $metaFile"
    exit 0
}
finally {
    if (Test-Path $cnfPath) { Remove-Item -Force $cnfPath -ErrorAction SilentlyContinue }
    if (Test-Path $errPath) { Remove-Item -Force $errPath -ErrorAction SilentlyContinue }
}