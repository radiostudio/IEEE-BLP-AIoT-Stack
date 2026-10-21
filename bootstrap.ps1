# Downloads the AIoT gateway course code and runs the one-command setup, so
# a student can go from nothing to a working environment with one line:
#
#   iwr <raw-url-of-this-file> -UseBasicParsing | iex
#
# To pass extra flags through (e.g. --with-pptx), download this file first,
# then run it directly:
#
#   .\bootstrap.ps1 --with-pptx
#
# IMPORTANT: this never calls "exit". When this file's content is piped
# into "iex" (Invoke-Expression) - the whole point of the one-liner - it
# runs inline in the CURRENT PowerShell session, not as a separate process,
# so a bare "exit" would close the student's entire PowerShell window
# instantly, wiping out every message before they can read it.
#
# It also deliberately does NOT wrap the logic in a function whose result
# gets assigned to a variable (e.g. "$code = MyFunction"). Doing that once
# caused a real bug here: capturing a function's return value captures
# EVERYTHING it emits, including every line of console output from the
# nested setup process invoked below - so the "exit code" variable ended
# up as a giant array of all that text with the real number tacked on the
# end, and a single-element array like @(0) evaluates as falsy in an "if",
# making a successful run look like a failure. Using a plain top-level
# "do { ... } while ($false)" block with "break" for early exits avoids
# this entirely, since nothing is ever captured from an assignment.
#
# NOTE: $RepoZipUrl below points at a branch. Update it to point at `main`
# once feature/onboarding-scripts merges.

$RepoZipUrl = "https://github.com/sriram-rs/IEEE-BLP-AIoT-Stack/archive/refs/heads/feature/onboarding-scripts.zip"
$DestDir = Join-Path (Get-Location) "IEEE-BLP-AIoT-Stack"
$ExitCode = 1

:main do {
    Write-Host "== Downloading the AIoT Gateway course code =="

    # The real, careful Python-version check happens later in setup.bat,
    # once it's downloaded - here we just need any Python 3 to run
    # start_installation.py.
    $PyExe = $null
    $PyArgs = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PyExe = "py"; $PyArgs = @("-3")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PyExe = "python"; $PyArgs = @()
    }

    if (-not $PyExe) {
        Write-Host "No Python installation was found on this machine."
        Write-Host "Install Python 3.10 or newer from https://www.python.org/downloads/windows/"
        Write-Host "IMPORTANT: check 'Add python.exe to PATH' during install, then run this command again."
        Write-Host ""
        Write-Host "If this is a school/managed laptop and you cannot install software,"
        Write-Host "ask your instructor for help."
        $ExitCode = 1
        break main
    }

    $TmpZip = Join-Path $env:TEMP ("aiot-stack-" + [guid]::NewGuid().ToString() + ".zip")
    try {
        Invoke-WebRequest -Uri $RepoZipUrl -OutFile $TmpZip -UseBasicParsing
    } catch {
        Write-Host "Could not download the code. Check your internet connection and try again."
        $ExitCode = 2
        break main
    }

    $ExtractDir = Join-Path $env:TEMP ("aiot-stack-extract-" + [guid]::NewGuid().ToString())
    try {
        Expand-Archive -Path $TmpZip -DestinationPath $ExtractDir -Force
    } catch {
        Write-Host "Downloaded the code but could not extract it. Ask your instructor for help."
        Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
        $ExitCode = 3
        break main
    }
    Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue

    $SrcDir = Get-ChildItem -Path $ExtractDir -Directory | Select-Object -First 1
    if (-not $SrcDir) {
        Write-Host "Downloaded the code but couldn't find it after extracting."
        Write-Host "Ask your instructor for help."
        $ExitCode = 4
        break main
    }

    if (Test-Path $DestDir) {
        Write-Host "Folder $DestDir already exists - using it as-is instead of overwriting."
    } else {
        Move-Item $SrcDir.FullName $DestDir
    }
    Remove-Item -Recurse -Force $ExtractDir -ErrorAction SilentlyContinue

    Write-Host "Code is in: $DestDir"
    Set-Location $DestDir
    Write-Host "Running setup..."
    & $PyExe @PyArgs "start_installation.py" @args
    $ExitCode = $LASTEXITCODE
} while ($false)

Write-Host ""
if ($ExitCode -eq 0) {
    # The PREREQUISITES.md reminder already printed above, as part of
    # setup.bat's own output - not repeated here.
    Write-Host "== Setup finished successfully. ==" -ForegroundColor Green
} else {
    Write-Host "== Setup did NOT finish successfully (exit code $ExitCode). ==" -ForegroundColor Red
    Write-Host "Scroll up to read the error message. Copy it and ask your instructor for help."
}
Write-Host ""
Write-Host "You are now in: $(Get-Location)"
Read-Host "Press Enter to continue (this window stays open - it does not close)"
