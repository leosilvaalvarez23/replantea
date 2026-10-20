FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY engine/ ./engine/
COPY backend/ ./backend/
COPY prototipo/ ./prototipo/
ENV PYTHONPATH=/app
ENV DJANGO_SETTINGS_MODULE=replantea.settings
WORKDIR /app/backend
ENTRYPOINT ["sh", "/app/backend/entrypoint.sh"]
