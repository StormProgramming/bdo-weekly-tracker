@echo off
echo Building BDO Weekly Tracker...
python -m PyInstaller --onefile --noconsole --name "BDO Weekly Tracker" bdo-weekly-tracker.py
echo.
echo Done! Your exe is in the dist\ folder.
pause
