<#
.SYNOPSIS
    Installs a Git pre-commit hook that runs the repository safety check before every commit.
.DESCRIPTION
    The hook blocks commits that stage CHM files, converted Markdown, personal Windows paths,
    secrets or other proprietary content. Run once after cloning:  .\scripts\install-hooks.ps1
#>
$ErrorActionPreference = 'Stop'
$repo = git rev-parse --show-toplevel
$hook = Join-Path $repo '.git/hooks/pre-commit'
$content = @'
#!/bin/sh
# Installed by scripts/install-hooks.ps1
PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python"
exec "$PY" scripts/check_repo_safety.py --staged
'@
Set-Content -Path $hook -Value $content -Encoding ascii -NoNewline
Write-Host "Pre-commit safety hook installed at $hook"
