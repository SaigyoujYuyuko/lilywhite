param(
    [string]$Name
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = Read-Host "Project package name (for example consumer_store)"
}
$Name = $Name.Trim()

if ($Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
    throw "Invalid Python package name. Use letters, digits and underscores; the first character cannot be a digit."
}

$pythonKeywords = @(
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally", "for",
    "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
    "or", "pass", "raise", "return", "try", "while", "with", "yield", "match", "case", "type"
)
if ($pythonKeywords -contains $Name) {
    throw "'$Name' is a Python keyword and cannot be used as a package name."
}

$sourcePackage = Join-Path $PSScriptRoot "lilywhite"
$targetPackage = Join-Path $PSScriptRoot $Name
if (-not (Test-Path -LiteralPath $sourcePackage -PathType Container)) {
    throw "The 'lilywhite' package was not found. Run this script in a fresh template copy."
}
if ($Name -ceq "lilywhite") {
    Write-Host "The package is already named 'lilywhite'."
    exit 0
}
if (Test-Path -LiteralPath $targetPackage) {
    throw "The target path already exists: $targetPackage"
}

$textExtensions = @(".py", ".md", ".toml", ".yaml", ".yml", ".json")
$files = @(
    Get-ChildItem -LiteralPath $sourcePackage -Recurse -File |
        Where-Object { $textExtensions -contains $_.Extension.ToLowerInvariant() }
)
foreach ($rootFile in @("README.md", "pyproject.toml", "config.example.yaml", "config.yaml", "uv.lock")) {
    $path = Join-Path $PSScriptRoot $rootFile
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $files += Get-Item -LiteralPath $path
    }
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
$updatedFiles = 0
foreach ($file in $files) {
    $content = [System.IO.File]::ReadAllText($file.FullName)
    $updated = [regex]::Replace($content, '\blilywhite\b', $Name)
    if ($updated -cne $content) {
        [System.IO.File]::WriteAllText($file.FullName, $updated, $utf8)
        $updatedFiles += 1
    }
}

foreach ($metadataFile in @("pyproject.toml", "uv.lock")) {
    $path = Join-Path $PSScriptRoot $metadataFile
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $content = [System.IO.File]::ReadAllText($path)
        $updated = [regex]::Replace(
            $content,
            '(?m)^name = "(?:lilywhite|reuse-server-template)"$',
            ('name = "' + $Name + '"')
        )
        if ($updated -cne $content) {
            [System.IO.File]::WriteAllText($path, $updated, $utf8)
        }
    }
}

Rename-Item -LiteralPath $sourcePackage -NewName $Name

Write-Host ""
Write-Host "Renamed package 'lilywhite' to '$Name' and updated $updatedFiles files."
Write-Host "Next steps:"
Write-Host "  uv sync"
Write-Host "  uv run python -m $Name --config config.yaml"
