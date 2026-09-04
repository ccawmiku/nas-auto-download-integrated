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
import yaml
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

COMMON_PATH = Path(__file__).resolve().parents[1] / "_common"
if COMMON_PATH.exists():
    sys.path.insert(0, str(COMMON_PATH))

try:
    from nas_auto_common.ui import app_css
except ModuleNotFoundError:
    def app_css(extra: str = "") -> str:
        return extra


PORT = int(os.environ.get("PORT", "14001"))
ROOT = Path("/opt/nas-auto")
APP_VERSION = os.environ.get("APP_VERSION", "v1.8.1-dev")
XHS_QUEUE_FILE = Path(os.environ.get("XHS_QUEUE_FILE", "/queue/xhs/links.txt"))
MAX_XHS_API_BODY_BYTES = 5_000_000
DOUYIN_CONFIG_PATH = Path(os.environ.get("DOUYIN_CONFIG_PATH", "/config/douyin/config.json"))
DOUYIN_COOKIE_YAML_PLACEHOLDER = "__DOUYIN_COOKIE_PLACEHOLDER__"
DEFAULT_DOUYIN_CONFIG: dict[str, Any] = {
    "download_dir": "/F2DL",
    "f2_config_dir": "/config/douyin/f2",
    "defaults": {
        "cover": False,
        "desc": False,
        "folderize": True,
        "interval": "all",
        "lyric": True,
        "max_connections": 5,
        "max_counts": 0,
        "max_retries": 5,
        "max_tasks": 10,
        "naming": "{create}-{nickname}-{aweme_id}",
        "page_counts": 20,
        "timeout": 10,
    },
    "jobs": [
        {
            "name": "like",
            "mode": "like",
            "url": "https://www.douyin.com/user/MS4wLjABAAAANozRUmTPV4ZpvI-QTMqocY_vLWGwerzSX5vlzfgWl5Q?from_tab_name=main&showTab=like&vid=7126720963458223363",
        },
        {
            "name": "collection",
            "mode": "collection",
            "url": "https://www.douyin.com/user/MS4wLjABAAAANozRUmTPV4ZpvI-QTMqocY_vLWGwerzSX5vlzfgWl5Q?from_tab_name=main&showTab=favorite_collection&vid=7126720963458223363",
        },
    ],
}

SERVICES = {
    "xhs": {"name": "小红书", "port": 18081, "path": "/xhs/", "config": "/config/xhs/config.json"},
    "x": {"name": "X", "port": 18082, "path": "/x/", "config": "/config/x/config.json"},
    "pixiv": {"name": "Pixiv", "port": 18083, "path": "/pixiv/", "config": "/config/pixiv/config.json"},
    "douyin": {"name": "抖音", "port": 18084, "path": "/douyin/", "config": "/config/douyin/config.json"},
}

DOUYIN_REFERENCE_COOKIE_ORDER = (
    "UIFID_TEMP",
    "UIFID",
    "my_rd",
    "volume_info",
    "WallpaperGuide",
    "FOLLOW_NUMBER_YELLOW_POINT_INFO",
    "_bd_ticket_crypt_doamin",
    "record_force_login",
    "stream_player_status_params",
    "passport_mfa_token",
    "d_ticket",
    "PhoneResumeUidCacheV1",
    "strategyABtestKey",
    "passport_csrf_token",
    "passport_csrf_token_default",
    "sdk_source_info",
    "bit_env",
    "gulu_source_res",
    "passport_auth_mix_state",
    "download_guide",
    "passport_assist_user",
    "n_mh",
    "sid_guard",
    "uid_tt",
    "uid_tt_ss",
    "sid_tt",
    "sessionid",
    "sessionid_ss",
    "session_tlb_tag",
    "is_staff_user",
    "has_biz_token",
    "sid_ucp_v1",
    "ssid_ucp_v1",
    "_bd_ticket_crypt_cookie",
    "__security_mc_1_s_sdk_sign_data_key_web_protect",
    "__security_mc_1_s_sdk_cert_key",
    "__security_mc_1_s_sdk_crypt_sdk",
    "__security_server_data_status",
    "login_time",
    "publish_badge_show_info",
    "DiscoverFeedExposedAd",
    "ttwid",
    "enter_pc_once",
    "hevc_supported",
    "home_can_add_dy_2_desktop",
    "stream_recommend_feed_params",
    "SelfTabRedDotControl",
    "FOLLOW_LIVE_POINT_INFO",
    "is_dash_user",
    "bd_ticket_guard_client_data",
    "bd_ticket_guard_client_web_domain",
    "odin_tt",
    "bd_ticket_guard_client_data_v2",
    "IsDouyinActive",
    "xgplayer_user_id",
    "fpk1",
    "fpk2",
    "__ac_nonce",
    "__ac_signature",
    "s_v_web_id",
    "dy_swidth",
    "dy_sheight",
    "gd_random",
    "bd_ticket_guard_web_domain",
)
DOUYIN_REFERENCE_COOKIE_LINE_GROUPS = (
    ("UIFID_TEMP",),
    ("UIFID",),
    ("my_rd", "volume_info", "WallpaperGuide"),
    ("FOLLOW_NUMBER_YELLOW_POINT_INFO",),
    ("_bd_ticket_crypt_doamin", "record_force_login"),
    ("stream_player_status_params",),
    ("passport_mfa_token",),
    ("d_ticket", "PhoneResumeUidCacheV1"),
    ("strategyABtestKey", "passport_csrf_token"),
    ("passport_csrf_token_default", "sdk_source_info"),
    ("bit_env",),
    ("gulu_source_res",),
    ("passport_auth_mix_state", "download_guide"),
    ("passport_assist_user",),
    ("n_mh", "sid_guard"),
    ("uid_tt", "uid_tt_ss"),
    ("sid_tt", "sessionid"),
    ("sessionid_ss", "session_tlb_tag"),
    ("is_staff_user", "has_biz_token", "sid_ucp_v1"),
    ("ssid_ucp_v1",),
    ("_bd_ticket_crypt_cookie", "__security_mc_1_s_sdk_sign_data_key_web_protect"),
    ("__security_mc_1_s_sdk_cert_key", "__security_mc_1_s_sdk_crypt_sdk"),
    ("__security_server_data_status", "login_time", "publish_badge_show_info"),
    ("DiscoverFeedExposedAd", "ttwid"),
    ("enter_pc_once", "hevc_supported", "home_can_add_dy_2_desktop", "stream_recommend_feed_params"),
    ("SelfTabRedDotControl",),
    ("FOLLOW_LIVE_POINT_INFO",),
    ("is_dash_user", "bd_ticket_guard_client_data"),
    ("bd_ticket_guard_client_web_domain", "odin_tt"),
    ("bd_ticket_guard_client_data_v2",),
    ("IsDouyinActive", "xgplayer_user_id", "fpk1"),
    ("fpk2", "__ac_nonce", "__ac_signature"),
    ("s_v_web_id", "dy_swidth"),
    ("dy_sheight", "gd_random"),
    ("bd_ticket_guard_web_domain",),
)
DOUYIN_REFERENCE_COOKIE_NAMES = set(DOUYIN_REFERENCE_COOKIE_ORDER)

COOKIE_LINE_RE = re.compile(r"^\s*cookie\s*:\s*", re.IGNORECASE)
YAML_KEY_RE = re.compile(r"^\s*[A-Za-z0-9_-]+\s*:\s*")
XHS_NOTE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)
processes: list[tuple[str, subprocess.Popen]] = []
log_lines: list[str] = []
log_lock = threading.Lock()
xhs_queue_lock = threading.Lock()


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with log_lock:
        log_lines.append(line)
        del log_lines[:-5000]


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
            "api_url": os.environ.get("XHS_API_URL", "http://xhs-api:5556/xhs/detail"),
            "database": "/state/xhs/xhs_queue.sqlite3",
            "queue_files": ["/queue/xhs/links.txt"],
            "settings_path": "/xhs-volume/settings.json",
            "xhs_api_log_file": "/xhs-volume/xhs-api.log",
            "image_format": os.environ.get("XHS_IMAGE_FORMAT", "AUTO"),
            "request_delay_seconds": int(os.environ.get("XHS_REQUEST_DELAY_SECONDS", "0")),
            "jitter_seconds": int(os.environ.get("XHS_JITTER_SECONDS", "0")),
            "max_items_per_run": int(os.environ.get("XHS_MAX_ITEMS_PER_RUN", "0") or "0"),
            "web": {"host": "127.0.0.1", "port": 18081, "log_lines": 5000},
            "sync_settings": {
                "path": "/xhs-volume/settings.json",
                "defaults": {"work_path": "/xhs"},
            },
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
    ensure_config(
        Path("/config/douyin/config.json"),
        ROOT / "douyin" / "config.example.json",
        {
            "cookie_file": "/config/douyin/douyin_cookie.txt",
            "f2_state_dir": "/state/douyin/f2",
            "f2_config_dir": "/config/douyin/f2",
            "download_dir": "/F2DL",
            "web": {"host": "127.0.0.1", "port": 18084},
        },
    )
    for path in [
        Path("/queue/xhs"),
        Path("/state/xhs"),
        Path("/state/x"),
        Path("/state/pixiv"),
        Path("/state/douyin/f2"),
        Path("/downloads/x/images"),
        Path("/downloads/x/videos"),
        Path("/downloads/x/downloads-metadata"),
        Path("/downloads/pixiv"),
        Path("/F2DL"),
    ]:
        path.mkdir(parents=True, exist_ok=True)


def stream_output(name: str, proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for raw in proc.stdout:
        log(f"{name}: {raw.rstrip()}")


def start_process(name: str, command: list[str], cwd: str, env_patch: dict[str, str] | None = None) -> None:
    env = dict(os.environ)
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
    processes.append((name, proc))
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


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def start_children() -> None:
    ensure_configs()
    wait_for_port("xhs-api", os.environ.get("XHS_API_HOST", "xhs-api"), int(os.environ.get("XHS_API_PORT", "5556")))
    start_process(
        "xhs-worker",
        [sys.executable, "/opt/nas-auto/xhs/xhs_auto_worker.py", "--config", "/config/xhs/config.json"],
        "/opt/nas-auto/xhs",
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
    start_process(
        "douyin-worker",
        [sys.executable, "/opt/nas-auto/douyin/douyin_f2_worker.py", "--config", "/config/douyin/config.json"],
        "/opt/nas-auto/douyin",
    )
def parse_cookie_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in str(text or "").replace("\r", "").split(";"):
        item = part.strip()
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        if name in seen:
            pairs = [pair for pair in pairs if pair[0] != name]
        seen.add(name)
        pairs.append((name, value))
    return pairs


def dedupe_cookie_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, value in pairs:
        if name in seen:
            deduped = [pair for pair in deduped if pair[0] != name]
        seen.add(name)
        deduped.append((name, value))
    return deduped


def is_ascii_cookie_pair(name: str, value: str) -> bool:
    return name.isascii() and value.isascii()


def select_douyin_cookie_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    values: dict[str, str] = {}
    for name, value in dedupe_cookie_pairs(pairs):
        if name not in DOUYIN_REFERENCE_COOKIE_NAMES:
            continue
        if not value or not is_ascii_cookie_pair(name, value):
            continue
        values[name] = value
    return [(name, values[name]) for name in DOUYIN_REFERENCE_COOKIE_ORDER if name in values]


def extract_douyin_cookie_text(text: str) -> str:
    lines = str(text or "").replace("\r", "").splitlines()
    if not lines:
        return ""
    collected: list[str] = []
    collecting = False
    for raw in lines:
        if not raw.strip():
            continue
        if not collecting and COOKIE_LINE_RE.match(raw):
            collecting = True
            tail = COOKIE_LINE_RE.sub("", raw, count=1).strip()
            if tail:
                collected.append(tail)
            continue
        if collecting:
            stripped = raw.strip()
            if YAML_KEY_RE.match(raw) and "=" not in stripped:
                break
            collected.append(stripped)
            continue
        collected.append(raw.strip())
    pairs = select_douyin_cookie_pairs(parse_cookie_pairs(" ".join(collected)))
    return "; ".join(f"{name}={value}" for name, value in pairs)


def render_douyin_cookie_block_lines(cookie_text: str, base_indent: str = "") -> list[str]:
    values = {name: value for name, value in parse_cookie_pairs(cookie_text)}
    grouped_parts: list[list[str]] = []
    for group in DOUYIN_REFERENCE_COOKIE_LINE_GROUPS:
        line_parts = [f"{name}={values[name]}" for name in group if name in values]
        if line_parts:
            grouped_parts.append(line_parts)
    if not grouped_parts:
        return [f"{base_indent}cookie:"]
    lines: list[str] = []
    last_index = len(grouped_parts) - 1
    for index, line_parts in enumerate(grouped_parts):
        suffix = ";" if index != last_index else ""
        prefix = f"{base_indent}cookie: " if index == 0 else f"{base_indent}  "
        lines.append(f"{prefix}{'; '.join(line_parts)}{suffix}")
    return lines


def render_douyin_cookie_block(cookie_text: str, base_indent: str = "") -> str:
    return "\n".join(render_douyin_cookie_block_lines(cookie_text, base_indent)) + "\n"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    return deep_update(merged, override)


def job_key(job: dict[str, Any], index: int) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(job.get("name") or "")).strip("-")
    return name or f"job-{index + 1}"


def render_douyin_job_yaml(douyin: dict[str, Any]) -> str:
    payload = {"douyin": dict(douyin, cookie=DOUYIN_COOKIE_YAML_PLACEHOLDER)}
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100000)
    placeholder_pattern = re.compile(
        rf"^  cookie:\s+['\"]?{re.escape(DOUYIN_COOKIE_YAML_PLACEHOLDER)}['\"]?\s*$"
    )
    output_lines: list[str] = []
    replaced = False
    for line in rendered.splitlines():
        if placeholder_pattern.match(line):
            output_lines.extend(render_douyin_cookie_block_lines(str(douyin.get("cookie") or ""), "  "))
            replaced = True
            continue
        output_lines.append(line)
    if not replaced:
        raise RuntimeError("未找到抖音 Cookie 占位符，无法生成任务 YAML")
    return "\n".join(output_lines) + "\n"


def build_douyin_job_payload(config: dict[str, Any], job: dict[str, Any], cookie_text: str) -> dict[str, Any]:
    defaults = dict(config.get("defaults") or {})
    return {
        "cookie": extract_douyin_cookie_text(cookie_text) if "cookie:" in cookie_text else "; ".join(
            f"{name}={value}" for name, value in parse_cookie_pairs(cookie_text)
        ),
        "cover": bool(defaults.get("cover", False)),
        "desc": bool(defaults.get("desc", False)),
        "folderize": bool(defaults.get("folderize", True)),
        "interval": str(defaults.get("interval") or "all"),
        "languages": defaults.get("languages"),
        "lyric": bool(defaults.get("lyric", True)),
        "max_connections": int(defaults.get("max_connections") or 5),
        "max_counts": int(defaults.get("max_counts") or 0),
        "max_retries": int(defaults.get("max_retries") or 5),
        "max_tasks": int(defaults.get("max_tasks") or 10),
        "mode": str(job.get("mode") or "like"),
        "music": defaults.get("music"),
        "naming": str(defaults.get("naming") or "{create}-{nickname}-{aweme_id}"),
        "page_counts": int(defaults.get("page_counts") or 20),
        "path": str(config.get("download_dir") or "/F2DL"),
        "timeout": int(defaults.get("timeout") or 10),
        "url": str(job.get("url") or ""),
    }


def sync_douyin_job_configs(cookie_text: str) -> None:
    config = deep_merge(DEFAULT_DOUYIN_CONFIG, read_json(DOUYIN_CONFIG_PATH))
    normalized_cookie = extract_douyin_cookie_text(cookie_text) if "cookie:" in cookie_text else "; ".join(
        f"{name}={value}" for name, value in parse_cookie_pairs(cookie_text)
    )
    config_dir = Path(str(config.get("f2_config_dir") or "/config/douyin/f2"))
    config_dir.mkdir(parents=True, exist_ok=True)
    for index, job in enumerate(config.get("jobs") or []):
        payload = build_douyin_job_payload(config, job, normalized_cookie)
        (config_dir / f"{job_key(job, index)}.yaml").write_text(render_douyin_job_yaml(payload), encoding="utf-8")


def query_child_status(svc: dict[str, Any]) -> dict[str, Any]:
    conn = http.client.HTTPConnection("127.0.0.1", int(svc["port"]), timeout=1.5)
    try:
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        if resp.status != 200:
            return {}
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except (OSError, TimeoutError, http.client.HTTPException, json.JSONDecodeError):
        return {}
    finally:
        conn.close()


def summarize_child_status(child: dict[str, Any]) -> dict[str, Any]:
    progress = child.get("progress") if isinstance(child.get("progress"), dict) else {}
    counts = child.get("counts") if isinstance(child.get("counts"), dict) else {}
    current = str(child.get("current_job") or progress.get("current_url") or "").strip()
    if current and len(current) > 90:
        current = current[:87] + "..."
    extra = ""
    if counts:
        retry = int(counts.get("retry", 0) or 0)
        extra = (
            f"待处理 {int(counts.get('pending', 0) or 0)}，"
            f"重试 {retry}，失败 {int(counts.get('failed', 0) or 0)}"
        )
    elif child.get("last_run_message"):
        extra = str(child.get("last_run_message") or "")
    return {
        "running": bool(child.get("running")),
        "next_run_at": str(child.get("next_run_at") or ""),
        "current": current,
        "extra": extra,
    }


def service_status() -> dict[str, Any]:
    services: list[dict[str, Any]] = []
    for key, svc in SERVICES.items():
        ready = is_port_open("127.0.0.1", int(svc["port"]))
        child = query_child_status(svc) if ready else {}
        services.append(
            {
                "key": key,
                "name": svc["name"],
                "path": svc["path"],
                "port": svc["port"],
                "ready": ready,
                **summarize_child_status(child),
            }
        )
    return {
        "processes": [
            {"name": name, "pid": proc.pid, "returncode": proc.poll()} for name, proc in processes
        ],
        "services": services,
        "logs": list(log_lines[-1000:]),
        "version": APP_VERSION,
    }


def dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_xhs_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for match in XHS_NOTE_URL_RE.finditer(str(text or "")):
        urls.append(match.group(0).strip().rstrip("),.;，。；"))
    return dedupe_ordered(urls)


def normalize_xhs_link_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    candidates: list[str] = []
    if isinstance(payload.get("urls"), list):
        candidates.extend(str(item) for item in payload["urls"])
    if payload.get("url"):
        candidates.append(str(payload["url"]))
    if payload.get("text"):
        candidates.extend(extract_xhs_urls_from_text(str(payload["text"])))

    urls: list[str] = []
    invalid: list[str] = []
    for raw in candidates:
        value = str(raw or "").strip()
        if not value:
            continue
        found = extract_xhs_urls_from_text(value)
        if found:
            urls.extend(found)
        else:
            invalid.append(value[:200])
    return dedupe_ordered(urls), invalid


def append_xhs_queue_links(urls: list[str]) -> dict[str, Any]:
    XHS_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with xhs_queue_lock:
        existing: set[str] = set()
        if XHS_QUEUE_FILE.exists():
            try:
                existing.update(extract_xhs_urls_from_text(XHS_QUEUE_FILE.read_text(encoding="utf-8-sig")))
            except OSError:
                existing = set()
        accepted = [url for url in urls if url not in existing]
        if accepted:
            with XHS_QUEUE_FILE.open("a", encoding="utf-8") as handle:
                if XHS_QUEUE_FILE.stat().st_size > 0:
                    handle.write("\n")
                handle.write("\n".join(accepted))
                handle.write("\n")
        return {
            "accepted": accepted,
            "skipped": [url for url in urls if url in existing],
            "queue_file": str(XHS_QUEUE_FILE),
        }


def trigger_xhs_worker_run() -> dict[str, Any]:
    svc = SERVICES["xhs"]
    conn = http.client.HTTPConnection("127.0.0.1", int(svc["port"]), timeout=10)
    try:
        conn.request("POST", "/api/run-now", body=b"{}", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body[:500]}
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        return {"ok": False, "status": 0, "body": str(error)}
    finally:
        conn.close()


def trigger_service_run(service_key: str) -> dict[str, Any]:
    svc = SERVICES[service_key]
    conn = http.client.HTTPConnection("127.0.0.1", int(svc["port"]), timeout=10)
    try:
        conn.request("POST", "/api/run-now", body=b"{}", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body[:500]}
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        return {"ok": False, "status": 0, "body": str(error)}
    finally:
        conn.close()


def post_xhs_worker(path: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    svc = SERVICES["xhs"]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", int(svc["port"]), timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            parsed = {"body": raw[:1000]}
        parsed.setdefault("ok", 200 <= resp.status < 300)
        parsed.setdefault("status", resp.status)
        return parsed
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        return {"ok": False, "status": 0, "error": str(error)}
    finally:
        conn.close()


def page(message: str = "") -> bytes:
    status_data = service_status()
    nav_items = ""
    overview_rows = ""
    ready_count = 0
    for svc in status_data["services"]:
        key = str(svc["key"])
        ready = bool(svc["ready"])
        if ready:
            ready_count += 1
        cls = "ready" if ready else "starting"
        label = "已就绪" if ready else "启动中"
        nav_items += (
            f'<a class="nav-item {cls}" href="{svc["path"]}" data-service="{key}">'
            f'<span>{html.escape(svc["name"])}</span><em data-status="{key}">{label}</em></a>'
        )
        run_label = "运行中" if svc.get("running") else ("空闲" if ready else "未就绪")
        overview_rows += (
            f'<tr data-overview-row="{key}">'
            f'<td>{html.escape(str(svc["name"]))}</td>'
            f'<td><span class="pill {cls}" data-ready-cell>{label}</span></td>'
            f'<td data-running-cell>{run_label}</td>'
            f'<td data-current-cell>{html.escape(str(svc.get("current") or "-"))}</td>'
            f'<td data-next-cell data-next-run-at="{html.escape(str(svc.get("next_run_at") or ""))}">-</td>'
            f'<td data-extra-cell>{html.escape(str(svc.get("extra") or ""))}</td>'
            f'</tr>'
        )
    shell_css = app_css(
        """
body{background:#f3f5f7}
.app-shell{min-height:100vh;display:grid;grid-template-columns:268px minmax(0,1fr)}
.shell-sidebar{height:100vh;position:sticky;top:0;background:#20242c;color:#f8fafc;padding:18px;display:flex;flex-direction:column;gap:18px;border-right:1px solid rgba(255,255,255,.08)}
.brand{display:grid;gap:4px;padding:4px 2px 12px;border-bottom:1px solid rgba(255,255,255,.08)}
.brand strong{font-size:21px;letter-spacing:0}.brand span{color:#aeb7c4;font-size:12px}
.nav-group{display:grid;gap:8px}.nav-title{color:#8f9aa8;font-size:12px;padding:0 10px}
.nav-item{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;background:transparent;color:#eef2f6;text-decoration:none;text-align:left;font:inherit;border:1px solid transparent;border-radius:8px;padding:10px;cursor:pointer}
.nav-item:hover,.nav-item.active{background:#2b3039;border-color:#3a424d}
.nav-item.active{box-shadow:inset 3px 0 0 var(--accent)}
.nav-item em{font-style:normal;color:#aeb7c4;font-size:12px}.nav-item.ready em{color:#90e2bd}.nav-item.starting em{color:#f3c969}
.workspace{min-width:0}.topbar{background:rgba(255,255,255,.94);color:var(--text);border-bottom:1px solid var(--line);min-height:64px;backdrop-filter:blur(8px)}
.topbar .status{margin-left:auto}.shell-main{max-width:none;padding:24px;align-content:start}
.hero-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:end;background:#fff;border:1px solid var(--line);border-radius:8px;padding:22px;box-shadow:var(--shadow)}
.hero-panel h1{font-size:25px}.hero-panel p{margin:8px 0 0}.summary-strip{display:flex;gap:10px;flex-wrap:wrap}
.summary-card{min-width:132px;border:1px solid var(--line);border-radius:8px;background:var(--panel-soft);padding:12px}
.summary-card span{display:block;color:var(--muted);font-size:12px}.summary-card strong{display:block;margin-top:4px;font-size:19px}
.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:16px}
.overview-table{overflow:auto}.overview-table td:nth-child(4),.overview-table td:nth-child(6){max-width:360px;overflow-wrap:anywhere}
.service-pane{display:none;height:calc(100vh - 112px);min-height:640px;padding:0;overflow:hidden}.service-pane.active{display:block}
.service-frame{width:100%;height:100%;border:0;background:#fff}
.dashboard-view.hidden{display:none}
pre{max-height:420px}
@media(max-width:980px){.app-shell{grid-template-columns:1fr}.shell-sidebar{height:auto;position:static}.dashboard-grid{grid-template-columns:1fr}.shell-main{padding:14px}.service-pane{height:72vh;min-height:520px}}
"""
    )
    script = """
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const dashboardView = $("dashboardView");
const servicePane = $("servicePane");
const serviceFrame = $("serviceFrame");

function showDashboard() {
  dashboardView.classList.remove("hidden");
  servicePane.classList.remove("active");
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  $("dashboardNav").classList.add("active");
}

function openService(url, item) {
  dashboardView.classList.add("hidden");
  servicePane.classList.add("active");
  serviceFrame.src = url;
  document.querySelectorAll(".nav-item").forEach((nav) => nav.classList.remove("active"));
  item.classList.add("active");
}

document.querySelectorAll("[data-service]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    openService(item.getAttribute("href"), item);
  });
});
document.querySelectorAll("[data-open-service]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    openService(item.getAttribute("href"), document.querySelector(`.nav-item[data-service="${item.dataset.openService}"]`) || item);
  });
});
$("dashboardNav").addEventListener("click", showDashboard);

function formatCountdown(value) {
  if (!value) return "未排程";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const seconds = Math.max(0, Math.floor((timestamp - Date.now()) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  if (hours > 0) return `${hours}小时${minutes}分`;
  if (minutes > 0) return `${minutes}分${rest}秒`;
  return `${rest}秒`;
}

function refreshCountdowns() {
  document.querySelectorAll("[data-next-cell]").forEach((cell) => {
    cell.textContent = formatCountdown(cell.dataset.nextRunAt || "");
  });
}

async function refreshStatus() {
  try {
    const resp = await fetch("/api/status", {cache:"no-store"});
    const data = await resp.json();
    $("versionText").textContent = data.version || "";
    $("logBox").textContent = (data.logs || []).join("\\n");
    let ready = 0;
    for (const svc of data.services || []) {
      if (svc.ready) ready += 1;
      const label = svc.ready ? "已就绪" : "启动中";
      const nav = document.querySelector(`[data-status="${svc.key}"]`);
      if (nav) nav.textContent = label;
      const navItem = document.querySelector(`.nav-item[data-service="${svc.key}"]`);
      if (navItem) {
        navItem.classList.toggle("ready", !!svc.ready);
        navItem.classList.toggle("starting", !svc.ready);
      }
      const row = document.querySelector(`[data-overview-row="${svc.key}"]`);
      if (row) {
        const readyCell = row.querySelector("[data-ready-cell]");
        if (readyCell) {
          readyCell.textContent = label;
          readyCell.classList.toggle("ready", !!svc.ready);
          readyCell.classList.toggle("starting", !svc.ready);
        }
        const runCell = row.querySelector("[data-running-cell]");
        if (runCell) runCell.textContent = svc.running ? "运行中" : (svc.ready ? "空闲" : "未就绪");
        const currentCell = row.querySelector("[data-current-cell]");
        if (currentCell) currentCell.textContent = svc.current || "-";
        const nextCell = row.querySelector("[data-next-cell]");
        if (nextCell) nextCell.dataset.nextRunAt = svc.next_run_at || "";
        const extraCell = row.querySelector("[data-extra-cell]");
        if (extraCell) extraCell.textContent = svc.extra || "";
      }
    }
    $("readyText").textContent = `${ready}/${(data.services || []).length}`;
    refreshCountdowns();
  } catch (_error) {}
}
refreshStatus();
setInterval(refreshStatus, 3000);
setInterval(refreshCountdowns, 1000);
"""
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NAS Auto Download</title>
<style>
{shell_css}
</style></head><body>
<div class="app-shell">
<aside class="shell-sidebar">
  <div class="brand"><strong>NAS Auto</strong><span id="versionText">{html.escape(APP_VERSION)}</span></div>
  <nav class="nav-group">
    <div class="nav-title">工作区</div>
    <button class="nav-item active" id="dashboardNav" type="button"><span>总览</span><em>当前</em></button>
    {nav_items}
  </nav>
</aside>
<div class="workspace">
  <header class="topbar"><h1>NAS Auto Download</h1><div class="status"><span class="pill">服务 <span id="readyText">{ready_count}/{len(SERVICES)}</span></span></div></header>
  <main class="shell-main">
    <div class="dashboard-view" id="dashboardView">
      {f'<section class="ok">{html.escape(message)}</section>' if message else ''}
      <section class="hero-panel">
        <div><h1>统一下载控制台</h1><p class="muted">侧边栏切换小红书、X、Pixiv、抖音；Cookie 分别在各项目页面手动粘贴保存。</p></div>
        <div class="summary-strip">
          <div class="summary-card"><span>服务就绪</span><strong>{ready_count}/{len(SERVICES)}</strong></div>
          <div class="summary-card"><span>版本</span><strong>{html.escape(APP_VERSION)}</strong></div>
        </div>
      </section>
      <div class="dashboard-grid">
        <section><h2>运行总览</h2><div class="overview-table"><table><thead><tr><th>项目</th><th>服务</th><th>运行</th><th>当前</th><th>下次运行倒计时</th><th>补充</th></tr></thead><tbody id="overviewBody">{overview_rows}</tbody></table></div></section>
        <section><h2>最近日志</h2><pre id="logBox">{html.escape(chr(10).join(log_lines[-500:]))}</pre></section>
      </div>
    </div>
    <section class="service-pane" id="servicePane"><iframe class="service-frame" id="serviceFrame" name="serviceFrame" title="服务页面"></iframe></section>
  </main>
</div>
</div>
<script>{script}</script>
</body></html>"""
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
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        data = page(f"{svc['name']} 服务暂不可用，请稍后刷新。{error}")
        handler.send_response(HTTPStatus.BAD_GATEWAY)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def send_json_payload(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        split = urlsplit(self.path)
        if split.path == "/api/status":
            self.send_json_payload(service_status())
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
        if split.path == "/api/xhs/links":
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > MAX_XHS_API_BODY_BYTES:
                self.send_json_payload({"ok": False, "error": "请求体过大"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError as error:
                self.send_json_payload({"ok": False, "error": f"JSON 解析失败：{error}"}, HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload, dict):
                self.send_json_payload({"ok": False, "error": "请求体必须是 JSON 对象"}, HTTPStatus.BAD_REQUEST)
                return
            urls, invalid = normalize_xhs_link_payload(payload)
            queue_result = append_xhs_queue_links(urls)
            trigger_result = trigger_xhs_worker_run() if urls else {"ok": False, "status": 0, "body": "没有有效链接"}
            accepted = queue_result["accepted"]
            skipped = queue_result["skipped"]
            ok = bool(urls) and not invalid and len(urls) == len(accepted) + len(skipped)
            result = {
                "ok": ok,
                "submitted": len(urls) + len(invalid),
                "valid": len(urls),
                "accepted": len(accepted),
                "skipped": len(skipped),
                "invalid": invalid,
                "queue_file": queue_result["queue_file"],
                "triggered": trigger_result,
                "message": (
                    f"已确认接收 {len(accepted)} 条新链接，{len(skipped)} 条已在队列中。"
                    if ok
                    else "存在无效链接或未识别到有效小红书链接。"
                ),
            }
            log(
                f"浏览器脚本提交小红书链接：valid={len(urls)} accepted={len(accepted)} "
                f"skipped={len(skipped)} invalid={len(invalid)} trigger={trigger_result.get('ok')}"
            )
            self.send_json_payload(result)
            return
        for key, svc in SERVICES.items():
            if split.path.startswith(svc["path"]):
                proxy(self, key, svc["path"])
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def reap_zombies() -> None:
    if hasattr(os, "waitpid"):
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid <= 0:
                    break
            except (ChildProcessError, OSError):
                break


def zombie_reaper_loop() -> None:
    while True:
        reap_zombies()
        time.sleep(5)


def shutdown(_signum: int, _frame: Any) -> None:
    for _name, proc in processes:
        if proc.poll() is None:
            proc.terminate()
    time.sleep(2)
    for _name, proc in processes:
        if proc.poll() is None:
            proc.kill()
    reap_zombies()
    raise SystemExit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGCHLD"):
        try:
            signal.signal(signal.SIGCHLD, lambda _s, _f: reap_zombies())
        except Exception:
            pass
    ensure_configs()
    threading.Thread(target=zombie_reaper_loop, daemon=True).start()
    threading.Thread(target=start_children, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"统一 Web UI listening on 0.0.0.0:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
