$ErrorActionPreference = 'Stop'
$repo = 'notdamien2009/horse'
$tag = 'sl-database-checkpoint'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Checked([string]$program, [string[]]$cmdargs) {
    & $program @cmdargs
    if ($LASTEXITCODE -ne 0) { throw "${program} failed with exit code $LASTEXITCODE" }
}

function CaptureChecked([string]$program, [string[]]$cmdargs) {
    $output = & $program @cmdargs
    if ($LASTEXITCODE -ne 0) { throw "${program} failed with exit code $LASTEXITCODE" }
    return $output
}

Write-Host 'Horse racing: complete the GitHub database backup' -ForegroundColor Cyan
foreach ($program in @('gh','py')) {
    if (-not (Get-Command $program -ErrorAction SilentlyContinue)) { throw "Required program not found: $program" }
}

$visibility = [string](CaptureChecked 'gh' @('repo','view',$repo,'--json','isPrivate','--jq','.isPrivate'))
if ($visibility.Trim() -ne 'true') { throw 'STOP: GitHub repository is not private. Database NOT uploaded.' }

$defaultDb = Join-Path $env:USERPROFILE 'Desktop\Speeds\HORSE-RACING-v2.7-HISTORY-READY\data\racing_history.sqlite'
Write-Host "Default database: $defaultDb"
$database = Read-Host 'Press ENTER to use this database, or paste another full racing_history.sqlite path'
if ([string]::IsNullOrWhiteSpace($database)) { $database = $defaultDb }
$database = $database.Trim().Trim('"')
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw "Database not found: $database" }

$tempDir = Join-Path $env:TEMP ('horse-checkpoint-' + [guid]::NewGuid().ToString('N'))
New-Item -Path $tempDir -ItemType Directory -Force | Out-Null
try {
    $archive = Join-Path $tempDir 'racing_history.sqlite.gz'
    Checked 'py' @('-3', (Join-Path $scriptRoot 'sl_checkpoint.py'), 'save', $database, $archive)
    $localReport = [string](CaptureChecked 'py' @('-3',(Join-Path $scriptRoot 'sl_checkpoint.py'),'verify',$database))
    if ($localReport -notmatch 'Verified races:\s*(\d+)') { throw "Cannot confirm local race count: $localReport" }
    $localCount = [int]$Matches[1]

    # Listing releases returns successfully when the tag does not exist. Unlike
    # `gh release view missing-tag`, it does not trigger PowerShell's native-command error.
    $releaseJson = [string](CaptureChecked 'gh' @('release','list','-R',$repo,'--limit','100','--json','tagName'))
    $releaseItems = @(ConvertFrom-Json -InputObject $releaseJson)
    $releaseExists = @($releaseItems | Where-Object { $_.tagName -eq $tag }).Count -gt 0
    if (-not $releaseExists) {
        Write-Host 'Creating the first private Release checkpoint.'
        Checked 'gh' @('release','create',$tag,'-R',$repo,'--target','main',
            '--title','Private racing database checkpoint',
            '--notes','SQLite backup for resumable Sporting Life research.', '--prerelease')
    } else {
        # Do not overwrite a newer cloud checkpoint with an old local database.
        $assetJson = [string](CaptureChecked 'gh' @('release','view',$tag,'-R',$repo,'--json','assets'))
        $assets = @((ConvertFrom-Json -InputObject $assetJson).assets)
        if (@($assets | Where-Object { $_.name -eq 'racing_history.sqlite.gz' }).Count -gt 0) {
            $oldDir = Join-Path $tempDir 'previous'; New-Item -Path $oldDir -ItemType Directory | Out-Null
            Checked 'gh' @('release','download',$tag,'-R',$repo,'--pattern','racing_history.sqlite.gz','--dir',$oldDir)
            $oldDb = Join-Path $tempDir 'previous.sqlite'
            Checked 'py' @('-3',(Join-Path $scriptRoot 'sl_checkpoint.py'),'restore',
                (Join-Path $oldDir 'racing_history.sqlite.gz'),$oldDb)
            $oldReport = [string](CaptureChecked 'py' @('-3',(Join-Path $scriptRoot 'sl_checkpoint.py'),'verify',$oldDb))
            if ($oldReport -match 'Verified races:\s*(\d+)') {
                $remoteCount = [int]$Matches[1]
                if ($remoteCount -gt $localCount) {
                    throw "STOP: GitHub already contains $remoteCount races, but the selected local DB has only $localCount. Nothing overwritten."
                }
            }
        }
    }

    Checked 'gh' @('release','upload',$tag,$archive,'-R',$repo,'--clobber')
    Write-Host "SUCCESS: $localCount races uploaded to PRIVATE GitHub checkpoint." -ForegroundColor Green
    Checked 'gh' @('release','view',$tag,'-R',$repo,'--json','tagName,assets','--jq','.tagName, (.assets[] | .name)')
    Write-Host 'The original local SQLite database has not been modified.'
    Write-Host 'Next: review PR #1; verify the GitHub Actions job only after the PR is merged.'
}
finally {
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
