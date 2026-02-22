from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.sync.sync_config import SyncConfig

_HCI_RE = re.compile(r"^hci\d+$", re.IGNORECASE)
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


class RequiredHardwareChecker:
    """Validate required local Bluetooth and Wi-Fi hardware before sync starts."""

    def __init__(
        self,
        *,
        wifi_ifname: str,
        bluetooth_adapter: Optional[str],
        net_sys_root: Path = Path("/sys/class/net"),
        bt_sys_root: Path = Path("/sys/class/bluetooth"),
        run_cmd: Optional[Callable[[list[str]], subprocess.CompletedProcess[str]]] = None,
    ) -> None:
        self.wifi_ifname = str(wifi_ifname).strip()
        self.bluetooth_adapter = str(bluetooth_adapter).strip() if bluetooth_adapter else None
        self.net_sys_root = net_sys_root
        self.bt_sys_root = bt_sys_root
        self._run_cmd = run_cmd or self._default_run_cmd

    def check(self) -> None:
        self._check_bluetooth()
        self._check_wifi()

    def _check_bluetooth(self) -> None:
        controllers = self._list_bluetooth_controllers()
        if not controllers:
            raise RuntimeError(
                "No Bluetooth adapter found. Expected at least one local BlueZ controller (hciX)."
            )

        if not self.bluetooth_adapter:
            return

        raw = self.bluetooth_adapter
        if _HCI_RE.fullmatch(raw):
            want = raw.lower()
            if want in controllers:
                return
            raise RuntimeError(
                f"Configured client.bluetooth_adapter={raw!r} was not found. "
                f"Available adapters: {self._format_controllers(controllers)}"
            )

        if _MAC_RE.fullmatch(raw):
            want_mac = raw.upper()
            for _name, addr in controllers.items():
                if addr and addr.upper() == want_mac:
                    return
            raise RuntimeError(
                f"Configured client.bluetooth_adapter MAC {raw!r} was not found. "
                f"Available adapters: {self._format_controllers(controllers)}"
            )

        raise RuntimeError(
            "client.bluetooth_adapter must be adapter hciX or controller MAC "
            "(example: hci0 or 8C:68:8B:83:07:DC)"
        )

    def _check_wifi(self) -> None:
        if not self.wifi_ifname:
            raise RuntimeError("client.wifi_ifname is empty")

        iface_path = self.net_sys_root / self.wifi_ifname
        if not iface_path.exists():
            available = self._list_wireless_ifaces()
            avail_txt = ", ".join(available) if available else "(none)"
            raise RuntimeError(
                f"Configured client.wifi_ifname={self.wifi_ifname!r} was not found. "
                f"Available Wi-Fi interfaces: {avail_txt}"
            )

        is_wireless = (iface_path / "wireless").exists() or (iface_path / "phy80211").exists()
        if not is_wireless:
            raise RuntimeError(
                f"Configured client.wifi_ifname={self.wifi_ifname!r} exists but is not a Wi-Fi interface."
            )

    def _list_wireless_ifaces(self) -> List[str]:
        if not self.net_sys_root.exists():
            return []
        out: List[str] = []
        for p in sorted(self.net_sys_root.iterdir()):
            if (p / "wireless").exists() or (p / "phy80211").exists():
                out.append(p.name)
        return out

    def _list_bluetooth_controllers(self) -> Dict[str, Optional[str]]:
        controllers: Dict[str, Optional[str]] = {}

        # Primary source: hciconfig (provides both adapter name and controller MAC).
        try:
            proc = self._run_cmd(["hciconfig", "-a"])
            if proc.returncode == 0:
                controllers.update(self._parse_hciconfig(proc.stdout or ""))
        except Exception:
            pass

        # Fallback: sysfs controller names.
        if self.bt_sys_root.exists():
            for p in sorted(self.bt_sys_root.iterdir()):
                name = p.name.lower()
                if not _HCI_RE.fullmatch(name):
                    continue
                addr_path = p / "address"
                addr: Optional[str] = None
                if addr_path.exists():
                    try:
                        addr = addr_path.read_text("utf-8").strip().upper() or None
                    except Exception:
                        addr = None
                controllers.setdefault(name, addr)

        return controllers

    @staticmethod
    def _parse_hciconfig(text: str) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        current_name: Optional[str] = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m_name = re.match(r"^(hci\d+):", line, flags=re.IGNORECASE)
            if m_name:
                current_name = m_name.group(1).lower()
                out.setdefault(current_name, None)
                continue
            if not current_name:
                continue
            m_addr = re.search(r"BD Address:\s*([0-9A-Fa-f:]{17})", line)
            if m_addr:
                out[current_name] = m_addr.group(1).upper()

        return out

    @staticmethod
    def _format_controllers(controllers: Dict[str, Optional[str]]) -> str:
        if not controllers:
            return "(none)"
        parts: List[str] = []
        for name in sorted(controllers):
            addr = controllers[name]
            parts.append(f"{name} ({addr})" if addr else name)
        return ", ".join(parts)

    @staticmethod
    def _default_run_cmd(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, text=True, capture_output=True)


def check_required_hardware(cfg: SyncConfig) -> None:
    if cfg.app_cfg is None:
        return
    checker = RequiredHardwareChecker(
        wifi_ifname=cfg.app_cfg.client.wifi_ifname,
        bluetooth_adapter=cfg.app_cfg.client.bluetooth_adapter,
    )
    checker.check()

