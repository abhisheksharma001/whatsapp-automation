@echo off
echo Starting Realty Mind Scraping Dashboard...
cd /d "C:\Users\15as0\Downloads\whatsapp_automation"

:: Start the Flask server in the background
start /b python app.py

:: Wait 3 seconds for server to start
timeout /t 3 /nobreak > nul

:: Open the browser to the dashboard
start http://127.0.0.1:5000

echo Dashboard is running! You can close this window at any time to stop the server.
cmd /k
