#!/usr/bin/env python3
from __future__ import annotations

import html
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


PORT = int(os.environ.get("PORT", "14001"))
ROOT = Path("/opt/nas-auto")
BROWSER_LOCK_PATH = os.environ.get("BROWSER_LOCK_PATH", "/tmp/nas-auto-browser.lock")

SERVICES = {
    "xhs": {"name": "小红书", "port": 18081, "path": "/xhs/", "config": "/config/xhs/config.json"},
    "x": {"name": "X", "port": 18082, "path": "/x/", "config": "/config/x/config.json"},
    "pixiv": {"name": "Pixiv", "port": 18083, "path": "/pixiv/", "config": "/config/pixiv/config.json"},
}

SITE_RULES = {
    "xhs": {
        "output": Path("/config/xhs/xhs_cookie.txt"),
        "names": {"a1", "web_session", "webId", "gid", "webBuild", "unread", "xsecappid", "loadts", "acw_tc"},
    },
    "x": {
        "output": Path("/config/x/x_cookies.txt"),
        "names": {
            "auth_token",
            "ct0",
            "twid",
            "guest_id",
            "guest_id_ads",
            "guest_id_marketing",
            "personalization_id",
            "kdt",
            "lang",
            "d_prefs",
            "night_mode",
        },
    },
}


processes: list[subprocess.Popen] = []
log_lines: list[str] = []
log_lock = threading.Lock()


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with log_lock:
        log_lines.append(line)
        del log_lines[:-300]


def deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as error:
        log(f"配置读取失败 {path}: {error}")
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_config(path: Path, example: Path, patch: dict[str, Any]) -> None:
    data = read_json(example)
    if path.exists():
        data = deep_update(data, read_json(path))
    deep_update(data, patch)
    write_json(path, data)


def ensure_configs() -> None:
    ensure_config(
        Path("/config/xhs/config.json"),
        ROOT / "xhs" / "config.example.json",
        {
            "api_url": "http://127.0.0.1:5556/xhs/detail",
            "database": "/state/xhs/xhs_auto.sqlite3",
            "secrets_path": "/state/xhs/secrets.json",
            "cookie_file": "/config/xhs/xhs_cookie.txt",
            "api_cookie_file": "/config/xhs/xhs_cookie.txt",
            "queue_files": ["/queue/xhs/links.txt"],
            "web": {"host": "127.0.0.1", "port": 18081},
            "sync_settings": {"path": "/xhs-volume/settings.json", "cookie_file": "/config/xhs/xhs_cookie.txt"},
            "browser": {"cookie_file": "/config/xhs/xhs_cookie.txt"},
        },
    )
    ensure_config(
        Path("/config/x/config.json"),
        ROOT / "x" / "config.example.json",
        {
            "database": "/state/x/x_auto.sqlite3",
            "cookie_file": "/config/x/x_cookies.txt",
            "download_dir": "/downloads/x",
            "redownload_missing_files": False,
            "web": {"host": "127.0.0.1", "port": 18082},
        },
    )
    ensure_config(
        Path("/config/pixiv/config.json"),
        ROOT / "pixiv" / "config.example.json",
        {
            "refresh_token_file": "/config/pixiv/pixiv_refresh_token.txt",
            "refresh_token_file_env": "PIXIV_REFRESH_TOKEN_FILE",
            "oauth_state_file": "/config/pixiv/pixiv_oauth_state.json",
            "database": "/state/pixiv/pixiv_auto.sqlite3",
            "download_dir": "/downloads/pixiv",
            "image_dir": "/downloads/pixiv/images",
            "metadata_dir": "/downloads/pixiv/downloads-metadata",
            "web": {"host": "127.0.0.1", "port": 18083},
        },
    )
    for path in [
        Path("/queue/xhs"),
        Path("/state/xhs"),
        Path("/state/x"),
        Path("/state/pixiv"),
        Path("/downloads/x/images"),
        Path("/downloads/x/videos"),
        Path("/downloads/x/downloads-metadata"),
        Path("/downloads/pixiv"),
    ]:
        path.mkdir(parents=True, exist_ok=True)


def stream_output(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for raw in proc.stdout:
        log(f"{name}: {raw.rstrip()}")


def start_process(name: str, command: list[str], cwd: str, env_patch: dict[str, str] | None = None) -> None:
    env = dict(os.environ)
    env["BROWSER_LOCK_PATH"] = BROWSER_LOCK_PATH
    env["BROWSER_LOCK_WAIT_SECONDS"] = os.environ.get("BROWSER_LOCK_WAIT_SECONDS", "7200")
    if env_patch:
        env.update(env_patch)
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    processes.append(proc)
    threading.Thread(target=stream_output, args=(name, proc), daemon=True).start()
    log(f"已启动 {name}: pid={proc.pid}")


def wait_for_port(name: str, host: str, port: int, timeout_seconds: int = 90) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            if sock.connect_ex((host, port)) == 0:
                log(f"{name} ready on {host}:{port}")
                return True
        time.sleep(2)
    log(f"{name} not ready after {timeout_seconds}s; workers will keep retrying through normal runs")
    return False


def start_children() -> None:
    ensure_configs()
    start_process("xhs-api", [sys.executable, "main.py", "api"], "/app")
    wait_for_port("xhs-api", "127.0.0.1", 5556)
    start_process(
        "xhs-worker",
        [sys.executable, "/opt/nas-auto/xhs/xhs_auto_worker.py", "--config", "/config/xhs/config.json"],
        "/opt/nas-auto/xhs",
        {"XHS_COOKIE_FILE": "/config/xhs/xhs_cookie.txt"},
    )
    start_process(
        "x-worker",
        [sys.executable, "/opt/nas-auto/x/x_auto_worker.py", "--config", "/config/x/config.json"],
        "/opt/nas-auto/x",
        {"X_COOKIE_FILE": "/config/x/x_cookies.txt"},
    )
    start_process(
        "pixiv-worker",
        [sys.executable, "/opt/nas-auto/pixiv/pixiv_auto_worker.py", "--config", "/config/pixiv/config.json"],
        "/opt/nas-auto/pixiv",
        {"PIXIV_REFRESH_TOKEN_FILE": "/config/pixiv/pixiv_refresh_token.txt"},
    )


def parse_cookie_header(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1]
        for part in line.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if name:
                values[name] = value.strip()
    return values


def import_all_cookie(text: str) -> dict[str, Any]:
    values = parse_cookie_header(text)
    result: dict[str, Any] = {}
    for key, rule in SITE_RULES.items():
        selected = {name: values[name] for name in sorted(rule["names"]) if name in values}
        if selected:
            output: Path = rule["output"]
            output.parent.mkdir(parents=True, exist_ok=True)
            if key == "x":
                expires = int(time.time()) + 86400 * 180
                lines = ["# Netscape HTTP Cookie File"]
                for name, value in selected.items():
                    lines.append(f".x.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}")
                output.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                output.write_text("; ".join(f"{name}={value}" for name, value in selected.items()) + "\n", encoding="utf-8")
        result[key] = {"count": len(selected), "output": str(rule["output"]), "names": sorted(selected)}
    return result


def read_import_cookie_payload(handler: BaseHTTPRequestHandler, length: int) -> str:
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        form = parse_qs(body.decode("utf-8", errors="replace"))
        return (form.get("cookie_text") or [""])[0]

    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not match:
        return ""
    boundary = (match.group(1) or match.group(2)).encode("utf-8")
    marker = b"--" + boundary
    values: list[str] = []
    for part in body.split(marker):
        if b"\r\n\r\n" not in part:
            continue
        header_bytes, value = part.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("utf-8", errors="replace")
        value = value.removesuffix(b"\r\n").removesuffix(b"--").strip()
        if 'name="cookie_text"' in headers or 'name="cookie_file"' in headers:
            decoded = value.decode("utf-8-sig", errors="replace").strip()
            if decoded:
                values.append(decoded)
    return "\n".join(values)


def service_status() -> dict[str, Any]:
    return {
        "processes": [
            {"pid": proc.pid, "returncode": proc.poll()} for proc in processes
        ],
        "browser_lock": Path(BROWSER_LOCK_PATH).exists(),
        "logs": list(log_lines[-80:]),
    }


def page(message: str = "") -> bytes:
    cards = "".join(
        f'<a class="card" href="{svc["path"]}"><strong>{html.escape(svc["name"])}</strong><span>{html.escape(svc["path"])}</span></a>'
        for svc in SERVICES.values()
    )
    lock = "占用中，其他浏览器任务会等待" if Path(BROWSER_LOCK_PATH).exists() else "空闲"
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NAS Auto Download</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f7fb;color:#182033}}
header{{background:#111827;color:#fff;padding:18px 24px}} main{{max-width:1100px;margin:0 auto;padding:20px;display:grid;gap:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}} .card,section{{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:16px}}
.card{{display:grid;gap:6px;text-decoration:none;color:inherit}} .card strong{{font-size:18px}} .card span,.muted{{color:#64748b}}
textarea,input[type=file]{{width:100%;box-sizing:border-box;border:1px solid #d8dee9;border-radius:6px;padding:10px;font:inherit;background:white}} textarea{{min-height:140px}} button{{border:0;border-radius:6px;background:#111827;color:white;padding:9px 14px;cursor:pointer}}
pre{{background:#0f172a;color:#dbeafe;padding:12px;border-radius:6px;overflow:auto;max-height:360px;white-space:pre-wrap}}
.ok{{background:#ecfdf5;border-color:#bbf7d0}}
</style></head><body>
<header><h1>NAS Auto Download</h1><div>统一入口：小红书 / X / Pixiv</div></header>
<main>
{f'<section class="ok">{html.escape(message)}</section>' if message else ''}
<section><h2>服务入口</h2><div class="grid">{cards}</div><p class="muted">无头浏览器锁：{lock}</p></section>
<section><h2>一次性导入 Cookie</h2><p class="muted">粘贴或上传浏览器插件导出的全站 Cookie。服务器只读取内容并拆出小红书/X 所需字段，不保存原始上传文件。Pixiv 请进入 Pixiv 页面生成登录链接并换取 Token。</p>
<form method="post" action="/import-cookies" enctype="multipart/form-data">
<label class="muted">上传 cookies.txt</label><input type="file" name="cookie_file" accept=".txt,.cookies,text/plain">
<label class="muted">或直接粘贴 Cookie 内容</label><textarea name="cookie_text" placeholder="name=value; name2=value2; ..."></textarea>
<p><button type="submit">导入小红书和 X Cookie</button></p></form></section>
<section><h2>最近日志</h2><pre>{html.escape(chr(10).join(log_lines[-80:]))}</pre></section>
</main></body></html>"""
    return body.encode("utf-8")


def rewrite_html(prefix: str, body: bytes, content_type: str) -> bytes:
    if "text/html" not in content_type.lower():
        return body
    text = body.decode("utf-8", errors="replace")
    replacements = {
        'action="/': f'action="{prefix}',
        'href="/': f'href="{prefix}',
        'src="/': f'src="{prefix}',
        'fetch("/': f'fetch("{prefix}',
        "fetch('/": f"fetch('{prefix}",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    back = (
        '<div style="position:sticky;top:0;z-index:9999;background:#111827;color:#fff;'
        'padding:8px 14px;font:14px system-ui,-apple-system,Segoe UI,sans-serif">'
        '<a href="/" style="color:#fff;text-decoration:none">← 返回统一主页</a></div>'
    )
    if "<body>" in text and "返回统一主页" not in text:
        text = text.replace("<body>", "<body>" + back, 1)
    return text.encode("utf-8")


def proxy(handler: BaseHTTPRequestHandler, service_key: str, prefix: str) -> None:
    svc = SERVICES[service_key]
    raw_path = handler.path
    path = raw_path[len(prefix) - 1 :] if raw_path.startswith(prefix) else "/"
    if not path.startswith("/"):
        path = "/" + path
    body = None
    if handler.command in {"POST", "PUT", "PATCH"}:
        length = int(handler.headers.get("Content-Length", "0") or 0)
        body = handler.rfile.read(length)
    headers = {k: v for k, v in handler.headers.items() if k.lower() not in {"host", "connection", "accept-encoding"}}
    conn = http.client.HTTPConnection("127.0.0.1", svc["port"], timeout=120)
    try:
        conn.request(handler.command, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        content_type = resp.getheader("Content-Type", "")
        data = rewrite_html(prefix, data, content_type)
        handler.send_response(resp.status)
        for key, value in resp.getheaders():
            lower = key.lower()
            if lower in {"content-length", "connection", "transfer-encoding", "content-encoding"}:
                continue
            if lower == "location" and value.startswith("/"):
                value = prefix.rstrip("/") + value
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        split = urlsplit(self.path)
        if split.path == "/api/status":
            data = json.dumps(service_status(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        for key, svc in SERVICES.items():
            if split.path == svc["path"].rstrip("/"):
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", svc["path"])
                self.end_headers()
                return
            if split.path.startswith(svc["path"]):
                proxy(self, key, svc["path"])
                return
        data = page()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        split = urlsplit(self.path)
        if split.path == "/import-cookies":
            length = int(self.headers.get("Content-Length", "0") or 0)
            result = import_all_cookie(read_import_cookie_payload(self, length))
            message = "导入完成：" + "；".join(
                f"{SERVICES[key]['name']} {value['count']} 项 -> {value['output']}" for key, value in result.items()
            )
            data = page(message)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        for key, svc in SERVICES.items():
            if split.path.startswith(svc["path"]):
                proxy(self, key, svc["path"])
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def shutdown(_signum: int, _frame: Any) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    time.sleep(2)
    for proc in processes:
        if proc.poll() is None:
            proc.kill()
    raise SystemExit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    start_children()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"统一 Web UI listening on 0.0.0.0:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
