#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$BuildPackage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($DryRun -eq $BuildPackage) { throw 'Specify exactly one of -DryRun or -BuildPackage.' }
$root = $PSScriptRoot
$component = Join-Path $root 'custom_components/powermesh_energy'
$manifest = Get-Content -LiteralPath (Join-Path $component 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.domain -ne 'powermesh_energy' -or $manifest.version -ne '0.6.0') {
    throw 'Expected the powermesh_energy 0.6.0 baseline.'
}
$const = Get-Content -LiteralPath (Join-Path $component 'const.py') -Raw
if ($const -notmatch '(?m)^VERSION:\s*Final\s*=\s*"0\.6\.0"\s*$') { throw 'manifest.json and const.py versions do not agree.' }
$files = [System.Collections.Generic.List[string]]::new()
foreach ($directory in @((Join-Path $root 'custom_components'), $component)) {
    if ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Symbolic links are not allowed in component inputs.' }
}
foreach ($file in Get-ChildItem -LiteralPath $component -Recurse -Force) {
    if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Symbolic links are not allowed in component inputs.' }
    if ($file.PSIsContainer) { continue }
    $relative = [IO.Path]::GetRelativePath($root, $file.FullName).Replace('\', '/')
    if ($relative -match '/__pycache__/' -or $file.Extension -notin @('.py', '.json')) { continue }
    if ($relative -match '/\.' -or $file.Name -eq 'secrets.json') { throw 'Hidden or secret files are not component inputs.' }
    $files.Add($relative)
}
$files.Add('LICENSE')
if (-not (Test-Path -LiteralPath (Join-Path $root 'LICENSE') -PathType Leaf) -or
    ((Get-Item -LiteralPath (Join-Path $root 'LICENSE')).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'A regular LICENSE file is required.'
}
if ($DryRun) {
    $files | Sort-Object
    Write-Output 'Offline package plan only. No Home Assistant connection, installation, release or upload.'
    return
}
$dist = Join-Path $root 'dist'
if (Test-Path -LiteralPath $dist) {
    if ((Get-Item -LiteralPath $dist).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'dist must not be a symbolic link.' }
} else {
    [void][IO.Directory]::CreateDirectory($dist)
}
$target = Join-Path $dist "powermesh-energy-homeassistant-$($manifest.version).zip"
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew)
$completed = $false
try {
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($relative in ($files | Sort-Object)) {
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, (Join-Path $root $relative), $relative)
        }
    } finally {
        $zip.Dispose()
    }
    $completed = $true
} finally {
    $stream.Dispose()
    if (-not $completed) { Remove-Item -LiteralPath $target }
}
Write-Output "Created $target"
Write-Output 'Unpack custom_components/powermesh_energy into the Home Assistant configuration directory and restart Home Assistant. No existing entries or buffers were modified.'
