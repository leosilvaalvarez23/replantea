# Pruebas de extremo a extremo sin Python

Este PC no tiene Python, Node ni Docker. Para verificar el backend y las pantallas se ejecuta
Django dentro del navegador con **Pyodide** (un entorno aislado de la pestaña, no instala nada).

- `iniciar.ps1` copia el código a una carpeta temporal y levanta un servidor estático local (puerto 8768).
- `e2e.html`: backend real + pantallas reales (iframe). Las llamadas a `/api/` se desvían al backend en Pyodide
  con `enforce_csrf_checks=True`. Datos de prueba y usuarios `asesor1` / `gerente1` se crean al arrancar.
- `unit.html`: corre `pytest engine/` y `manage.py test solicitudes`.
- `servidor.ps1`: sirve `/app/*`, `/comprador/<token>` y `/src/*`, e inyecta el desvío de `fetch`.

Limitaciones del entorno (solo del arnés, no del proyecto): hay que fijar `DJANGO_ALLOW_ASYNC_UNSAFE=true`,
usar el hasher MD5 (Pyodide no trae `pbkdf2`) y cargar el paquete `tzdata`.
No sustituye una prueba en el servidor real con IngeMAX.
