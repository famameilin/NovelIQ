param(
    [Parameter(Position = 0)]
    [string]$Command = "help",
    [Parameter(ValueFromRemainingArguments = $true)]
    [AllowNull()]
    [object[]]$CommandArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

# Keep uv state inside the repo to avoid user-profile permission issues
$env:UV_CACHE_DIR = Join-Path $RepoRoot ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RepoRoot ".uv-python"

# Normalize remaining args so strict mode does not trip on null/object values
$CommandArgs = @(
    $CommandArgs |
    Where-Object { $null -ne $_ -and $_ -ne "" } |
    ForEach-Object { [string]$_ }
)

function Test-CommandExists {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-UvInstalled {
    if (-not (Test-CommandExists "uv")) {
        throw "uv is not installed or not available in PATH. Install it first: https://docs.astral.sh/uv/"
    }
}

function Ensure-Venv {
    if (Test-Path ".venv\Scripts\python.exe") {
        return
    }

    Write-Host "Project virtual environment not found, creating .venv with Python 3.12..."

    if (Test-CommandExists "py") {
        & py -3.12 -m venv .venv
    } elseif (Test-CommandExists "python") {
        & python -m venv .venv
    } else {
        throw "No Python launcher found. Install Python 3.12+ and retry."
    }
}

function Ensure-Setup {
    Ensure-UvInstalled
    Ensure-Venv
}

function Run-Uv {
    param([Parameter(Mandatory = $true)][string[]]$CommandArgs)
    & uv run @CommandArgs
}

function Run-VenvPython {
    param([Parameter(Mandatory = $true)][string[]]$CommandArgs)
    & ".venv\Scripts\python.exe" @CommandArgs
}

function Show-Help {
    @"
Usage:
  powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 <command> [args...]

Commands:
  setup                Create .venv if missing and sync dependencies (uv sync --all-groups)
  api [args...]        Run API via uv run python -m src.api.main [args...]
  test [args...]       Run tests via .venv\Scripts\python.exe -m pytest [args...]
  lint [args...]       Run ruff via uv run ruff check [args...]
  typecheck [args...]  Run mypy for src via uv run mypy [args...]
  help                 Show this help

Examples:
  scripts/dev.ps1 setup
  scripts/dev.ps1 api --reload --port 8000
  scripts/dev.ps1 test tests/test_e2e_integration.py -v
"@
}

switch ($Command.ToLowerInvariant()) {
    "setup" {
        Ensure-Setup
        & uv sync --all-groups
    }
    "api" {
        Ensure-Setup
        $commandArgs = @("python", "-m", "src.api.main") + $CommandArgs
        Run-Uv -CommandArgs $commandArgs
    }
    "test" {
        Ensure-Setup
        if ($CommandArgs.Count -eq 0) {
            Run-VenvPython -CommandArgs @("-m", "pytest", "tests/", "-v")
        } else {
            $commandArgs = @("-m", "pytest") + $CommandArgs
            Run-VenvPython -CommandArgs $commandArgs
        }
    }
    "lint" {
        Ensure-Setup
        if ($CommandArgs.Count -eq 0) {
            Run-Uv -CommandArgs @(
                "--group",
                "dev",
                "ruff",
                "check",
                "--force-exclude",
                "src",
                "tests",
                "scripts/run_api.py"
            )
        } else {
            $commandArgs = @("--group", "dev", "ruff", "check", "--force-exclude") + $CommandArgs
            Run-Uv -CommandArgs $commandArgs
        }
    }
    "typecheck" {
        Ensure-Setup
        if ($CommandArgs.Count -eq 0) {
            Run-Uv -CommandArgs @("--group", "dev", "mypy", "src")
        } else {
            $commandArgs = @("--group", "dev", "mypy") + $CommandArgs
            Run-Uv -CommandArgs $commandArgs
        }
    }
    default {
        Show-Help
    }
}
