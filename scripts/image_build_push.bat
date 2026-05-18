@echo off
setlocal

set REGISTRY=172.25.46.10:32000
set TAG=local

cd /d "%~dp0.."

docker compose -f docker/services.yaml build
if errorlevel 1 (
    echo Build failed. Skipping push.
    exit /b 1
)

docker compose -f docker/services.yaml push

endlocal
