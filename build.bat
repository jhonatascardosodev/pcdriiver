@echo off
cd /d "%~dp0"
py -m pip install -q pyinstaller -r requirements.txt
py -m PyInstaller --noconfirm --onefile --windowed --name MonitorPC --collect-data sv_ttk app.py
echo.
echo Pronto: dist\MonitorPC.exe
