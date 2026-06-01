FROM joeanamier/xhs-downloader

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    BROWSER_LOCK_PATH=/tmp/nas-auto-browser.lock

WORKDIR /opt/nas-auto

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY _integrated/requirements.txt /tmp/integrated-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/integrated-requirements.txt \
    && python -m playwright install --with-deps chromium

COPY _src/XHS-Downloader-NAS-main /opt/nas-auto/xhs
COPY _src/x-auto-download-nas-main /opt/nas-auto/x
COPY _src/pixiv-auto-download-nas-main /opt/nas-auto/pixiv
COPY tools/import_credentials.py /opt/nas-auto/tools/import_credentials.py
COPY _integrated/integrated_server.py /opt/nas-auto/integrated_server.py

EXPOSE 14001

CMD ["python", "/opt/nas-auto/integrated_server.py"]
