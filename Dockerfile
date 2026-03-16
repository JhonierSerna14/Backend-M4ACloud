# Dockerfile para desplegar el backend en Railway (u otros hosts Docker).
# Incluye las dependencias nativas que necesita WeasyPrint (GTK/Cairo).

FROM python:3.11-slim

# Evitar prompts en apt
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema necesarias para WeasyPrint en Debian slim.
# libpangoft2 y harfbuzz son requeridas por el renderizado de texto/PDF en Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        libgdk-pixbuf-2.0-0 \
        libglib2.0-0 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libffi8 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar paquetes Python
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . /app

# Puerto que usará Railway (o cambiar según plataforma)
# Railway inyecta $PORT, así que definimos un valor por defecto para entornos locales.
ENV PORT=8000
EXPOSE 8000

# Comando de arranque por defecto
# Usamos shell para que ${PORT} se expanda correctamente en entornos como Railway.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
