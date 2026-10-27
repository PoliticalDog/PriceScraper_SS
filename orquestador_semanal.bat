@echo off
REM Corrida semanal del pipeline de PriceScraper para el Programador de tareas de Windows (ver orquestador.py).
REM
REM Programarla (una vez, en cmd desde la raiz del repo, porque usa %CD%; ajusta el dia y la hora):
REM   schtasks /Create /TN "PriceScraper semanal" /SC WEEKLY /D MON /ST 03:00 /TR "\"%CD%\orquestador_semanal.bat\""
REM Correrla ahora para probar:   schtasks /Run /TN "PriceScraper semanal"
REM Quitarla:                     schtasks /Delete /TN "PriceScraper semanal" /F
REM
REM La computadora debe estar encendida y PostgreSQL corriendo a esa hora. El detalle queda en logs\orquestador.log,
REM el resumen de la ultima corrida en logs\orquestador_ultima_corrida.json y la salida de consola en
REM logs\orquestador_tarea.log. El codigo de salida es 1 si alguna etapa tuvo errores.

cd /d "%~dp0"
if not exist logs mkdir logs
"%~dp0venv\Scripts\python.exe" "%~dp0orquestador.py" %* >> "%~dp0logs\orquestador_tarea.log" 2>&1
exit /b %ERRORLEVEL%
