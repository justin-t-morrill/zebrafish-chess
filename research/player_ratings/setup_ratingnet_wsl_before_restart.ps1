# Run this file once from an Administrator PowerShell window.
$ErrorActionPreference = "Stop"

Write-Host "Enabling WSL 2 and Virtual Machine Platform..."
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
$WslExitCode = $LASTEXITCODE
# DISM 3010 means success with a restart required.
if ($WslExitCode -notin @(0, 3010)) {
    throw "Could not enable Windows Subsystem for Linux (DISM exit $WslExitCode)."
}
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
$VmExitCode = $LASTEXITCODE
if ($VmExitCode -notin @(0, 3010)) {
    throw "Could not enable Virtual Machine Platform (DISM exit $VmExitCode)."
}

Write-Host "The required Windows features are enabled. Restart Windows now."
Write-Host "After the restart, return to this task; Ubuntu and ROCm still need installation."
