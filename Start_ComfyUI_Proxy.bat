@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if "%COMFY_PROXY_TOKEN%"=="" (
  echo Please set COMFY_PROXY_TOKEN before starting the proxy.
  echo Example:
  echo   set COMFY_PROXY_TOKEN=your-long-secret-token
  pause
  exit /b 1
)
if "%COMFY_LOCAL_URL%"=="" set "COMFY_LOCAL_URL=http://127.0.0.1:8188"
if "%COMFY_PROXY_PORT%"=="" set "COMFY_PROXY_PORT=8190"
python comfy_proxy.py
