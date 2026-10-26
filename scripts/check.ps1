<#
.SYNOPSIS
    SMASS 本地/CI 质量门禁。

.DESCRIPTION
    依次执行：
      1. Django 系统检查
      2. 迁移一致性检查（不应有未生成的迁移）
      3. 自动化测试
      4. 部署风险审计（仅提示，不计入失败）

.EXAMPLE
    pwsh -File scripts\check.ps1
    pwsh -File scripts\check.ps1 -EnvName smass -SkipDeployCheck
#>
[CmdletBinding()]
param(
    [string]$EnvName = 'smass',
    [switch]$SkipTests,
    [switch]$SkipDeployCheck
)

$ErrorActionPreference = 'Continue'

# 切到项目根目录（本脚本位于 <root>/scripts）
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# 避免 user site-packages 污染环境（Windows 上很常见）
$env:PYTHONNOUSERSITE = '1'

function Invoke-CondaStep {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & conda run --no-capture-output -n $EnvName python @Arguments 2>&1 | Out-Host
    return $LASTEXITCODE
}

$failures = @()

# 1. 系统检查
if ((Invoke-CondaStep -Name 'django check' -Arguments @('manage.py', 'check')) -ne 0) {
    $failures += 'django check'
}

# 2. 迁移一致性
if ((Invoke-CondaStep -Name 'migration check' -Arguments @('manage.py', 'makemigrations', '--check', '--dry-run')) -ne 0) {
    $failures += 'migration check'
}

# 3. 测试
if (-not $SkipTests) {
    if ((Invoke-CondaStep -Name 'unit tests' -Arguments @('manage.py', 'test', 'app01', '-v', '1')) -ne 0) {
        $failures += 'unit tests'
    }
}

# 4. 部署风险审计（开发环境下必然出现 DEBUG/SECRET_KEY 等警告，仅作提示）
if (-not $SkipDeployCheck) {
    Write-Host ""
    Write-Host "=== deploy audit (informational, not a gate) ===" -ForegroundColor Yellow
    & conda run --no-capture-output -n $EnvName python manage.py check --deploy 2>&1 |
        Select-Object -First 40
    Write-Host "（开发环境出现 DEBUG/SECURE_* 警告属预期，生产部署需逐项消除）" -ForegroundColor Yellow
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "GATE FAILED: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host "ALL GATES PASSED" -ForegroundColor Green
exit 0
