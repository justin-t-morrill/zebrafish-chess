param([switch]$ApplyPatch)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$checkout = Join-Path $root 'third_party\lichess-bot'
if (-not (Test-Path -LiteralPath (Join-Path $checkout 'lichess-bot.py'))) { throw 'Restore the pinned bot checkout first; see README.md.' }
$patch = Join-Path $PSScriptRoot 'patches\local-bridge.patch'
$legacyCheckout = Join-Path $root 'integrations\lichess-bot'
& git -c "safe.directory=$checkout" -c "safe.directory=$legacyCheckout" -C $checkout apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -eq 0) { Write-Output 'Zebrafish bridge patch is already installed.'; exit 0 }
& git -c "safe.directory=$checkout" -c "safe.directory=$legacyCheckout" -C $checkout apply --check $patch
if ($LASTEXITCODE -ne 0) { throw 'The bot checkout differs from the pinned bridge. Its local changes were left intact.' }
if ($ApplyPatch) {
    & git -c "safe.directory=$checkout" -c "safe.directory=$legacyCheckout" -C $checkout apply $patch
    if ($LASTEXITCODE -ne 0) { throw 'Bridge patch failed.' }
} else { Write-Output 'Patch applies cleanly. Re-run with -ApplyPatch to install it.' }
