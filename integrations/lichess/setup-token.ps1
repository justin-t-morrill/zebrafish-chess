$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$target = Join-Path $root 'local\config\lichess\config.yml'
if (Test-Path -LiteralPath $target) { throw 'A private configuration already exists. Back it up before replacing it.' }
$secure = Read-Host 'Paste the Lichess BOT token (stored only on this computer)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ($token -notmatch '^[A-Za-z0-9_-]+$') { throw 'The token contains unexpected characters or whitespace.' }
    $text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'config.yml.example')).Replace('PASTE_LICHESS_BOT_TOKEN_HERE',$token)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    [IO.File]::WriteAllText($target,$text,[Text.UTF8Encoding]::new($false))
} finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $token = $null }
Write-Output 'Saved the private bot configuration under local/config/lichess. It is excluded from Git.'
