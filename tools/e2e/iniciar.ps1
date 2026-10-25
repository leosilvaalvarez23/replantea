# Prepara y levanta el entorno de pruebas de extremo a extremo (no requiere Python ni Docker).
# Uso (PowerShell, desde la raíz del repo):   .\tools\e2e\iniciar.ps1
# Luego abre en Chrome:  http://localhost:8768/e2e.html   (unos 40 s en arrancar la primera vez)
#   e2e.html  -> backend Django real (en Pyodide) + las pantallas reales dentro de un iframe, con CSRF activo.
#                IngeMAX y el correo se simulan; usuarios de prueba: asesor1 / clave-asesor-1, gerente1 / clave-gerente-1.
#   unit.html -> corre los tests del motor (pytest) y de la API (manage.py test) dentro del navegador.
# Requiere internet (carga Pyodide y paquetes desde cdn.jsdelivr.net).
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$www = Join-Path $env:TEMP 'replantea-e2e'
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*tools*e2e*servidor.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
New-Item -ItemType Directory -Force "$www\app", "$www\src" | Out-Null
robocopy "$repo\prototipo\v2" "$www\app" /MIR /NFL /NDL /NJH /NJS | Out-Null
robocopy "$repo\engine" "$www\src\engine" /MIR /XD __pycache__ .pytest_cache /NFL /NDL /NJH /NJS | Out-Null
robocopy "$repo\backend" "$www\src\backend" /MIR /XD __pycache__ staticfiles /XF db.sqlite3 /NFL /NDL /NJH /NJS | Out-Null
Copy-Item "$PSScriptRoot\e2e.html", "$PSScriptRoot\unit.html" $www -Force
Start-Process powershell -ArgumentList '-NoProfile', '-File', "$PSScriptRoot\servidor.ps1", '-Root', $www, '-Port', '8768' -WindowStyle Hidden
Write-Host "Listo: http://localhost:8768/e2e.html  y  http://localhost:8768/unit.html"
Write-Host "Para detener: Get-CimInstance Win32_Process -Filter ""Name='powershell.exe'"" | ? { `$_.CommandLine -like '*servidor.ps1*' } | % { Stop-Process -Id `$_.ProcessId -Force }"
