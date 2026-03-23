param(
    [Parameter(Position = 0)]
    [string]$Command = "help",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

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

function Show-Help {
    @"
Usage:
  powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 <command> [args...]

Commands:
  setup                Create .venv if missing and sync dependencies (uv sync --all-groups)
  api [args...]        Run API via uv run python -m src.api.main [args...]
  cli [args...]        Run CLI via uv run python -m src.cli.main [args...]
  test [args...]       Run tests via uv run python -m pytest [args...]
  lint [args...]       Run ruff via uv run ruff check [args...]
  typecheck [args...]  Run mypy via uv run mypy [args...]
  help                 Show this help

Examples:
  scripts/dev.ps1 setup
  scripts/dev.ps1 api --reload --port 8000
  scripts/dev.ps1 cli preprocess --source data\novel.txt --db novel_analysis.db
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
        $commandArgs = @("python", "-m", "src.api.main") + $Args
        Run-Uv -CommandArgs $commandArgs
    }
    "cli" {
        Ensure-Setup
        if ($Args.Count -eq 0) {
            throw "Missing CLI arguments. Example: scripts/dev.ps1 cli preprocess --source <file> --db <db_path>"
        }
        $commandArgs = @("python", "-m", "src.cli.main") + $Args
        Run-Uv -CommandArgs $commandArgs
    }
    "test" {
        Ensure-Setup
        if ($Args.Count -eq 0) {
            Run-Uv -CommandArgs @("--group", "dev", "python", "-m", "pytest", "tests/", "-v")
        } else {
            $commandArgs = @("--group", "dev", "python", "-m", "pytest") + $Args
            Run-Uv -CommandArgs $commandArgs
        }
    }
    "lint" {
        Ensure-Setup
        if ($Args.Count -eq 0) {
            Run-Uv -CommandArgs @("--group", "dev", "ruff", "check", "src", "tests", "scripts")
        } else {
            $commandArgs = @("--group", "dev", "ruff", "check") + $Args
            Run-Uv -CommandArgs $commandArgs
        }
    }
    "typecheck" {
        Ensure-Setup
        if ($Args.Count -eq 0) {
            Run-Uv -CommandArgs @("--group", "dev", "mypy", "src", "tests", "scripts")
        } else {
            $commandArgs = @("--group", "dev", "mypy") + $Args
            Run-Uv -CommandArgs $commandArgs
        }
    }
    default {
        Show-Help
    }
}
