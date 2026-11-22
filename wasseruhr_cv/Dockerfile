# Wasseruhr-CV – Home Assistant add-on and standalone Docker service.
#
# Base deliberately python:3.12-slim (Debian, glibc) instead of the Alpine base of
# HA: opencv-python-headless and numpy ship ready-made wheels for aarch64 and
# amd64, so nothing is compiled on the Home Assistant Green.
ARG BUILD_FROM
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    MODEL_DIR=/opt/wasseruhr/model \
    OPENCV_IO_MAX_IMAGE_PIXELS=25000000

WORKDIR /opt/wasseruhr

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY start.py .

# Bundled initial model (images/, templates/): copied into an empty /data on the
# very first start, never over data that was already learned.
COPY model ./model

# 8099: ingress/internal (always), 8080: HTTP and 8443: HTTPS for the local network (optional)
EXPOSE 8099 8080 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8099'), timeout=4).status == 200 else 1)"

CMD ["python", "start.py"]
