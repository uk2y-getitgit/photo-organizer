@echo off
chcp 65001 > nul
rem 현장사진정리기.exe 만들기 — 결과는 dist 폴더에 생긴다.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name 현장사진정리기 --paths src src\main.py
if errorlevel 1 (
  echo.
  echo [실패] .exe를 만들지 못했어요. 위 메시지를 확인해 주세요.
  pause
  exit /b 1
)
copy /y config.json dist\config.json > nul
echo.
echo [완료] dist\현장사진정리기.exe 가 만들어졌어요.
pause
