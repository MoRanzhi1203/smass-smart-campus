<#
.SYNOPSIS
    Convert the smass schema to utf8mb4 inside an ISOLATED prototype database (drill only).

.DESCRIPTION
    Never touches the real `smass` database.

    Why foreign keys matter: converting table-by-table fails with MySQL error 3780
    ("Referencing column ... are incompatible") because a FK requires BOTH sides to
    share charset/collation. `foreign_key_checks=0` does NOT bypass this definition
    level check. Correct order therefore is:

      1. dump smass -> import into smass_proto_charset_<ts>
      2. PRE-GENERATE the ADD FOREIGN KEY statements (before dropping them)
      3. DROP all foreign keys
      4. ALTER DATABASE + per-table CONVERT TO utf8mb4
      5. REPLAY the pre-generated ADD FOREIGN KEY statements
      6. probe a 4-byte character; compare table/index/migration/FK counts
      7. drop the prototype database unless -Keep

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\charset_drill.ps1
#>
[CmdletBinding()]
param(
    [string]$SourceDatabase = 'smass',
    [string]$MysqlBin = 'D:\mysql-8.0.18-winx64\bin',
    [switch]$Keep
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$TargetDatabase = "smass_proto_charset_$stamp"

if ($SourceDatabase -ne 'smass') { Write-Host "[GUARD] source must be smass" -ForegroundColor Red; exit 2 }
if ($TargetDatabase -notlike 'smass_proto_charset_*') { Write-Host "[GUARD] bad target prefix" -ForegroundColor Red; exit 2 }

$mysqlExe = Join-Path $MysqlBin 'mysql.exe'
$dumpExe = Join-Path $MysqlBin 'mysqldump.exe'
foreach ($exe in @($mysqlExe, $dumpExe)) {
    if (-not (Test-Path $exe)) { Write-Host "[ERROR] missing $exe" -ForegroundColor Red; exit 3 }
}

$cfg = @{ host = 'localhost'; port = '3306'; user = 'root'; password = '' }
foreach ($line in Get-Content -Encoding UTF8 (Join-Path $ProjectRoot '.env')) {
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

$cnfPath   = Join-Path $env:TEMP ("cs_{0}.cnf" -f $stamp)
$dumpFile  = Join-Path $env:TEMP ("cs_{0}.sql" -f $stamp)
$dropFile  = Join-Path $env:TEMP ("cs_{0}_dropfk.sql" -f $stamp)
$convFile  = Join-Path $env:TEMP ("cs_{0}_convert.sql" -f $stamp)
$addFile   = Join-Path $env:TEMP ("cs_{0}_addfk.sql" -f $stamp)
$errFile   = Join-Path $env:TEMP ("cs_{0}.err" -f $stamp)

@"
[client]
user=$($cfg.user)
password=$($cfg.password)
host=$($cfg.host)
port=$($cfg.port)
"@ | Set-Content -Path $cnfPath -Encoding ASCII

$base = "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`""
$baseIn = "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`" --default-character-set=utf8mb4 $TargetDatabase"

function Sql-Value([string]$sql) {
    $o = (cmd /c "$base -N -e `"$sql`" 2> `"$errFile`"").ToString()
    return $o.Trim()
}
function Show-Err {
    if (Test-Path $errFile) {
        $e = Get-Content -Raw -Encoding UTF8 $errFile -ErrorAction SilentlyContinue
        if ($e -and $e.Trim()) { Write-Host "[stderr] $($e.Trim())" -ForegroundColor Yellow }
    }
}
function Sql-File([string]$sql, [string]$outFile) {
    cmd /c "$base -N -e `"$sql`" > `"$outFile`" 2> `"$errFile`""
    return $LASTEXITCODE
}

$created = $false
$exitCode = 1

$qTables = "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$TargetDatabase' AND TABLE_TYPE='BASE TABLE'"
$qIdx    = "SELECT COUNT(DISTINCT TABLE_NAME, INDEX_NAME) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='$TargetDatabase'"
$qMig    = "SELECT COUNT(*) FROM ${TargetDatabase}.django_migrations"
$qFk     = "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA='$TargetDatabase' AND CONSTRAINT_TYPE='FOREIGN KEY'"

try {
    Write-Host "=== [1/7] dump source ===" -ForegroundColor Cyan
    cmd /c "`"$dumpExe`" --defaults-extra-file=`"$cnfPath`" --single-transaction --quick --routines --triggers --set-gtid-purged=OFF --no-tablespaces --default-character-set=utf8 $SourceDatabase > `"$dumpFile`" 2> `"$errFile`""
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] dump" -ForegroundColor Red; Show-Err; exit 5 }

    Write-Host "=== [2/7] create + import $TargetDatabase ===" -ForegroundColor Cyan
    cmd /c "$base -e `"CREATE DATABASE $TargetDatabase DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci;`" 2> `"$errFile`""
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] create" -ForegroundColor Red; Show-Err; exit 5 }
    $created = $true
    cmd /c "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`" --default-character-set=utf8 $TargetDatabase < `"$dumpFile`" 2> `"$errFile`""
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] import" -ForegroundColor Red; Show-Err; exit 6 }

    $tablesBefore = Sql-Value $qTables
    $idxBefore    = Sql-Value $qIdx
    $migBefore    = Sql-Value $qMig
    $fkBefore     = Sql-Value $qFk
    Write-Host ("baseline: tables={0} indexes={1} migrations={2} fks={3}" -f $tablesBefore, $idxBefore, $migBefore, $fkBefore)

    Write-Host "=== [2.5/7] pre-generate ADD FOREIGN KEY statements ===" -ForegroundColor Cyan
    $genAdd = "SELECT CONCAT('ALTER TABLE ``', k.TABLE_NAME, '`` ADD CONSTRAINT ``', k.CONSTRAINT_NAME, '`` FOREIGN KEY (``', k.COLUMN_NAME, '``) REFERENCES ``', k.REFERENCED_TABLE_NAME, '`` (``', k.REFERENCED_COLUMN_NAME, '``) ON DELETE ', r.DELETE_RULE, ' ON UPDATE ', r.UPDATE_RULE, ';') FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA = '$TargetDatabase' AND k.REFERENCED_TABLE_NAME IS NOT NULL ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION"
    Sql-File $genAdd $addFile | Out-Null
    $addCount = @(Get-Content $addFile -ErrorAction SilentlyContinue | Where-Object { $_ -like 'ALTER TABLE*' }).Count
    Write-Host ("pre-generated ADD statements: {0}" -f $addCount)
    if ($addCount -eq 0) { Write-Host "[FAIL] could not generate FK statements" -ForegroundColor Red; exit 7 }

    Write-Host "=== [3/7] drop all foreign keys ===" -ForegroundColor Cyan
    $genDrop = "SELECT CONCAT('ALTER TABLE ``', TABLE_NAME, '`` DROP FOREIGN KEY ``', CONSTRAINT_NAME, '``;') FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = '$TargetDatabase' AND CONSTRAINT_TYPE = 'FOREIGN KEY' ORDER BY TABLE_NAME, CONSTRAINT_NAME"
    Sql-File $genDrop $dropFile | Out-Null
    $dropCount = @(Get-Content $dropFile -ErrorAction SilentlyContinue | Where-Object { $_ -like 'ALTER TABLE*' }).Count
    Write-Host ("drop statements: {0}" -f $dropCount)
    cmd /c "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`" $TargetDatabase < `"$dropFile`" 2> `"$errFile`""
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] drop fk" -ForegroundColor Red; Show-Err; exit 7 }
    Write-Host ("fks after drop: {0}" -f (Sql-Value $qFk))

    Write-Host "=== [4/7] convert to utf8mb4 ===" -ForegroundColor Cyan
    cmd /c "$base -e `"ALTER DATABASE $TargetDatabase CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;`" 2> `"$errFile`""
    $genConv = "SELECT CONCAT('ALTER TABLE ``', TABLE_NAME, '`` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;') FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$TargetDatabase' AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
    Sql-File $genConv $convFile | Out-Null
    $convCount = @(Get-Content $convFile -ErrorAction SilentlyContinue | Where-Object { $_ -like 'ALTER TABLE*' }).Count
    Write-Host ("convert statements: {0}" -f $convCount)
    cmd /c "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`" --default-character-set=utf8mb4 $TargetDatabase < `"$convFile`" 2> `"$errFile`""
    $convExit = $LASTEXITCODE
    Write-Host ("convert exit: {0}" -f $convExit)
    Show-Err
    if ($convExit -ne 0) { Write-Host "[FAIL] convert" -ForegroundColor Red; exit 8 }

    Write-Host "=== [5/7] recreate foreign keys ===" -ForegroundColor Cyan
    cmd /c "`"$mysqlExe`" --defaults-extra-file=`"$cnfPath`" --default-character-set=utf8mb4 $TargetDatabase < `"$addFile`" 2> `"$errFile`""
    $addExit = $LASTEXITCODE
    if ($addExit -ne 0) { Write-Host "[FAIL] recreate fk" -ForegroundColor Red; Show-Err; exit 9 }
    $fkAfter = Sql-Value $qFk
    Write-Host ("fks after recreate: {0}" -f $fkAfter)

    Write-Host "=== [6/7] probe 4-byte char + metrics ===" -ForegroundColor Cyan
    $probeSql = "CREATE TABLE _charset_probe (id INT PRIMARY KEY, txt VARCHAR(64)) DEFAULT CHARSET=utf8mb4; INSERT INTO _charset_probe VALUES (1, _utf8mb4 0xF09F9982E4B8ADE69687);"
    cmd /c "$baseIn -e `"$probeSql`" 2> `"$errFile`""
    $probeWrite = $LASTEXITCODE
    $probeHex = Sql-Value "SELECT HEX(txt) FROM ${TargetDatabase}._charset_probe WHERE id = 1"

    $tablesAfter = Sql-Value $qTables
    $idxAfter    = Sql-Value $qIdx
    $migAfter    = Sql-Value $qMig
    $charset     = Sql-Value "SELECT DEFAULT_CHARACTER_SET_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$TargetDatabase'"

    Write-Host ("after   : tables={0} indexes={1} migrations={2} fks={3} charset={4}" -f $tablesAfter, $idxAfter, $migAfter, $fkAfter, $charset)
    Write-Host ("probe   : write_exit={0} hex={1}" -f $probeWrite, $probeHex)

    Write-Host "=== [7/7] verdict ===" -ForegroundColor Cyan
    $ok = $true
    if ([int]$tablesAfter -ne ([int]$tablesBefore + 1)) { Write-Host "[FAIL] table count (probe table)" -ForegroundColor Red; $ok = $false }
    if ($migAfter -ne $migBefore) { Write-Host "[FAIL] migration count" -ForegroundColor Red; $ok = $false }
    if ($fkAfter -ne $fkBefore) { Write-Host "[FAIL] fk count before=$fkBefore after=$fkAfter" -ForegroundColor Red; $ok = $false }
    if ($charset -ne 'utf8mb4') { Write-Host "[FAIL] charset=$charset" -ForegroundColor Red; $ok = $false }
    if ($probeWrite -ne 0) { Write-Host "[FAIL] probe insert" -ForegroundColor Red; $ok = $false }
    if ($probeHex -ne 'F09F9982E4B8ADE69687') { Write-Host "[FAIL] 4-byte char got $probeHex" -ForegroundColor Red; $ok = $false }

    if ($ok) {
        Write-Host ("[PASS] utf8mb4 drill: {0} tables, {1} fks recreated, {2} indexes, 4-byte char OK" -f $tablesBefore, $fkAfter, $idxAfter) -ForegroundColor Green
        $exitCode = 0
    } else {
        Write-Host "[FAIL] drill" -ForegroundColor Red
        $exitCode = 10
    }
}
finally {
    if ($created) {
        if ($Keep) { Write-Host "[KEEP] $TargetDatabase" -ForegroundColor Yellow }
        else { cmd /c "$base -e `"DROP DATABASE $TargetDatabase;`"" | Out-Null; Write-Host "[OK] prototype dropped" -ForegroundColor Green }
    }
    foreach ($f in @($cnfPath, $dumpFile, $dropFile, $convFile, $addFile, $errFile)) {
        if (Test-Path $f) { Remove-Item -Force $f -ErrorAction SilentlyContinue }
    }
}
exit $exitCode