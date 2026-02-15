CAMERA_IP = "192.168.43.1"
LOCAL_PORT = 16734
DISCOVERY_PORT = 32108
WIFI_IFNAME = "wlan0"

CAMERA_USERNAME = "admin"
CAMERA_PASSWORD = "admin"

# Default runtime tunables (used by config parsing; overridden by config.yaml, then CLI where allowed)
DEFAULT_PAGE_NO = 0
DEFAULT_PAGE_ITEM_CNT = 48
DEFAULT_LIST_MAX_PAGES = 200
DEFAULT_DOWNLOAD_LISTEN_S = 45.0
DEFAULT_DOWNLOAD_IDLE_S = 4.0
DEFAULT_VIDEO_FPS = 30

# Default camera media directory (DCIM folder number)
DEFAULT_DIR_NUM = 100

# Camera constraint: returns an error if itemCntPerPage >= 50.
MAX_PAGE_ITEM_CNT_EXCLUSIVE = 50

# AES command channel (from libArLink.so)
AES_CMD_KEY = b"xs38nul7cqf7m1va"
AES_CMD_IV = b"\x00" * 16

# BLE defaults (from prior reverse-engineering)
DEFAULT_BLE_ADDRESS = "C6:1E:0D:E0:0C:FB"
CHAR_WRITE = "00000002-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00000003-0000-1000-8000-00805f9b34fb"
WAKE_PAYLOAD = bytes.fromhex(
    "13 57 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
)
