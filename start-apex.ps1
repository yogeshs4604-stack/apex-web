$ErrorActionPreference = "Stop"

$backendPath = Join-Path $PSScriptRoot "backend"
$pythonPath = Join-Path $backendPath ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonPath)) {
    python -m venv (Join-Path $backendPath ".venv")
    & $pythonPath -m pip install -r (Join-Path $backendPath "requirements.txt")
}

$secureKey = Read-Host "Paste your NEW Anthropic API key" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
    $env:ANTHROPIC_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}

$env:APEX_JWT_SECRET = "local-dev-secret-$([Guid]::NewGuid().ToString('N'))"
$env:APEX_SANDBOX_MODE = "local_dev_INSECURE"

Set-Location $backendPath
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000