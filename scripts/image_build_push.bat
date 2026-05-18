@echo off
setlocal

set REGISTRY=172.25.46.10:32000
set TAG=local

cd /d "%~dp0.."

docker compose -f docker/services.yaml build
docker compose -f docker/services.yaml push

endlocal
