#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

try:
    from nas_auto_common.ui import app_css
except ModuleNotFoundError:
    def app_css(extra: str = "") -> str:
        return extra

APP_NAME = "Instagram Queue Downloader"
DEFAULT_CONFIG_PATH = Path("/config/instagram/config.json")
INSTAGRAM_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+/?[^\s\"'<>]*",
    re.IGNORECASE,
)
RUN_NOW_EVENT = threading.Event()

DEFAULT_CONFIG: dict[str, Any] = {
    "database": "/state/instagram/instagram_queue.sqlite3",
    "queue_files": ["/queue/instagram/links.txt"],
    "download_dir": "/downloads/instagram",
    "cookie_file": "/config/instagram/instagram_cookies.txt",
    "interval_seconds": 300,
    "max_attempts": 3,
    "request_delay_seconds": 2,
    "download_images": False,
    "download_videos": True,
    "yt_dlp_format": "bv*+ba/b",
    "web": {"host": "127.0.0.1", "port": 18085, "log_lines": 1000},
}

MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return deep_merge(DEFAULT_CONFIG, read_json(path))
    write_json(path, DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def extract_urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in INSTAGRAM_URL_RE.finditer(str(text or "")):
        raw = match.group(0).strip().rstrip("),.;，。；").split("#", 1)[0]
        permalink = re.search(r"instagram\.com/((?:p|reel|tv)/[A-Za-z0-9_-]+)", raw, re.IGNORECASE)
        value = f"https://www.instagram.com/{permalink.group(1)}/" if permalink else ""
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    return urls


def note_id_from_url(url: str) -> str:
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url, re.IGNORECASE)
    return match.group(1) if match else url[:180]


def media_files(path: Path) -> set[Path]:
    if not path.exists():
        return set()
    return {
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS and not item.name.endswith(".part")
    }


def tail_file(path: Path, limit: int = 200) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


class RingLog:
    def __init__(self, max_lines: int = 1000):
        self.max_lines = max_lines
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        line = f"{now_iso()} {message}"
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self.max_lines:
                self._lines = self._lines[-self.max_lines :]
        print(line, flush=True)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


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
        with closing(self.connect()) as conn, conn:
            conn.executescript(
                """
                create table if not exists notes (
                    note_id text primary key,
                    url text not null,
                    source text,
                    status text not null default 'pending',
                    attempts integer not null default 0,
                    last_error text,
                    first_seen_at text not null,
                    updated_at text not null,
                    downloaded_at text
                );
                create index if not exists idx_instagram_status on notes(status);
                """
            )

    def add_urls(self, urls: list[str], source: str = "") -> QueueResult:
        accepted: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []
        with self._lock, closing(self.connect()) as conn, conn:
            for url in urls:
                found = extract_urls_from_text(url)
                if not found:
                    invalid.append(url[:200])
                    continue
                normalized = found[0]
                note_id = note_id_from_url(normalized)
                row = conn.execute("select note_id from notes where note_id=?", (note_id,)).fetchone()
                if row:
                    skipped.append(normalized)
                    continue
                conn.execute(
                    """
                    insert into notes(note_id,url,source,status,attempts,last_error,first_seen_at,updated_at)
                    values(?,?,?,?,?,?,?,?)
                    """,
                    (note_id, normalized, source, "pending", 0, "", now_iso(), now_iso()),
                )
                accepted.append(normalized)
        return QueueResult(accepted, skipped, invalid)

    def next_pending(self) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "select * from notes where status in ('pending','retry') order by first_seen_at limit 1"
            ).fetchone()
            return dict(row) if row else None

    def mark_running(self, note_id: str) -> None:
        with self._lock, closing(self.connect()) as conn, conn:
            conn.execute("update notes set status='running', attempts=attempts+1, updated_at=? where note_id=?", (now_iso(), note_id))

    def mark_done(self, note_id: str) -> None:
        with self._lock, closing(self.connect()) as conn, conn:
            conn.execute(
                "update notes set status='done', last_error='', downloaded_at=?, updated_at=? where note_id=?",
                (now_iso(), now_iso(), note_id),
            )

    def mark_error(self, note_id: str, error: str, max_attempts: int) -> None:
        with self._lock, closing(self.connect()) as conn, conn:
            row = conn.execute("select attempts from notes where note_id=?", (note_id,)).fetchone()
            attempts = int(row["attempts"] if row else 0)
            status = "failed" if attempts >= max_attempts else "retry"
            conn.execute(
                "update notes set status=?, last_error=?, updated_at=? where note_id=?",
                (status, error[-2000:], now_iso(), note_id),
            )

    def mark_pending_for_statuses(self, statuses: list[str]) -> int:
        allowed = [status for status in statuses if status in {"failed", "retry"}]
        if not allowed:
            return 0
        with self._lock, closing(self.connect()) as conn, conn:
            placeholders = ",".join("?" for _ in allowed)
            cur = conn.execute(
                f"update notes set status='pending', last_error='', updated_at=? where status in ({placeholders})",
                [now_iso(), *allowed],
            )
            return int(cur.rowcount or 0)

    def counts(self) -> dict[str, int]:
        with closing(self.connect()) as conn:
            rows = conn.execute("select status, count(*) c from notes group by status").fetchall()
        return {str(row["status"]): int(row["c"]) for row in rows}

    def recent_notes(self, limit: int = 200) -> list[dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute("select * from notes order by updated_at desc limit ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.log = RingLog(int(self.config.get("web", {}).get("log_lines", 1000)))
        self.store = Store(Path(str(self.config.get("database"))), self.log)
        self.running = False
        self.run_lock = threading.Lock()
        self.last_run_message = ""
        self.progress: dict[str, Any] = {"phase": "idle", "current_url": ""}
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        Path(str(self.config.get("download_dir") or "/downloads/instagram")).mkdir(parents=True, exist_ok=True)
        Path(str(self.config.get("cookie_file") or "/config/instagram/instagram_cookies.txt")).parent.mkdir(parents=True, exist_ok=True)
        Path(str(self.config.get("database") or "/state/instagram/instagram_queue.sqlite3")).parent.mkdir(parents=True, exist_ok=True)
        for item in self.config.get("queue_files") or []:
            Path(str(item)).parent.mkdir(parents=True, exist_ok=True)

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)
        self.log.max_lines = int(self.config.get("web", {}).get("log_lines", 1000))
        self.store = Store(Path(str(self.config.get("database"))), self.log)
        self.ensure_dirs()

    def import_queue_files(self) -> QueueResult:
        accepted: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []
        for item in self.config.get("queue_files") or []:
            path = Path(str(item))
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            result = self.store.add_urls(extract_urls_from_text(text), source=f"file:{path}")
            accepted.extend(result.accepted)
            skipped.extend(result.skipped)
            invalid.extend(result.invalid)
            path.write_text("", encoding="utf-8")
        if accepted or skipped or invalid:
            self.log.write(f"导入 Instagram 队列文件：新增 {len(accepted)}，已存在 {len(skipped)}，无效 {len(invalid)}")
        return QueueResult(accepted, skipped, invalid)

    def submit_links(self, urls: list[str], source: str = "web") -> QueueResult:
        result = self.store.add_urls(urls, source=source)
        self.last_run_message = f"提交 Instagram 链接：新增 {len(result.accepted)}，已存在 {len(result.skipped)}，无效 {len(result.invalid)}"
        self.log.write(self.last_run_message)
        return result

    def retry_errors(self) -> int:
        changed = self.store.mark_pending_for_statuses(["failed", "retry"])
        self.log.write(f"已将 {changed} 条 Instagram 错误记录重新加入队列")
        return changed

    def work_dir_for_url(self, url: str) -> Path:
        note_id = note_id_from_url(url)
        return Path(str(self.config.get("download_dir") or "/downloads/instagram")) / note_id

    def gallery_dl_image_command(self, url: str) -> list[str]:
        work_dir = self.work_dir_for_url(url)
        cmd = [
            "gallery-dl",
            "--no-input",
            "--no-part",
            "--write-metadata",
            "-D",
            str(work_dir),
            "-f",
            "{num}_{media_id}.{extension}",
            "-o",
            "videos=false",
            "-o",
            "audio=false",
            "-o",
            "previews=false",
        ]
        cookie_file = Path(str(self.config.get("cookie_file") or ""))
        if cookie_file.exists() and cookie_file.stat().st_size > 0:
            cmd.extend(["-o", f"cookies={cookie_file}"])
        cmd.append(url)
        return cmd

    def yt_dlp_video_command(self, url: str) -> list[str]:
        work_dir = self.work_dir_for_url(url)
        outtmpl = "%(upload_date>%Y-%m-%d|unknown)s_%(title).80B_%(id)s.%(ext)s"
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--newline",
            "--write-info-json",
            "--write-thumbnail",
            "--merge-output-format",
            "mp4",
            "-f",
            str(self.config.get("yt_dlp_format") or "bv*+ba/b"),
            "-P",
            str(work_dir),
            "-o",
            outtmpl,
        ]
        cookie_file = Path(str(self.config.get("cookie_file") or ""))
        if cookie_file.exists() and cookie_file.stat().st_size > 0:
            cmd.extend(["--cookies", str(cookie_file)])
        cmd.append(url)
        return cmd

    def run_downloader(self, name: str, cmd: list[str], work_dir: Path) -> tuple[bool, str, int]:
        before = media_files(work_dir)
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
        )
        output = (result.stdout or "")[-5000:]
        after = media_files(work_dir)
        added = len(after - before)
        if output.strip():
            self.log.write(f"{name} 输出：{output.strip()[-1200:]}")
        if result.returncode != 0:
            return False, output or f"{name} exited {result.returncode}", added
        return True, "", added

    def download_one(self, item: dict[str, Any]) -> None:
        note_id = str(item["note_id"])
        url = str(item["url"])
        self.store.mark_running(note_id)
        self.progress = {"phase": "downloading", "current_url": url, "note_id": note_id}
        work_dir = self.work_dir_for_url(url)
        work_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        media_added = 0
        if bool(self.config.get("download_images", True)):
            self.log.write(f"gallery-dl Instagram 图片/轮播：{url}")
            ok, error, added = self.run_downloader("gallery-dl", self.gallery_dl_image_command(url), work_dir)
            media_added += added
            if not ok:
                errors.append(f"gallery-dl: {error[-1200:]}")
        if bool(self.config.get("download_videos", True)):
            self.log.write(f"yt-dlp Instagram 视频：{url}")
            ok, error, added = self.run_downloader("yt-dlp", self.yt_dlp_video_command(url), work_dir)
            media_added += added
            if not ok:
                errors.append(f"yt-dlp: {error[-1200:]}")
        if media_added <= 0:
            raise RuntimeError("\n".join(errors) or "没有下载到任何媒体文件")
        if errors:
            self.log.write(f"Instagram 部分下载完成：{note_id}，新增 {media_added} 个媒体文件；部分错误：{errors[-1][-500:]}")
        self.store.mark_done(note_id)
        self.log.write(f"Instagram 下载完成：{note_id}，目录：{work_dir}，新增媒体文件：{media_added}")

    def run_once(self) -> None:
        if bool(self.config.get("download_images", True)) and not shutil.which("gallery-dl"):
            raise RuntimeError("gallery-dl 不存在，镜像依赖安装异常")
        if bool(self.config.get("download_videos", True)) and not shutil.which("yt-dlp"):
            raise RuntimeError("yt-dlp 不存在，镜像依赖安装异常")
        self.import_queue_files()
        max_attempts = int(self.config.get("max_attempts") or 3)
        delay = float(self.config.get("request_delay_seconds") or 0)
        while True:
            item = self.store.next_pending()
            if not item:
                self.last_run_message = "Instagram 队列为空"
                self.progress = {"phase": "idle", "current_url": ""}
                return
            try:
                self.download_one(item)
            except Exception as error:
                self.store.mark_error(str(item["note_id"]), str(error), max_attempts)
                self.log.write(f"Instagram 下载失败：{item['note_id']} {error}")
            if delay > 0:
                time.sleep(delay)

    def start_run_thread(self) -> bool:
        if self.running:
            return False

        def target() -> None:
            with self.run_lock:
                self.running = True
                try:
                    self.run_once()
                except Exception as error:
                    self.last_run_message = f"Instagram 运行失败：{error}"
                    self.log.write(self.last_run_message)
                finally:
                    self.running = False
                    self.progress = {"phase": "idle", "current_url": ""}

        threading.Thread(target=target, daemon=True).start()
        return True

    def scheduler_loop(self) -> None:
        while True:
            interval = max(30, int(self.config.get("interval_seconds") or 300))
            triggered = RUN_NOW_EVENT.wait(interval)
            RUN_NOW_EVENT.clear()
            if triggered or not self.running:
                self.start_run_thread()

    def status(self) -> dict[str, Any]:
        cookie_file = Path(str(self.config.get("cookie_file") or ""))
        return {
            "running": self.running,
            "counts": self.store.counts(),
            "progress": self.progress,
            "config": self.config,
            "cookie_present": cookie_file.exists() and cookie_file.stat().st_size > 0,
            "notes": self.store.recent_notes(),
            "logs": self.log.lines(),
            "last_run_message": self.last_run_message,
        }


def html_page(app: App) -> str:
    data = app.status()
    cfg = data["config"]
    counts = data["counts"]
    style = app_css(
        """
.grid{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
textarea{min-height:110px}.wide-table{overflow:auto}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}pre{white-space:pre-wrap;max-height:420px;overflow:auto}
"""
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Instagram Downloader</title><style>{style}</style></head><body>
<header><h1>Instagram Downloader</h1><div><span class="pill">运行：{"运行中" if data["running"] else "空闲"}</span><span class="pill">Cookie：{"可选已保存" if data["cookie_present"] else "未使用"}</span></div></header>
<main>
<section><h2>控制</h2><div class="actions"><form method="post" action="/run"><button type="submit">立即处理队列</button></form><form method="post" action="/retry-errors"><button class="secondary" type="submit">重试错误</button></form><form method="post" action="/reload"><button class="secondary" type="submit">重新读取配置</button></form></div><p class="muted">{html.escape(str(data["last_run_message"] or ""))}</p></section>
<section><h2>队列</h2><div class="grid"><div>待处理<br><strong>{counts.get("pending",0)}</strong></div><div>重试<br><strong>{counts.get("retry",0)}</strong></div><div>完成<br><strong>{counts.get("done",0)}</strong></div><div>失败<br><strong>{counts.get("failed",0)}</strong></div></div></section>
<section><h2>提交链接</h2><form method="post" action="/submit-links"><textarea name="links" placeholder="https://www.instagram.com/reel/..."></textarea><div class="actions"><button type="submit">加入队列</button></div></form></section>
<section><h2>配置</h2><form method="post" action="/settings"><div class="grid"><label>下载目录<input name="download_dir" value="{html.escape(str(cfg.get("download_dir") or ""))}"></label><label>运行间隔秒<input name="interval_seconds" type="number" value="{html.escape(str(cfg.get("interval_seconds") or 300))}"></label><label>最大尝试<input name="max_attempts" type="number" value="{html.escape(str(cfg.get("max_attempts") or 3))}"></label><label>yt-dlp 视频格式<input name="yt_dlp_format" value="{html.escape(str(cfg.get("yt_dlp_format") or "bv*+ba/b"))}"></label></div><div class="actions"><label><input type="checkbox" name="download_images" value="1" {"checked" if cfg.get("download_images", False) else ""}> 图片/轮播使用 gallery-dl</label><label><input type="checkbox" name="download_videos" value="1" {"checked" if cfg.get("download_videos", True) else ""}> 视频/Reels 使用 yt-dlp</label><button type="submit">保存配置</button></div></form><p class="muted">每个作品保存到下载目录下独立文件夹，例如 /downloads/instagram/DZxxxx/。默认不使用 Cookie；如以后需要小号 Cookie，可把 Netscape cookies.txt 放到 {html.escape(str(cfg.get("cookie_file") or ""))}。</p></section>
<section><h2>最近记录</h2><div class="wide-table"><table><thead><tr><th>作品</th><th>状态</th><th>次数</th><th>更新时间</th><th>错误</th></tr></thead><tbody>{"".join(f'<tr><td><a href="{html.escape(row["url"])}" target="_blank">{html.escape(row["note_id"])}</a></td><td>{html.escape(row["status"])}</td><td>{row["attempts"]}</td><td>{html.escape(str(row["updated_at"]))}</td><td>{html.escape(str(row["last_error"] or "")[:180])}</td></tr>' for row in data["notes"])}</tbody></table></div></section>
<section><h2>日志</h2><pre>{"\n".join(html.escape(line) for line in data["logs"][-200:])}</pre></section>
</main></body></html>"""


def send_json(handler: BaseHTTPRequestHandler, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def redirect(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", "/")
    handler.end_headers()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
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
                send_json(self, {"ok": True})
                return
            if self.path == "/api/submit-links":
                try:
                    payload = json.loads(raw or "{}") if "application/json" in content_type else {"text": raw}
                except json.JSONDecodeError as error:
                    send_json(self, {"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                    return
                candidates: list[str] = []
                if isinstance(payload.get("urls"), list):
                    candidates.extend(str(item) for item in payload["urls"])
                if payload.get("url"):
                    candidates.append(str(payload["url"]))
                if payload.get("text"):
                    candidates.extend(extract_urls_from_text(str(payload["text"])))
                result = app.submit_links(candidates, str(payload.get("source") or "api"))
                RUN_NOW_EVENT.set()
                send_json(self, {"ok": not result.invalid, "accepted": len(result.accepted), "skipped": len(result.skipped), "invalid": result.invalid})
                return
            form = parse_qs(raw)
            if self.path == "/run":
                app.start_run_thread()
                redirect(self)
                return
            if self.path == "/retry-errors":
                app.retry_errors()
                RUN_NOW_EVENT.set()
                redirect(self)
                return
            if self.path == "/reload":
                app.reload_config()
                redirect(self)
                return
            if self.path == "/submit-links":
                app.submit_links(extract_urls_from_text((form.get("links") or [""])[0]), "web")
                RUN_NOW_EVENT.set()
                redirect(self)
                return
            if self.path == "/settings":
                app.config["download_dir"] = (form.get("download_dir") or [app.config.get("download_dir")])[0]
                app.config["interval_seconds"] = int((form.get("interval_seconds") or [app.config.get("interval_seconds")])[0])
                app.config["max_attempts"] = int((form.get("max_attempts") or [app.config.get("max_attempts")])[0])
                app.config["yt_dlp_format"] = (form.get("yt_dlp_format") or [app.config.get("yt_dlp_format")])[0]
                app.config["download_images"] = "download_images" in form
                app.config["download_videos"] = "download_videos" in form
                write_json(app.config_path, app.config)
                app.reload_config()
                redirect(self)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args()
    app = App(Path(args.config))
    threading.Thread(target=app.scheduler_loop, daemon=True).start()
    web = app.config.get("web", {})
    server = ThreadingHTTPServer((str(web.get("host") or "127.0.0.1"), int(web.get("port") or 18085)), make_handler(app))
    app.log.write(f"{APP_NAME} web listening on {server.server_address}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
