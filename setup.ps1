$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

function Test-PythonProbe {
    param(
        [string]$Executable,
        [string[]]$Prefix,
        [string]$Expression
    )
    try {
        $null = & $Executable @Prefix -c $Expression 2>&1
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $projectDir ".venv\Scripts\python.exe"),
        "py",
        "python",
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "py" -or $candidate -eq "python") {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if (-not $command) { continue }
            if ($candidate -eq "py") {
                $ok = Test-PythonProbe -Executable "py" -Prefix @("-3") -Expression `
                    "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
                if ($ok) {
                    return [pscustomobject]@{ Executable = "py"; Prefix = @("-3") }
                }
            } else {
                $ok = Test-PythonProbe -Executable "python" -Prefix @() -Expression `
                    "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
                if ($ok) {
                    return [pscustomobject]@{ Executable = "python"; Prefix = @() }
                }
            }
        } elseif (Test-Path -LiteralPath $candidate) {
            $ok = Test-PythonProbe -Executable $candidate -Prefix @() -Expression `
                "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
            if ($ok) {
                return [pscustomobject]@{ Executable = $candidate; Prefix = @() }
            }
        }
    }
    throw "没有找到 Python 3.10+。请先安装 Python，并勾选 Add Python to PATH。"
}

$pythonCommand = Find-Python
$pythonExe = $pythonCommand.Executable
$pythonPrefix = @($pythonCommand.Prefix)

Write-Host "正在检查 Pillow..." -ForegroundColor DarkGreen
$hasPillow = Test-PythonProbe -Executable $pythonExe -Prefix $pythonPrefix -Expression "import PIL"
if (-not $hasPillow) {
    try {
        & $pythonExe @pythonPrefix -m pip install -r requirements.txt
    } catch {
        throw "Pillow 安装失败，请检查网络后重试。"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Pillow 安装失败，请检查网络后重试。"
    }
}

Write-Host ""
Write-Host "栖心环境已就绪。" -ForegroundColor Green
Write-Host "正式使用: $pythonExe $($pythonPrefix -join ' ') -m qixin"
Write-Host "演示模式: $pythonExe $($pythonPrefix -join ' ') -m qixin --demo"
