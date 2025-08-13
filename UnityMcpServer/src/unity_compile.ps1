# PowerShell示例脚本
# 演示如何轻量地调用Unity编译功能
# 输出PostToolUse Decision Control格式的JSON

param(
    [switch]$NoTrigger,
    [ValidateSet("json", "text")]
    [string]$OutputFormat = "text",
    [switch]$Verbose
)

# 获取脚本目录
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Python脚本路径
$pythonScript = Join-Path $scriptDir "compile_unity.py"

# 构建命令参数
$args = @()
if ($NoTrigger) { $args += "--no-trigger" }
if ($OutputFormat) { $args += "--output", $OutputFormat }
if ($Verbose) { $args += "--verbose" }

try {
    # 开始编译
    $startMessage = "Start compiling"
    
    # 调用Python编译脚本
    $result = & python $pythonScript @args 2>&1
    $exitCode = $LASTEXITCODE
    
    # 处理Python脚本的输出结果
    $pythonOutput = ""
    if ($result) {
        $pythonOutput = ($result -join "`n")
    }
    
    # 根据退出码决定输出格式
    if ($exitCode -eq 0) {
        $output = @{
            decision = "block"
            reason = "$pythonOutput"
        } | ConvertTo-Json -Compress
    } else {
        $output = @{
            decision = "block"
            reason = "$pythonOutput`nExecution failed with exit code: $exitCode"
        } | ConvertTo-Json -Compress
    }
    
    Write-Output $output
    exit $exitCode
}
catch {
    $errorOutput = @{
        decision = "block"
        reason = "Execution failed: $($_.Exception.Message)"
    } | ConvertTo-Json -Compress
    
    Write-Output $errorOutput
    exit 1
}