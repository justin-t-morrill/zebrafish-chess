$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "review_gui.py"
python $source
