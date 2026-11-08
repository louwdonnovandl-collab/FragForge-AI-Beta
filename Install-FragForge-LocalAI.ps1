# FragForge Local AI optional setup. Runs only after user approval.
$ErrorActionPreference = 'Stop'
Write-Host 'FragForge Local AI Setup (Ollama + Qwen3 4B)' -ForegroundColor Cyan
try {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
            if (Test-Path $candidate) { $ollama = @{ Source = $candidate }; break }
        }
    }
    if (-not $ollama) {
        Write-Host 'Installing Ollama through Windows Package Manager...'
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget is missing. Install Ollama from https://ollama.com/download/windows then run setup again.' }
        winget install --id Ollama.Ollama --exact --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Ollama installation failed with code $LASTEXITCODE" }
        foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
            if (Test-Path $candidate) { $ollama = @{ Source = $candidate }; break }
        }
        if (-not $ollama) { $ollama = Get-Command ollama -ErrorAction SilentlyContinue }
    }
    if (-not $ollama) { throw 'Ollama was installed but its executable could not be found. Restart Windows and retry.' }
    $exe = $ollama.Source
    Write-Host "Using $exe"
    Write-Host 'Downloading free Qwen3 4B model. This may take several minutes and several GB of disk space.'
    & $exe pull qwen3:4b
    if ($LASTEXITCODE -ne 0) { throw "Model download failed with code $LASTEXITCODE" }
    Write-Host 'Local AI installed. Open FragForge > Mr Director > Connect.' -ForegroundColor Green
} catch {
    Write-Host "SETUP FAILED: $_" -ForegroundColor Red
    exit 1
}
