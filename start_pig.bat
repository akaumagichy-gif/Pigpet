@echo off
rem 一键启动 旋转猪猪桌宠 (优先用 pythonw 无控制台启动, 没有则退回 python)
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw pigpet.py
) else (
    start "" python pigpet.py
)
