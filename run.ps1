[CmdletBinding()]
param(
    [ValidateSet('setup','check','sender','demo','test','build','launch','launch-demo')]
    [string]$Action = 'launch',
    [string]$Python = 'python',
    [string]$Blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
    [ValidateRange(1,65535)][int]$Port = 9009,
    [ValidateSet('desktop','hmd','screen-top')][string]$Mode = 'desktop'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$senderScript = Join-Path $projectRoot 'sender\sender.py'

function Assert-Success {
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
function Assert-Python {
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run .\run.cmd setup first.' }
}
function Assert-Blender {
    if (-not (Test-Path -LiteralPath $Blender)) { throw "Blender not found: $Blender. Pass -Blender with the path to Blender 5.2." }
}

Push-Location -LiteralPath $projectRoot
try {
    switch ($Action) {
        'setup' {
            & $Python -m venv (Join-Path $projectRoot '.venv')
            Assert-Success
            & $venvPython -m pip install -r (Join-Path $projectRoot 'sender\requirements.txt')
            Assert-Success
            Write-Host 'Ready. Run .\run.cmd launch or .\run.cmd launch-demo.'
        }
        'check' {
            Assert-Python
            & $venvPython $senderScript --check --port $Port --mode $Mode
            Assert-Success
        }
        'sender' {
            Assert-Python
            & $venvPython $senderScript --port $Port --mode $Mode
            Assert-Success
        }
        'demo' {
            Assert-Python
            & $venvPython $senderScript --demo --port $Port
            Assert-Success
        }
        'test' {
            Assert-Python
            Assert-Blender
            & $venvPython -m unittest discover -s tests -p 'test_*.py' -v
            Assert-Success
            & $Blender --background --factory-startup --python-exit-code 1 --python (Join-Path $projectRoot 'tests\blender_integration.py')
            Assert-Success
        }
        'build' {
            Assert-Blender
            New-Item -ItemType Directory -Path (Join-Path $projectRoot 'dist') -Force | Out-Null
            & $Blender --command extension validate (Join-Path $projectRoot 'leap_live_link')
            Assert-Success
            & $Blender --command extension build --source-dir (Join-Path $projectRoot 'leap_live_link') --output-dir (Join-Path $projectRoot 'dist')
            Assert-Success
        }
        { $_ -in 'launch','launch-demo' } {
            Assert-Python
            Assert-Blender
            $startupScript = Join-Path $projectRoot 'scripts\start_blender.py'
            $launchArgs = '--factory-startup --python "{0}" -- --port {1} --mode {2}' -f $startupScript,$Port,$Mode
            if ($Action -eq 'launch-demo') { $launchArgs += ' --demo' }
            # Blender is the visible interactive tool; its sender runs hidden.
            Start-Process -FilePath $Blender -WorkingDirectory $projectRoot -ArgumentList $launchArgs | Out-Null
            Write-Host 'Blender opened with the receiver and sender. Close Blender to stop its sender.'
        }
    }
} finally {
    Pop-Location
}
