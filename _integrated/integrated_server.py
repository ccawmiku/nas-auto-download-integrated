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
from urllib.parse import parse_qs, urlsplit

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
BROWSER_LOCK_PATH = os.environ.get("BROWSER_LOCK_PATH", "/tmp/nas-auto-browser.lock")
APP_VERSION = os.environ.get("APP_VERSION", "v1.4.1-dev")
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
COOKIE_IMPORT_KEYS = ("xhs", "x", "douyin")

SITE_RULES = {
    "xhs": {
        "output": Path("/config/xhs/xhs_cookie.txt"),
        "domains": {"xiaohongshu.com", ".xiaohongshu.com", "www.xiaohongshu.com", ".www.xiaohongshu.com"},
        "names": {"a1", "web_session", "webId", "gid", "webBuild", "unread", "xsecappid", "loadts", "acw_tc"},
    },
    "x": {
        "output": Path("/config/x/x_cookies.txt"),
        "domains": {"x.com", ".x.com", "twitter.com", ".twitter.com"},
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
    "douyin": {
        "output": Path("/config/douyin/douyin_cookie.txt"),
        "domains": {"douyin.com", ".douyin.com", "www.douyin.com", ".www.douyin.com"},
    },
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


processes: list[tuple[str, subprocess.Popen]] = []
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
            "api_url": os.environ.get("XHS_API_URL", "http://xhs-api:5556/xhs/detail"),
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
    start_process(
        "douyin-worker",
        [sys.executable, "/opt/nas-auto/douyin/douyin_f2_worker.py", "--config", "/config/douyin/config.json"],
        "/opt/nas-auto/douyin",
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


def parse_netscape_cookies(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expires, name, value = parts[:7]
        if name:
            rows.append(
                {
                    "domain": domain.strip(),
                    "path": path.strip() or "/",
                    "secure": secure.strip().upper(),
                    "expires": expires.strip() or "0",
                    "name": name.strip(),
                    "value": value.strip(),
                }
            )
    return rows


def select_cookie_values(text: str, key: str) -> dict[str, str]:
    rule = SITE_RULES[key]
    values = parse_cookie_header(text)
    rows = parse_netscape_cookies(text)
    if key == "douyin":
        if rows:
            selected_pairs: list[tuple[str, str]] = []
            domains = set(rule.get("domains") or [])
            for row in rows:
                domain = row["domain"].removeprefix("#HttpOnly_")
                if domain in domains:
                    selected_pairs.append((row["name"], row["value"]))
            return dict(select_douyin_cookie_pairs(selected_pairs))
        return dict(parse_cookie_pairs(extract_douyin_cookie_text(text)))
    if rows and rule.get("domains"):
        selected: dict[str, str] = {}
        domains = set(rule.get("domains") or [])
        names = set(rule.get("names") or [])
        for row in rows:
            domain = row["domain"].removeprefix("#HttpOnly_")
            if domain in domains and row["name"] in names:
                selected[row["name"]] = row["value"]
        return selected
    return {name: values[name] for name in sorted(rule["names"]) if name in values}


def read_existing_cookie_values(key: str) -> dict[str, str]:
    path = SITE_RULES[key]["output"]
    if not path.exists() or not path.is_file():
        return {}
    try:
        return select_cookie_values(path.read_text(encoding="utf-8-sig"), key)
    except OSError:
        return {}


def compare_cookie_values(incoming: dict[str, str], existing: dict[str, str]) -> dict[str, Any]:
    incoming_names = set(incoming)
    existing_names = set(existing)
    changed = sorted(name for name in incoming_names & existing_names if incoming[name] != existing[name])
    same = sorted(name for name in incoming_names & existing_names if incoming[name] == existing[name])
    added = sorted(incoming_names - existing_names)
    removed = sorted(existing_names - incoming_names)
    return {
        "incoming_count": len(incoming),
        "existing_count": len(existing),
        "same_count": len(same),
        "added_count": len(added),
        "changed_count": len(changed),
        "removed_count": len(removed),
        "incoming_names": sorted(incoming),
        "added_names": added,
        "changed_names": changed,
        "removed_names": removed,
    }


def analyze_cookie_import(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in COOKIE_IMPORT_KEYS:
        incoming = select_cookie_values(text, key)
        existing = read_existing_cookie_values(key)
        comparison = compare_cookie_values(incoming, existing)
        comparison.update(
            {
                "key": key,
                "name": SERVICES[key]["name"],
                "output": str(SITE_RULES[key]["output"]),
                "selected": bool(incoming),
            }
        )
        result[key] = comparison
    return result


def normalize_import_targets(targets: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if targets is None:
        return list(COOKIE_IMPORT_KEYS)
    selected = [key for key in COOKIE_IMPORT_KEYS if key in set(targets)]
    return selected


def import_all_cookie(text: str, targets: list[str] | tuple[str, ...] | set[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in normalize_import_targets(targets):
        rule = SITE_RULES[key]
        selected = select_cookie_values(text, key)
        if selected:
            output: Path = rule["output"]
            output.parent.mkdir(parents=True, exist_ok=True)
            if key == "x":
                expires = int(time.time()) + 86400 * 180
                lines = ["# Netscape HTTP Cookie File"]
                for name, value in selected.items():
                    lines.append(f".x.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}")
                output.write_text("\n".join(lines) + "\n", encoding="utf-8")
            elif key == "douyin":
                cookie_text = "; ".join(f"{name}={value}" for name, value in selected.items())
                output.write_text(render_douyin_cookie_block(cookie_text), encoding="utf-8")
                sync_douyin_job_configs(cookie_text)
            else:
                output.write_text("; ".join(f"{name}={value}" for name, value in selected.items()) + "\n", encoding="utf-8")
        result[key] = {"count": len(selected), "output": str(rule["output"]), "names": sorted(selected)}
    return result


def read_import_cookie_form(handler: BaseHTTPRequestHandler, length: int) -> dict[str, Any]:
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        form = parse_qs(body.decode("utf-8", errors="replace"))
        return {
            "text": (form.get("cookie_text") or [""])[0],
            "targets": [key for key in form.get("targets", []) if key in COOKIE_IMPORT_KEYS],
            "action": (form.get("action") or [""])[0],
        }

    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not match:
        return {"text": "", "targets": [], "action": ""}
    boundary = (match.group(1) or match.group(2)).encode("utf-8")
    marker = b"--" + boundary
    values: list[str] = []
    targets: list[str] = []
    action = ""
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
        elif 'name="targets"' in headers:
            target = value.decode("utf-8", errors="replace").strip()
            if target in COOKIE_IMPORT_KEYS:
                targets.append(target)
        elif 'name="action"' in headers:
            action = value.decode("utf-8", errors="replace").strip()
    return {"text": "\n".join(values), "targets": targets, "action": action}


def read_import_cookie_payload(handler: BaseHTTPRequestHandler, length: int) -> str:
    return str(read_import_cookie_form(handler, length).get("text") or "")


def service_status() -> dict[str, Any]:
    return {
        "processes": [
            {"name": name, "pid": proc.pid, "returncode": proc.poll()} for name, proc in processes
        ],
        "services": [
            {
                "key": key,
                "name": svc["name"],
                "path": svc["path"],
                "port": svc["port"],
                "ready": is_port_open("127.0.0.1", int(svc["port"])),
            }
            for key, svc in SERVICES.items()
        ],
        "browser_lock": Path(BROWSER_LOCK_PATH).exists(),
        "logs": list(log_lines[-80:]),
        "version": APP_VERSION,
    }


def page(message: str = "") -> bytes:
    nav_items = ""
    service_cards = ""
    ready_count = 0
    for key, svc in SERVICES.items():
        ready = is_port_open("127.0.0.1", int(svc["port"]))
        if ready:
            ready_count += 1
        cls = "ready" if ready else "starting"
        label = "已就绪" if ready else "启动中"
        nav_items += (
            f'<a class="nav-item {cls}" href="{svc["path"]}" data-service="{key}">'
            f'<span>{html.escape(svc["name"])}</span><em data-status="{key}">{label}</em></a>'
        )
        service_cards += (
            f'<a class="card {cls}" href="{svc["path"]}" data-open-service="{key}" data-service-card="{key}">'
            f'<strong>{html.escape(svc["name"])}</strong><span>{html.escape(svc["path"])}</span><em>{label}</em></a>'
        )
    lock = "占用中，其他浏览器任务会等待" if Path(BROWSER_LOCK_PATH).exists() else "空闲"
    shell_css = app_css(
        """
body{background:#f4f6f8}
.app-shell{min-height:100vh;display:grid;grid-template-columns:260px minmax(0,1fr)}
.shell-sidebar{height:100vh;position:sticky;top:0;background:#171b24;color:#f8fafc;padding:18px;display:flex;flex-direction:column;gap:18px}
.brand{display:grid;gap:3px;padding:4px 2px 10px}
.brand strong{font-size:20px}.brand span{color:#a8b3c7;font-size:12px}
.nav-group{display:grid;gap:8px}.nav-title{color:#8792a6;font-size:12px;padding:0 10px}
.nav-item{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;background:transparent;color:#e5e7eb;text-decoration:none;text-align:left;font:inherit;border:1px solid transparent;border-radius:8px;padding:10px;cursor:pointer}
.nav-item:hover,.nav-item.active{background:#222838;border-color:#323b52}
.nav-item em{font-style:normal;color:#a8b3c7;font-size:12px}.nav-item.ready em{color:#86efac}.nav-item.starting em{color:#fbbf24}
.workspace{min-width:0}.topbar{background:#fff;color:var(--text);border-bottom:1px solid var(--line);min-height:64px}
.topbar .status{margin-left:auto}.shell-main{max-width:none;padding:24px;align-content:start}
.hero-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:end;background:#fff;border:1px solid var(--line);border-radius:8px;padding:20px}
.hero-panel h1{font-size:24px}.hero-panel p{margin:8px 0 0}.summary-strip{display:flex;gap:10px;flex-wrap:wrap}
.summary-card{min-width:128px;border:1px solid var(--line);border-radius:8px;background:var(--panel-soft);padding:10px}
.summary-card span{display:block;color:var(--muted);font-size:12px}.summary-card strong{display:block;margin-top:4px;font-size:18px}
.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:16px}
.service-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.import-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,.55fr);gap:14px}
.target-grid{display:grid;gap:10px}.target-check{display:flex;align-items:center;gap:8px;margin:0;border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--panel-soft);color:var(--text)}
.target-check input{width:auto}.target-check span{display:grid;gap:2px}.target-check small{color:var(--muted)}
.preview-grid{display:grid;gap:10px}.preview-card{border:1px solid var(--line);border-radius:8px;padding:12px;background:var(--panel-soft)}
.preview-card header{all:unset;display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
.preview-card h3{margin:0;font-size:15px}.preview-card dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0}
.preview-card dt{color:var(--muted);font-size:12px}.preview-card dd{margin:2px 0 0;font-weight:700}.preview-names{margin-top:8px;color:var(--muted);font-size:12px;line-height:1.55}
.service-pane{display:none;height:calc(100vh - 112px);min-height:640px;padding:0;overflow:hidden}.service-pane.active{display:block}
.service-frame{width:100%;height:100%;border:0;background:#fff}
.dashboard-view.hidden{display:none}
pre{max-height:420px}
@media(max-width:980px){.app-shell{grid-template-columns:1fr}.shell-sidebar{height:auto;position:static}.dashboard-grid,.import-layout{grid-template-columns:1fr}.shell-main{padding:14px}.service-pane{height:72vh;min-height:520px}}
"""
    )
    script = """
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const form = $("cookieImportForm");
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

function compactNames(names) {
  if (!names || !names.length) return "无";
  const visible = names.slice(0, 12).map(esc).join(", ");
  return names.length > 12 ? `${visible} ...` : visible;
}

function renderPreview(data) {
  const box = $("cookiePreview");
  const items = Object.values(data.targets || {});
  if (!items.length) {
    box.innerHTML = '<p class="muted">还没有可预览的数据。</p>';
    return;
  }
  box.innerHTML = items.map((item) => `
    <div class="preview-card">
      <header><h3>${esc(item.name)}</h3><span class="pill ${item.incoming_count ? "ok" : "warn"}">${item.incoming_count ? "可导入" : "未识别"}</span></header>
      <dl>
        <div><dt>导入文件</dt><dd>${item.incoming_count}</dd></div>
        <div><dt>现有文件</dt><dd>${item.existing_count}</dd></div>
        <div><dt>新增</dt><dd>${item.added_count}</dd></div>
        <div><dt>变化</dt><dd>${item.changed_count}</dd></div>
      </dl>
      <div class="preview-names">导入字段：${compactNames(item.incoming_names)}</div>
      <div class="preview-names">变化字段：${compactNames(item.changed_names)}</div>
      <div class="preview-names">现有但本次没有：${compactNames(item.removed_names)}</div>
    </div>
  `).join("");
}

$("previewCookie").addEventListener("click", async () => {
  const fd = new FormData(form);
  const button = $("previewCookie");
  button.disabled = true;
  button.textContent = "预览中...";
  try {
    const resp = await fetch("/api/cookie-preview", {method:"POST", body:fd});
    renderPreview(await resp.json());
  } catch (error) {
    $("cookiePreview").innerHTML = `<p class="muted">预览失败：${esc(error)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "预览差异";
  }
});

async function refreshStatus() {
  try {
    const resp = await fetch("/api/status", {cache:"no-store"});
    const data = await resp.json();
    $("versionText").textContent = data.version || "";
    $("lockText").textContent = data.browser_lock ? "占用中" : "空闲";
    $("logBox").textContent = (data.logs || []).join("\\n");
    let ready = 0;
    for (const svc of data.services || []) {
      if (svc.ready) ready += 1;
      const label = svc.ready ? "已就绪" : "启动中";
      const nav = document.querySelector(`[data-status="${svc.key}"]`);
      const card = document.querySelector(`[data-service-card="${svc.key}"]`);
      if (nav) nav.textContent = label;
      const navItem = document.querySelector(`.nav-item[data-service="${svc.key}"]`);
      if (navItem) {
        navItem.classList.toggle("ready", !!svc.ready);
        navItem.classList.toggle("starting", !svc.ready);
      }
      if (card) {
        card.classList.toggle("ready", !!svc.ready);
        card.classList.toggle("starting", !svc.ready);
        const em = card.querySelector("em");
        if (em) em.textContent = label;
      }
    }
    $("readyText").textContent = `${ready}/${(data.services || []).length}`;
  } catch (_error) {}
}
refreshStatus();
setInterval(refreshStatus, 3000);
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
    <button class="nav-item active" id="dashboardNav" type="button"><span>总览与导入</span><em>当前</em></button>
    {nav_items}
  </nav>
</aside>
<div class="workspace">
  <header class="topbar"><h1>NAS Auto Download</h1><div class="status"><span class="pill">服务 <span id="readyText">{ready_count}/{len(SERVICES)}</span></span><span class="pill">浏览器锁 <span id="lockText">{lock}</span></span></div></header>
  <main class="shell-main">
    <div class="dashboard-view" id="dashboardView">
      {f'<section class="ok">{html.escape(message)}</section>' if message else ''}
      <section class="hero-panel">
        <div><h1>统一下载控制台</h1><p class="muted">侧边栏切换小红书、X、Pixiv、抖音；Cookie 导入先预览差异，再按目标写入。</p></div>
        <div class="summary-strip">
          <div class="summary-card"><span>服务就绪</span><strong>{ready_count}/{len(SERVICES)}</strong></div>
          <div class="summary-card"><span>浏览器锁</span><strong>{lock}</strong></div>
          <div class="summary-card"><span>版本</span><strong>{html.escape(APP_VERSION)}</strong></div>
        </div>
      </section>
      <div class="dashboard-grid">
        <section><h2>服务入口</h2><div class="service-grid">{service_cards}</div></section>
        <section><h2>最近日志</h2><pre id="logBox">{html.escape(chr(10).join(log_lines[-80:]))}</pre></section>
      </div>
      <section><h2>Cookie 导入</h2>
        <p class="muted">先上传浏览器导出的 cookies.txt，或粘贴单行 Cookie Header / 抖音 app.yaml 的 <code>cookie:</code> 段。预览只比较字段名和数量，不显示 Cookie 明文；点击导入后只写入勾选目标。</p>
        <form id="cookieImportForm" method="post" action="/import-cookies" enctype="multipart/form-data">
          <div class="import-layout">
            <div>
              <label>上传 cookies.txt（浏览器导出的 Netscape 格式）</label>
              <input type="file" name="cookie_file" accept=".txt,.cookies,text/plain">
              <label>粘贴 Cookie 内容（Cookie Header 或抖音 app.yaml 的 cookie 段）</label>
              <textarea name="cookie_text" placeholder="cookie: sessionid=...; ttwid=..."></textarea>
            </div>
            <div class="target-grid">
              <label class="target-check"><input type="checkbox" name="targets" value="xhs" checked><span>小红书<small>/config/xhs/xhs_cookie.txt</small></span></label>
              <label class="target-check"><input type="checkbox" name="targets" value="x" checked><span>X<small>/config/x/x_cookies.txt</small></span></label>
              <label class="target-check"><input type="checkbox" name="targets" value="douyin" checked><span>抖音<small>/config/douyin/douyin_cookie.txt，并同步 f2 YAML</small></span></label>
            </div>
          </div>
          <div class="actions"><button class="secondary" id="previewCookie" type="button">预览差异</button><button name="action" value="import" type="submit">导入勾选项目</button></div>
        </form>
        <div class="preview-grid" id="cookiePreview"><p class="muted">预览后会显示每个目标的导入字段数、现有字段数、新增字段和变化字段。</p></div>
      </section>
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
        if split.path == "/api/cookie-preview":
            length = int(self.headers.get("Content-Length", "0") or 0)
            form = read_import_cookie_form(self, length)
            payload = {
                "targets": analyze_cookie_import(str(form.get("text") or "")),
                "selected": normalize_import_targets(form.get("targets")),
            }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if split.path == "/import-cookies":
            length = int(self.headers.get("Content-Length", "0") or 0)
            form = read_import_cookie_form(self, length)
            targets = normalize_import_targets(form.get("targets"))
            if not targets:
                message = "未选择要导入的项目，请至少勾选小红书、X 或抖音中的一个。"
            else:
                result = import_all_cookie(str(form.get("text") or ""), targets)
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
    for _name, proc in processes:
        if proc.poll() is None:
            proc.terminate()
    time.sleep(2)
    for _name, proc in processes:
        if proc.poll() is None:
            proc.kill()
    raise SystemExit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    ensure_configs()
    threading.Thread(target=start_children, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"统一 Web UI listening on 0.0.0.0:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
