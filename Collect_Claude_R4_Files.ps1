# Collect the minimum useful source context for Claude task R4.
# Run this from the repository root (or pass -ProjectRoot).
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$OutputDir = "_claude_R4_bundle"
)

$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot([string]$Path) {
    $p = (Resolve-Path -LiteralPath $Path).Path
    # The pasted project listing shows a possible nested montage_project folder.
    foreach ($candidate in @($p, (Join-Path $p "montage_project"))) {
        if ((Test-Path (Join-Path $candidate "mt\templates\t4")) -and
            (Test-Path (Join-Path $candidate "mt"))) {
            return (Resolve-Path $candidate).Path
        }
    }
    # Search a few levels down for the actual Python project root.
    $found = Get-ChildItem -LiteralPath $p -Directory -Recurse -ErrorAction SilentlyContinue |
        Where-Object {
            (Test-Path (Join-Path $_.FullName "mt\templates\t4")) -and
            (Test-Path (Join-Path $_.FullName "mt"))
        } | Select-Object -First 1
    if ($found) { return $found.FullName }
    throw "Could not find project root containing mt\templates\t4. Run from the repo root or use -ProjectRoot."
}

$Root = Resolve-ProjectRoot $ProjectRoot
$Out = Join-Path $Root $OutputDir
$Payload = Join-Path $Out "source"
if (Test-Path $Out) { Remove-Item -LiteralPath $Out -Recurse -Force }
New-Item -ItemType Directory -Path $Payload -Force | Out-Null

$included = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Add-ProjectFile([string]$FullPath) {
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) { return }
    $full = (Resolve-Path -LiteralPath $FullPath).Path
    $rel = $full.Substring($Root.Length).TrimStart('\','/')
    if (-not $included.Add($rel)) { return }
    $dest = Join-Path $Payload $rel
    $parent = Split-Path -Parent $dest
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Copy-Item -LiteralPath $full -Destination $dest -Force
}

# Required task guidance. Fail rather than silently omit either file.
foreach ($name in @("T4_RULES.md", "T4_NOTES.md")) {
    $doc = Get-ChildItem -LiteralPath $Root -Filter $name -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '[\\/](\.git|\.venv|venv|node_modules|__pycache__)[\\/]' } |
        Select-Object -First 1
    if (-not $doc) { throw "Required file $name was not found under $Root. Put it in the repo, then rerun." }
    Add-ProjectFile $doc.FullName
}

# All T4 template source: broll must follow existing template conventions.
$t4Dir = Join-Path $Root "mt\templates\t4"
Get-ChildItem -LiteralPath $t4Dir -File -Filter "*.py" | ForEach-Object { Add-ProjectFile $_.FullName }

# Shared rendering, timing, animation, drawing, media and config infrastructure.
$coreFiles = @(
    "mt\__init__.py", "mt\anim.py", "mt\captions.py", "mt\cfg.py",
    "mt\common.py", "mt\draw.py", "mt\flow.py", "mt\fonts.py",
    "mt\render.py", "mt\split.py", "mt\selftest.py",
    "montage.py", "pyproject.toml", "requirements.txt", "setup.cfg"
)
foreach ($rel in $coreFiles) { Add-ProjectFile (Join-Path $Root $rel) }

# Existing T4 validation/check scripts.
$toolsDir = Join-Path $Root "tools"
if (Test-Path $toolsDir) {
    Get-ChildItem -LiteralPath $toolsDir -File -Filter "*.py" |
        Where-Object { $_.Name -match '(^mt_t4_|^p1[7-9]_|broll|video|render|audit)' } |
        ForEach-Object { Add-ProjectFile $_.FullName }
}

# Find implementation references for video-layer baking/compositing and audio continuity.
# Include only source files with relevant code hits, excluding generated/vendor folders.
$patterns = 'bake|baked|video.?layer|layer.?video|composit|overlay|ffmpeg|audio.?stream|audio.?continu|xfade|wipe|transition'
$scanRoots = @("mt", "tools")
foreach ($scan in $scanRoots) {
    $scanPath = Join-Path $Root $scan
    if (-not (Test-Path $scanPath)) { continue }
    Get-ChildItem -LiteralPath $scanPath -Recurse -File |
        Where-Object {
            $_.Extension -in @(".py", ".ts", ".tsx", ".js") -and
            $_.FullName -notmatch '[\\/](\.git|\.venv|venv|node_modules|__pycache__|dist|build)[\\/]'
        } | ForEach-Object {
            $hit = Select-String -LiteralPath $_.FullName -Pattern $patterns -Quiet -ErrorAction SilentlyContinue
            if ($hit) { Add-ProjectFile $_.FullName }
        }
}

# Preserve project metadata/config that may define package behavior.
Get-ChildItem -LiteralPath $Root -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(pyproject\.toml|requirements.*\.txt|setup\.py|setup\.cfg|pytest\.ini|tox\.ini|ruff\.toml|\.python-version)$' } |
    ForEach-Object { Add-ProjectFile $_.FullName }

# Give Claude the exact requested task and verification criteria.
$brief = @'
TASK REF: R4

Read T4_RULES.md and T4_NOTES.md first.

Create: mt/templates/t4/broll.py

Implement a full-canvas takeover of a video/image segment while the speaker audio continues. Add a HUD decoration plate on top:
- diagonal neon light streaks
- faint grid lines
- code icon watermark at top-left
- dot matrix at top-right
- hazard stripes at bottom-left

Use cross-fade or diagonal wipe for entry/exit.
Configuration: {media, start|trigger, hold, decor on/off, anim}.
Use the existing video-layer baking implementation for the clip; do not invent a parallel baking path.

Verify both canvases and confirm speaker audio remains continuous throughout the takeover and transitions. Follow existing project conventions and the guidance in T4_RULES.md / T4_NOTES.md.
'@
Set-Content -LiteralPath (Join-Path $Out "TASK_R4.txt") -Value $brief -Encoding UTF8

$manifest = @(
    "Project root: $Root",
    "Task: R4 - T4 full-canvas B-roll takeover",
    "Included source files:"
) + ($included | Sort-Object | ForEach-Object { "  $_" })
Set-Content -LiteralPath (Join-Path $Out "MANIFEST.txt") -Value $manifest -Encoding UTF8

$zipPath = Join-Path $Root "Claude_R4_source_bundle.zip"
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -LiteralPath (Join-Path $Out "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "R4 bundle created successfully:" -ForegroundColor Green
Write-Host "  ZIP: $zipPath"
Write-Host "  Folder: $Out"
Write-Host "  Source files included: $($included.Count)"
Write-Host ""
Write-Host "Send Claude_R4_source_bundle.zip together with your task prompt."
