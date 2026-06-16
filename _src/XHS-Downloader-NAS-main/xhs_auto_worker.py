#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import signal
import sqlite3
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import requests

COMMON_PATH = Path(__file__).resolve().parents[2] / "_common"
if COMMON_PATH.exists():
    sys.path.insert(0, str(COMMON_PATH))

try:
    from nas_auto_common.ui import app_css
except ModuleNotFoundError:
    def app_css(extra: str = "") -> str:
        return extra


APP_NAME = "XHS Queue Downloader"
DEFAULT_CONFIG_PATH = Path("/config/config.json")
NOTE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)
NOTE_ID_RE = re.compile(r"/(?:discovery/)?item/([0-9a-fA-F]{16,32})")
XHS_API_FAILURE_MARKERS = (
    "下载失败",
    "网络异常",
    "HTTPStatusError",
    "ReadTimeout",
    "RemoteProtocolError",
    "peer closed",
    "Traceback",
    "Exception",
)
XHS_TRANSIENT_FAILURE_MARKERS = (
    "网络异常",
    "ReadTimeout",
    "RemoteProtocolError",
    "peer closed",
    "ConnectionError",
    "ConnectTimeout",
    "Timeout",
    "temporarily unavailable",
)

DEFAULT_DOWNLOADER_SETTINGS: dict[str, Any] = {
    "mapping_data": {},
    "work_path": "/xhs",
    "folder_name": "Download",
    "name_format": "发布时间 作者昵称 作品标题",
    "date_format": "%Y-%m-%d %H.%M.%S",
    "folder_mode": True,
    "download_record": True,
    "record_data": True,
    "image_download": True,
    "video_download": True,
    "live_download": True,
    "image_format": "AUTO",
    "proxy": None,
    "timeout": 10,
    "chunk": 2097152,
    "max_retry": 5,
    "language": "zh_CN",
    "author_archive": False,
    "write_mtime": False,
    "video_preference": "resolution",
    "script_server": False,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "api_url": "http://xhs-api:5556/xhs/detail",
    "database": "/state/xhs_queue.sqlite3",
    "queue_files": ["/queue/links.txt"],
    "settings_path": "/xhs-volume/settings.json",
    "xhs_api_log_file": "/xhs-volume/xhs-api.log",
    "image_format": "AUTO",
    "request_delay_seconds": 0,
    "jitter_seconds": 0,
    "retry_failed": True,
    "max_download_attempts": 0,
    "max_items_per_run": 0,
    "api_skip_existing": True,
    "api_timeout_seconds": 120,
    "network_retry_delay_seconds": 300,
    "sync_settings": {
        "path": "/xhs-volume/settings.json",
        "defaults": DEFAULT_DOWNLOADER_SETTINGS,
    },
    "web": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8080,
        "log_lines": 5000,
    },
}

RUN_NOW_EVENT = threading.Event()
STOP_EVENT = threading.Event()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class RingLog:
    def __init__(self, max_lines: int = 5000):
        self.max_lines = max_lines
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        line = f"[{now_iso()}] {message}"
        print(line, flush=True)
        with self._lock:
            self._lines.append(line)
            self._lines = self._lines[-self.max_lines :]

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


def extract_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in NOTE_URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(".,;，。；、)")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def note_id_from_url(url: str) -> str:
    match = NOTE_ID_RE.search(str(url or ""))
    if match:
        return match.group(1).lower()
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(url or "").strip()).strip("_")[:120]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return deep_merge(DEFAULT_CONFIG, read_json(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(path: Path, config: dict[str, Any]) -> None:
    write_json(path, config)


def settings_path_from_config(config: dict[str, Any]) -> Path:
    sync = config.get("sync_settings") or {}
    return Path(str(config.get("settings_path") or sync.get("path") or "/xhs-volume/settings.json"))


def sync_downloader_settings(config: dict[str, Any]) -> dict[str, Any]:
    path = settings_path_from_config(config)
    existing = read_json(path)
    sync = config.get("sync_settings") or {}
    defaults = deep_merge(DEFAULT_DOWNLOADER_SETTINGS, sync.get("defaults") or {})
    merged = deep_merge(defaults, existing)
    image_format = str(config.get("image_format") or "").strip().upper()
    if image_format:
        merged["image_format"] = image_format
    write_json(path, merged)
    return merged


def save_web_settings(config_path: Path, config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deep_merge(config, patch)
    save_config(config_path, merged)
    return merged


def save_settings_cookie(config: dict[str, Any], cookie_text: str) -> dict[str, Any]:
    settings = sync_downloader_settings(config)
    settings["cookie"] = str(cookie_text or "").strip()
    path = settings_path_from_config(config)
    write_json(path, settings)
    return settings


def cookie_summary_from_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = read_json(settings_path_from_config(config))
    cookie = str(settings.get("cookie") or "").strip()
    names = []
    for part in cookie.split(";"):
        if "=" in part:
            name = part.split("=", 1)[0].strip()
            if name:
                names.append(name)
    required = {"a1", "web_session"}
    return {
        "present": bool(cookie),
        "count": len(names),
        "has_a1": "a1" in names,
        "has_web_session": "web_session" in names,
        "missing_required": sorted(required - set(names)),
    }


def tail_file(path: Path, max_lines: int = 1000) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip("\n") for line in lines[-max_lines:]]
    except OSError as error:
        return [f"读取日志失败：{error}"]


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_file_since(path: Path, offset: int, max_bytes: int = 120000) -> str:
    try:
        size = path.stat().st_size
        if size <= offset:
            return ""
        start = max(offset, size - max_bytes)
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(size - start)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def normalize_compare_text(value: str) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-:：.。·,，!！?？'\"“”‘’()[\]【】{}]+", "", text)


def strip_xhs_date_prefix(folder_name: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}[_ ]\d{2}[.:]\d{2}[.:]\d{2}_", "", str(folder_name or ""), count=1)


def local_folder_record(path: Path) -> dict[str, str]:
    body = strip_xhs_date_prefix(path.name)
    parts = body.split("_", 1)
    author = parts[0].strip() if parts else ""
    title = parts[1].strip() if len(parts) > 1 else body.strip()
    return {
        "folder": path.name,
        "author": author,
        "title": title,
        "key": f"{normalize_compare_text(author)}|{normalize_compare_text(title)}",
        "title_key": normalize_compare_text(title),
    }


def submitted_item_record(item: dict[str, Any]) -> dict[str, str]:
    author = str(item.get("author") or item.get("nickname") or "").strip()
    title = str(item.get("title") or item.get("name") or "").strip()
    return {
        "id": str(item.get("id") or item.get("note_id") or "").strip(),
        "url": str(item.get("url") or "").strip(),
        "author": author,
        "title": title,
        "key": f"{normalize_compare_text(author)}|{normalize_compare_text(title)}",
        "title_key": normalize_compare_text(title),
    }


def compare_xhs_library(items: list[dict[str, Any]], work_path: Path) -> dict[str, Any]:
    submitted = [submitted_item_record(item) for item in items if isinstance(item, dict)]
    submitted = [item for item in submitted if item["title_key"]]
    local: list[dict[str, str]] = []
    if work_path.exists() and work_path.is_dir():
        for path in work_path.iterdir():
            if path.is_dir():
                local.append(local_folder_record(path))
    local_by_key = {item["key"]: item for item in local if item["key"]}
    local_by_title: dict[str, list[dict[str, str]]] = {}
    for item in local:
        if item["title_key"]:
            local_by_title.setdefault(item["title_key"], []).append(item)

    matched_local_folders: set[str] = set()
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in submitted:
        local_item = local_by_key.get(item["key"])
        if local_item is None:
            candidates = local_by_title.get(item["title_key"], [])
            local_item = candidates[0] if candidates else None
        if local_item is None:
            missing.append(item)
            continue
        matched_local_folders.add(local_item["folder"])
        matched.append({**item, "folder": local_item["folder"]})
    extra = [item for item in local if item["folder"] not in matched_local_folders]
    return {
        "submitted_count": len(submitted),
        "local_count": len(local),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "matched": matched[:500],
        "missing": missing[:500],
        "extra": extra[:500],
        "work_path": str(work_path),
        "checked_at": now_iso(),
    }


def resolve_xhs_library_path(settings: dict[str, Any], config: dict[str, Any]) -> Path:
    base = Path(str(settings.get("work_path") or config.get("work_path") or DEFAULT_DOWNLOADER_SETTINGS["work_path"]))
    folder_name = str(settings.get("folder_name") or DEFAULT_DOWNLOADER_SETTINGS["folder_name"] or "").strip()
    if folder_name:
        nested = base / folder_name
        if nested.exists() and nested.is_dir():
            return nested
    return base


def xhs_api_segment_has_failure(text: str) -> bool:
    return any(marker in str(text or "") for marker in XHS_API_FAILURE_MARKERS)


def is_transient_xhs_failure(text: str) -> bool:
    return any(marker.lower() in str(text or "").lower() for marker in XHS_TRANSIENT_FAILURE_MARKERS)


@dataclass
class QueueResult:
    accepted: list[str]
    skipped: list[str]
    invalid: list[str]


class Store:
    def __init__(self, db_path: Path, log: RingLog):
        self.db_path = db_path
        self.log = log
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(
                """
                create table if not exists notes (
                    note_id text primary key,
                    url text not null,
                    source text,
                    status text not null default 'pending',
                    attempts integer not null default 0,
                    last_error text,
                    retry_after real,
                    first_seen_at text not null,
                    updated_at text not null,
                    downloaded_at text
                );
                create index if not exists idx_notes_status on notes(status);
                create table if not exists runs (
                    id integer primary key autoincrement,
                    started_at text not null,
                    finished_at text,
                    status text not null,
                    queued integer not null default 0,
                    downloaded integer not null default 0,
                    skipped integer not null default 0,
                    failed integer not null default 0,
                    message text
                );
                """
            )
            try:
                conn.execute("alter table notes add column retry_after real")
            except sqlite3.OperationalError:
                pass
            conn.execute("create index if not exists idx_notes_retry_after on notes(retry_after)")
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, urls: list[str], source: str = "queue") -> QueueResult:
        accepted: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []
        with self._lock, self.connect() as conn:
            for url in urls:
                note_id = note_id_from_url(url)
                if not note_id:
                    invalid.append(url)
                    continue
                row = conn.execute("select status from notes where note_id=?", (note_id,)).fetchone()
                if row:
                    skipped.append(url)
                    continue
                conn.execute(
                    """
                    insert into notes(note_id, url, source, status, first_seen_at, updated_at)
                    values(?, ?, ?, 'pending', ?, ?)
                    """,
                    (note_id, url, source, now_iso(), now_iso()),
                )
                accepted.append(url)
        return QueueResult(accepted=accepted, skipped=skipped, invalid=invalid)

    def import_queue_files(self, paths: list[str]) -> QueueResult:
        accepted: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []
        for raw_path in paths:
            path = Path(str(raw_path))
            if not path.exists():
                continue
            urls = extract_urls_from_text(path.read_text(encoding="utf-8-sig", errors="replace"))
            result = self.enqueue(urls, source=str(path))
            accepted.extend(result.accepted)
            skipped.extend(result.skipped)
            invalid.extend(result.invalid)
        return QueueResult(accepted=accepted, skipped=skipped, invalid=invalid)

    def pending(self, retry_failed: bool, max_attempts: int, limit: int) -> list[sqlite3.Row]:
        now_ts = time.time()
        where = ["status='pending'", "(status='retry' and coalesce(retry_after, 0) <= ?)"]
        params: list[Any] = [now_ts]
        if retry_failed:
            if max_attempts > 0:
                where.append("(status='failed' and attempts < ?)")
                params.append(max_attempts)
            else:
                where.append("status='failed'")
        sql = f"select * from notes where {' or '.join(where)} order by first_seen_at asc"
        if limit > 0:
            sql += " limit ?"
            params.append(limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def begin_run(self) -> int:
        with self._lock, self.connect() as conn:
            cur = conn.execute("insert into runs(started_at, status) values(?, 'running')", (now_iso(),))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict[str, int], message: str = "") -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                update runs
                set finished_at=?, status=?, queued=?, downloaded=?, skipped=?, failed=?, message=?
                where id=?
                """,
                (
                    now_iso(),
                    status,
                    stats.get("queued", 0),
                    stats.get("downloaded", 0),
                    stats.get("skipped", 0),
                    stats.get("failed", 0),
                    message[-2000:],
                    run_id,
                ),
            )

    def mark_downloaded(self, note_id: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                update notes
                set status='done', attempts=attempts+1, last_error='', retry_after=null, downloaded_at=?, updated_at=?
                where note_id=?
                """,
                (now_iso(), now_iso(), note_id),
            )

    def mark_failed(self, note_id: str, error: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                update notes
                set status='failed', attempts=attempts+1, last_error=?, retry_after=null, updated_at=?
                where note_id=?
                """,
                (error[-2000:], now_iso(), note_id),
            )

    def mark_retry(self, note_id: str, error: str, retry_after: float) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                update notes
                set status='retry', attempts=attempts+1, last_error=?, retry_after=?, updated_at=?
                where note_id=?
                """,
                (error[-2000:], retry_after, now_iso(), note_id),
            )

    def mark_pending(self, note_ids: list[str]) -> int:
        cleaned = [str(note_id or "").strip() for note_id in note_ids if str(note_id or "").strip()]
        if not cleaned:
            return 0
        with self._lock, self.connect() as conn:
            placeholders = ",".join("?" for _ in cleaned)
            cur = conn.execute(
                f"""
                update notes
                set status='pending', retry_after=null, last_error='', updated_at=?
                where note_id in ({placeholders}) and status in ('failed', 'retry')
                """,
                [now_iso(), *cleaned],
            )
            return int(cur.rowcount or 0)

    def mark_pending_for_statuses(self, statuses: list[str]) -> int:
        allowed = [status for status in statuses if status in {"failed", "retry"}]
        if not allowed:
            return 0
        with self._lock, self.connect() as conn:
            placeholders = ",".join("?" for _ in allowed)
            cur = conn.execute(
                f"""
                update notes
                set status='pending', retry_after=null, last_error='', updated_at=?
                where status in ({placeholders})
                """,
                [now_iso(), *allowed],
            )
            return int(cur.rowcount or 0)

    def recent_notes(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from notes order by updated_at desc limit ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def error_notes(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "select * from notes where status in ('failed', 'retry') order by updated_at desc limit ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from runs order by id desc limit ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("select status, count(*) as n from notes group by status").fetchall()
            result = {"pending": 0, "retry": 0, "done": 0, "failed": 0}
            for row in rows:
                result[str(row["status"])] = int(row["n"])
            return result

    def clear_queue(self) -> int:
        with self._lock, self.connect() as conn:
            row = conn.execute("select count(*) from notes where status in ('pending', 'retry', 'failed')").fetchone()
            count = int(row[0]) if row else 0
            conn.execute("delete from notes where status in ('pending', 'retry', 'failed')")
            return count

    def has_due_retry(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "select 1 from notes where status='retry' and coalesce(retry_after, 0) <= ? limit 1",
                (time.time(),),
            ).fetchone()
            return row is not None


def append_queue_links(queue_file: Path, urls: list[str]) -> QueueResult:
    valid = []
    invalid = []
    for url in urls:
        if note_id_from_url(url):
            valid.append(url)
        else:
            invalid.append(url)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    existing = set(extract_urls_from_text(queue_file.read_text(encoding="utf-8-sig", errors="replace")) if queue_file.exists() else "")
    accepted = [url for url in valid if url not in existing]
    skipped = [url for url in valid if url in existing]
    if accepted:
        with queue_file.open("a", encoding="utf-8") as handle:
            for url in accepted:
                handle.write(url + "\n")
    return QueueResult(accepted=accepted, skipped=skipped, invalid=invalid)


def post_download(api_url: str, url: str, *, skip: bool, timeout: int) -> tuple[bool, str]:
    body = {"url": url, "download": True, "skip": skip}
    response = requests.post(api_url, json=body, timeout=timeout)
    text = response.text[:2000]
    if 200 <= response.status_code < 300:
        return True, text or f"HTTP {response.status_code}"
    return False, f"HTTP {response.status_code}: {text}"


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.log = RingLog(int(self.config.get("web", {}).get("log_lines", 5000)))
        self.store = Store(Path(str(self.config.get("database"))), self.log)
        self.running = False
        self.run_lock = threading.Lock()
        self.last_run_message = ""
        self.last_library_compare: dict[str, Any] = {}
        self.progress: dict[str, Any] = {"phase": "idle", "current_url": ""}
        self.progress_lock = threading.Lock()
        sync_downloader_settings(self.config)

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)
        self.log.max_lines = int(self.config.get("web", {}).get("log_lines", 5000))
        self.store = Store(Path(str(self.config.get("database"))), self.log)
        sync_downloader_settings(self.config)

    def set_progress(self, patch: dict[str, Any]) -> None:
        with self.progress_lock:
            self.progress.update(patch)

    def get_progress(self) -> dict[str, Any]:
        with self.progress_lock:
            return dict(self.progress)

    def run_once(self) -> dict[str, int]:
        if not self.run_lock.acquire(blocking=False):
            self.log.write("已有小红书下载任务正在运行，忽略本次触发。")
            return {"queued": 0, "downloaded": 0, "skipped": 0, "failed": 0, "retry": 0}
        self.running = True
        run_id = self.store.begin_run()
        stats = {"queued": 0, "downloaded": 0, "skipped": 0, "failed": 0, "retry": 0}
        message = ""
        try:
            self.reload_config()
            imported = self.store.import_queue_files([str(path) for path in self.config.get("queue_files", [])])
            self.log.write(
                f"队列文件导入：新增 {len(imported.accepted)}，已存在 {len(imported.skipped)}，无效 {len(imported.invalid)}。"
            )
            pending = self.store.pending(
                bool(self.config.get("retry_failed", True)),
                int(self.config.get("max_download_attempts", 0) or 0),
                int(self.config.get("max_items_per_run", 0) or 0),
            )
            stats["queued"] = len(pending)
            self.set_progress({"phase": "downloading", "total": len(pending), "done": 0, "current_url": ""})
            if not pending:
                message = "没有待下载的小红书链接。"
                self.log.write(message)
                self.store.finish_run(run_id, "done", stats, message)
                return stats
            delay = max(0.0, float(self.config.get("request_delay_seconds", 0) or 0))
            jitter = max(0.0, float(self.config.get("jitter_seconds", 0) or 0))
            api_url = str(self.config.get("api_url") or DEFAULT_CONFIG["api_url"])
            timeout = int(self.config.get("api_timeout_seconds", 120) or 120)
            retry_delay = max(60, int(self.config.get("network_retry_delay_seconds", 300) or 300))
            skip = bool(self.config.get("api_skip_existing", True))
            xhs_api_log_path = Path(str(self.config.get("xhs_api_log_file") or "/xhs-volume/xhs-api.log"))
            for index, row in enumerate(pending, start=1):
                url = str(row["url"])
                note_id = str(row["note_id"])
                self.set_progress({"current_url": url, "done": index - 1})
                self.log.write(f"提交小红书下载 [{index}/{len(pending)}] {note_id}: {url}")
                api_log_offset = file_size(xhs_api_log_path)
                try:
                    ok, detail = post_download(api_url, url, skip=skip, timeout=timeout)
                except Exception as error:
                    ok, detail = False, str(error)
                api_log_segment = read_file_since(xhs_api_log_path, api_log_offset)
                if ok and xhs_api_segment_has_failure(api_log_segment):
                    ok = False
                    detail = (api_log_segment.strip() or detail)[-2000:]
                if ok:
                    stats["downloaded"] += 1
                    self.store.mark_downloaded(note_id)
                    self.log.write(f"下载提交成功：{note_id}")
                elif is_transient_xhs_failure(detail):
                    stats["retry"] += 1
                    retry_after = time.time() + retry_delay
                    self.store.mark_retry(note_id, detail, retry_after)
                    self.log.write(
                        f"下载遇到网络异常，已安排 {retry_delay // 60} 分钟后重试：{note_id} {detail}"
                    )
                else:
                    stats["failed"] += 1
                    self.store.mark_failed(note_id, detail)
                    self.log.write(f"下载提交失败：{note_id} {detail}")
                self.set_progress({"done": index})
                sleep_for = delay + random.random() * jitter
                if sleep_for > 0 and index < len(pending):
                    self.log.write(f"休眠 {sleep_for:.0f} 秒后继续下一条。")
                    STOP_EVENT.wait(sleep_for)
                    if STOP_EVENT.is_set():
                        break
            message = f"完成：成功 {stats['downloaded']}，待重试 {stats['retry']}，失败 {stats['failed']}。"
            self.store.finish_run(run_id, "done", stats, message)
            self.log.write(message)
            return stats
        except Exception as error:
            message = str(error)
            self.store.finish_run(run_id, "failed", stats, message)
            self.log.write(f"运行失败：{message}")
            self.log.write(traceback.format_exc())
            raise
        finally:
            self.last_run_message = message
            self.set_progress({"phase": "idle", "current_url": ""})
            self.running = False
            self.run_lock.release()

    def start_run_thread(self) -> None:
        threading.Thread(target=self.run_once, daemon=True).start()

    def submit_links(self, urls: list[str]) -> QueueResult:
        result = self.store.enqueue(urls, source="web")
        queue_files = self.config.get("queue_files") or ["/queue/links.txt"]
        append_queue_links(Path(str(queue_files[0])), result.accepted)
        return result

    def clear_queue(self) -> int:
        removed = self.store.clear_queue()
        for raw_path in self.config.get("queue_files", []):
            path = Path(str(raw_path))
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            except OSError as error:
                self.log.write(f"清空队列文件失败：{path} {error}")
        self.last_run_message = f"已清空队列 {removed} 条"
        self.log.write(self.last_run_message)
        return removed

    def retry_note(self, note_id: str) -> bool:
        changed = self.store.mark_pending([note_id])
        if changed:
            self.last_run_message = f"已重新加入重试：{note_id}"
            self.log.write(self.last_run_message)
        return changed > 0

    def retry_errors(self) -> int:
        changed = self.store.mark_pending_for_statuses(["failed", "retry"])
        self.last_run_message = f"已将 {changed} 条错误记录重新加入队列"
        self.log.write(self.last_run_message)
        return changed

    def compare_library(self, items: list[dict[str, Any]], source: str = "") -> dict[str, Any]:
        settings = sync_downloader_settings(self.config)
        work_path = resolve_xhs_library_path(settings, self.config)
        result = compare_xhs_library(items, work_path)
        result["source"] = source
        self.last_library_compare = result
        self.log.write(
            "小红书本地目录对比："
            f"网页 {result['submitted_count']}，本地 {result['local_count']}，"
            f"缺少 {result['missing_count']}，本地多余 {result['extra_count']}"
        )
        return result

    def status(self) -> dict[str, Any]:
        log_limit = int(self.config.get("web", {}).get("log_lines", 5000))
        api_log_path = Path(str(self.config.get("xhs_api_log_file") or "/xhs-volume/xhs-api.log"))
        return {
            "running": self.running,
            "config": self.config,
            "counts": self.store.counts(),
            "runs": self.store.recent_runs(),
            "notes": self.store.recent_notes(),
            "error_notes": self.store.error_notes(),
            "logs": self.log.lines()[-log_limit:],
            "xhs_api_logs": tail_file(api_log_path, min(log_limit, 3000)),
            "settings_cookie": cookie_summary_from_settings(self.config),
            "last_run_message": self.last_run_message,
            "library_compare": self.last_library_compare,
            "progress": self.get_progress(),
        }

    def has_due_retry(self) -> bool:
        return self.store.has_due_retry()


def html_page(app: App) -> str:
    delay_value = html.escape(str(app.config.get("request_delay_seconds", 0)))
    jitter_value = html.escape(str(app.config.get("jitter_seconds", 0)))
    max_items_value = html.escape(str(app.config.get("max_items_per_run", 0)))
    image_format_value = str(app.config.get("image_format") or "AUTO").upper()
    image_options = "".join(
        f'<option value="{value}"{" selected" if value == image_format_value else ""}>{value}</option>'
        for value in ("AUTO", "JPEG", "WEBP", "PNG", "HEIC")
    )
    style = app_css(
        """
.split{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.log-grid{display:grid;grid-template-columns:1fr;gap:16px}
.queue-form textarea{min-height:180px}
.wide-table{overflow:auto}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:999px;margin-right:6px;background:var(--muted)}
.status-pending .status-dot{background:var(--warn)}
.status-retry .status-dot{background:var(--warn)}
.status-done .status-dot{background:var(--ok)}
.status-failed .status-dot{background:var(--danger)}
button.danger{background:var(--danger)}
button.danger:hover{background:#8f1d14;box-shadow:0 6px 16px rgba(180,35,24,.18)}
.compare-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}.compare-list{max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel-soft);padding:10px}
.compare-list h3{font-size:14px;margin:0 0 8px}.compare-list ul{margin:0;padding-left:18px}.compare-list li{margin:4px 0;overflow-wrap:anywhere}
pre{max-height:680px}
@media(max-width:900px){.split,.compare-columns{grid-template-columns:1fr}}
        """
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{APP_NAME}</title>
  <style>{style}</style>
</head>
<body>
  <header>
    <h1>小红书队列下载</h1>
    <div class="status"><span id="runningPill" class="pill">读取中</span><span id="cookiePill" class="pill">Cookie 读取中</span></div>
  </header>
  <main>
    <section>
      <h2>队列控制</h2>
      <div class="actions">
        <form method="post" action="/run"><button type="submit">立即处理队列</button></form>
        <form method="post" action="/reload"><button class="secondary" type="submit">重新读取配置</button></form>
        <form method="post" action="/clear-queue"><button class="danger" type="submit">清空所有队列</button></form>
      </div>
      <div class="progress-grid">
        <div class="metric"><span class="label">待处理</span><strong id="pendingMetric">0</strong></div>
        <div class="metric"><span class="label">待重试</span><strong id="retryMetric">0</strong></div>
        <div class="metric"><span class="label">已完成</span><strong id="doneMetric">0</strong></div>
        <div class="metric"><span class="label">失败</span><strong id="failedMetric">0</strong></div>
        <div class="metric"><span class="label">当前</span><strong id="progressMetric">0 / 0</strong></div>
      </div>
      <div class="help" id="currentUrl"></div>
    </section>
    <section>
      <h2>下载节奏</h2>
      <form method="post" action="/settings">
        <div class="grid">
          <div><label>两条之间基础间隔（秒）</label><input name="request_delay_seconds" type="number" min="0" step="1" value="{delay_value}"></div>
          <div><label>随机抖动上限（秒）</label><input name="jitter_seconds" type="number" min="0" step="1" value="{jitter_value}"></div>
          <div><label>单轮最多处理条数（0 表示不限制）</label><input name="max_items_per_run" type="number" min="0" step="1" value="{max_items_value}"></div>
          <div><label>图片格式</label><select name="image_format">{image_options}</select></div>
        </div>
        <div class="help">实际间隔 = 基础间隔 + 0 到抖动上限之间的随机秒数。默认 0 秒，上一条提交完成后立即处理下一条。图片格式默认 AUTO，避免强制 PNG 时 CDN 返回 400。</div>
        <div class="actions"><button type="submit">保存下载节奏</button></div>
      </form>
    </section>
    <div class="split">
      <section class="queue-form">
        <h2>从网页端发过来的链接</h2>
        <form method="post" action="/submit-links">
          <label>批量粘贴小红书作品链接</label>
          <textarea name="links" placeholder="https://www.xiaohongshu.com/discovery/item/..."></textarea>
          <div class="actions"><button type="submit">加入队列并开始下载</button></div>
        </form>
      </section>
      <section>
        <h2>XHS-Downloader Cookie</h2>
        <form method="post" action="/settings-cookie">
          <div class="help">这里写入的是 JoeanAmier/XHS-Downloader 2.7 使用的 <code>settings.json</code> 里的 <code>cookie</code> 字段，不再使用旧的自动采集 Cookie。</div>
          <label>Cookie Header</label>
          <textarea name="cookie_text" placeholder="a1=...; web_session=..."></textarea>
          <div class="actions"><button type="submit">保存到 settings.json</button></div>
        </form>
        <div class="help" id="cookieSummary"></div>
      </section>
    </div>
    <section>
      <h2>错误列表</h2>
      <div class="actions"><button class="secondary" id="retryAllErrors" type="button">全部重试</button></div>
      <div class="wide-table"><table><thead><tr><th>作品</th><th>状态</th><th>次数</th><th>下次重试</th><th>更新时间</th><th>错误</th><th>操作</th></tr></thead><tbody id="errorsBody"></tbody></table></div>
    </section>
    <section>
      <h2>本地目录对比</h2>
      <div class="progress-grid">
        <div class="metric"><span class="label">网页提交</span><strong id="compareSubmitted">0</strong></div>
        <div class="metric"><span class="label">本地文件夹</span><strong id="compareLocal">0</strong></div>
        <div class="metric"><span class="label">本地还没有</span><strong id="compareMissing">0</strong></div>
        <div class="metric"><span class="label">本地多余</span><strong id="compareExtra">0</strong></div>
      </div>
      <div class="help" id="compareMeta">等待 userscript 提交点赞/收藏名单。</div>
      <div class="compare-columns">
        <div class="compare-list"><h3>本地还没有</h3><ul id="missingList"></ul></div>
        <div class="compare-list"><h3>本地多余</h3><ul id="extraList"></ul></div>
      </div>
    </section>
    <section>
      <h2>最近链接</h2>
      <div class="wide-table"><table><thead><tr><th>作品</th><th>状态</th><th>次数</th><th>来源</th><th>更新时间</th><th>错误</th></tr></thead><tbody id="notesBody"></tbody></table></div>
    </section>
    <div class="log-grid">
      <section><h2>xhs-api 日志</h2><pre id="apiLogBox"></pre></section>
      <section><h2>队列 worker 日志</h2><pre id="logBox"></pre></section>
    </div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    function statusLabel(status) {{
      return {{pending:"待处理", retry:"待重试", done:"完成", failed:"失败"}}[status] || status || "";
    }}
    function retryTime(value) {{
      if (!value) return "-";
      const date = new Date(Number(value) * 1000);
      return Number.isFinite(date.getTime()) ? date.toLocaleString() : "-";
    }}
    function updateLogs(id, lines) {{
      const box = $(id);
      const stuck = Math.abs(box.scrollHeight - box.scrollTop - box.clientHeight) < 60;
      box.textContent = (lines || []).join("\\n");
      if (stuck) box.scrollTop = box.scrollHeight;
    }}
    function renderNotes(notes) {{
      $("notesBody").innerHTML = (notes || []).map((n) => `
        <tr class="status-${{esc(n.status)}}">
          <td><span class="status-dot"></span><a href="${{esc(n.url)}}" target="_blank">${{esc(n.note_id)}}</a></td>
          <td>${{esc(statusLabel(n.status))}}</td>
          <td>${{esc(n.attempts)}}</td>
          <td>${{esc(n.source || "")}}</td>
          <td>${{esc(n.updated_at || "")}}</td>
          <td>${{esc((n.last_error || "").slice(0, 240))}}</td>
        </tr>`).join("");
    }}
    async function postJson(url, payload) {{
      const resp = await fetch(url, {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(payload || {{}})
      }});
      if (!resp.ok) throw new Error(await resp.text());
      return resp.json();
    }}
    async function retryNote(noteId) {{
      await postJson("/api/retry-note", {{note_id: noteId}});
      await refreshStatus();
    }}
    function renderErrors(notes) {{
      $("errorsBody").innerHTML = (notes || []).map((n) => `
        <tr class="status-${{esc(n.status)}}">
          <td><span class="status-dot"></span><a href="${{esc(n.url)}}" target="_blank">${{esc(n.note_id)}}</a></td>
          <td>${{esc(statusLabel(n.status))}}</td>
          <td>${{esc(n.attempts)}}</td>
          <td>${{esc(retryTime(n.retry_after))}}</td>
          <td>${{esc(n.updated_at || "")}}</td>
          <td>${{esc((n.last_error || "").slice(0, 360))}}</td>
          <td><button class="secondary retry-note" type="button" data-note-id="${{esc(n.note_id)}}">重试</button></td>
        </tr>`).join("");
    }}
    function renderCompare(compare) {{
      compare = compare || {{}};
      $("compareSubmitted").textContent = compare.submitted_count || 0;
      $("compareLocal").textContent = compare.local_count || 0;
      $("compareMissing").textContent = compare.missing_count || 0;
      $("compareExtra").textContent = compare.extra_count || 0;
      $("compareMeta").textContent = compare.checked_at
        ? `检查时间：${{compare.checked_at}}；目录：${{compare.work_path || ""}}；来源：${{compare.source || ""}}`
        : "等待 userscript 提交点赞/收藏名单。";
      $("missingList").innerHTML = (compare.missing || []).map((item) => `<li>${{esc(item.author)}}_${{esc(item.title)}}</li>`).join("");
      $("extraList").innerHTML = (compare.extra || []).map((item) => `<li>${{esc(item.folder || item.title || "")}}</li>`).join("");
    }}
    function renderCookie(summary) {{
      const missing = (summary?.missing_required || []).join(", ") || "无";
      $("cookiePill").textContent = `Cookie：${{summary?.present ? "已保存" : "未保存"}}`;
      $("cookieSummary").textContent = `Cookie 字段数：${{summary?.count || 0}}；a1：${{summary?.has_a1 ? "有" : "缺"}}；web_session：${{summary?.has_web_session ? "有" : "缺"}}；缺少：${{missing}}`;
    }}
    async function refreshStatus() {{
      try {{
        const res = await fetch("/api/status", {{cache:"no-store"}});
        const data = await res.json();
        const counts = data.counts || {{}};
        const progress = data.progress || {{}};
        $("runningPill").textContent = `运行状态：${{data.running ? "运行中" : "空闲"}}`;
        $("pendingMetric").textContent = counts.pending || 0;
        $("retryMetric").textContent = counts.retry || 0;
        $("doneMetric").textContent = counts.done || 0;
        $("failedMetric").textContent = counts.failed || 0;
        $("progressMetric").textContent = `${{progress.done || 0}} / ${{progress.total || 0}}`;
        $("currentUrl").textContent = progress.current_url ? `当前：${{progress.current_url}}` : (data.last_run_message || "");
        renderErrors(data.error_notes || []);
        renderNotes(data.notes || []);
        renderCompare(data.library_compare || {{}});
        renderCookie(data.settings_cookie || {{}});
        updateLogs("apiLogBox", data.xhs_api_logs || []);
        updateLogs("logBox", data.logs || []);
      }} catch (error) {{
        $("runningPill").textContent = `刷新失败：${{error}}`;
      }}
    }}
    document.addEventListener("click", async (event) => {{
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.classList.contains("retry-note")) {{
        target.setAttribute("disabled", "disabled");
        try {{ await retryNote(target.dataset.noteId || ""); }} catch (error) {{ alert(`重试失败：${{error}}`); }}
        target.removeAttribute("disabled");
      }}
      if (target.id === "retryAllErrors") {{
        target.setAttribute("disabled", "disabled");
        try {{
          await postJson("/api/retry-errors", {{}});
          await refreshStatus();
        }} catch (error) {{
          alert(`批量重试失败：${{error}}`);
        }}
        target.removeAttribute("disabled");
      }}
    }});
    refreshStatus();
    setInterval(refreshStatus, 3000);
  </script>
</body>
</html>"""


def redirect(handler: BaseHTTPRequestHandler, location: str = "/") -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.end_headers()


def send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path.startswith("/api/status"):
                send_json(self, app.status())
                return
            body = html_page(app).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            content_type = self.headers.get("Content-Type", "")
            if self.path == "/api/run-now":
                RUN_NOW_EVENT.set()
                send_json(self, {"ok": True, "message": "已触发小红书队列处理"})
                return
            if self.path == "/api/submit-links":
                try:
                    payload = json.loads(raw or "{}") if "application/json" in content_type else {"text": raw}
                except json.JSONDecodeError as error:
                    send_json(self, {"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                    return
                urls = extract_urls_from_text("\n".join(str(value) for value in payload.values()))
                result = app.submit_links(urls)
                RUN_NOW_EVENT.set()
                send_json(
                    self,
                    {
                        "ok": not result.invalid,
                        "accepted": len(result.accepted),
                        "skipped": len(result.skipped),
                        "invalid": result.invalid,
                    },
                )
                return
            if self.path == "/api/retry-note":
                try:
                    payload = json.loads(raw or "{}") if "application/json" in content_type else {}
                except json.JSONDecodeError as error:
                    send_json(self, {"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                    return
                changed = app.retry_note(str(payload.get("note_id") or ""))
                if changed:
                    RUN_NOW_EVENT.set()
                send_json(self, {"ok": changed, "message": "已重新加入队列" if changed else "未找到可重试记录"})
                return
            if self.path == "/api/retry-errors":
                changed = app.retry_errors()
                if changed:
                    RUN_NOW_EVENT.set()
                send_json(self, {"ok": True, "changed": changed})
                return
            if self.path == "/api/library-compare":
                try:
                    payload = json.loads(raw or "{}") if "application/json" in content_type else {}
                except json.JSONDecodeError as error:
                    send_json(self, {"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                    return
                items = payload.get("items") if isinstance(payload.get("items"), list) else []
                result = app.compare_library(items, str(payload.get("source") or payload.get("kind") or ""))
                send_json(self, {"ok": True, "result": result})
                return
            form = parse_qs(raw)
            if self.path == "/run":
                RUN_NOW_EVENT.set()
                redirect(self)
                return
            if self.path == "/reload":
                app.reload_config()
                app.log.write("已从网页端重新读取配置。")
                redirect(self)
                return
            if self.path == "/clear-queue":
                app.clear_queue()
                redirect(self)
                return
            if self.path == "/submit-links":
                urls = extract_urls_from_text((form.get("links") or [""])[0])
                result = app.submit_links(urls)
                app.log.write(f"网页提交链接：新增 {len(result.accepted)}，已存在 {len(result.skipped)}，无效 {len(result.invalid)}。")
                RUN_NOW_EVENT.set()
                redirect(self)
                return
            if self.path == "/settings-cookie":
                cookie_text = (form.get("cookie_text") or [""])[0]
                save_settings_cookie(app.config, cookie_text)
                app.log.write("已保存小红书下载器 settings.json Cookie。")
                redirect(self)
                return
            if self.path == "/settings":
                def number(name: str, default: float) -> float:
                    raw_value = (form.get(name) or [str(default)])[0]
                    try:
                        return max(0.0, float(raw_value))
                    except ValueError:
                        return default

                patch = {
                    "request_delay_seconds": int(number("request_delay_seconds", 0)),
                    "jitter_seconds": int(number("jitter_seconds", 0)),
                    "max_items_per_run": int(number("max_items_per_run", 0)),
                    "image_format": ((form.get("image_format") or ["AUTO"])[0] or "AUTO").upper(),
                }
                app.config = save_web_settings(app.config_path, app.config, patch)
                sync_downloader_settings(app.config)
                app.log.write(
                    "已保存小红书下载节奏："
                    f"基础间隔 {patch['request_delay_seconds']} 秒，"
                    f"抖动 {patch['jitter_seconds']} 秒，"
                    f"单轮上限 {patch['max_items_per_run']}，"
                    f"图片格式 {patch['image_format']}"
                )
                redirect(self)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def worker_loop(app: App) -> None:
    app.log.write("小红书队列 worker 已启动；不会自动打开账号页面，只等待网页脚本/手动提交链接。")
    while not STOP_EVENT.is_set():
        if not RUN_NOW_EVENT.wait(30) and not app.has_due_retry():
            continue
        RUN_NOW_EVENT.clear()
        if STOP_EVENT.is_set():
            break
        try:
            app.run_once()
        except Exception:
            pass


def shutdown(_signum: int, _frame: Any) -> None:
    STOP_EVENT.set()
    RUN_NOW_EVENT.set()
    raise SystemExit(0)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    app = App(Path(args.config))
    if args.run_once:
        app.run_once()
        return 0
    threading.Thread(target=worker_loop, args=(app,), daemon=True).start()
    web_cfg = app.config.get("web", {})
    host = str(web_cfg.get("host", "0.0.0.0"))
    port = int(web_cfg.get("port", 8080))
    app.log.write(f"Web UI listening on {host}:{port}")
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
