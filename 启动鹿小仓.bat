@echo off
chcp 65001 >nul
title 鹿小仓 - 独立商业智能体
cd /d "%~dp0"
echo 正在启动鹿小仓...
"C:\Users\13522\AppData\Local\Programs\Python\Python312\python.exe" app.py
pause
