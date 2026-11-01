$ErrorActionPreference = 'Stop'
$repo = 'notdamien2009/horse'
$branch = 'feature/sportinglife-private-actions'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Run-Checked([string]$program, [string[]]$commandArgs) {
    & $program @commandArgs
    if ($LASTEXITCODE -ne 0) { throw "$program failed (exit $LASTEXITCODE)" }
}

Write-Host 'Horse racing: private GitHub setup' -ForegroundColor Cyan
foreach ($prog in @('git', 'gh', 'py')) {
    if (-not (Get-Command $prog -ErrorAction SilentlyContinue)) {
        throw "$prog not installed. Install Git, GitHub CLI and Python before running. No files have been changed."
    }
}
Run-Checked 'gh' @('auth','status')
$isPrivate = (& gh repo view $repo --json isPrivate --jq '.isPrivate' 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $isPrivate -ne 'true') {
    throw "STOP: $repo must be PRIVATE before uploading any racing information. No data uploaded."
}

$known = Join-Path $env:USERPROFILE 'Desktop\Speeds\HORSE-RACING-v2.7-HISTORY-READY\data\racing_history.sqlite'
Write-Host "\nCurrent collector database default:" -ForegroundColor Cyan
Write-Host $known
$chosen = Read-Host 'Press Enter to use that path or paste the full path of your newest racing_history.sqlite'
if ([string]::IsNullOrWhiteSpace($chosen)) { $chosen = $known }
$chosen = $chosen.Trim().Trim('"')
if (-not (Test-Path -LiteralPath $chosen -PathType Leaf)) { throw "Database not found: $chosen" }

$work = Join-Path $env:TEMP ('horse-github-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
    Run-Checked 'gh' @('auth','setup-git')
    Run-Checked 'git' @('clone', '--branch', $branch, "https://github.com/$repo.git", (Join-Path $work 'repo'))
    $dest = Join-Path $work 'repo'
    foreach ($folder in @('src','tools','tests')) {
        $target = Join-Path $dest $folder
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $root $folder) -File | Where-Object { $_.Extension -in @('.py', '.txt') -and $_.Name -ne 'test_recovery.py' } | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $target -Force }
    }
    Copy-Item -LiteralPath (Join-Path $root '.gitignore') -Destination $dest -Force
    Push-Location $dest
    try {
        Run-Checked 'git' @('add','src','tools','tests','.gitignore')
        & git diff --cached --quiet
        if ($LASTEXITCODE -eq 1) {
            $name = (& gh api user --jq .login).Trim()
            Run-Checked 'git' @('-c', "user.name=$name", '-c', "user.email=$name@users.noreply.github.com", 'commit', '-m', 'Add tested collector source and checkpoint tooling')
            Run-Checked 'git' @('push','origin',$branch)
        }
    } finally { Pop-Location }

    Write-Host 'Saving a consistent SQLite backup (safe while the collector is running).'
    $archive = Join-Path $work 'racing_history.sqlite.gz'
    Run-Checked 'py' @('-3', (Join-Path $root 'tools\sl_checkpoint.py'), 'save', $chosen, $archive)
    & gh release view sl-database-checkpoint -R $repo 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Run-Checked 'gh' @('release','create','sl-database-checkpoint','-R',$repo,'--title','Private racing database checkpoint','--notes','SQLite backup: Sporting Life historical research','--prerelease')
    }
    Run-Checked 'gh' @('release','upload','sl-database-checkpoint',$archive,'--clobber','-R',$repo)
    Write-Host 'DONE: collector source pushed to review branch and database backed up to a PRIVATE GitHub Release.' -ForegroundColor Green
    Write-Host "Next: review $($repo)/pull/1, merge it and run the 'verify' action."
} finally {
    if (Test-Path $work) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
}
