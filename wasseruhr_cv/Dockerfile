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
    MODELL_DIR=/opt/wasseruhr/modell

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

EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=4).status == 200 else 1)"

CMD ["python", "start.py"]
