#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import yaml

try:
    import f2
except Exception:
    f2 = None


DEFAULT_CONFIG_PATH = Path("/config/config.json")
DEFAULT_CONFIG: dict[str, Any] = {
    "run_interval_hours": 12,
    "run_timeout_seconds": 300,
    "cookie_file": "/config/douyin/douyin_cookie.txt",
    "f2_state_dir": "/state/douyin/f2",
    "f2_config_dir": "/config/douyin/f2",
    "download_dir": "/F2DL",
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
            "label": "点赞",
            "enabled": True,
            "mode": "like",
            "url": "https://www.douyin.com/user/MS4wLjABAAAANozRUmTPV4ZpvI-QTMqocY_vLWGwerzSX5vlzfgWl5Q?from_tab_name=main&showTab=like&vid=7126720963458223363",
        },
        {
            "name": "collection",
            "label": "收藏",
            "enabled": True,
            "mode": "collection",
            "url": "https://www.douyin.com/user/MS4wLjABAAAANozRUmTPV4ZpvI-QTMqocY_vLWGwerzSX5vlzfgWl5Q?from_tab_name=main&showTab=favorite_collection&vid=7126720963458223363",
        },
    ],
    "web": {"host": "0.0.0.0", "port": 8080, "log_lines": 400},
}


@dataclass
class RunResult:
    job: str
    status: str
    returncode: int | None
    started_at: str
    finished_at: str
    message: str


class RingLog:
    def __init__(self, max_lines: int = 400):
        self.max_lines = max_lines
        self._lock = threading.Lock()
        self._lines: list[str] = []

    def write(self, message: str) -> None:
        line = f"[{now_iso()}] {message}"
        print(line, flush=True)
        with self._lock:
            self._lines.append(line)
            self._lines = self._lines[-self.max_lines :]

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return deep_merge(DEFAULT_CONFIG, json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception:
            traceback.print_exc()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def read_cookie(path_value: str) -> str:
    path = Path(str(path_value or ""))
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8-sig").strip()


def bool_form(form: dict[str, list[str]], key: str) -> bool:
    return (form.get(key) or [""])[0] in {"1", "true", "on", "yes"}


def job_key(job: dict[str, Any], index: int) -> str:
    value = str(job.get("name") or "").strip()
    return value or f"job{index}"


def version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in str(value or "").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.log = RingLog(int(self.config.get("web", {}).get("log_lines", 400)))
        self.run_lock = threading.Lock()
        self.running = False
        self.stop_event = threading.Event()
        self.next_run_at = 0.0
        self.current_job = ""
        self.last_results: list[RunResult] = []
        self.last_run_message = ""
        self.f2_installed_version = str(getattr(f2, "__version__", "") or "unknown")
        self.f2_latest_version = ""
        self.f2_version_checked_at = ""
        self.f2_version_message = "尚未检查"
        self.ensure_dirs()
        self.start_version_check_thread()

    def ensure_dirs(self) -> None:
        for key in ["f2_state_dir", "f2_config_dir", "download_dir"]:
            Path(str(self.config.get(key) or "")).mkdir(parents=True, exist_ok=True)
        Path(str(self.config.get("cookie_file") or "")).parent.mkdir(parents=True, exist_ok=True)

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)
        self.log.max_lines = int(self.config.get("web", {}).get("log_lines", 400))
        self.ensure_dirs()

    def save_config(self, patch: dict[str, Any]) -> None:
        self.config = deep_merge(self.config, patch)
        save_config(self.config_path, self.config)
        self.ensure_dirs()

    def cookie_present(self) -> bool:
        return bool(read_cookie(str(self.config.get("cookie_file") or "")))

    def db_status(self) -> dict[str, Any]:
        state_dir = Path(str(self.config.get("f2_state_dir") or "/state/douyin/f2"))
        result: dict[str, Any] = {}
        for name in ["douyin_users.db", "douyin_videos.db"]:
            path = state_dir / name
            count = None
            if path.exists():
                try:
                    table = "user_info_web" if "users" in name else "video_info"
                    with sqlite3.connect(path) as conn:
                        count = int(conn.execute(f"select count(*) from {table}").fetchone()[0])
                except Exception:
                    count = None
            result[name] = {
                "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
                "rows": count,
                "required": name == "douyin_users.db",
            }
        return result

    def check_f2_version(self) -> None:
        self.f2_version_message = "检查中"
        try:
            with urllib.request.urlopen("https://pypi.org/pypi/f2/json", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            latest = str((payload.get("info") or {}).get("version") or "")
            self.f2_latest_version = latest
            self.f2_version_checked_at = now_iso()
            if latest and version_tuple(self.f2_installed_version) < version_tuple(latest):
                self.f2_version_message = f"发现新版本 {latest}"
                self.log.write(f"f2 版本检查：当前 {self.f2_installed_version}，最新 {latest}")
            elif latest:
                self.f2_version_message = "已是最新"
                self.log.write(f"f2 版本检查：当前 {self.f2_installed_version}，最新 {latest}")
            else:
                self.f2_version_message = "无法读取最新版本"
        except Exception as error:
            self.f2_version_checked_at = now_iso()
            self.f2_version_message = f"检查失败：{error}"
            self.log.write(f"f2 版本检查失败：{error}")

    def start_version_check_thread(self) -> None:
        threading.Thread(target=self.check_f2_version, daemon=True).start()

    def f2_config_for_job(self, job: dict[str, Any], index: int) -> Path:
        cookie = read_cookie(str(self.config.get("cookie_file") or ""))
        defaults = dict(self.config.get("defaults") or {})
        douyin = {
            "cookie": cookie,
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
            "path": str(self.config.get("download_dir") or "/F2DL"),
            "timeout": int(defaults.get("timeout") or 10),
            "url": str(job.get("url") or ""),
        }
        config_path = Path(str(self.config.get("f2_config_dir") or "/config/douyin/f2")) / f"{job_key(job, index)}.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump({"douyin": douyin}, allow_unicode=True, sort_keys=False, width=100000),
            encoding="utf-8",
        )
        return config_path

    def run_job(self, job: dict[str, Any], index: int) -> RunResult:
        key = job_key(job, index)
        started_at = now_iso()
        self.current_job = key
        if not str(job.get("url") or "").strip():
            message = "URL 为空，已跳过"
            self.log.write(f"{key}: {message}")
            return RunResult(key, "skipped", None, started_at, now_iso(), message)
        config_path = self.f2_config_for_job(job, index)
        timeout_seconds = int(self.config.get("run_timeout_seconds") or 300)
        command = [sys.executable, "-m", "f2", "dy", "-c", str(config_path)]
        env = dict(os.environ)
        env.update({"PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "COLUMNS": "160"})
        self.log.write(f"{key}: 启动 f2，配置 {config_path}")
        proc = subprocess.Popen(
            command,
            cwd=str(Path(str(self.config.get("f2_state_dir") or "/state/douyin/f2"))),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        timed_out = False

        def reader() -> None:
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self.log.write(f"{key}: {line}")

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            returncode = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            returncode = proc.returncode
        thread.join(timeout=2)
        if timed_out:
            status = "timeout"
            message = f"超过 {timeout_seconds}s，已终止"
        elif returncode == 0:
            status = "done"
            message = "ok"
        else:
            status = "failed"
            message = f"f2 exited with {returncode}"
        self.log.write(f"{key}: {message}")
        return RunResult(key, status, returncode, started_at, now_iso(), message)

    def run_once(self, only_job: str = "") -> list[RunResult]:
        if not self.run_lock.acquire(blocking=False):
            raise RuntimeError("已有抖音任务正在运行")
        self.running = True
        self.current_job = ""
        results: list[RunResult] = []
        try:
            self.reload_config()
            if not self.cookie_present():
                raise RuntimeError("未找到抖音 Cookie，请先在统一主页导入 Cookie 文件")
            self.log.write("抖音 f2 运行开始")
            jobs = list(self.config.get("jobs") or [])
            for index, job in enumerate(jobs):
                key = job_key(job, index)
                if only_job and key != only_job:
                    continue
                if not bool(job.get("enabled", True)) and not only_job:
                    continue
                results.append(self.run_job(job, index))
            self.last_results = results[-20:]
            failures = [item for item in results if item.status not in {"done", "skipped"}]
            self.last_run_message = f"{len(results)} job(s), {len(failures)} failed"
            self.log.write(f"抖音 f2 运行结束：{self.last_run_message}")
            return results
        except Exception as error:
            self.last_run_message = str(error)
            self.log.write(f"抖音 f2 运行失败：{error}")
            self.log.write(traceback.format_exc())
            raise
        finally:
            self.current_job = ""
            self.running = False
            self.run_lock.release()

    def start_run_thread(self, only_job: str = "") -> None:
        threading.Thread(target=lambda: self._thread_wrap(self.run_once, only_job), daemon=True).start()

    def _thread_wrap(self, fn: Any, *args: Any) -> None:
        try:
            fn(*args)
        except Exception:
            pass

    def scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            self.reload_config()
            interval = max(60, int(float(self.config.get("run_interval_hours") or 12) * 3600))
            if self.next_run_at <= 0:
                self.next_run_at = time.time() + 5
            if time.time() >= self.next_run_at and not self.running:
                if self.cookie_present():
                    self.start_run_thread()
                    self.next_run_at = time.time() + interval
                else:
                    self.log.write("未找到抖音 Cookie，自动运行暂缓")
                    self.next_run_at = time.time() + 60
            self.stop_event.wait(5)

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "current_job": self.current_job,
            "next_run_at": datetime.fromtimestamp(self.next_run_at).isoformat() if self.next_run_at else "",
            "cookie_present": self.cookie_present(),
            "config": self.config,
            "db": self.db_status(),
            "f2_version": {
                "installed": self.f2_installed_version,
                "latest": self.f2_latest_version,
                "checked_at": self.f2_version_checked_at,
                "message": self.f2_version_message,
            },
            "last_results": [item.__dict__ for item in self.last_results],
            "last_run_message": self.last_run_message,
            "logs": self.log.lines(),
        }


def html_page(app: App) -> str:
    data = app.status()
    cfg = data["config"]
    jobs_html = ""
    for index, job in enumerate(cfg.get("jobs") or []):
        key = job_key(job, index)
        checked = " checked" if job.get("enabled", True) else ""
        jobs_html += f"""
        <div class="job">
          <label><input type="checkbox" name="enabled_{index}"{checked}> {html.escape(str(job.get("label") or key))}</label>
          <input name="name_{index}" value="{html.escape(key)}">
          <input name="mode_{index}" value="{html.escape(str(job.get("mode") or ""))}">
          <input name="url_{index}" value="{html.escape(str(job.get("url") or ""))}">
          <button formaction="/run-job?name={html.escape(key)}" type="submit">运行</button>
        </div>"""
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Douyin F2 Downloader</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f7f9;color:#1d2433}}
header{{min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 24px;background:#111827;color:white}}
main{{max-width:1180px;margin:0 auto;padding:20px;display:grid;gap:16px}}section{{background:#fff;border:1px solid #d9dde5;border-radius:8px;padding:16px}}
h1{{font-size:18px;margin:0}}h2{{font-size:16px;margin:0 0 12px}}input{{box-sizing:border-box;border:1px solid #d9dde5;border-radius:6px;padding:8px;font:inherit;background:white}}
button{{border:0;background:#111827;color:white;border-radius:6px;padding:8px 12px;cursor:pointer}}button.secondary{{background:#475569}}
.muted{{color:#657084}}.pill{{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;background:#e6edf6;font-size:12px;color:#334155}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.job{{display:grid;grid-template-columns:120px 130px 120px minmax(260px,1fr) 72px;gap:8px;align-items:center;margin:8px 0}}
pre{{margin:0;background:#0f172a;color:#dbeafe;padding:12px;border-radius:6px;overflow:auto;max-height:520px;white-space:pre-wrap}}
@media(max-width:820px){{header{{padding:10px 14px;align-items:flex-start;flex-direction:column}}main{{padding:12px}}.job{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>Douyin F2 Downloader</h1><div><span class="pill">运行：{"运行中" if data["running"] else "空闲"}</span> <span class="pill">Cookie：{"已导入" if data["cookie_present"] else "未导入"}</span></div></header>
<main>
<section><h2>控制</h2><div class="muted">下一次自动运行：{html.escape(data["next_run_at"] or "未排程")}；当前任务：{html.escape(data["current_job"] or "-")}</div>
<div class="actions"><form method="post" action="/run"><button type="submit">立即运行全部</button></form><form method="post" action="/reload"><button class="secondary" type="submit">重新读取配置</button></form><form method="post" action="/check-version"><button class="secondary" type="submit">检查 f2 版本</button></form></div></section>
<section><h2>f2 版本</h2><div class="grid">
<div>当前版本<br><strong>{html.escape(str(data["f2_version"]["installed"]))}</strong></div>
<div>最新版本<br><strong>{html.escape(str(data["f2_version"]["latest"] or "-"))}</strong></div>
<div>检查时间<br><strong>{html.escape(str(data["f2_version"]["checked_at"] or "-"))}</strong></div>
<div>状态<br><strong>{html.escape(str(data["f2_version"]["message"]))}</strong></div>
</div></section>
<section><h2>配置</h2><form method="post" action="/settings">
<div class="grid"><label>运行间隔（小时）<input name="run_interval_hours" type="number" min="0.1" step="0.1" value="{html.escape(str(cfg.get("run_interval_hours") or 12))}"></label>
<label>单任务超时（秒）<input name="run_timeout_seconds" type="number" min="60" step="10" value="{html.escape(str(cfg.get("run_timeout_seconds") or 300))}"></label>
<label>下载目录<input name="download_dir" value="{html.escape(str(cfg.get("download_dir") or ""))}"></label>
<label>f2 数据目录<input name="f2_state_dir" value="{html.escape(str(cfg.get("f2_state_dir") or ""))}"></label></div>
{jobs_html}
<div class="actions"><button type="submit">保存配置</button></div></form></section>
<section><h2>数据库</h2><div class="grid">
<div>douyin_users.db<br><strong>{data["db"]["douyin_users.db"]["rows"] if data["db"]["douyin_users.db"]["rows"] is not None else "-"}</strong><br><span class="muted">点赞/收藏记录</span></div>
<div>douyin_videos.db<br><strong>{data["db"]["douyin_videos.db"]["rows"] if data["db"]["douyin_videos.db"]["rows"] is not None else "-"}</strong><br><span class="muted">没有也可运行</span></div>
</div></section>
<section><h2>最近结果</h2><pre>{html.escape(json.dumps(data["last_results"], ensure_ascii=False, indent=2))}</pre></section>
<section><h2>日志</h2><pre id="logBox">{html.escape(chr(10).join(data["logs"][-120:]))}</pre></section>
</main></body></html>"""
    return body


def redirect(handler: BaseHTTPRequestHandler, location: str = "/") -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.end_headers()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/status"):
                body = json.dumps(app.status(), ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = html_page(app).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
            if self.path == "/run":
                app.start_run_thread()
                redirect(self)
                return
            if self.path.startswith("/run-job"):
                name = self.path.split("name=", 1)[1] if "name=" in self.path else ""
                app.start_run_thread(name)
                redirect(self)
                return
            if self.path == "/reload":
                app.reload_config()
                redirect(self)
                return
            if self.path == "/check-version":
                app.start_version_check_thread()
                redirect(self)
                return
            if self.path == "/settings":
                jobs = []
                old_jobs = list(app.config.get("jobs") or [])
                for index, old_job in enumerate(old_jobs):
                    jobs.append(
                        {
                            "name": (form.get(f"name_{index}") or [job_key(old_job, index)])[0],
                            "label": old_job.get("label") or (form.get(f"name_{index}") or [job_key(old_job, index)])[0],
                            "enabled": bool_form(form, f"enabled_{index}"),
                            "mode": (form.get(f"mode_{index}") or [old_job.get("mode") or "like"])[0],
                            "url": (form.get(f"url_{index}") or [old_job.get("url") or ""])[0],
                        }
                    )
                try:
                    hours = max(0.1, float((form.get("run_interval_hours") or ["12"])[0] or "12"))
                except ValueError:
                    hours = 12.0
                try:
                    timeout_seconds = max(60, int((form.get("run_timeout_seconds") or ["300"])[0] or "300"))
                except ValueError:
                    timeout_seconds = 300
                app.save_config(
                    {
                        "run_interval_hours": hours,
                        "run_timeout_seconds": timeout_seconds,
                        "download_dir": (form.get("download_dir") or [app.config.get("download_dir")])[0],
                        "f2_state_dir": (form.get("f2_state_dir") or [app.config.get("f2_state_dir")])[0],
                        "jobs": jobs,
                    }
                )
                app.log.write("已从网页端保存抖音配置")
                redirect(self)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    app = App(Path(args.config))
    if args.run_once:
        app.run_once()
        return 0

    def shutdown(_signum: int, _frame: Any) -> None:
        app.stop_event.set()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=app.scheduler_loop, daemon=True).start()
    web_cfg = app.config.get("web", {})
    host = str(web_cfg.get("host", "0.0.0.0"))
    port = int(web_cfg.get("port", 8080))
    app.log.write(f"Web UI listening on {host}:{port}")
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
