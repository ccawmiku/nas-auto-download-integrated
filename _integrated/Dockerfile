FROM node:22-bookworm-slim AS web-build

WORKDIR /web

COPY _frontend/integrated/package*.json ./
RUN npm ci

COPY _frontend/integrated ./
RUN npm run build

FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ARG APP_VERSION=v1.5.1-dev

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    BROWSER_LOCK_PATH=/tmp/nas-auto-browser.lock \
    PYTHONPATH=/opt/nas-auto \
    APP_VERSION=${APP_VERSION}

WORKDIR /opt/nas-auto

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY _integrated/requirements.txt /tmp/integrated-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/integrated-requirements.txt

COPY _src/XHS-Downloader-NAS-main /opt/nas-auto/xhs
COPY _src/x-auto-download-nas-main /opt/nas-auto/x
COPY _src/pixiv-auto-download-nas-main /opt/nas-auto/pixiv
COPY _src/douyin-f2-auto-main /opt/nas-auto/douyin
COPY _common/nas_auto_common /opt/nas-auto/nas_auto_common
COPY tools/import_credentials.py /opt/nas-auto/tools/import_credentials.py
COPY _integrated/integrated_server.py /opt/nas-auto/integrated_server.py
COPY --from=web-build /web/dist /opt/nas-auto/web

EXPOSE 14001

CMD ["python", "/opt/nas-auto/integrated_server.py"]
