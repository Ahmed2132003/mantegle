[CmdletBinding()]
param(
    [string]$Root = (Get-Location).Path,
    [string]$OutputFile = "T4_CLAUDE_CONTEXT.txt"
)

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 compatible. This script collects ONLY the explicit
# allowlist below. It does not recursively scan the project for R7, P19,
# job/config files, or other source files.

$Root = (Resolve-Path -LiteralPath $Root).Path

# If launched one level above the active project, use the nested project root.
if (-not (Test-Path -LiteralPath (Join-Path $Root "montage.py")) -or
    -not (Test-Path -LiteralPath (Join-Path $Root "mt\templates\t4"))) {
    $nested = Join-Path $Root "montage_project"
    if ((Test-Path -LiteralPath (Join-Path $nested "montage.py")) -and
        (Test-Path -LiteralPath (Join-Path $nested "mt\templates\t4"))) {
        $Root = (Resolve-Path -LiteralPath $nested).Path
    }
    else {
        throw "Project root not found. Run from the folder containing montage.py and mt\templates\t4, or use -Root."
    }
}

if ([System.IO.Path]::IsPathRooted($OutputFile)) {
    $OutputPath = [System.IO.Path]::GetFullPath($OutputFile)
}
else {
    $OutputPath = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputFile))
}

function Get-RelPath {
    param([string]$Path)
    return $Path.Substring($Root.Length).TrimStart('\', '/')
}

# EXACT requested source paths only.
$RequestedFiles = @(
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

# Rules/notes: check only the project root and the explicitly relevant folders.
$RuleNoteCandidates = @(
    "T4_RULES.md",
    "T4_NOTES.md",
    "docs\T4_RULES.md",
    "docs\T4_NOTES.md",
    "mt\templates\t4\T4_RULES.md",
    "mt\templates\t4\T4_NOTES.md"
)

$Selected = New-Object 'System.Collections.Generic.List[string]'
$Missing = New-Object 'System.Collections.Generic.List[string]'
$Seen = @{}

foreach ($relative in $RequestedFiles) {
    $full = Join-Path $Root $relative
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $resolved = (Resolve-Path -LiteralPath $full).Path
        $key = $resolved.ToLowerInvariant()
        if (-not $Seen.ContainsKey($key) -and $resolved -ne $OutputPath) {
            $Seen[$key] = $true
            $Selected.Add($resolved)
        }
    }
    else {
        $Missing.Add($relative)
    }
}

$FoundRuleNotes = New-Object 'System.Collections.Generic.List[string]'
foreach ($relative in $RuleNoteCandidates) {
    $full = Join-Path $Root $relative
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $resolved = (Resolve-Path -LiteralPath $full).Path
        $key = $resolved.ToLowerInvariant()
        if (-not $Seen.ContainsKey($key)) {
            $Seen[$key] = $true
            $Selected.Add($resolved)
        }
        $FoundRuleNotes.Add($relative)
    }
}

# P19 is searched ONLY inside the allowlisted files already selected.
$P19Report = New-Object 'System.Collections.Generic.List[string]'
foreach ($path in $Selected) {
    try {
        $lines = [System.IO.File]::ReadAllLines($path)
        for ($i = 0; $i -lt $lines.Length; $i++) {
            if ($lines[$i] -match '(?i)P19') {
                $P19Report.Add(("{0}:{1}: {2}" -f (Get-RelPath $path), ($i + 1), $lines[$i].Trim()))
            }
        }
    }
    catch {
        # Continue if a selected file cannot be read as text.
    }
}

$Builder = New-Object System.Text.StringBuilder
[void]$Builder.AppendLine("T4 / R7 - STRICT REQUESTED FILES ONLY")
[void]$Builder.AppendLine("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$Builder.AppendLine("Project root: $Root")
[void]$Builder.AppendLine("")
[void]$Builder.AppendLine("Collection policy: explicit file allowlist only.")
[void]$Builder.AppendLine("No recursive content scan. No automatic R7/config/job file discovery.")
[void]$Builder.AppendLine("P19 search is limited to the selected files listed in this bundle.")
[void]$Builder.AppendLine("Nested duplicate project and _send_* folders are never searched.")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== SUMMARY =====")
[void]$Builder.AppendLine("Files included: $($Selected.Count)")
[void]$Builder.AppendLine("P19 matches in included files: $($P19Report.Count)")
[void]$Builder.AppendLine("T4 rules/notes found: $($FoundRuleNotes.Count)")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== INCLUDED FILES =====")
foreach ($path in $Selected) {
    [void]$Builder.AppendLine((Get-RelPath $path))
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== MISSING REQUESTED FILES =====")
if ($Missing.Count -eq 0) {
    [void]$Builder.AppendLine("(None)")
}
else {
    foreach ($item in $Missing) { [void]$Builder.AppendLine($item) }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== T4 RULES / NOTES =====")
if ($FoundRuleNotes.Count -eq 0) {
    [void]$Builder.AppendLine("Not found in the limited locations checked: project root, docs, mt\templates\t4.")
}
else {
    foreach ($item in $FoundRuleNotes) { [void]$Builder.AppendLine($item) }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== P19 OCCURRENCES (SELECTED FILES ONLY) =====")
if ($P19Report.Count -eq 0) {
    [void]$Builder.AppendLine("(No P19 occurrences in the selected files.)")
}
else {
    foreach ($item in $P19Report) { [void]$Builder.AppendLine($item) }
}
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== TEST VIDEO / CANVAS INFORMATION =====")
[void]$Builder.AppendLine("The video is not embedded. Attach the requested short test clip separately if needed.")
[void]$Builder.AppendLine("Canvas dimensions and video properties are not guessed by this script.")
[void]$Builder.AppendLine("")

[void]$Builder.AppendLine("===== FILE CONTENTS =====")
foreach ($path in $Selected) {
    [void]$Builder.AppendLine("")
    [void]$Builder.AppendLine(("=" * 88))
    [void]$Builder.AppendLine("FILE: $(Get-RelPath $path)")
    [void]$Builder.AppendLine(("=" * 88))
    try {
        [void]$Builder.AppendLine([System.IO.File]::ReadAllText($path))
    }
    catch {
        [void]$Builder.AppendLine("[Could not read this file: $($_.Exception.Message)]")
    }
    [void]$Builder.AppendLine("")
}

$encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutputPath, $Builder.ToString(), $encoding)

Write-Host ""
Write-Host "Done. Strict bundle created:" -ForegroundColor Green
Write-Host $OutputPath -ForegroundColor Cyan
Write-Host "Included files: $($Selected.Count)"
Write-Host "P19 matches (selected files only): $($P19Report.Count)"
Write-Host "No full-project scan was performed."
