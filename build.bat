@echo off
echo ============================================
echo  BUILD AEGIS AUDIO EXE (iOS GLASS EDITION)
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
  --collect-all matplotlib ^
  --hidden-import scipy ^
  --hidden-import scipy.signal ^
  --hidden-import sounddevice ^
  --hidden-import fpdf ^
  --hidden-import soundfile ^
  main.py

echo.
echo ============================================
echo  ГОТОВО! EXE лежит в папке dist\
echo ============================================
pause
