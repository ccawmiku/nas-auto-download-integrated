import argparse
import asyncio
import contextlib
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

COMMON_PATH = Path(__file__).resolve().parents[2] / "_common"
if COMMON_PATH.exists():
    sys.path.insert(0, str(COMMON_PATH))

try:
    from nas_auto_common.ui import app_css
except ModuleNotFoundError:
    def app_css(extra: str = "") -> str:
        return extra


NOTE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)
NOTE_ID_PATTERNS = (
    re.compile(r"/(?:explore|discovery/item)/([^/?#]+)", re.IGNORECASE),
    re.compile(r"/user/profile/[^/?#]+/([^/?#]+)", re.IGNORECASE),
)


DEFAULT_CONFIG: dict[str, Any] = {
    "api_url": "http://192.168.1.20:13001/xhs/detail",
    "auto_run_enabled": False,
    "run_interval_seconds": 2592000,
    "request_delay_seconds": 3,
    "jitter_seconds": 2,
    "database": "/state/xhs_auto.sqlite3",
    "secrets_path": "/state/secrets.json",
    "cookie_file": "/config/xhs_cookie.txt",
    "default_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "legacy_processed_json": "/state/processed.json",
    "queue_files": ["/queue/links.txt"],
    "api_skip": True,
    "api_cookie_enabled": False,
    "api_cookie_env": "XHS_COOKIE",
    "api_cookie_file": "/config/xhs_cookie.txt",
    "api_cookie_secret_key": "xhs_cookie",
    "retry_failed": True,
    "max_download_attempts": 0,
    "sync_settings": {
        "enabled": True,
        "sync_cookie": False,
        "sync_user_agent": True,
        "path": "/xhs-volume/settings.json",
        "cookie_env": "XHS_COOKIE",
        "cookie_file": "/config/xhs_cookie.txt",
        "user_agent_env": "XHS_USER_AGENT",
        "cookie_secret_key": "xhs_cookie",
        "user_agent_secret_key": "xhs_user_agent",
        "defaults": {
            "mapping_data": {},
            "work_path": "/xhs",
            "folder_name": "Download",
            "name_format": "发布时间 作者昵称 作品标题",
            "proxy": None,
            "timeout": 10,
            "chunk": 2097152,
            "max_retry": 5,
            "record_data": True,
            "image_format": "PNG",
            "folder_mode": True,
            "language": "zh_CN",
            "image_download": True,
            "video_download": True,
            "live_download": True,
            "download_record": True,
            "author_archive": False,
            "write_mtime": False,
            "video_preference": "resolution",
            "script_server": False,
        },
    },
    "stop_marker": {
        "enabled": True,
        "title": "\u6570\u5b66\u754c\u6700\u7f8e\u5473\u7684\u4e00\u5929",
        "match": "exact",
    },
    "browser": {
        "enabled": False,
        "backend": "cloakbrowser",
        "headless": True,
        "user_agent_env": "XHS_USER_AGENT",
        "cookie_env": "XHS_COOKIE",
        "cookie_file": "/config/xhs_cookie.txt",
        "user_agent_secret_key": "xhs_user_agent",
        "cookie_secret_key": "xhs_cookie",
        "scroll_count": 40,
        "scroll_delay_ms": 1200,
        "consecutive_downloaded_stop_count": 10,
        "target_timeout_ms": 45000,
        "extractor": "/app/liked_extractor.js",
        "auto_install_playwright": True,
        "cloakbrowser_humanize": True,
        "cloakbrowser_human_preset": "default",
        "cloakbrowser_persistent_profile": True,
        "cloakbrowser_user_data_dir": "/state/xhs/cloakbrowser/profile",
        "cloakbrowser_stealth_args": True,
        "cloakbrowser_geoip": False,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1440, "height": 1000},
        "playwright_version": "1.56.0",
        "targets": [],
    },
    "web": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8080,
        "log_lines": 200,
    },
}


RUNTIME_LOCK = Lock()
RUN_NOW_EVENT = Event()
SETTINGS_CHANGED_EVENT = Event()
LOG_LINES: deque[str] = deque(maxlen=300)
MAX_RUN_INTERVAL_SECONDS = 30 * 24 * 3600
RUNTIME: dict[str, Any] = {
    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "is_running": False,
    "last_run_started_at": None,
    "last_run_finished_at": None,
    "next_run_at": None,
    "last_error": None,
}


@contextlib.contextmanager
def browser_lock():
    lock_path = Path(os.environ.get("BROWSER_LOCK_PATH", "/tmp/nas-auto-browser.lock"))
    wait_seconds = int(os.environ.get("BROWSER_LOCK_WAIT_SECONDS", "7200") or "7200")
    poll_seconds = max(1, int(os.environ.get("BROWSER_LOCK_POLL_SECONDS", "10") or "10"))
    deadline = time.time() + wait_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"xhs-auto-worker pid={os.getpid()} at={time.time()}\n".encode("utf-8"))
        except FileExistsError:
            try:
                if f"pid={os.getpid()}" in lock_path.read_text(encoding="utf-8", errors="ignore"):
                    yield
                    return
            except OSError:
                pass
            if time.time() >= deadline:
                raise TimeoutError(f"timed out waiting for browser lock: {lock_path}")
            log(f"等待其他浏览器任务结束：{lock_path}")
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


class LockedPlaywright:
    def __init__(self, manager: Any):
        self.manager = manager
        self.lock_cm: Any | None = None

    async def __aenter__(self) -> Any:
        self.lock_cm = browser_lock()
        self.lock_cm.__enter__()
        try:
            return await self.manager.__aenter__()
        except Exception:
            self.lock_cm.__exit__(*sys.exc_info())
            self.lock_cm = None
            raise

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return await self.manager.__aexit__(exc_type, exc, tb)
        finally:
            if self.lock_cm is not None:
                self.lock_cm.__exit__(exc_type, exc, tb)
                self.lock_cm = None


def locked_async_playwright(factory: Any) -> Any:
    def create() -> LockedPlaywright:
        return LockedPlaywright(factory())

    return create


def log(message: str) -> None:
    line = f"{time.strftime('[%Y-%m-%d %H:%M:%S]')} {message}"
    print(line, flush=True)
    with RUNTIME_LOCK:
        LOG_LINES.append(line)


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        user_config = json.loads(path.read_text(encoding="utf-8"))
        deep_update(config, user_config)
    else:
        log(f"未找到配置文件：{path}，使用默认配置。")
    apply_saved_runtime_settings(config)
    return config


def apply_saved_runtime_settings(config: dict[str, Any]) -> None:
    secrets = load_secrets(config)
    interval = secrets.get("run_interval_seconds")
    if interval:
        try:
            config["run_interval_seconds"] = min(MAX_RUN_INTERVAL_SECONDS, max(60, int(interval)))
        except ValueError:
            log(f"已忽略无效的运行间隔设置：{interval}")
    duplicate_stop_count = secrets.get("consecutive_downloaded_stop_count")
    if duplicate_stop_count not in (None, ""):
        try:
            browser_config = config.setdefault("browser", {})
            browser_config["consecutive_downloaded_stop_count"] = max(0, int(duplicate_stop_count))
        except ValueError:
            log(f"已忽略无效的连续已下载停止阈值：{duplicate_stop_count}")


def load_secrets(config: dict[str, Any]) -> dict[str, str]:
    path = Path(str(config.get("secrets_path", DEFAULT_CONFIG["secrets_path"])))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log(f"无法读取密钥文件：{error}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def read_text_secret_file(path_value: Any) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        log(f"无法读取凭据文件 {path}: {error}")
    return ""


def normalize_cookie_text(cookie_text: str, domain_hint: str = "xiaohongshu.com") -> str:
    text = cookie_text.strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        raw_items = parsed.get("cookies", parsed) if isinstance(parsed, dict) else parsed
        if isinstance(raw_items, list):
            pairs: list[str] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain") or "")
                if domain_hint not in domain:
                    continue
                name = str(item.get("name") or "").strip()
                value = str(item.get("value") or "").strip()
                if name and value:
                    pairs.append(f"{name}={value}")
            return "; ".join(pairs)

    if "# Netscape HTTP Cookie File" in text or "\t" in text:
        pairs = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, name, value = parts[0], parts[5].strip(), parts[6].strip()
            if domain_hint in domain and name and value:
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "; ".join(line.rstrip(";") for line in lines)


def write_text_secret_file(path_value: Any, value: str) -> None:
    raw_path = str(path_value or "").strip()
    if not raw_path or not value:
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")


def remove_text_secret_file(path_value: Any) -> None:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return
    path = Path(raw_path)
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError as error:
        log(f"无法删除凭据文件 {path}: {error}")


def cookie_summary(cookie_value: str) -> dict[str, Any]:
    cookie = normalize_cookie_text(cookie_value)
    names = []
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        name, _value = part.strip().split("=", 1)
        if name:
            names.append(name)
    unique_names = sorted(set(names))
    return {
        "valid": bool(unique_names),
        "count": len(unique_names),
        "has_a1": "a1" in unique_names,
        "has_web_session": "web_session" in unique_names,
        "names": unique_names[:12],
    }


def save_web_settings(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(config.get("secrets_path", DEFAULT_CONFIG["secrets_path"])))
    path.parent.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets(config)

    cookie = normalize_cookie_text(str(payload.get("cookie", "")))
    user_agent = str(payload.get("user_agent", "")).strip()
    if cookie:
        secrets["xhs_cookie"] = cookie
        write_text_secret_file(config.get("cookie_file", "/config/xhs_cookie.txt"), cookie)
    if user_agent:
        secrets["xhs_user_agent"] = user_agent
    if payload.get("clear_cookie"):
        secrets.pop("xhs_cookie", None)
        remove_text_secret_file(config.get("cookie_file", "/config/xhs_cookie.txt"))

    interval_changed = False
    duplicate_stop_changed = False
    interval_payload = None
    interval_unit = "秒"
    if payload.get("run_interval_hours") not in (None, ""):
        interval_unit = "小时"
        try:
            interval_payload = int(round(float(payload.get("run_interval_hours")) * 3600))
        except (TypeError, ValueError) as error:
            raise ValueError("运行间隔必须是数字小时数") from error
    elif payload.get("run_interval_seconds") not in (None, ""):
        try:
            interval_payload = int(payload.get("run_interval_seconds"))
        except (TypeError, ValueError) as error:
            raise ValueError("运行间隔必须是数字秒数") from error

    if interval_payload is not None:
        interval = int(interval_payload)
        if interval < 60:
            raise ValueError("运行间隔不能小于 60 秒")
        if interval > MAX_RUN_INTERVAL_SECONDS:
            raise ValueError("运行间隔不能超过 30 天")
        secrets["run_interval_seconds"] = str(interval)
        if int(config.get("run_interval_seconds", 0) or 0) != interval:
            config["run_interval_seconds"] = interval
            interval_changed = True

    if payload.get("consecutive_downloaded_stop_count") not in (None, ""):
        try:
            duplicate_stop_count = int(payload.get("consecutive_downloaded_stop_count"))
        except (TypeError, ValueError) as error:
            raise ValueError("连续已下载停止阈值必须是数字") from error
        if duplicate_stop_count < 0:
            raise ValueError("连续已下载停止阈值不能小于 0")
        if duplicate_stop_count > 1000:
            raise ValueError("连续已下载停止阈值不能超过 1000")
        secrets["consecutive_downloaded_stop_count"] = str(duplicate_stop_count)
        browser_config = config.setdefault("browser", {})
        if int(browser_config.get("consecutive_downloaded_stop_count", 0) or 0) != duplicate_stop_count:
            browser_config["consecutive_downloaded_stop_count"] = duplicate_stop_count
            duplicate_stop_changed = True

    path.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")
    log("已将网页设置保存到密钥文件。")
    if interval_changed:
        SETTINGS_CHANGED_EVENT.set()
        log(f"已将运行间隔更新为 {config['run_interval_seconds']} 秒（网页按{interval_unit}保存）。")
    if duplicate_stop_changed:
        log(f"已将连续已下载停止阈值更新为 {config['browser']['consecutive_downloaded_stop_count']} 条。")
    return {
        "ok": True,
        "cookie_present": bool(secrets.get("xhs_cookie", "").strip()),
        "cookie_summary": cookie_summary(secrets.get("xhs_cookie", "")),
        "user_agent_present": bool(secrets.get("xhs_user_agent", "").strip()),
        "run_interval_seconds": config.get("run_interval_seconds"),
        "run_interval_hours": round(float(config.get("run_interval_seconds") or 0) / 3600, 3),
        "consecutive_downloaded_stop_count": config.get("browser", {}).get("consecutive_downloaded_stop_count"),
    }


def runtime_value(
    config: dict[str, Any],
    secret_key: str,
    env_name: str,
    default: str = "",
    file_path: str = "",
) -> str:
    secrets = load_secrets(config)
    secret_value = secrets.get(secret_key, "").strip()
    if secret_value:
        return secret_value
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    env_file_value = read_text_secret_file(os.getenv(f"{env_name}_FILE", ""))
    if env_file_value:
        return env_file_value
    file_value = read_text_secret_file(file_path)
    if file_value:
        return file_value
    return default


def runtime_cookie_value(config: dict[str, Any], secret_key: str, env_name: str, file_path: str = "") -> str:
    return normalize_cookie_text(runtime_value(config, secret_key, env_name, file_path=file_path))


def sync_downloader_settings(config: dict[str, Any]) -> None:
    sync_config = config.get("sync_settings", {})
    if not sync_config.get("enabled", False):
        return

    settings_path = Path(sync_config.get("path") or "")
    settings: dict[str, Any] = {}
    changed = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            log(f"无法读取 settings.json，跳过 Cookie 同步：{error}")
            return
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        changed = True

    defaults = sync_config.get("defaults", {})
    if isinstance(defaults, dict):
        for key, value in defaults.items():
            if key == "mapping_data" and isinstance(settings.get(key), dict):
                continue
            if key not in settings or settings.get(key) != value:
                settings[key] = value
                changed = True

    sync_cookie = bool(sync_config.get("sync_cookie", False))
    sync_user_agent = bool(sync_config.get("sync_user_agent", True))
    cookie = ""
    if sync_cookie:
        cookie = runtime_value(
            config,
            sync_config.get("cookie_secret_key", "xhs_cookie"),
            sync_config.get("cookie_env", "XHS_COOKIE"),
            file_path=str(sync_config.get("cookie_file") or config.get("cookie_file", "")),
        )
        cookie = normalize_cookie_text(cookie)
    elif "cookie" in settings:
        settings.pop("cookie", None)
        changed = True
    user_agent = runtime_value(
        config,
        sync_config.get("user_agent_secret_key", "xhs_user_agent"),
        sync_config.get("user_agent_env", "XHS_USER_AGENT"),
        str(config.get("default_user_agent", "")),
    )
    if not cookie and not (sync_user_agent and user_agent) and not changed:
        log("Cookie 和 User Agent 均为空，跳过设置同步。")
        return
    if cookie and settings.get("cookie") != cookie:
        settings["cookie"] = cookie
        changed = True
    if sync_user_agent and user_agent and settings.get("user_agent") != user_agent:
        settings["user_agent"] = user_agent
        changed = True

    if not changed:
        return

    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    log(f"已同步小红书下载器 settings 到 {settings_path}（Cookie 同步：{'开启' if sync_cookie else '关闭'}）")


def start_dashboard_server(config: dict[str, Any], config_path: str) -> None:
    web_config = config.get("web", {})
    if not web_config.get("enabled", False):
        return

    host = str(web_config.get("host", "0.0.0.0"))
    port = int(web_config.get("port", 8080))
    handler = make_dashboard_handler(config, config_path)
    server = ThreadingHTTPServer((host, port), handler)
    thread = Thread(target=server.serve_forever, name="dashboard-server", daemon=True)
    thread.start()
    log(f"状态面板已启动：http://{host}:{port}")


def make_dashboard_handler(config: dict[str, Any], config_path: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self.send_html(DASHBOARD_HTML)
            elif path == "/api/status":
                self.send_json(collect_dashboard_status(config, config_path))
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/run-now":
                with RUNTIME_LOCK:
                    already_running = bool(RUNTIME.get("is_running"))
                if not already_running:
                    RUN_NOW_EVENT.set()
                    log("状态面板请求立即运行。")
                self.send_json({"ok": True, "already_running": already_running})
            elif path == "/api/settings":
                try:
                    payload = self.read_json_body()
                    self.send_json(save_web_settings(config, payload))
                except ValueError as error:
                    self.send_json({"ok": False, "error": str(error)})
            else:
                self.send_error(404)

        def read_json_body(self) -> dict[str, Any]:
            length_text = self.headers.get("Content-Length", "0")
            try:
                length = int(length_text)
            except ValueError as error:
                raise ValueError("Invalid Content-Length") from error
            if length > 300000:
                raise ValueError("Request body is too large")
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def send_json(self, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def collect_dashboard_status(config: dict[str, Any], config_path: str) -> dict[str, Any]:
    with RUNTIME_LOCK:
        runtime = dict(RUNTIME)
        logs = list(LOG_LINES)[-int(config.get("web", {}).get("log_lines", 200)) :]

    db_path = str(config.get("database", DEFAULT_CONFIG["database"]))
    status_counts: dict[str, int] = {}
    recent_runs: list[dict[str, Any]] = []
    recent_failed: list[dict[str, Any]] = []
    recent_downloaded: list[dict[str, Any]] = []
    last_run: dict[str, Any] | None = None
    total_notes = 0

    if Path(db_path).exists():
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            total_notes = int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
            status_counts = {
                row["status"]: int(row["count"])
                for row in conn.execute("SELECT status, COUNT(*) AS count FROM notes GROUP BY status")
            }
            recent_runs = rows_to_dicts(
                conn.execute(
                    """
                    SELECT id, started_at, finished_at, discovered_count, pending_count,
                           downloaded_count, failed_count, stop_marker_found, message
                    FROM runs
                    ORDER BY id DESC
                    LIMIT 8
                    """
                )
            )
            last_run = recent_runs[0] if recent_runs else None
            recent_failed = rows_to_dicts(
                conn.execute(
                    """
                    SELECT note_id, title, author, last_error, updated_at
                    FROM notes
                    WHERE status = 'failed'
                    ORDER BY updated_at DESC
                    LIMIT 8
                    """
                )
            )
            recent_downloaded = rows_to_dicts(
                conn.execute(
                    """
                    SELECT note_id, title, author, downloaded_at
                    FROM notes
                    WHERE status = 'downloaded'
                    ORDER BY downloaded_at DESC
                    LIMIT 8
                    """
                )
            )
            conn.close()
        except sqlite3.Error as error:
            runtime["last_error"] = f"Dashboard database read failed: {error}"

    browser_config = config.get("browser", {})
    sync_config = config.get("sync_settings", {})
    cookie_value = runtime_cookie_value(
        config,
        str(config.get("api_cookie_secret_key", "xhs_cookie")),
        str(config.get("api_cookie_env", "XHS_COOKIE")),
        str(config.get("api_cookie_file") or config.get("cookie_file", "")),
    )
    user_agent_value = runtime_value(
        config,
        str(browser_config.get("user_agent_secret_key", "xhs_user_agent")),
        str(browser_config.get("user_agent_env", "XHS_USER_AGENT")),
        str(config.get("default_user_agent", "")),
    )
    return {
        "runtime": runtime,
        "config": {
            "config_path": config_path,
            "api_url": config.get("api_url"),
            "auto_run_enabled": config.get("auto_run_enabled"),
            "api_cookie_enabled": config.get("api_cookie_enabled"),
            "database": db_path,
            "run_interval_seconds": config.get("run_interval_seconds"),
            "request_delay_seconds": config.get("request_delay_seconds"),
            "jitter_seconds": config.get("jitter_seconds"),
            "secrets_path": config.get("secrets_path"),
            "cookie_file": config.get("cookie_file"),
            "cookie_present": bool(cookie_value),
            "cookie_summary": cookie_summary(cookie_value),
            "user_agent_present": bool(user_agent_value),
            "user_agent_value": user_agent_value,
            "browser_enabled": browser_config.get("enabled"),
            "browser_backend": browser_config.get("backend", "playwright"),
            "browser_human_preset": browser_config.get("cloakbrowser_human_preset", "default"),
            "browser_persistent_profile": browser_config.get("cloakbrowser_persistent_profile", True),
            "browser_locale": browser_config.get("locale", "zh-CN"),
            "browser_timezone": browser_config.get("timezone_id", "Asia/Shanghai"),
            "headless": browser_config.get("headless"),
            "scroll_count": browser_config.get("scroll_count"),
            "consecutive_downloaded_stop_count": browser_config.get("consecutive_downloaded_stop_count"),
            "settings_sync_enabled": sync_config.get("enabled"),
            "settings_sync_cookie": sync_config.get("sync_cookie", False),
            "settings_path": sync_config.get("path"),
            "targets": [
                {
                    "name": item.get("name"),
                    "kind": item.get("kind"),
                    "url": item.get("url"),
                    "max_links": item.get("max_links"),
                    "stop_title": item.get("stop_title"),
                }
                for item in browser_config.get("targets", [])
            ],
        },
        "database": {
            "total_notes": total_notes,
            "status_counts": status_counts,
            "last_run": last_run,
            "recent_runs": recent_runs,
            "recent_failed": recent_failed,
            "recent_downloaded": recent_downloaded,
        },
        "logs": logs,
    }


def rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def ensure_profile_tab_url(url: str, kind: str) -> str:
    if kind != "profile_liked" or not url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("tab") == "liked":
        return url
    query["tab"] = "liked"
    return urlunparse(parsed._replace(query=urlencode(query)))


DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>XHS Auto Worker</title>
  <style>
__APP_STYLE__
  </style>
</head>
<body>
  <header>
    <div>
      <h1>小红书点赞自动下载</h1>
      <div class="muted" id="subtitle">正在读取状态...</div>
    </div>
    <div class="toolbar">
      <span class="pill" id="statusPill">状态</span>
      <button id="runNow" type="button">立即运行一次</button>
    </div>
  </header>
  <main>
    <div class="grid">
      <div class="metric"><div class="label">上次开始</div><div class="value" id="lastStart">-</div></div>
      <div class="metric"><div class="label">上次结束</div><div class="value" id="lastFinish">-</div></div>
      <div class="metric"><div class="label">下次运行</div><div class="value" id="nextRun">-</div></div>
      <div class="metric"><div class="label">运行间隔</div><div class="value" id="interval">-</div></div>
    </div>
    <div class="grid">
      <div class="metric"><div class="label">作品总数</div><div class="value" id="totalNotes">0</div></div>
      <div class="metric"><div class="label">已下载</div><div class="value" id="downloaded">0</div></div>
      <div class="metric"><div class="label">待处理</div><div class="value" id="pending">0</div></div>
      <div class="metric"><div class="label">失败</div><div class="value" id="failed">0</div></div>
    </div>
    <section>
      <h2>Cookie 设置</h2>
      <div class="body">
        <label class="muted" for="cookieInput">小红书 Cookie</label>
        <textarea id="cookieInput" rows="5" placeholder="在这里粘贴新的 Cookie；留空保存不会覆盖旧 Cookie"></textarea>
        <label class="muted" for="userAgentInput">User Agent</label>
        <input id="userAgentInput" type="text" placeholder="浏览器 User Agent">
        <label class="muted" for="intervalInput">运行间隔（小时）</label>
        <input id="intervalInput" type="number" min="0.02" max="720" step="0.1" placeholder="例如 720 表示 30 天">
        <label class="muted" for="duplicateStopInput">连续已下载自动停止（条，0 表示关闭）</label>
        <input id="duplicateStopInput" type="number" min="0" max="1000" step="1" placeholder="例如 10 表示连续 10 条已下载就停止滚动">
        <div class="toolbar formbar">
          <button id="saveSettings" type="button">保存设置</button>
          <span class="muted" id="saveMessage"></span>
        </div>
      </div>
    </section>
    <section>
      <h2>配置与调试</h2>
      <div class="body kv" id="debugKv"></div>
    </section>
    <div class="split">
      <section>
        <h2>最近运行</h2>
        <div class="body"><table id="runsTable"></table></div>
      </section>
      <section>
        <h2>最近失败</h2>
        <div class="body"><table id="failedTable"></table></div>
      </section>
    </div>
    <section>
      <h2>最近下载</h2>
      <div class="body"><table id="downloadedTable"></table></div>
    </section>
    <section>
      <h2>日志</h2>
      <div class="body"><pre id="logs"></pre></div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (s) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[s]));
    const fmtTime = (value) => {
      if (!value) return "无";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
    };
    const fmtInterval = (seconds) => {
      seconds = Number(seconds || 0);
      if (seconds >= 3600) return `${Math.round(seconds / 3600 * 10) / 10} 小时`;
      if (seconds >= 60) return `${Math.round(seconds / 60)} 分钟`;
      return `${seconds} 秒`;
    };
    const count = (data, name) => Number(data.database.status_counts[name] || 0);

    async function loadStatus() {
      const response = await fetch("/api/status", { cache: "no-store" });
      const data = await response.json();
      render(data);
    }

    function render(data) {
      const runtime = data.runtime;
      const cfg = data.config;
      $("subtitle").textContent = `API: ${cfg.api_url}`;
      if (document.activeElement !== $("userAgentInput")) {
        $("userAgentInput").value = cfg.user_agent_value || "";
      }
      if (document.activeElement !== $("intervalInput")) {
        const hours = Number(cfg.run_interval_seconds || 0) / 3600;
        $("intervalInput").value = hours ? String(Math.round(hours * 100) / 100) : "";
      }
      if (document.activeElement !== $("duplicateStopInput")) {
        $("duplicateStopInput").value = cfg.consecutive_downloaded_stop_count ?? "";
      }
      $("lastStart").textContent = fmtTime(runtime.last_run_started_at);
      $("lastFinish").textContent = fmtTime(runtime.last_run_finished_at);
      $("nextRun").textContent = fmtTime(runtime.next_run_at);
      $("interval").textContent = fmtInterval(cfg.run_interval_seconds);
      $("totalNotes").textContent = data.database.total_notes;
      $("downloaded").textContent = count(data, "downloaded");
      $("pending").textContent = count(data, "discovered") + count(data, "pending");
      $("failed").textContent = count(data, "failed");

      const pill = $("statusPill");
      pill.className = "pill";
      if (runtime.is_running) {
        pill.textContent = "正在运行";
        pill.classList.add("warn");
      } else if (runtime.last_error) {
        pill.textContent = "有错误";
        pill.classList.add("bad");
      } else {
        pill.textContent = "空闲";
        pill.classList.add("good");
      }

      $("debugKv").innerHTML = kvRows([
        ["Cookie", cfg.cookie_present ? "已填写" : "未填写"],
        ["User Agent", cfg.user_agent_present ? "已填写" : "未填写"],
        ["网页保存路径", cfg.secrets_path],
        ["配置文件", cfg.config_path],
        ["数据库", cfg.database],
        ["同步 settings", cfg.settings_sync_enabled ? `开启：${cfg.settings_path}` : "关闭"],
        ["同步下载器 Cookie", cfg.settings_sync_cookie ? "开启" : "关闭"],
        ["自动运行", cfg.auto_run_enabled ? "开启" : "关闭"],
        ["下载请求 Cookie", cfg.api_cookie_enabled ? "开启" : "关闭"],
        ["无头浏览器", cfg.browser_enabled ? "开启" : "关闭"],
        ["浏览器后端", cfg.browser_backend || "playwright"],
        ["CloakBrowser", `${cfg.browser_persistent_profile ? "持久 profile" : "临时 context"} / ${cfg.browser_human_preset || "default"}`],
        ["地区指纹", `${cfg.browser_locale || "zh-CN"} / ${cfg.browser_timezone || "Asia/Shanghai"}`],
        ["滚动次数", cfg.scroll_count],
        ["连续已下载自动停止", Number(cfg.consecutive_downloaded_stop_count || 0) > 0 ? `${cfg.consecutive_downloaded_stop_count} 条` : "关闭"],
        ["请求间隔", `${cfg.request_delay_seconds}s + 随机 ${cfg.jitter_seconds}s`],
        ["目标页面", (cfg.targets || []).map(t => `${t.name || ""} ${t.kind || ""} ${t.url || ""}`).join("\n") || "未配置"],
        ["最近错误", runtime.last_error || "无"],
      ]);

      $("runsTable").innerHTML = table(
        ["开始", "发现", "待下", "成功", "失败", "停止标记"],
        data.database.recent_runs.map(r => [
          fmtTime(r.started_at), r.discovered_count, r.pending_count,
          r.downloaded_count, r.failed_count, r.stop_marker_found ? "是" : "否"
        ])
      );
      $("failedTable").innerHTML = table(
        ["时间", "标题", "错误"],
        data.database.recent_failed.map(r => [fmtTime(r.updated_at), r.title || r.note_id, r.last_error || ""])
      );
      $("downloadedTable").innerHTML = table(
        ["时间", "标题", "作者"],
        data.database.recent_downloaded.map(r => [fmtTime(r.downloaded_at), r.title || r.note_id, r.author || ""])
      );
      $("logs").textContent = (data.logs || []).join("\n") || "暂无日志";
    }

    function kvRows(rows) {
      return rows.map(([k, v]) => `<div>${esc(k)}</div><div><code>${esc(v)}</code></div>`).join("");
    }

    function table(headers, rows) {
      const head = `<tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr>`;
      const body = rows.length
        ? rows.map(row => `<tr>${row.map(cell => `<td>${esc(cell)}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${headers.length}" class="muted">暂无</td></tr>`;
      return head + body;
    }

    $("runNow").addEventListener("click", async () => {
      $("runNow").disabled = true;
      await fetch("/api/run-now", { method: "POST" });
      setTimeout(() => { $("runNow").disabled = false; loadStatus(); }, 800);
    });

    $("saveSettings").addEventListener("click", async () => {
      $("saveSettings").disabled = true;
      $("saveMessage").textContent = "正在保存...";
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cookie: $("cookieInput").value,
          user_agent: $("userAgentInput").value,
          run_interval_hours: $("intervalInput").value,
          consecutive_downloaded_stop_count: $("duplicateStopInput").value
        })
      });
      const result = await response.json();
      if (result.ok) {
        $("cookieInput").value = "";
        $("saveMessage").textContent = "已保存，新设置会自动生效。";
      } else {
        $("saveMessage").textContent = result.error || "保存失败";
      }
      $("saveSettings").disabled = false;
      loadStatus();
    });

    loadStatus();
    setInterval(loadStatus, 5000);
  </script>
</body>
</html>
""".replace(
    "__APP_STYLE__",
    app_css(
        """
header{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);color:var(--text);backdrop-filter:blur(8px)}
main{display:block;max-width:1180px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:16px}
.metric{min-height:88px}
section{padding:0;margin-bottom:16px;overflow:hidden}
section h2{margin:0;padding:14px 16px;border-bottom:1px solid var(--line)}
.body{padding:14px 16px}
textarea{min-height:112px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.pill.good{background:var(--ok-bg);border-color:var(--ok-line);color:var(--ok)}
.pill.bad{background:var(--danger-bg);border-color:#efb0aa;color:var(--danger)}
.split{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.kv{display:grid;grid-template-columns:160px minmax(0,1fr);gap:8px 12px;font-size:14px}
.kv div:nth-child(odd){color:var(--muted)}
.nowrap{white-space:nowrap}
@media(max-width:860px){header{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.split{grid-template-columns:1fr}.kv{grid-template-columns:1fr}}
@media(max-width:520px){.grid{grid-template-columns:1fr}table{font-size:13px}}
"""
    ),
)


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def open_database(path: str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_database(conn)
    return conn


def init_database(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            note_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            author TEXT,
            source TEXT,
            target_name TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            stop_marker INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            downloaded_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_stop_marker ON notes(stop_marker)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            discovered_count INTEGER NOT NULL DEFAULT 0,
            pending_count INTEGER NOT NULL DEFAULT 0,
            downloaded_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            stop_marker_found INTEGER NOT NULL DEFAULT 0,
            message TEXT
        )
        """
    )
    conn.commit()


def migrate_legacy_processed_json(conn: sqlite3.Connection, path: str | None) -> None:
    if not path:
        return
    source = Path(path)
    if not source.exists():
        return
    marker = source.with_suffix(source.suffix + ".migrated")
    if marker.exists():
        return
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log(f"发现旧版 processed 文件，但无法迁移：{source}")
        return
    if not isinstance(data, list):
        return
    timestamp = now_text()
    for item in data:
        note_id = str(item)
        conn.execute(
            """
            INSERT OR IGNORE INTO notes (
                note_id, url, source, status, first_seen, last_seen, downloaded_at, updated_at
            ) VALUES (?, ?, 'legacy', 'downloaded', ?, ?, ?, ?)
            """,
            (note_id, note_id, timestamp, timestamp, timestamp, timestamp),
        )
    conn.commit()
    marker.write_text(timestamp, encoding="utf-8")
    log(f"已迁移 {len(data)} 条旧版 processed 记录到 SQLite。")


def normalize_title(title: Any) -> str:
    if title is None:
        return ""
    return re.sub(r"\s+", " ", str(title)).strip()


def matches_stop_title(title: str, target: dict[str, Any], config: dict[str, Any]) -> bool:
    stop_config = dict(config.get("stop_marker", {}))
    stop_config.update(target.get("stop_marker", {}))
    if target.get("stop_title"):
        stop_config["title"] = target["stop_title"]
    if target.get("stop_title_match"):
        stop_config["match"] = target["stop_title_match"]
    if not stop_config.get("enabled", True):
        return False
    expected = normalize_title(stop_config.get("title"))
    actual = normalize_title(title)
    if not expected or not actual:
        return False
    if stop_config.get("match", "exact") == "contains":
        return expected in actual
    return actual == expected


def note_id_from_url(url: str) -> str:
    for pattern in NOTE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return url


def make_note(
    url: str,
    *,
    note_id: str | None = None,
    title: str | None = None,
    author: str | None = None,
    source: str,
    target_name: str | None = None,
    stop_marker: bool = False,
) -> dict[str, Any]:
    return {
        "note_id": note_id or note_id_from_url(url),
        "url": url,
        "title": normalize_title(title),
        "author": normalize_title(author),
        "source": source,
        "target_name": target_name,
        "stop_marker": bool(stop_marker),
    }


def record_note(conn: sqlite3.Connection, note: dict[str, Any]) -> None:
    timestamp = now_text()
    status = "stop_marker" if note.get("stop_marker") else "discovered"
    conn.execute(
        """
        INSERT INTO notes (
            note_id, url, title, author, source, target_name, status, stop_marker,
            first_seen, last_seen, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET
            url = excluded.url,
            title = COALESCE(NULLIF(excluded.title, ''), notes.title),
            author = COALESCE(NULLIF(excluded.author, ''), notes.author),
            source = COALESCE(excluded.source, notes.source),
            target_name = COALESCE(excluded.target_name, notes.target_name),
            stop_marker = CASE WHEN excluded.stop_marker = 1 THEN 1 ELSE notes.stop_marker END,
            status = CASE
                WHEN excluded.stop_marker = 1 THEN 'stop_marker'
                WHEN notes.status IN ('downloaded', 'stop_marker') THEN notes.status
                ELSE notes.status
            END,
            last_seen = excluded.last_seen,
            updated_at = excluded.updated_at
        """,
        (
            note["note_id"],
            note["url"],
            note.get("title") or None,
            note.get("author") or None,
            note.get("source"),
            note.get("target_name"),
            status,
            1 if note.get("stop_marker") else 0,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def get_pending_notes(conn: sqlite3.Connection, config: dict[str, Any]) -> list[sqlite3.Row]:
    retry_failed = bool(config.get("retry_failed", True))
    max_attempts = int(config.get("max_download_attempts", 0) or 0)
    params: list[Any] = []
    status_clause = "status IN ('discovered', 'pending')"
    if retry_failed:
        status_clause = f"({status_clause} OR status = 'failed')"
    attempts_clause = ""
    if max_attempts > 0:
        attempts_clause = "AND attempts < ?"
        params.append(max_attempts)
    return list(
        conn.execute(
            f"""
            SELECT * FROM notes
            WHERE stop_marker = 0
              AND {status_clause}
              {attempts_clause}
            ORDER BY first_seen ASC
            """,
            params,
        )
    )


def mark_downloaded(conn: sqlite3.Connection, note_id: str) -> None:
    timestamp = now_text()
    conn.execute(
        """
        UPDATE notes
        SET status = 'downloaded',
            attempts = attempts + 1,
            last_error = NULL,
            downloaded_at = ?,
            updated_at = ?
        WHERE note_id = ?
        """,
        (timestamp, timestamp, note_id),
    )


def mark_failed(conn: sqlite3.Connection, note_id: str, error: str) -> None:
    timestamp = now_text()
    conn.execute(
        """
        UPDATE notes
        SET status = 'failed',
            attempts = attempts + 1,
            last_error = ?,
            updated_at = ?
        WHERE note_id = ?
        """,
        (error[:1000], timestamp, note_id),
    )


def extract_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for match in NOTE_URL_RE.finditer(text):
        url = match.group(0).strip().rstrip("),.;，。；")
        urls.append(url)
    return dedupe(urls)


def read_queue_notes(paths: list[str]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for item in paths:
        path = Path(item)
        files = sorted(path.glob("*.txt")) if path.is_dir() else [path]
        for file in files:
            if not file.exists():
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file.read_text(encoding="utf-8-sig")
            for url in extract_urls_from_text(text):
                notes.append(make_note(url, source="queue", target_name=file.name))
    return dedupe_notes(notes)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def dedupe_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for note in notes:
        key = note.get("note_id") or note.get("url")
        if key and key not in seen:
            seen.add(key)
            result.append(note)
    return result


def note_downloaded_before(conn: sqlite3.Connection, note: dict[str, Any]) -> bool:
    note_id = note.get("note_id")
    url = note.get("url")
    row = conn.execute(
        """
        SELECT status FROM notes
        WHERE note_id = ? OR url = ?
        LIMIT 1
        """,
        (note_id, url),
    ).fetchone()
    return bool(row and row["status"] == "downloaded")


def post_download(api_url: str, url: str, *, skip: bool, cookie: str | None, timeout: int = 90) -> tuple[bool, str]:
    body: dict[str, Any] = {"url": url, "download": True, "skip": skip}
    if cookie:
        body["cookie"] = cookie
    data = json.dumps(body).encode("utf-8")
    request = Request(
        api_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 300, text[:500]
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        return False, f"HTTP {error.code}: {text[:500]}"
    except URLError as error:
        return False, f"Request failed: {error.reason}"
    except TimeoutError:
        return False, "Request timed out"


def cookie_header_to_playwright(cookie_header: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for part in normalize_cookie_text(cookie_header).split(";"):
        if "=" not in part:
            continue
        name, value = part.strip().split("=", 1)
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return cookies


def load_extractor_script(config: dict[str, Any]) -> str:
    path = Path(config.get("browser", {}).get("extractor") or "")
    if path.exists():
        return path.read_text(encoding="utf-8")
    bundled = Path(__file__).with_name("liked_extractor.js")
    if bundled.exists():
        return bundled.read_text(encoding="utf-8")
    return FALLBACK_EXTRACTOR_JS


def load_async_playwright(browser_config: dict[str, Any]) -> Any | None:
    try:
        from playwright.async_api import async_playwright

        return locked_async_playwright(async_playwright)
    except ImportError as error:
        log(f"Playwright 导入失败：{error}")
        log(f"Python 可执行文件：{sys.executable}")

    if not browser_config.get("auto_install_playwright", False):
        log("浏览器模式需要 Playwright。请等 GitHub Actions 构建新镜像，或关闭 browser.enabled。")
        return None

    version = str(browser_config.get("playwright_version", "1.56.0"))
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        f"playwright=={version}",
    ]
    log(f"正在容器内尝试安装 Python Playwright {version}。")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as error:
        log(f"自动安装 Playwright 时 pip 未完成即失败：{error}")
        return None

    if result.returncode != 0:
        log(f"自动安装 Playwright 失败，退出码：{result.returncode}。")
        if result.stdout.strip():
            log(f"pip 标准输出：{result.stdout.strip()[-1200:]}")
        if result.stderr.strip():
            log(f"pip 错误输出：{result.stderr.strip()[-1200:]}")
        return None

    log("Playwright 自动安装完成。")
    try:
        from playwright.async_api import async_playwright

        return locked_async_playwright(async_playwright)
    except ImportError as error:
        log(f"安装后仍无法导入 Playwright：{error}")
        return None


async def run_with_browser_context(
    browser_config: dict[str, Any],
    context_kwargs: dict[str, Any],
    callback: Any,
) -> list[dict[str, Any]]:
    backend = str(browser_config.get("backend") or "playwright").lower()
    if backend == "cloakbrowser":
        lock_cm = browser_lock()
        lock_cm.__enter__()
        context = None
        close_target = None
        try:
            from cloakbrowser import launch_context_async, launch_persistent_context_async

            viewport = browser_config.get("viewport") or context_kwargs.get("viewport")
            locale = str(browser_config.get("locale") or context_kwargs.get("locale") or "zh-CN")
            timezone_id = str(browser_config.get("timezone_id") or context_kwargs.get("timezone_id") or "Asia/Shanghai")
            user_agent = context_kwargs.get("user_agent")
            human_preset = str(browser_config.get("cloakbrowser_human_preset") or "default")
            launch_options: dict[str, Any] = {
                "headless": bool(browser_config.get("headless", True)),
                "stealth_args": bool(browser_config.get("cloakbrowser_stealth_args", True)),
                "locale": locale,
                "timezone": timezone_id,
                "geoip": bool(browser_config.get("cloakbrowser_geoip", False)),
                "humanize": bool(browser_config.get("cloakbrowser_humanize", True)),
                "human_preset": human_preset,
                "viewport": viewport,
                "backend": browser_config.get("cloakbrowser_backend") or None,
                "color_scheme": browser_config.get("color_scheme") or "light",
            }
            if user_agent:
                launch_options["user_agent"] = user_agent
            human_config = browser_config.get("cloakbrowser_human_config")
            if isinstance(human_config, dict):
                launch_options["human_config"] = human_config
            if browser_config.get("proxy"):
                launch_options["proxy"] = browser_config.get("proxy")

            persistent = bool(browser_config.get("cloakbrowser_persistent_profile", True))
            if persistent:
                user_data_dir = Path(str(browser_config.get("cloakbrowser_user_data_dir") or "/state/xhs/cloakbrowser/profile"))
                user_data_dir.mkdir(parents=True, exist_ok=True)
                log(f"小红书浏览器后端：CloakBrowser（持久 profile，human={human_preset}）")
                context = await launch_persistent_context_async(
                    user_data_dir,
                    **launch_options,
                )
                close_target = context
            else:
                log(f"小红书浏览器后端：CloakBrowser（临时 context，human={human_preset}）")
                context = await launch_context_async(
                    **launch_options,
                )
                close_target = context
        except ImportError as error:
            log(f"CloakBrowser 导入失败，回退 Playwright：{error}")
        except Exception as error:
            log(f"CloakBrowser 启动失败，回退 Playwright：{error}")
        finally:
            if context is None:
                lock_cm.__exit__(*sys.exc_info())

        if context is not None:
            try:
                return await callback(context)
            finally:
                try:
                    if close_target is not None:
                        await close_target.close()
                finally:
                    lock_cm.__exit__(*sys.exc_info())

    async_playwright = load_async_playwright(browser_config)
    if async_playwright is None:
        log("未安装 Python Playwright，浏览器模式不可用。")
        return []

    log("小红书浏览器后端：Playwright")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=bool(browser_config.get("headless", True)))
        context = await browser.new_context(**context_kwargs)
        try:
            return await callback(context)
        finally:
            await context.close()
            await browser.close()


async def collect_browser_notes(config: dict[str, Any], conn: sqlite3.Connection) -> list[dict[str, Any]]:
    browser_config = config.get("browser", {})
    if not browser_config.get("enabled"):
        return []

    user_agent = runtime_value(
        config,
        browser_config.get("user_agent_secret_key", "xhs_user_agent"),
        browser_config.get("user_agent_env", "XHS_USER_AGENT"),
        str(config.get("default_user_agent", "")),
    )
    cookie = runtime_cookie_value(
        config,
        browser_config.get("cookie_secret_key", "xhs_cookie"),
        browser_config.get("cookie_env", "XHS_COOKIE"),
        str(browser_config.get("cookie_file") or config.get("cookie_file", "")),
    )
    targets = browser_config.get("targets", [])
    if not targets:
        log("浏览器模式已启用，但 browser.targets 为空。")
        return []

    extractor = load_extractor_script(config)
    viewport = browser_config.get("viewport")
    if not isinstance(viewport, dict):
        viewport = {"width": 1440, "height": 1000}
    context_kwargs: dict[str, Any] = {
        "viewport": viewport,
        "locale": str(browser_config.get("locale") or "zh-CN"),
        "timezone_id": str(browser_config.get("timezone_id") or "Asia/Shanghai"),
    }
    if user_agent:
        context_kwargs["user_agent"] = user_agent

    async def collect_from_context(context: Any) -> list[dict[str, Any]]:
        if cookie:
            await context.add_cookies(cookie_header_to_playwright(cookie))
        else:
            log("Cookie 为空；采集点赞页通常需要已登录的 Cookie。")

        collected: list[dict[str, Any]] = []
        for target in targets:
            target_notes = await collect_target_notes(context, target, browser_config, config, extractor, conn)
            collected.extend(target_notes)
        return collected

    collected = await run_with_browser_context(browser_config, context_kwargs, collect_from_context)
    return dedupe_notes(collected)


async def collect_target_notes(
    context: Any,
    target: dict[str, Any],
    browser_config: dict[str, Any],
    config: dict[str, Any],
    extractor: str,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    kind = target.get("kind", "profile_liked")
    url = ensure_profile_tab_url(str(target.get("url", "")), kind)
    if not url:
        return []

    name = target.get("name") or url
    max_links = int(target.get("max_links", 0) or 0)
    timeout_ms = int(browser_config.get("target_timeout_ms", 45000))
    scroll_count = int(target.get("scroll_count", browser_config.get("scroll_count", 40)))
    scroll_delay_ms = int(target.get("scroll_delay_ms", browser_config.get("scroll_delay_ms", 1200)))
    consecutive_downloaded_stop_count = int(
        target.get(
            "consecutive_downloaded_stop_count",
            browser_config.get("consecutive_downloaded_stop_count", 10),
        )
        or 0
    )

    async def extract_loaded_notes() -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
        result = await page.evaluate(extractor, {"kind": kind, "url": url})
        raw_notes = []
        if isinstance(result, dict):
            raw_notes = result.get("stateNotes") or []
            if not raw_notes and not stop_required_for_target(target, config):
                raw_notes = result.get("hrefNotes") or []

        notes: list[dict[str, Any]] = []
        seen: set[str] = set()
        consecutive_downloaded = 0
        for item in raw_notes:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            note = make_note(
                item["url"],
                note_id=item.get("id"),
                title=item.get("title"),
                author=item.get("author"),
                source=kind,
                target_name=name,
            )
            key = note.get("note_id") or note.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            if matches_stop_title(note.get("title", ""), target, config):
                note["stop_marker"] = True
                notes.append(note)
                return notes, note, False
            notes.append(note)
            if consecutive_downloaded_stop_count > 0 and note_downloaded_before(conn, note):
                consecutive_downloaded += 1
                if consecutive_downloaded >= consecutive_downloaded_stop_count:
                    return notes, None, True
            else:
                consecutive_downloaded = 0
        return notes, None, False

    page = await context.new_page()
    try:
        log(f"正在打开目标：{name}")
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(3000)
        await maybe_click_profile_tab(page, target, kind)
        await page.wait_for_timeout(2000)

        notes: list[dict[str, Any]] = []
        stop_note: dict[str, Any] | None = None
        duplicate_stop = False
        for scroll_index in range(scroll_count + 1):
            notes, stop_note, duplicate_stop = await extract_loaded_notes()
            if stop_note or duplicate_stop or scroll_index >= scroll_count:
                break
            await page.mouse.wheel(0, random.randint(500, 1100))
            await page.wait_for_timeout(scroll_delay_ms + random.randint(0, 350))

        if stop_note:
            log(f"目标 {name}：已找到停止标记，停止于标题之前：{stop_note.get('title')}")
        elif duplicate_stop:
            log(
                f"目标 {name}：连续 {consecutive_downloaded_stop_count} 条作品均已下载，停止继续滚动。"
            )
        elif stop_required_for_target(target, config):
            log(f"目标 {name}：本次未找到停止标记，仅下载数据库中新发现的作品。")

        downloadable_count = sum(1 for note in notes if not note.get("stop_marker"))
        if max_links > 0:
            keep: list[dict[str, Any]] = []
            kept_downloadable = 0
            for note in notes:
                if note.get("stop_marker"):
                    keep.append(note)
                elif kept_downloadable < max_links:
                    keep.append(note)
                    kept_downloadable += 1
            notes = keep
            downloadable_count = kept_downloadable

        log(f"目标 {name}：采集到 {downloadable_count} 条可下载作品。")
        return notes
    except Exception as error:
        log(f"目标 {name}：采集点赞作品失败：{error}")
        return []
    finally:
        await page.close()


def stop_required_for_target(target: dict[str, Any], config: dict[str, Any]) -> bool:
    if target.get("kind", "profile_liked") != "profile_liked":
        return False
    stop_config = dict(config.get("stop_marker", {}))
    stop_config.update(target.get("stop_marker", {}))
    return bool(stop_config.get("enabled", True))


async def maybe_click_profile_tab(page: Any, target: dict[str, Any], kind: str) -> None:
    labels = target.get("click_texts")
    if labels is None:
        labels = {
            "profile_liked": ["赞过", "点赞", "Liked", "Likes"],
            "profile_saved": ["收藏", "Collect", "Collections"],
            "profile_published": ["笔记", "发布", "Notes", "Posts"],
        }.get(kind, [])
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=True)
            count = await locator.count()
            if count > 0:
                await locator.first.click(timeout=3000)
                log(f"已点击主页标签：{label}")
                return
        except Exception:
            continue


FALLBACK_EXTRACTOR_JS = r"""
({kind, url}) => {
  const state = window.__INITIAL_STATE__ || {};
  const raw = (value) => value?._rawValue ?? value?.value ?? value;
  const makeNoteUrl = (id, token) => {
    if (!id || !token) return null;
    return `https://www.xiaohongshu.com/discovery/item/${id}?source=webshare&xhsshare=pc_web&xsec_token=${token}&xsec_source=pc_share`;
  };
  const normalizeRows = (rows) => {
    if (!Array.isArray(rows)) return [];
    return rows.map((item) => {
      const card = item?.noteCard || item?.note_card || item || {};
      const user = card?.user || item?.user || {};
      const id = item?.id || item?.noteId || item?.note_id || card?.id || card?.noteId || card?.note_id;
      const token = item?.xsecToken || item?.xsec_token || card?.xsecToken || card?.xsec_token;
      const noteUrl = makeNoteUrl(id, token);
      if (!noteUrl) return null;
      return {
        id,
        token,
        url: noteUrl,
        title: card?.displayTitle || card?.title || item?.displayTitle || item?.title || "",
        author: user?.nickName || user?.nickname || user?.name || ""
      };
    }).filter(Boolean);
  };

  let stateNotes = [];
  if (kind === "profile_liked") {
    stateNotes = normalizeRows(raw(state.user?.notes)?.[2]);
  } else if (kind === "profile_saved") {
    stateNotes = normalizeRows(raw(state.user?.notes)?.[1]);
  } else if (kind === "profile_published") {
    stateNotes = normalizeRows(raw(state.user?.notes)?.[0]);
  } else {
    const userNotes = raw(state.user?.notes);
    if (Array.isArray(userNotes)) {
      userNotes.forEach((rows) => stateNotes.push(...normalizeRows(rows)));
    }
  }

  const hrefNotes = Array.from(document.querySelectorAll("a[href]")).map((a) => {
    try {
      const link = new URL(a.getAttribute("href"), location.href);
      if (!/xiaohongshu\.com$/.test(link.hostname)) return null;
      if (!(/\/explore\/|\/discovery\/item\//.test(link.pathname))) return null;
      return { id: link.pathname.split("/").filter(Boolean).pop(), url: link.href, title: "", author: "" };
    } catch {
      return null;
    }
  }).filter(Boolean);

  return { stateNotes, hrefNotes };
}
"""


async def run_once(config: dict[str, Any]) -> None:
    sync_downloader_settings(config)

    started_at = now_text()
    with RUNTIME_LOCK:
        RUNTIME["is_running"] = True
        RUNTIME["last_run_started_at"] = started_at
        RUNTIME["last_run_finished_at"] = None
        RUNTIME["next_run_at"] = None
        RUNTIME["last_error"] = None

    conn: sqlite3.Connection | None = None
    run_id: int | None = None
    downloaded_count = 0
    failed_count = 0
    try:
        conn = open_database(str(config.get("database", DEFAULT_CONFIG["database"])))
        migrate_legacy_processed_json(conn, config.get("legacy_processed_json"))
        run_id = conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)",
            (started_at,),
        ).lastrowid
        conn.commit()

        notes = read_queue_notes(config.get("queue_files", []))
        notes.extend(await collect_browser_notes(config, conn))
        notes = dedupe_notes(notes)
        for note in notes:
            record_note(conn, note)
        conn.commit()

        pending = get_pending_notes(conn, config)
        stop_marker_found = any(note.get("stop_marker") for note in notes)
        log(f"本次发现 {len(notes)} 条作品，待下载 {len(pending)} 条。")

        api_url = str(config.get("api_url", DEFAULT_CONFIG["api_url"]))
        api_skip = bool(config.get("api_skip", True))
        api_cookie = None
        if bool(config.get("api_cookie_enabled", False)):
            api_cookie = runtime_cookie_value(
                config,
                str(config.get("api_cookie_secret_key", "xhs_cookie")),
                str(config.get("api_cookie_env", "XHS_COOKIE")),
                str(config.get("api_cookie_file") or config.get("cookie_file", "")),
            ) or None
        delay = float(config.get("request_delay_seconds", 3))
        jitter = float(config.get("jitter_seconds", 2))

        for index, row in enumerate(pending, start=1):
            note_id = row["note_id"]
            title = row["title"] or ""
            log(f"正在提交下载 [{index}/{len(pending)}] {note_id} {title}")
            ok, message = post_download(api_url, row["url"], skip=api_skip, cookie=api_cookie)
            if ok:
                mark_downloaded(conn, note_id)
                downloaded_count += 1
                log(f"下载提交成功：{note_id}")
            else:
                mark_failed(conn, note_id, message)
                failed_count += 1
                log(f"下载提交失败：{note_id}；{message}")
            conn.commit()
            if index < len(pending):
                time.sleep(delay + random.random() * jitter)

        conn.execute(
            """
            UPDATE runs
            SET finished_at = ?,
                discovered_count = ?,
                pending_count = ?,
                downloaded_count = ?,
                failed_count = ?,
                stop_marker_found = ?
            WHERE id = ?
            """,
            (
                now_text(),
                len(notes),
                len(pending),
                downloaded_count,
                failed_count,
                1 if stop_marker_found else 0,
                run_id,
            ),
        )
        conn.commit()
    except Exception as error:
        error_text = str(error)
        with RUNTIME_LOCK:
            RUNTIME["last_error"] = error_text
        log(f"本轮运行失败：{error_text}")
        if conn is not None and run_id is not None:
            conn.execute(
                "UPDATE runs SET finished_at = ?, message = ? WHERE id = ?",
                (now_text(), error_text[:1000], run_id),
            )
            conn.commit()
    finally:
        finished_at = now_text()
        with RUNTIME_LOCK:
            RUNTIME["is_running"] = False
            RUNTIME["last_run_finished_at"] = finished_at
        if conn is not None:
            conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="NAS worker for XHS-Downloader liked-note sync.")
    parser.add_argument("--config", default="/config/config.json", help="Path to config.json")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if not args.once:
        start_dashboard_server(config, args.config)
    while True:
        if args.once:
            await run_once(config)
            return 0
        auto_run_enabled = bool(config.get("auto_run_enabled", False))
        interval = int(config.get("run_interval_seconds", 1800))
        next_run_ts = time.time() + interval if auto_run_enabled else None
        with RUNTIME_LOCK:
            RUNTIME["next_run_at"] = (
                datetime.fromtimestamp(next_run_ts, timezone.utc).isoformat(timespec="seconds")
                if next_run_ts is not None
                else None
            )
        if auto_run_enabled:
            log(f"自动运行已启用，休眠 {interval} 秒，等待下次运行。")
        else:
            log("小红书自动运行已关闭，等待手动运行或浏览器脚本提交链接。")
        while True:
            remaining = (next_run_ts - time.time()) if next_run_ts is not None else None
            if remaining is not None and remaining <= 0:
                log("到达自动运行时间，开始执行。")
                break
            wait_timeout = min(remaining, 5) if remaining is not None else 5
            if RUN_NOW_EVENT.wait(timeout=wait_timeout):
                RUN_NOW_EVENT.clear()
                log("开始执行手动运行。")
                break
            if SETTINGS_CHANGED_EVENT.is_set():
                SETTINGS_CHANGED_EVENT.clear()
                auto_run_enabled = bool(config.get("auto_run_enabled", False))
                interval = int(config.get("run_interval_seconds", 1800))
                next_run_ts = time.time() + interval if auto_run_enabled else None
                with RUNTIME_LOCK:
                    RUNTIME["next_run_at"] = (
                        datetime.fromtimestamp(next_run_ts, timezone.utc).isoformat(timespec="seconds")
                        if next_run_ts is not None
                        else None
                    )
                if auto_run_enabled:
                    log(f"运行间隔已变化，已按 {interval} 秒重新安排下次运行。")
                else:
                    log("自动运行已关闭，取消下次自动运行时间。")
        await run_once(config)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
