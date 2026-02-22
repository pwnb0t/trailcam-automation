from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.sync.hardware_check import RequiredHardwareChecker


class TestRequiredHardwareChecker(unittest.TestCase):
    def test_passes_when_specific_bluetooth_adapter_and_wifi_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            net = root / "net"
            bt = root / "bluetooth"
            (net / "wlp3s0" / "wireless").mkdir(parents=True)
            (bt / "hci1").mkdir(parents=True)
            (bt / "hci1" / "address").write_text("8C:68:8B:83:07:DC\n", encoding="utf-8")

            checker = RequiredHardwareChecker(
                wifi_ifname="wlp3s0",
                bluetooth_adapter="hci1",
                net_sys_root=net,
                bt_sys_root=bt,
            )
            checker.check()

    def test_fails_when_configured_bluetooth_adapter_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            net = root / "net"
            bt = root / "bluetooth"
            (net / "wlp3s0" / "wireless").mkdir(parents=True)
            (bt / "hci1").mkdir(parents=True)
            (bt / "hci1" / "address").write_text("8C:68:8B:83:07:DC\n", encoding="utf-8")

            checker = RequiredHardwareChecker(
                wifi_ifname="wlp3s0",
                bluetooth_adapter="hci0",
                net_sys_root=net,
                bt_sys_root=bt,
            )
            with self.assertRaisesRegex(RuntimeError, "client.bluetooth_adapter"):
                checker.check()

    def test_fails_when_wifi_interface_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            net = root / "net"
            bt = root / "bluetooth"
            net.mkdir(parents=True)
            (bt / "hci0").mkdir(parents=True)
            (bt / "hci0" / "address").write_text("AA:BB:CC:DD:EE:FF\n", encoding="utf-8")

            checker = RequiredHardwareChecker(
                wifi_ifname="wlp3s0",
                bluetooth_adapter=None,
                net_sys_root=net,
                bt_sys_root=bt,
            )
            with self.assertRaisesRegex(RuntimeError, "client.wifi_ifname"):
                checker.check()

    def test_fails_when_wifi_interface_is_not_wireless(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            net = root / "net"
            bt = root / "bluetooth"
            (net / "enp0s25").mkdir(parents=True)
            (bt / "hci0").mkdir(parents=True)
            (bt / "hci0" / "address").write_text("AA:BB:CC:DD:EE:FF\n", encoding="utf-8")

            checker = RequiredHardwareChecker(
                wifi_ifname="enp0s25",
                bluetooth_adapter=None,
                net_sys_root=net,
                bt_sys_root=bt,
            )
            with self.assertRaisesRegex(RuntimeError, "not a Wi-Fi interface"):
                checker.check()


if __name__ == "__main__":
    unittest.main()

