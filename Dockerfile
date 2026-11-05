# Imagen oficial de Playwright: ya trae Chromium + todas las libs del
# sistema necesarias, así no hay que instalar dependencias de navegador
# a mano dentro del contenedor.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# PYTHONPATH=/app: permite correr cualquier script directo
# (python matchers/tyco_matcher.py) y que encuentre scraper_precios.config.
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py", "--help"]
