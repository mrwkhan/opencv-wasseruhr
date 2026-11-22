# Wasseruhr-CV – Home-Assistant-Add-on und eigenständiger Docker-Dienst.
#
# Basis bewusst python:3.12-slim (Debian, glibc) statt der Alpine-Basis von HA:
# Für opencv-python-headless und numpy gibt es fertige Wheels für aarch64 und
# amd64, auf dem Home Assistant Green wird also nichts kompiliert.
ARG BUILD_FROM
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    MODELL_DIR=/opt/wasseruhr/modell \
    OPENCV_IO_MAX_IMAGE_PIXELS=25000000

WORKDIR /opt/wasseruhr

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY start.py .

# Optional: ein eigenes, fertig trainiertes Modell (lernbilder/, vorlagen/) in
# modell/ wird beim allerersten Start in ein leeres /data übernommen. Im
# Repository ist der Ordner leer, dort wird das Modell über die Verwaltung
# importiert oder auf der Lernseite angelernt.
COPY modell ./modell

# 8099: Ingress/intern (immer), 8080: HTTP und 8443: HTTPS fürs Heimnetz (optional)
EXPOSE 8099 8080 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8099'), timeout=4).status == 200 else 1)"

CMD ["python", "start.py"]
