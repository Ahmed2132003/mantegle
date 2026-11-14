[CmdletBinding()]
param(
    [string]$Root = (Get-Location).Path,
    [string]$OutputFile = "T4_CLAUDE_CONTEXT.txt"
)

$ErrorActionPreference = "Stop"

# Resolve the project root. The expected root contains montage.py and mt\templates\t4.
$Root = (Resolve-Path -LiteralPath $Root).Path
if (-not (Test-Path -LiteralPath (Join-Path $Root "montage.py")) -or
    -not (Test-Path -LiteralPath (Join-Path $Root "mt\templates\t4"))) {

    $nestedRoot = Join-Path $Root "montage_project"
    if ((Test-Path -LiteralPath (Join-Path $nestedRoot "montage.py")) -and
        (Test-Path -LiteralPath (Join-Path $nestedRoot "mt\templates\t4"))) {
        $Root = (Resolve-Path -LiteralPath $nestedRoot).Path
    }
    else {
        throw "Project root not found. Run this script from the folder containing montage.py and mt\templates\t4, or pass the path using -Root."
    }
}

if ([System.IO.Path]::IsPathRooted($OutputFile)) {
    $OutputPath = $OutputFile
}
else {
    $OutputPath = Join-Path $Root $OutputFile
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

# Exclude duplicate/temporary copies so the bundle reflects the active project only.
$ExcludedDirectoryNames = @(
    "_send_min",
    "_send_step4",
    "_send_t4"
)

function Test-IsExcludedPath {
    param([string]$Path)

    $relative = $Path.Substring($Root.Length).TrimStart('\', '/')
    $parts = $relative -split '[\\/]'
    if ($parts -contains "montage_project") { return $true }
    foreach ($part in $parts) {
        if ($ExcludedDirectoryNames -contains $part) { return $true }
    }
    return $false
}

function Get-RelativePath {
    param([string]$Path)
    return $Path.Substring($Root.Length).TrimStart('\', '/')
}

# Enumerate text/source files once. Video, audio, images and other binaries are not included.
$AllowedExtensions = @(
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".ps1", ".ts", ".tsx"
)

$AllTextFiles = @(
    Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        -not (Test-IsExcludedPath $_.FullName) -and
        $_.FullName -ne $OutputPath -and
        ($AllowedExtensions -contains $_.Extension.ToLowerInvariant())
    }
)

$Selected = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
$Missing = [System.Collections.Generic.List[string]]::new()

function Add-ProjectFile {
    param([string]$RelativePath)

    $full = Join-Path $Root $RelativePath
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $resolved = (Resolve-Path -LiteralPath $full).Path
        if (-not (Test-IsExcludedPath $resolved) -and $resolved -ne $OutputPath) {
            [void]$Selected.Add($resolved)
        }
    }
    else {
        $Missing.Add($RelativePath)
    }
}

# Core files explicitly requested.
$CoreFiles = @(
    "montage.py",
    "mt\render.py",
    "mt\common.py",
    "mt\templates\t3\layout.py",
    "mt\anim.py",

    "mt\templates\t4\cfg.py",
    "mt\templates\t4\split.py",
    "mt\templates\t4\split_video.py",
    "mt\templates\t4\timing.py",
    "mt\templates\t4\frame.py",
    "mt\templates\t4\base.py",
    "mt\templates\t4\__init__.py",

    "tools\mt_t4_split_check.py",
    "tools\mt_t4_quick.py",
    "tools\mt_move.py",
    "mt_move.py",
    "baseline\mt_move_test_common.py",
    "mt\selftest.py"
)

foreach ($file in $CoreFiles) { Add-ProjectFile $file }

# Find T4 rules/notes wherever they live in the active project.
$RuleFiles = @(
    $AllTextFiles | Where-Object {
        $_.Name -in @("T4_RULES.md", "T4_NOTES.md")
    }
)
foreach ($file in $RuleFiles) { [void]$Selected.Add($file.FullName) }

# Include R7-related source/config files and job/config files that mention R7.
$R7Files = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
$JobConfigFiles = [System.Collections.Generic.List[System.IO.FileInfo]]::new()

foreach ($file in $AllTextFiles) {
    $isJobConfigName = ($file.BaseName -match '(?i)(job|config|cfg|settings)') -and
                       ($file.Extension -match '(?i)^\.(json|ya?ml|toml|ini|cfg|conf)$')
    $content = $null
    try {
        $content = [System.IO.File]::ReadAllText($file.FullName)
    }
    catch {
        continue
    }

    if ($file.Name -match '(?i)R7' -or $content -match '(?i)\bR7\b') {
        $R7Files.Add($file)
        [void]$Selected.Add($file.FullName)
    }

    if ($isJobConfigName) {
        $JobConfigFiles.Add($file)
        # Job/config files are useful even if R7 is referenced indirectly.
        [void]$Selected.Add($file.FullName)
    }
}

# Build a searchable P19 occurrence report from the active code/docs.
$P19Matches = [System.Collections.Generic.List[string]]::new()
foreach ($file in $AllTextFiles) {
    try {
        $lines = [System.IO.File]::ReadAllLines($file.FullName)
        for ($i = 0; $i -lt $lines.Length; $i++) {
            if ($lines[$i] -match '(?i)P19') {
                $P19Matches.Add(("{0}:{1}: {2}" -f (Get-RelativePath $file.FullName), ($i + 1), $lines[$i].Trim()))
                [void]$Selected.Add($file.FullName)
            }
        }
    }
    catch {
        # Skip unreadable text files and continue collecting the rest.
    }
}

# Assemble one UTF-8 bundle with clear file boundaries.
$Builder = [System.Text.StringBuilder]::new()
[void]$Builder.AppendLine("T4 / R7 PROJECT CONTEXT BUNDLE")
[void]$Builder.AppendLine("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$Builder.AppendLine("Project root: $Root")
[void]$Builder.AppendLine("Output: $OutputPath")
[void]$Builder.AppendLine("")
[void]$Builder.AppendLine("IMPORTANT: This bundle contains text/source files only. Media files are intentionally not embedded.")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== COLLECTION SUMMARY =====")
[void]$Builder.AppendLine("Collected files: $($Selected.Count)")
[void]$Builder.AppendLine("T4_RULES/T4_NOTES found: $($RuleFiles.Count)")
[void]$Builder.AppendLine("Files mentioning R7 or named with R7: $($R7Files.Count)")
[void]$Builder.AppendLine("Job/config files included: $($JobConfigFiles.Count)")
[void]$Builder.AppendLine("P19 matches: $($P19Matches.Count)")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== MISSING REQUESTED FILES =====")
if ($Missing.Count -eq 0) {
    [void]$Builder.AppendLine("(None)")
}
else {
    foreach ($item in $Missing) { [void]$Builder.AppendLine($item) }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== T4 RULES / NOTES DISCOVERY =====")
if ($RuleFiles.Count -eq 0) {
    [void]$Builder.AppendLine("T4_RULES.md and T4_NOTES.md were not found inside the project root.")
}
else {
    foreach ($file in $RuleFiles) {
        [void]$Builder.AppendLine((Get-RelativePath $file.FullName))
    }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== R7 FILE DISCOVERY =====")
if ($R7Files.Count -eq 0) {
    [void]$Builder.AppendLine("No R7 references found in scanned text files.")
}
else {
    foreach ($file in ($R7Files | Sort-Object FullName -Unique)) {
        [void]$Builder.AppendLine((Get-RelativePath $file.FullName))
    }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== JOB / CONFIG FILES INCLUDED =====")
if ($JobConfigFiles.Count -eq 0) {
    [void]$Builder.AppendLine("No job/config files found by filename pattern.")
}
else {
    foreach ($file in ($JobConfigFiles | Sort-Object FullName -Unique)) {
        [void]$Builder.AppendLine((Get-RelativePath $file.FullName))
    }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== P19 SEARCH RESULTS =====")
if ($P19Matches.Count -eq 0) {
    [void]$Builder.AppendLine("No P19 matches found.")
}
else {
    foreach ($match in $P19Matches) { [void]$Builder.AppendLine($match) }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== CANVAS / TEST MEDIA DETAILS =====")
[void]$Builder.AppendLine("Canvas dimensions (both canvases): NOT automatically inferable with confidence; please specify.")
[void]$Builder.AppendLine("R7 test clip: media is not embedded. Include a 5-10 second clip separately, or provide resolution, FPS, and speaker position.")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== FILE CONTENTS =====")
foreach ($path in ($Selected | Sort-Object)) {
    $relative = Get-RelativePath $path
    [void]$Builder.AppendLine("")
    [void]$Builder.AppendLine(("`n" + ("=" * 90)))
    [void]$Builder.AppendLine("FILE: $relative")
    [void]$Builder.AppendLine(("=" * 90))
    try {
        $content = [System.IO.File]::ReadAllText($path)
        [void]$Builder.AppendLine($content)
    }
    catch {
        [void]$Builder.AppendLine("[ERROR reading file: $($_.Exception.Message)]")
    }
    [void]$Builder.AppendLine("")
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($OutputPath, $Builder.ToString(), $utf8NoBom)

Write-Host ""
Write-Host "Bundle created successfully:" -ForegroundColor Green
Write-Host $OutputPath -ForegroundColor Cyan
Write-Host "Send the generated bundle to Claude. Attach the test video separately if available."
Write-Host "Send the generated bundle to Claude. Attach the test video separately if available."
Write-Host "Send the generated bundle to Claude. Attach the test video separately if available."
Write-Host "Send the generated bundle to Claude. Attach the test video separately if available."
Write-Host ""
Write-Host "Send the generated bundle to Claude. Attach the test video separately if available."
