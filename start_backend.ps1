# ===============================
# Backend startup script (PowerShell)
# ===============================

# 加载 .env 文件
if (Test-Path ".env") {
    Get-Content ".env" |
        Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' } |
        ForEach-Object {
            $parts = $_ -split '=', 2
            $key = $parts[0].Trim()
            $value = $parts[1].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value)
        }
}

# 读取环境变量，提供默认值
$BACKEND_HOST = if ($env:BACKEND_HOST) { $env:BACKEND_HOST } else { "0.0.0.0" }
$BACKEND_PORT = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "9000" }

Write-Host "Starting backend server..."
Write-Host "Host: $BACKEND_HOST"
Write-Host "Port: $BACKEND_PORT"
Write-Host "CORS Origins: $env:CORS_ORIGINS"

# 启动 FastAPI 应用
python -m uvicorn app.main:app `
    --host $BACKEND_HOST `
    --port $BACKEND_PORT `
    --reload
