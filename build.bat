@echo off
echo ============================================
echo  BUILD MUSIC LICENSE GENERATOR EXE
echo ============================================

python -m PyInstaller ^
  --name "MusicLicenseGenerator" ^
  --onefile ^
  --windowed ^
  --noconfirm ^
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
