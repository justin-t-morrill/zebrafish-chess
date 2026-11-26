$ErrorActionPreference = 'Stop'
$name = 'Zebrafish Lichess Bot'
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$runner = Join-Path $PSScriptRoot 'run-bot.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '" -Standby')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -User $account -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "Enabled the Zebrafish Lichess Bot task for $account. It starts at Windows sign-in."
