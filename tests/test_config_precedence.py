import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.config import parse_config_and_args  # noqa: E402
from src.constants import DEFAULT_PAGE_ITEM_CNT  # noqa: E402


def _write_config(path: Path, *, two_cameras: bool = False) -> None:
    if two_cameras:
        cameras = textwrap.dedent(
            """
            cameras:
              back:
                ble_address: "AA:BB:CC:DD:EE:01"
                ssid: "TrailCam_BACK"
              front:
                ble_address: "AA:BB:CC:DD:EE:02"
                ssid: "TrailCam_FRONT"
            """
        ).strip()
    else:
        cameras = textwrap.dedent(
            """
            cameras:
              back:
                ble_address: "AA:BB:CC:DD:EE:01"
                ssid: "TrailCam_BACK"
            """
        ).strip()

    body = f"""
version: 1
{cameras}
client:
  wifi_ifname: "wlan0"
  udp_local_port: 16734
  page_item_cnt: 33
  list_max_pages: 111
  download_listen_s: 12.5
  download_idle_s: 3.0
  photo_download_retries: 4
  video_fps: 24
  strict_video: false
paths:
  staging_dir: "cfg/staging"
  tmp_dir: "cfg/tmp"
"""
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")


class TestConfigPrecedence(unittest.TestCase):
    def test_parse_config_and_args_precedence_config_then_cli(self):
        with tempfile.TemporaryDirectory(prefix="cfg_precedence_") as td:
            root = Path(td)
            cfg_path = root / "config.yaml"
            _write_config(cfg_path)

            cli_staging = root / "cli_staging"
            cli_tmp = root / "cli_tmp"
            cfg = parse_config_and_args(
                [
                    "--config",
                    str(cfg_path),
                    "--camera",
                    "back",
                    "--list-media-page",
                    "--page-no",
                    "4",
                    "--page-item-cnt",
                    "49",
                    "--staging-dir",
                    str(cli_staging),
                    "--tmp-dir",
                    str(cli_tmp),
                ]
            )

            self.assertEqual(cfg.op, "list_media_page")
            self.assertEqual(cfg.camera.alias, "back")
            self.assertEqual(cfg.client.page_no, 4)  # CLI override
            self.assertEqual(cfg.client.page_item_cnt, 49)  # CLI override
            self.assertEqual(cfg.client.list_max_pages, 111)  # config value
            self.assertEqual(cfg.client.download_listen_s, 12.5)  # config-only
            self.assertEqual(cfg.client.download_idle_s, 3.0)  # config-only
            self.assertEqual(cfg.client.video_fps, 24)  # config-only
            self.assertFalse(cfg.client.strict_video)  # config default
            self.assertEqual(cfg.paths.staging_dir, str(cli_staging))  # CLI override
            self.assertEqual(cfg.paths.tmp_dir, str(cli_tmp))  # CLI override

    def test_strict_video_cli_override(self):
        with tempfile.TemporaryDirectory(prefix="cfg_strict_video_") as td:
            root = Path(td)
            cfg_path = root / "config.yaml"
            _write_config(cfg_path)

            cfg = parse_config_and_args(
                [
                    "--config",
                    str(cfg_path),
                    "--camera",
                    "back",
                    "--download-single",
                    "105",
                    "--dir-num",
                    "100",
                    "--strict-video",
                ]
            )
            self.assertTrue(cfg.client.strict_video)

    def test_page_item_cnt_is_clamped_for_list_and_download_ops(self):
        with tempfile.TemporaryDirectory(prefix="cfg_clamp_") as td:
            root = Path(td)
            cfg_path = root / "config.yaml"
            _write_config(cfg_path)

            cfg = parse_config_and_args(
                [
                    "--config",
                    str(cfg_path),
                    "--camera",
                    "back",
                    "--list-media-page",
                    "--page-item-cnt",
                    "80",
                ]
            )
            self.assertEqual(cfg.client.page_item_cnt, DEFAULT_PAGE_ITEM_CNT)

    def test_camera_required_when_multiple_configured(self):
        with tempfile.TemporaryDirectory(prefix="cfg_camera_req_") as td:
            root = Path(td)
            cfg_path = root / "config.yaml"
            _write_config(cfg_path, two_cameras=True)
            with self.assertRaises(SystemExit):
                parse_config_and_args(["--config", str(cfg_path), "--list-media-page"])


if __name__ == "__main__":
    unittest.main()
