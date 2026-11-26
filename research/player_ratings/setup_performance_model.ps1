$ErrorActionPreference = "Stop"
$runtime = Join-Path $PSScriptRoot "model_runtime"
$bundledPython = "C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$python = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { "python" }
& $python -m pip install --target $runtime "numpy>=2.1,<3" "catboost>=1.2.8,<2"
if ($LASTEXITCODE -ne 0) { throw "Performance-model dependency installation failed." }
Write-Host "Performance-model dependencies installed in $runtime"
