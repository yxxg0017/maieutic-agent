# 构建独立 sidecar 可执行文件（Windows）。
# 产物命名必须带 Rust target triple，Tauri externalBin 才能解析。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$OutDir = Join-Path $Root "apps/desktop/src-tauri/binaries"
$Venv = Join-Path $Backend ".venv"
$Python = Join-Path $Venv "Scripts/python.exe"

if (-not (Test-Path $Python)) {
    uv venv --python 3.11 $Venv
}

Push-Location $Backend
uv pip install --python $Python -e ".[dev]"

$Triple = (rustc -vV | Select-String '^host:').ToString().Split(' ')[1]
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Remove-Item -Recurse -Force (Join-Path $Backend "build"), (Join-Path $Backend "dist") -ErrorAction SilentlyContinue

& $Python -m PyInstaller --noconfirm --clean --onefile `
    --name kel-sidecar `
    --paths src `
    --collect-all langgraph `
    --collect-all langgraph_checkpoint `
    --collect-all langchain_core `
    --collect-submodules kel `
    --hidden-import aiosqlite `
    --hidden-import sqlite3 `
    --hidden-import keyring.backends.Windows `
    sidecar_entry.py
Pop-Location

$Target = Join-Path $OutDir "kel-sidecar-$Triple.exe"
Copy-Item (Join-Path $Backend "dist/kel-sidecar.exe") $Target -Force
Write-Host "已生成 $Target"

# smoke test：ready 事件与健康检查
$SmokeDir = Join-Path $env:TEMP ("kel-smoke-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $SmokeDir | Out-Null
$ReadyFile = Join-Path $SmokeDir "ready.json"
$env:KEL_SESSION_TOKEN = "smoketoken"
$Process = Start-Process -FilePath $Target -ArgumentList "--data-dir", $SmokeDir `
    -RedirectStandardOutput $ReadyFile -PassThru -NoNewWindow

try {
    for ($i = 0; $i -lt 60; $i++) {
        if ((Test-Path $ReadyFile) -and (Get-Content $ReadyFile -Raw) -match '"event": "ready"') { break }
        Start-Sleep -Seconds 1
    }
    $Port = (Get-Content $ReadyFile -Raw | ConvertFrom-Json).port
    $Headers = @{ Authorization = "Bearer smoketoken" }
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Headers $Headers | Out-Null
    $Session = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/sessions" `
        -Headers $Headers -ContentType "application/json" -Body '{"title":"smoke"}'
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/sessions/$($Session.session_id)/messages" `
        -Headers $Headers -ContentType "application/json" -Body '{"content":"最小 smoke 会话"}' | Out-Null
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/shutdown" -Headers $Headers | Out-Null
    Write-Host "smoke test 通过"
}
finally {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
    Remove-Item -Recurse -Force $SmokeDir -ErrorAction SilentlyContinue
}
