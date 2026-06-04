import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import requests
from pixivpy3.utils import PixivError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_integrated"))
sys.path.insert(0, str(ROOT / "_src" / "pixiv-auto-download-nas-main"))

import integrated_server
from pixiv_auto_worker import classify_error, safe_extract_zip


class IntegratedPageTests(unittest.TestCase):
    def test_home_page_includes_version_and_service_cards(self) -> None:
        body = integrated_server.page().decode("utf-8")
        self.assertIn("v1.1.6", body)
        self.assertIn("小红书", body)
        self.assertIn("Pixiv", body)


class PixivNetworkTests(unittest.TestCase):
    def test_classifies_transient_network_errors(self) -> None:
        self.assertEqual(classify_error(requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")), "network")
        self.assertEqual(classify_error(PixivError("requests POST https://oauth.secure.pixiv.net/auth/token error")), "network")

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
