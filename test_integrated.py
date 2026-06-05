import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import requests
import yaml
from pixivpy3.utils import PixivError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_integrated"))
sys.path.insert(0, str(ROOT / "_src" / "douyin-f2-auto-main"))
sys.path.insert(0, str(ROOT / "_src" / "pixiv-auto-download-nas-main"))

import integrated_server
from douyin_f2_worker import (
    DOUYIN_REFERENCE_COOKIE_ORDER,
    build_f2_runtime_conf,
    cookie_summary,
    normalize_cookie_text,
    render_cookie_block,
    render_douyin_job_yaml,
)
from pixiv_auto_worker import classify_error, safe_extract_zip


class IntegratedPageTests(unittest.TestCase):
    def test_home_page_includes_version_and_service_cards(self) -> None:
        body = integrated_server.page().decode("utf-8")
        self.assertIn("v1.4.0-dev", body)
        self.assertIn("小红书", body)
        self.assertIn("Pixiv", body)
        self.assertIn("抖音", body)

    def test_imports_douyin_cookie_from_netscape_export(self) -> None:
        old_rule = integrated_server.SITE_RULES["douyin"]
        old_config_path = integrated_server.DOUYIN_CONFIG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "douyin_cookie.txt"
            config_path = Path(tmp) / "config.json"
            f2_dir = Path(tmp) / "f2"
            config_path.write_text(
                '{"f2_config_dir": "%s"}' % str(f2_dir).replace("\\", "\\\\"),
                encoding="utf-8",
            )
            integrated_server.SITE_RULES["douyin"] = dict(old_rule, output=output)
            integrated_server.DOUYIN_CONFIG_PATH = config_path
            try:
                result = integrated_server.import_all_cookie(
                    ".douyin.com\tTRUE\t/\tTRUE\t1999999999\tttwid\tabc\n"
                    ".douyin.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tdef\n"
                    ".douyin.com\tTRUE\t/\tTRUE\t1999999999\tcustom_douyin_cookie\tghi\n"
                    ".x.com\tTRUE\t/\tTRUE\t1999999999\tauth_token\tnope\n"
                )
            finally:
                integrated_server.SITE_RULES["douyin"] = old_rule
                integrated_server.DOUYIN_CONFIG_PATH = old_config_path
            self.assertEqual(result["douyin"]["count"], 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "cookie: sessionid=def;\n  ttwid=abc\n")
            self.assertIn("  cookie: sessionid=def;\n    ttwid=abc\n", (f2_dir / "like.yaml").read_text(encoding="utf-8"))
            self.assertIn("  cookie: sessionid=def;\n    ttwid=abc\n", (f2_dir / "collection.yaml").read_text(encoding="utf-8"))

    def test_imports_douyin_cookie_from_app_yaml_segment(self) -> None:
        old_rule = integrated_server.SITE_RULES["douyin"]
        old_config_path = integrated_server.DOUYIN_CONFIG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "douyin_cookie.txt"
            config_path = Path(tmp) / "config.json"
            f2_dir = Path(tmp) / "f2"
            config_path.write_text(
                '{"f2_config_dir": "%s"}' % str(f2_dir).replace("\\", "\\\\"),
                encoding="utf-8",
            )
            integrated_server.SITE_RULES["douyin"] = dict(old_rule, output=output)
            integrated_server.DOUYIN_CONFIG_PATH = config_path
            try:
                result = integrated_server.import_all_cookie(
                    "cookie: sessionid=abc;\n"
                    "  ttwid=def;\n"
                    "  msToken=ghi;\n"
                    "  random_key=keepme;\n"
                    "naming: '{create}-{nickname}-{aweme_id}'\n"
                )
            finally:
                integrated_server.SITE_RULES["douyin"] = old_rule
                integrated_server.DOUYIN_CONFIG_PATH = old_config_path
            self.assertEqual(result["douyin"]["count"], 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "cookie: sessionid=abc;\n  ttwid=def\n")
            self.assertIn("  cookie: sessionid=abc;\n    ttwid=def\n", (f2_dir / "like.yaml").read_text(encoding="utf-8"))
            self.assertIn("  cookie: sessionid=abc;\n    ttwid=def\n", (f2_dir / "collection.yaml").read_text(encoding="utf-8"))


class DouyinCookieTests(unittest.TestCase):
    def test_builds_bark_disabled_runtime_conf(self) -> None:
        runtime_conf = build_f2_runtime_conf(
            {"f2": {"enable_bark": True, "douyin": {"headers": {"Referer": "https://www.douyin.com/"}}}}
        )
        self.assertFalse(runtime_conf["f2"]["enable_bark"])
        self.assertEqual(runtime_conf["f2"]["douyin"]["headers"]["Referer"], "https://www.douyin.com/")

    def test_normalizes_cookie_text_and_summary(self) -> None:
        normalized = normalize_cookie_text(
            "cookie: sessionid=abc;\n"
            "  ttwid=def;\n"
            "  msToken=ghi;\n"
            "  random_key=keepme;\n"
            "naming: ignored\n"
        )
        self.assertEqual(normalized, "sessionid=abc; ttwid=def")
        summary = cookie_summary(normalized)
        self.assertEqual(summary["fields"], 2)
        self.assertEqual(summary["missing_required"], [])
        self.assertEqual(summary["status"], "高风险")
        self.assertEqual(summary["reference_present"], 2)
        self.assertEqual(summary["reference_total"], len(DOUYIN_REFERENCE_COOKIE_ORDER))

    def test_full_reference_cookie_is_normal(self) -> None:
        cookie_text = "; ".join(f"{name}=x" for name in DOUYIN_REFERENCE_COOKIE_ORDER)
        summary = cookie_summary(cookie_text)
        self.assertEqual(summary["status"], "正常")
        self.assertEqual(summary["risk"], "正常")
        self.assertEqual(summary["missing_reference"], [])

    def test_renders_saved_cookie_block_with_reference_line_breaks(self) -> None:
        rendered = render_cookie_block("sessionid=abc; ttwid=def")
        self.assertEqual(rendered, "cookie: sessionid=abc;\n  ttwid=def\n")
        self.assertEqual(normalize_cookie_text(rendered), "sessionid=abc; ttwid=def")

    def test_renders_saved_cookie_block_with_reference_grouping(self) -> None:
        rendered = render_cookie_block(
            "my_rd=1; volume_info=2; WallpaperGuide=3; FOLLOW_NUMBER_YELLOW_POINT_INFO=4"
        )
        self.assertEqual(
            rendered,
            "cookie: my_rd=1; volume_info=2; WallpaperGuide=3;\n  FOLLOW_NUMBER_YELLOW_POINT_INFO=4\n",
        )

    def test_renders_job_yaml_with_reference_cookie_line_breaks(self) -> None:
        rendered = render_douyin_job_yaml(
            {
                "cookie": "sessionid=abc; ttwid=def",
                "cover": False,
                "desc": False,
                "folderize": True,
                "interval": "all",
                "languages": None,
                "lyric": True,
                "max_connections": 5,
                "max_counts": 0,
                "max_retries": 5,
                "max_tasks": 10,
                "mode": "like",
                "music": None,
                "naming": "{create}-{nickname}-{aweme_id}",
                "page_counts": 20,
                "path": "/F2DL",
                "timeout": 10,
                "url": "https://www.douyin.com/user/example?showTab=like",
            }
        )
        self.assertIn("  cookie: sessionid=abc;\n    ttwid=def\n", rendered)
        loaded = yaml.safe_load(rendered) or {}
        self.assertEqual(loaded["douyin"]["cookie"], "sessionid=abc; ttwid=def")


class PixivNetworkTests(unittest.TestCase):
    def test_classifies_transient_network_errors(self) -> None:
        self.assertEqual(classify_error(requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")), "network")
        self.assertEqual(classify_error(PixivError("requests POST https://oauth.secure.pixiv.net/auth/token error")), "network")
        response = requests.Response()
        response.status_code = 429
        self.assertEqual(classify_error(requests.exceptions.HTTPError("too many requests", response=response)), "rate_limit")

    def test_rejects_unsafe_zip_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", b"nope")
            out_dir = root / "out"
            out_dir.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(RuntimeError):
                    safe_extract_zip(archive, out_dir)


if __name__ == "__main__":
    unittest.main()
