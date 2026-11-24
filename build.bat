@echo off
echo ============================================
echo  BUILD AEGIS AUDIO EXE
echo ============================================

python -m PyInstaller ^
  --name "AegisAudio" ^
  --onefile ^
  --windowed ^
  --noconfirm ^
  --icon=app.ico ^
  --collect-all transformers ^
  --collect-all torch ^
  --collect-all customtkinter ^
  --hidden-import sounddevice ^
  --hidden-import fpdf ^
  --hidden-import soundfile ^
  main.py

echo.
echo ============================================
echo  ГОТОВО! EXE лежит в папке dist\
echo ============================================
pause
