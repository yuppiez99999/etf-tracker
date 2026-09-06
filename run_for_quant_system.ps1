#!/usr/bin/env pwsh
# ETF-tracker 盘前监测运行脚本
# 报告归档到主量化系统每日报告归档目录，供盘前流程参考
#
# 用法:
#   ./run_for_quant_system.ps1                      # 默认 5 日窗口
#   ./run_for_quant_system.ps1 -Days 10             # 10 日窗口
#   ./run_for_quant_system.ps1 -Source mock         # 演示模式自检

param(
    [int]$Days = 5,
    [string]$Source = "auto",
    [string]$ArchiveDir = "",
    [switch]$NoArchive
)

# 国内金融 API 不走系统代理
$env:NO_PROXY = "sinajs.cn,sina.com.cn,eastmoney.com,push2his.eastmoney.com,push2.eastmoney.com"

# 归档目录: 参数 > 环境变量 > 主系统默认路径
if (-not $ArchiveDir) {
    $ArchiveDir = $env:ETF_TRACKER_ARCHIVE_DIR
}
if (-not $ArchiveDir) {
    $ArchiveDir = "E:\各种PY程序\28-终极量化交易系统8.4\每日报告归档"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$tracker = Join-Path $scriptDir "etf_tracker.py"

$args = @("--source", $Source, "--days", $Days)
if ($NoArchive) {
    $args += "--no-archive"
} else {
    $args += "--archive-dir", $ArchiveDir
}

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ETF-tracker 盘前监测启动"
Write-Host "  归档目录: $ArchiveDir"
Write-Host "  数据源: $Source | 窗口: $Days 日"

& python $tracker @args

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ETF-tracker 盘前监测完成"