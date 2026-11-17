param(
  [Parameter(Mandatory=$false)]
  [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
  $ProjectRoot = Read-Host 'Paste the full path of your local horse project (containing package.json)'
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot.Trim('"'))

$files = @(
  'web/src/app/race/[id]/page.tsx',
  'web/src/components/RaceSectionals.tsx',
  'web/src/components/RaceIntelligence.tsx',
  'web/src/components/RaceIntelligence.module.css',
  'web/src/components/RaceSectionals.module.css'
)
$required = @(
  'package.json',
  'web/src/lib/racing.ts',
  'web/src/components/RaceCard.tsx',
  'web/src/components/RaceSectionals.tsx',
  'web/src/app/race/[id]/page.tsx'
)
foreach ($rel in $required) {
  $p = Join-Path $ProjectRoot $rel
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
    throw "This does not look like the expected FurlongIQ project. Missing: $p. No files copied."
  }
}
foreach ($rel in $files) {
  $p = Join-Path $PSScriptRoot $rel
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
    throw "Upgrade package incomplete. Missing: $p. No files copied."
  }
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path ([System.IO.Directory]::GetParent($ProjectRoot).FullName) "furlongiq-backup-before-race-intelligence-$stamp"
[void][System.IO.Directory]::CreateDirectory($backup)
foreach ($rel in $files) {
  $original = Join-Path $ProjectRoot $rel
  if (Test-Path -LiteralPath $original -PathType Leaf) {
    $to = Join-Path $backup $rel
    [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($to))
    Copy-Item -LiteralPath $original -Destination $to -ErrorAction Stop
  }
}
foreach ($rel in $files) {
  $source = Join-Path $PSScriptRoot $rel
  $dest = Join-Path $ProjectRoot $rel
  [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($dest))
  Copy-Item -LiteralPath $source -Destination $dest -Force -ErrorAction Stop
  Write-Host "Installed: $rel"
}
Write-Host "`nUpgrade files copied. Backup: $backup" -ForegroundColor Green
Write-Host "Next: cd `"$ProjectRoot`"; npm run typecheck; npm run dev"
Write-Host 'Do not push/deploy until you have checked the layout and both race screens.'
