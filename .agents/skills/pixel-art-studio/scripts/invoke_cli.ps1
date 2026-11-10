[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]] $CliArgs
)

$ErrorActionPreference = "Stop"

$command = Get-Command cli-anything-aseprite -ErrorAction SilentlyContinue | Select-Object -First 1
if ($command) {
    & $command.Source @CliArgs
    exit $LASTEXITCODE
}

$candidates = [System.Collections.Generic.List[string]]::new()

if ($env:LOCALAPPDATA) {
    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $localPython) {
        Get-ChildItem -LiteralPath $localPython -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $candidates.Add((Join-Path $_.FullName "Scripts\cli-anything-aseprite.exe"))
            }
    }
}

if ($env:APPDATA) {
    $roamingPython = Join-Path $env:APPDATA "Python"
    if (Test-Path -LiteralPath $roamingPython) {
        Get-ChildItem -LiteralPath $roamingPython -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $candidates.Add((Join-Path $_.FullName "Scripts\cli-anything-aseprite.exe"))
            }
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$candidates.Add((Join-Path $repoRoot ".venv\Scripts\cli-anything-aseprite.exe"))
$candidates.Add((Join-Path $repoRoot "agent-harness\.venv\Scripts\cli-anything-aseprite.exe"))

$executable = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $executable) {
    throw "cli-anything-aseprite is not installed. Install the local harness with: python -m pip install -e `"$repoRoot\agent-harness`""
}

& $executable @CliArgs
exit $LASTEXITCODE
