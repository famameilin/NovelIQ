param(
    [Parameter(Mandatory = $true)]
    [string]$RunId,

    [Parameter(Mandatory = $false)]
    [int]$ProcessId = 0,

    [Parameter(Mandatory = $false)]
    [int]$ApiPort = 8000,

    [Parameter(Mandatory = $false)]
    [int]$IntervalSec = 5,

    [Parameter(Mandatory = $false)]
    [int]$DurationSec = 0,

    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：自动采样 CPU、内存、数据库、日志和导出文件体积，便于填写比赛资源占用表。
function Resolve-ApiProcessId {
    param(
        [int]$ExplicitProcessId,
        [int]$ListenPort
    )

    if ($ExplicitProcessId -gt 0) {
        return $ExplicitProcessId
    }

    $connection = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($null -eq $connection) {
        throw "未找到监听端口 $ListenPort 的进程。请显式传入 -ProcessId。"
    }

    return [int]$connection.OwningProcess
}

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：统一统计目录大小，减少重复口径。
function Get-DirectorySizeBytes {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [int64]0
    }

    $sum = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    if ($null -eq $sum.Sum) {
        return [int64]0
    }
    return [int64]$sum.Sum
}

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：导出文件可能尚未生成，缺失时按0处理。
function Get-FileSizeBytes {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [int64]0
    }

    return [int64](Get-Item -LiteralPath $Path).Length
}

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：数据库体积与运行阶段最适合通过项目已有配置和 SQLAlchemy 引擎读取。
function Get-RunDatabaseSnapshot {
    param(
        [string]$RootPath,
        [string]$TargetRunId
    )

    $pythonExe = Join-Path $RootPath ".venv\Scripts\python.exe"
    $pythonScript = Join-Path $RootPath "scripts\tools\query_run_db_snapshot.py"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "未找到项目虚拟环境 Python：$pythonExe"
    }
    if (-not (Test-Path -LiteralPath $pythonScript)) {
        throw "未找到数据库快照查询脚本：$pythonScript"
    }

    $output = & {
        $env:LOGURU_LEVEL = "ERROR"
        & $pythonExe $pythonScript $TargetRunId
    }
    if ($LASTEXITCODE -ne 0) {
        throw "数据库快照查询失败。"
    }

    return $output | ConvertFrom-Json
}

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：CPU 百分比基于累计 CPU 时间差计算，统一处理逻辑处理器数。
function Get-ProcessCpuPercent {
    param(
        [double]$CurrentCpuSeconds,
        [double]$PreviousCpuSeconds,
        [double]$ElapsedWallSeconds,
        [int]$LogicalProcessorCount
    )

    if ($ElapsedWallSeconds -le 0 -or $LogicalProcessorCount -le 0) {
        return [double]0
    }

    $cpuDelta = $CurrentCpuSeconds - $PreviousCpuSeconds
    if ($cpuDelta -lt 0) {
        return [double]0
    }

    return [math]::Round(($cpuDelta / ($ElapsedWallSeconds * $LogicalProcessorCount)) * 100, 2)
}

# 2026-05-02，任务：补充表15资源占用监测脚本。
# 新建原因：统一汇总平均值、峰值与增长量，直接对应比赛表字段。
function Build-SummaryPayload {
    param(
        [array]$Samples,
        [pscustomobject]$StartSnapshot,
        [pscustomobject]$EndSnapshot,
        [string]$TargetRunId,
        [int]$ResolvedProcessId
    )

    $cpuSamples = @($Samples | Where-Object { $_.CpuPercent -ne $null })
    $memorySamples = @($Samples | Where-Object { $_.MemoryBytes -gt 0 })

    $avgCpu = if ($cpuSamples.Count -gt 0) { [math]::Round((($cpuSamples | Measure-Object -Property CpuPercent -Average).Average), 2) } else { 0 }
    $peakCpuSample = $cpuSamples | Sort-Object CpuPercent -Descending | Select-Object -First 1
    $peakCpu = if ($null -ne $peakCpuSample) { $peakCpuSample.CpuPercent } else { 0 }

    $avgMemoryGb = if ($memorySamples.Count -gt 0) {
        [math]::Round((($memorySamples | Measure-Object -Property MemoryBytes -Average).Average / 1GB), 2)
    } else {
        0
    }
    $peakMemorySample = $memorySamples | Sort-Object MemoryBytes -Descending | Select-Object -First 1
    $peakMemoryGb = if ($null -ne $peakMemorySample) { [math]::Round(($peakMemorySample.MemoryBytes / 1GB), 2) } else { 0 }
    $endMemoryGb = if ($Samples.Count -gt 0) { [math]::Round(($Samples[-1].MemoryBytes / 1GB), 2) } else { 0 }

    $dbGrowthMb = [math]::Round((($EndSnapshot.DatabaseSizeBytes - $StartSnapshot.DatabaseSizeBytes) / 1MB), 2)
    $logGrowthMb = [math]::Round((($EndSnapshot.LogSizeBytes - $StartSnapshot.LogSizeBytes) / 1MB), 2)
    $exportGrowthMb = [math]::Round((($EndSnapshot.ExportSizeBytes - $StartSnapshot.ExportSizeBytes) / 1MB), 2)
    $diskGrowthMb = [math]::Round((($EndSnapshot.WatchedDiskBytes - $StartSnapshot.WatchedDiskBytes) / 1MB), 2)

    return [pscustomobject]@{
        RunId = $TargetRunId
        ProcessId = $ResolvedProcessId
        SampleCount = $Samples.Count
        AvgCpuPercent = $avgCpu
        PeakCpuPercent = $peakCpu
        PeakCpuStage = $(if ($null -ne $peakCpuSample) { "$($peakCpuSample.Stage)/$($peakCpuSample.SubStage)" } else { "" })
        AvgMemoryGb = $avgMemoryGb
        PeakMemoryGb = $peakMemoryGb
        EndMemoryGb = $endMemoryGb
        PeakMemoryStage = $(if ($null -ne $peakMemorySample) { "$($peakMemorySample.Stage)/$($peakMemorySample.SubStage)" } else { "" })
        DatabaseGrowthMb = $dbGrowthMb
        LogGrowthMb = $logGrowthMb
        ExportGrowthMb = $exportGrowthMb
        WatchedDiskGrowthMb = $diskGrowthMb
        FinalStatus = $EndSnapshot.Status
        FinalStage = $EndSnapshot.Stage
        FinalSubStage = $EndSnapshot.SubStage
        FinalProgress = $(if ($Samples.Count -gt 0) { $Samples[-1].Progress } else { $null })
    }
}

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedProcessId = Resolve-ApiProcessId -ExplicitProcessId $ProcessId -ListenPort $ApiPort
$logicalProcessorCount = [Environment]::ProcessorCount

$logDir = Join-Path $resolvedRoot "logs\$RunId"
$exportFile = Join-Path $resolvedRoot "outputs\$RunId.json"
$outputDir = Join-Path $resolvedRoot "output\monitoring"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$startDbSnapshot = Get-RunDatabaseSnapshot -RootPath $resolvedRoot -TargetRunId $RunId
$startSnapshot = [pscustomobject]@{
    DatabaseSizeBytes = [int64]$startDbSnapshot.database_size_bytes
    LogSizeBytes = Get-DirectorySizeBytes -Path $logDir
    ExportSizeBytes = Get-FileSizeBytes -Path $exportFile
    WatchedDiskBytes = 0
    Status = [string]$startDbSnapshot.status
    Stage = [string]$startDbSnapshot.stage
    SubStage = [string]$startDbSnapshot.sub_stage
}
$startSnapshot.WatchedDiskBytes = $startSnapshot.DatabaseSizeBytes + $startSnapshot.LogSizeBytes + $startSnapshot.ExportSizeBytes

$samples = New-Object System.Collections.Generic.List[object]
$startTime = Get-Date
$previousProcess = Get-Process -Id $resolvedProcessId -ErrorAction Stop
$previousWallTime = Get-Date
$previousCpuSeconds = [double]$previousProcess.CPU

Write-Host "开始监测 run_id=$RunId, process_id=$resolvedProcessId, interval=${IntervalSec}s"
Write-Host "日志目录: $logDir"
Write-Host "导出文件: $exportFile"
Write-Host "按 Ctrl+C 可提前结束监测。"

while ($true) {
    Start-Sleep -Seconds $IntervalSec

    try {
        $currentProcess = Get-Process -Id $resolvedProcessId -ErrorAction Stop
    }
    catch {
        Write-Warning "目标进程已退出，结束采样。"
        break
    }

    $currentWallTime = Get-Date
    $elapsedWallSeconds = ($currentWallTime - $previousWallTime).TotalSeconds
    $currentCpuSeconds = [double]$currentProcess.CPU
    $cpuPercent = Get-ProcessCpuPercent `
        -CurrentCpuSeconds $currentCpuSeconds `
        -PreviousCpuSeconds $previousCpuSeconds `
        -ElapsedWallSeconds $elapsedWallSeconds `
        -LogicalProcessorCount $logicalProcessorCount

    $dbSnapshot = Get-RunDatabaseSnapshot -RootPath $resolvedRoot -TargetRunId $RunId
    $logSizeBytes = Get-DirectorySizeBytes -Path $logDir
    $exportSizeBytes = Get-FileSizeBytes -Path $exportFile

    $sample = [pscustomobject]@{
        Timestamp = $currentWallTime.ToString("yyyy-MM-dd HH:mm:ss")
        CpuPercent = $cpuPercent
        MemoryBytes = [int64]$currentProcess.WorkingSet64
        MemoryGb = [math]::Round(($currentProcess.WorkingSet64 / 1GB), 2)
        DatabaseSizeBytes = [int64]$dbSnapshot.database_size_bytes
        DatabaseSizeMb = [math]::Round(($dbSnapshot.database_size_bytes / 1MB), 2)
        LogSizeBytes = $logSizeBytes
        LogSizeMb = [math]::Round(($logSizeBytes / 1MB), 2)
        ExportSizeBytes = $exportSizeBytes
        ExportSizeMb = [math]::Round(($exportSizeBytes / 1MB), 2)
        WatchedDiskBytes = [int64]$dbSnapshot.database_size_bytes + $logSizeBytes + $exportSizeBytes
        WatchedDiskMb = [math]::Round((([int64]$dbSnapshot.database_size_bytes + $logSizeBytes + $exportSizeBytes) / 1MB), 2)
        Status = [string]$dbSnapshot.status
        Stage = [string]$dbSnapshot.stage
        SubStage = [string]$dbSnapshot.sub_stage
        Progress = $(if ($dbSnapshot.total) { [math]::Round(($dbSnapshot.current / [double]$dbSnapshot.total) * 100, 2) } else { $null })
        Message = [string]$dbSnapshot.message
    }
    $samples.Add($sample) | Out-Null

    Write-Host ("[{0}] CPU={1}% MEM={2}GB DB={3}MB LOG={4}MB OUT={5}MB STAGE={6}/{7}" -f `
        $sample.Timestamp,
        $sample.CpuPercent,
        $sample.MemoryGb,
        $sample.DatabaseSizeMb,
        $sample.LogSizeMb,
        $sample.ExportSizeMb,
        $sample.Stage,
        $sample.SubStage)

    if ($DurationSec -gt 0 -and (($currentWallTime - $startTime).TotalSeconds -ge $DurationSec)) {
        break
    }

    if ($dbSnapshot.status -in @("completed", "failed", "cancelled")) {
        Write-Host "检测到任务状态变为 $($dbSnapshot.status)，结束采样。"
        break
    }

    $previousWallTime = $currentWallTime
    $previousCpuSeconds = $currentCpuSeconds
}

$endDbSnapshot = Get-RunDatabaseSnapshot -RootPath $resolvedRoot -TargetRunId $RunId
$endSnapshot = [pscustomobject]@{
    DatabaseSizeBytes = [int64]$endDbSnapshot.database_size_bytes
    LogSizeBytes = Get-DirectorySizeBytes -Path $logDir
    ExportSizeBytes = Get-FileSizeBytes -Path $exportFile
    WatchedDiskBytes = 0
    Status = [string]$endDbSnapshot.status
    Stage = [string]$endDbSnapshot.stage
    SubStage = [string]$endDbSnapshot.sub_stage
}
$endSnapshot.WatchedDiskBytes = $endSnapshot.DatabaseSizeBytes + $endSnapshot.LogSizeBytes + $endSnapshot.ExportSizeBytes

$summary = Build-SummaryPayload `
    -Samples $samples `
    -StartSnapshot $startSnapshot `
    -EndSnapshot $endSnapshot `
    -TargetRunId $RunId `
    -ResolvedProcessId $resolvedProcessId

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$csvPath = Join-Path $outputDir "${RunId}_resource_samples_${timestamp}.csv"
$jsonPath = Join-Path $outputDir "${RunId}_resource_summary_${timestamp}.json"

$samples | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8

Write-Host ""
Write-Host "监测完成。"
Write-Host ("平均 CPU: {0}% / 峰值 CPU: {1}%（{2}）" -f $summary.AvgCpuPercent, $summary.PeakCpuPercent, $summary.PeakCpuStage)
Write-Host ("平均内存: {0} GB / 峰值内存: {1} GB（{2}）" -f $summary.AvgMemoryGb, $summary.PeakMemoryGb, $summary.PeakMemoryStage)
Write-Host ("数据库增长: {0} MB / 日志增长: {1} MB / 导出增长: {2} MB / 监测口径磁盘增长: {3} MB" -f `
    $summary.DatabaseGrowthMb,
    $summary.LogGrowthMb,
    $summary.ExportGrowthMb,
    $summary.WatchedDiskGrowthMb)
Write-Host "样本 CSV: $csvPath"
Write-Host "汇总 JSON: $jsonPath"
