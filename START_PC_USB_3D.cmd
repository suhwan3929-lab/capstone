@echo off
setlocal
cd /d "%~dp0"
set "GUI_PY=%~dp0capstone_code\.venv\Scripts\python.exe"
if not exist "%GUI_PY%" (
  echo Project Python environment is missing. See capstone_code\docs\usb_3d_pc_test.md
  pause
  exit /b 1
)
set "USB_ONE=COM4"
set "USB_TWO=COM5"
if not "%~1"=="" set "USB_ONE=%~1"
if not "%~2"=="" set "USB_TWO=%~2"
"%GUI_PY%" capstone_code\tools\usb_lidar_3d.py --list
echo.
echo USB 1 = %USB_ONE%, USB 2 = %USB_TWO%. Physical left/right is not assigned.
echo Frequency channels: USB 1 = 0, USB 2 = 1.
echo GUI test only. SOS, guardian notifications and safety decisions are disabled.
"%GUI_PY%" -u capstone_code\tools\usb_lidar_3d.py --left "%USB_ONE%" --right "%USB_TWO%" --left-channel 0 --right-channel 1
if errorlevel 1 pause
