#!/usr/bin/env python3
import argparse
import asyncio
import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from bleak import BleakClient
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CAMERA_IP = "192.168.43.1"
LOCAL_PORT = 16734
DISCOVERY_PORT = 32108
WIFI_IFNAME = "wlan0"

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

# Hard-coded connect-phase D0 request packets (from pcap/trailcam_2-1-connect.pcap)
# Order is by first appearance in capture.
CONNECT_D0_PACKETS = [
    bytes.fromhex(
        "f1d000c5d1000000415254454d4953000200000021000000ad000000"
        "4a385757755144506d59534c66752f675841472b557162427935354b503269453235"
        "51504e6f667a6e3034302b4e493967377a65584c6b497058704330375358766f7372"
        "577363316d386d786e7136684d694b776550624b4a5577765376715a62367330736c"
        "3173667a692f3563525a746137586c30772f5a2b74345959397a57594143715232426c"
        "786473477a73636878734538476b57736f346c64735a6c614645716f797254416e413d00"
    ),
    bytes.fromhex(
        "f1d00045d1000001415254454d49530002000000220000002d000000"
        "792b444462714d4e4e6e56354c446a7533786c4568647a387975482b69334b63747763627670667a4d73773d00"
    ),
    bytes.fromhex(
        "f1d00045d1000002415254454d49530002000000230000002d000000"
        "792b444462714d4e4e6e56354c446a7533786c4568647a387975482b69334b63747763627670667a4d73773d00"
    ),
    bytes.fromhex(
        "f1d00071d1000003415254454d495300020000002400000059000000"
        "39305248304d6734504d6666594931664143796364504446764b52562f32327965695a6f"
        "44504b5246637947306a48376d6b5a43453136756378576347416f33687452413167624564337839743067493434454764413d3d00"
    ),
    bytes.fromhex(
        "f1d00031d1000004415254454d4953000200000001000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "f1d00404d1000005415254454d4953000200000025000000590a0000"
        "794a7565306f4e58423357704c79645a774e305035432f2f3368586d6458356e5938364d4f"
        "41397349316c584565657751447958396a6539535a7971794c5a494a737a3151734347435a4a"
        "7846364e3657414a524d6c6b357361692f353949356131436f5642624f34796336393454334d"
        "6d6a466669592f536569413242686f6957332b45554870515262437045774d5a597453373973"
        "7a4d47674f516251504a3278442f414b555232643672642b6a33436a5158714457434974717073"
        "725736787366644d2f43636b7635655571314f55746b4479526951746d72702f715947443843"
        "2f476862385873703735626e3869674e4c3632714f314c637456597745757835772f4344496a66"
        "6f6b5777654c766348664c553666305a3336386e32344b796e512b5164495a75533467484f374f"
        "592f6c6936497156526d617644716f624e594948594b6f586d364f795773354c4248366a4c5734"
        "5a706258614c35622f2b583433345844557a306b654c4e324b467470574a572b58492b42677156"
        "684d4736374c683937714954546f7762793843306a6f58356a516b307531307556323743496d"
        "2b6c5275394a30536d6263434f7661436171727972324a594c593952755150786f4f624f51664c"
        "6651724d44316959544571455545714e4f4e65397575336c59596a637a2b5035654f717534716c"
        "67784f4e7572315639744562706f643255384d635a4565514b4e675066725a70756f3143397864"
        "4e597a456b706d71394e33536f487a39735a434234584a5365674f657964322b59426263576956"
        "66762f42387059587042636a667148576930526465684746506f484e4f346d46426439335a4c32"
        "37645447483576574972344e56694630556471676265474b594a506b716d3941556a56526e2b59"
        "685264703134714e5652566c564b5046626a32726c336d333648356b316269424c696c7948326e"
        "6453495974516153657457774e4d54453850454b656e7a6b766354634768666b776d38324d6943"
        "596a776835424b6d42714670337a3336672f37554a325033332f382b6172514f54656554656130"
        "624d774d4b2b4c6e555863486f6e737a6d4451423759794b30474f65516951426365566e70614a"
        "492f44496b7935764c7573303859564175796b733042524a6949576673635467306f464139366c"
        "696d483158617254755639473278744e6d6b686a424a4e51464d492b4a53375450314d724d4f32"
        "5033576e7430462b704459335949496c61335a57623873544d4a3765685158706e582b7632354f"
        "78445a737a6274393233634e5138525739567942726a746f654955446763484546724362697a72"
        "35375351446f587841614e774e3938534674414670537a3279424563364b464d375a6f4e"
    ),
    bytes.fromhex(
        "f1d00404d10000066f6d566a497667453776594d57334b2f4f2f786d593131323937685937342b"
        "686c3551476c496a735a745871585071597347413067574438552f706a385a54476154566a79562b"
        "6b623873467a3430325832514d47734152773536337370316247466844696535376b6d4a6b70544a"
        "52526d2f5771354631414a35636c544c52326c4558314674645077742f525748412b777652436f51"
        "73595351614d34533356304634774e586e6f596c593745705a304a4d775a495966364b4233514a6c"
        "4343553663694b7a5832306c493571484d644e6e62736b455a612b33304a62557a70444c45315830"
        "32467154316c58624a663568386b4635327233384b5a4e53473065674d554f4b616534776c376467"
        "504f514e6d70437a364a37674765484f6a76516347363961497030514b597a432f306a6f79676f43"
        "636156487455533969676b67716b533646596f4259585032794b4c344b5978495678436b75416472"
        "584b4d496f684645306e4e7173694d73577933416e67764f584d706d344743633777675a59666b72"
        "6a36356f75464a792b4b546d4746316b6b597a7674554a6f51546a7a4b7535596b304741734b5752"
        "5830527742394c7464755134754d70795a4d5566676c4d6c75476f31425872657463796d5764616c"
        "756c7454416e4e69546c556231705776394f50664b374536706155796a4762683948547a77544939"
        "5a4c664c5139495164414d79484d49695472726f3742346646447743696378673631794a5964506b"
        "413139673766575365796f473536387638734b4f58374f7a7949685a76597774457376726d67736f"
        "7662506d314a307a634d304c565079655578797049314b385861436b6d494677664d574f4a334469"
        "756a30565848724b6e433774785252624b5a584e504275414b676a5a507446365a6b6f3967393376"
        "7154544d4164556549776e726d646549734e6631333578786a733633426d7068672f7878664b424c"
        "4c6f36534675772f5852645732413431324c4757303872484f74524831427955514e6568416e7837"
        "79325759706533454a74625949426d7133414b2b6c452b3259392f49787262654d45554372496f78"
        "4a4a52456872504f5a3639727272617746764d31444459617567564d313746596c2f45765568424d"
        "5950414558756c786a7361506c4f74484370694d64746c70766b2b7a6b424c6273626b497032476b"
        "596b676f63515a726174624e6935495378506b3850612b4362366b3066696b414a3377564c6f3656"
        "6a71386749387247615479755a6e6a425544356d6e35667374666976562b77376f6b7a4566756476"
        "6d467676716673556674743262457475527a725161596858467737785151517149676a464c464364"
        "6b5a362b327170426d554f464e32327355595a6e436b7a6176656858517a666941"
    ),
    bytes.fromhex(
        "f1d00271d100000734636b6843524d644d336a6c7070365a62306f484144446946537a664751584a6d"
        "776b59524a6f556237522b39674b657a37464f6534643870304232542b4c67525a50536d73722b694c"
        "4931626a766b4d45446a44364b55726657447a742f3646427454736d776a3137506a7058383170336433"
        "2b4856384476556648514e4668307a424f745371546a686b6c4538326364344c746b43654a4979345339"
        "787945676c486b522b563862494e69466b3969793953315077334d6b4d7761654b7635433248436b3030"
        "356f49676e6176384978557077383732346668656230516d6e757154443334464a354837344d6c38793073"
        "706748713857655533364f775334365931456f47613149377861786a64714a366b554d456d453941625674"
        "676566595a325634435a79367454705565322f3948416475795975304c5a4a38474447694337435a726f38"
        "445a6c76305358334e413136673834786c596d4a426551414e642b6643346f534a5a75457742345573376b"
        "6949415361563351664859755642505543504b342f746631323370354868745653554338577a67322f3653"
        "595666376a31316a586c6b7679613074376f6a5669677967774b4448566d6273526d79723248673231546b"
        "6766536d614a53727a4c6464496d6e61502b506e6d4d6958555167394b69782b656f6f5138354e6c644b2f"
        "51394572564f7669436d4d79576c5848595638536565566d764638574f4f635342634d356f376877484973"
        "33365642306b66316a6165716359496532717656746a394d4574394d6736706a47594c68797a44694d4874"
        "31464533676a4d646b5a534f723256543875525344454c564c46614a49673d3d00"
    ),
    bytes.fromhex(
        "f1d00031d1000008415254454d4953000200000002000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "f1d00031d1000009415254454d4953000200000003000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "f1d00031d100000a415254454d4953000200000004000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "f1d00031d100000b415254454d4953000200000005000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
]

REFRESH_D0_PACKETS = [
    bytes.fromhex("f1d00031d100000e415254454d4953000200000008000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"),
    bytes.fromhex("f1d00031d100000f415254454d4953000200000009000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"),
    bytes.fromhex("f1d00071d1000010415254454d49530002000000260000005900000039305248304d6734504d6666594931664143796364504446764b52562f32327965695a6f44504b5246637947306a48376d6b5a43453136756378576347416f33687452413167624564337839743067493434454764413d3d00"),
    bytes.fromhex("f1d00404d1000011415254454d4953000200000027000000590a0000794a7565306f4e58423357704c79645a774e305035432f2f3368586d6458356e5938364d4f41397349316c584565657751447958396a6539535a7971794c5a494a737a3151734347435a4a7846364e3657414a524d6c6b357361692f353949356131436f5642624f34796336393454334d6d6a466669592f536569413242686f6957332b45554870515262437045774d5a5974533739737a4d47674f516251504a3278442f414b555232643672642b6a33436a5158714457434974717073725736787366644d2f43636b7635655571314f55746b4479526951746d72702f7159474438432f476862385873703735626e3869674e4c3632714f314c637456597745757835772f4344496a666f6b5777654c766348664c553666305a3336386e32344b796e512b5164495a75533467484f374f592f6c6936497156526d617644716f624e594948594b6f586d364f795773354c4248366a4c57345a706258614c35622f2b583433345844557a306b654c4e324b467470574a572b58492b42677156684d4736374c683937714954546f7762793843306a6f58356a516b307531307556323743496d2b6c5275394a30536d6263434f7661436171727972324a594c593952755150786f4f624f51664c6651724d44316959544571455545714e4f4e65397575336c59596a637a2b5035654f717534716c67784f4e7572315639744562706f643255384d635a4565514b4e675066725a70756f31433978644e597a456b706d71394e33536f487a39735a434234584a5365674f657964322b5942626357695666762f42387059587042636a667148576930526465684746506f484e4f346d46426439335a4c3237645447483576574972344e56694630556471676265474b594a506b716d3941556a56526e2b59685264703134714e5652566c564b5046626a32726c336d333648356b316269424c696c7948326e6453495974516153657457774e4d54453850454b656e7a6b766354634768666b776d38324d6943596a776835424b6d42714670337a3336672f37554a325033332f382b6172514f54656554656130624d774d4b2b4c6e555863486f6e737a6d4451423759794b30474f65516951426365566e70614a492f44496b7935764c7573303859564175796b733042524a6949576673635467306f464139366c696d483158617254755639473278744e6d6b686a424a4e51464d492b4a53375450314d724d4f325033576e7430462b704459335949496c61335a57623873544d4a3765685158706e582b7632354f78445a737a6274393233634e5138525739567942726a746f654955446763484546724362697a7235375351446f587841614e774e3938534674414670537a3279424563364b464d375a6f4e"),
    bytes.fromhex("f1d00404d10000126f6d566a497667453776594d57334b2f4f2f786d593131323937685937342b686c3551476c496a735a745871585071597347413067574438552f706a385a54476154566a79562b6b623873467a3430325832514d47734152773536337370316247466844696535376b6d4a6b70544a52526d2f5771354631414a35636c544c52326c4558314674645077742f525748412b777652436f5173595351614d34533356304634774e586e6f596c593745705a304a4d775a495966364b4233514a6c4343553663694b7a5832306c493571484d644e6e62736b455a612b33304a62557a70444c4531583032467154316c58624a663568386b4635327233384b5a4e53473065674d554f4b616534776c376467504f514e6d70437a364a37674765484f6a76516347363961497030514b597a432f306a6f79676f43636156487455533969676b67716b533646596f4259585032794b4c344b5978495678436b75416472584b4d496f684645306e4e7173694d73577933416e67764f584d706d344743633777675a59666b726a36356f75464a792b4b546d4746316b6b597a7674554a6f51546a7a4b7535596b304741734b57525830527742394c7464755134754d70795a4d5566676c4d6c75476f31425872657463796d5764616c756c7454416e4e69546c556231705776394f50664b374536706155796a4762683948547a775449395a4c664c5139495164414d79484d49695472726f3742346646447743696378673631794a5964506b413139673766575365796f473536387638734b4f58374f7a7949685a76597774457376726d67736f7662506d314a307a634d304c565079655578797049314b385861436b6d494677664d574f4a334469756a30565848724b6e433774785252624b5a584e504275414b676a5a507446365a6b6f39673933767154544d4164556549776e726d646549734e6631333578786a733633426d7068672f7878664b424c4c6f36534675772f5852645732413431324c4757303872484f74524831427955514e6568416e783779325759706533454a74625949426d7133414b2b6c452b3259392f49787262654d45554372496f784a4a52456872504f5a3639727272617746764d31444459617567564d313746596c2f45765568424d5950414558756c786a7361506c4f74484370694d64746c70766b2b7a6b424c6273626b497032476b596b676f63515a726174624e6935495378506b3850612b4362366b3066696b414a3377564c6f36566a71386749387247615479755a6e6a425544356d6e35667374666976562b77376f6b7a45667564766d467676716673556674743262457475527a725161596858467737785151517149676a464c4643646b5a362b327170426d554f464e32327355595a6e436b7a6176656858517a666941"),
    bytes.fromhex("f1d00271d100001334636b6843524d644d336a6c7070365a62306f484144446946537a664751584a6d776b59524a6f556237522b39674b657a37464f6534643870304232542b4c67525a50536d73722b694c4931626a766b4d45446a44364b55726657447a742f3646427454736d776a3137506a70583831703364332b4856384476556648514e4668307a424f745371546a686b6c4538326364344c746b43654a4979345339787945676c486b522b563862494e69466b3969793953315077334d6b4d7761654b7635433248436b3030356f49676e6176384978557077383732346668656230516d6e757154443334464a354837344d6c38793073706748713857655533364f775334365931456f47613149377861786a64714a366b554d456d453941625674676566595a325634435a79367454705565322f3948416475795975304c5a4a38474447694337435a726f38445a6c76305358334e413136673834786c596d4a426551414e642b6643346f534a5a75457742345573376b6949415361563351664859755642505543504b342f746631323370354868745653554338577a67322f3653595665375a6931316a586c6b7679613074376f6a5669677967774b4448566d6273526d79723248673231546b6766536d614a53727a4c6464496d6e61502b506e6d4d6958555167394b69782b656f6f5138354e6c644b2f51394572564f7669436d4d79576c5848595638536565566d764638574f4f635342634d356f37687748497333365642306b66316a6165716359496532717656746a394d4574394d6736706a47594c68797a44694d487431464533676a4d646b5a534f723256543875525344454c564c46614a49673d3d00"),
    bytes.fromhex("f1d00031d1000014415254454d495300020000000a000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"),
    bytes.fromhex("f1d00031d1000015415254454d495300020000000b000100190000004d7a6c423336582f49566f385a7a49357247396a31773d3d00"),
]

def nmcli_rescan():
    subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan"], check=False)


def nmcli_list_ssids():
    p = subprocess.run(
        ["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
        text=True,
        capture_output=True,
    )
    return [l.strip() for l in p.stdout.splitlines() if l.strip()]


def nmcli_connect(ssid: str, pwd: str, ifname: str = WIFI_IFNAME) -> bool:
    subprocess.run(["sudo", "nmcli", "dev", "disconnect", ifname], capture_output=True, check=False)
    subprocess.run(["sudo", "nmcli", "connection", "delete", ssid], capture_output=True, check=False)
    p = subprocess.run(
        ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", pwd, "ifname", ifname],
        text=True,
        capture_output=True,
    )
    if p.returncode != 0:
        print("nmcli connect failed:")
        if p.stdout:
            print(p.stdout.strip())
        if p.stderr:
            print(p.stderr.strip())
        return False
    return True


def wifi_has_camera_ip(ifname: str = WIFI_IFNAME) -> bool:
    p = subprocess.run(["ip", "-br", "addr", "show", ifname], text=True, capture_output=True)
    out = p.stdout.strip()
    return "192.168.43." in out


async def ble_wake_and_get_creds(address: str) -> Dict[str, str]:
    creds = {"ssid": None, "pwd": None}

    async with BleakClient(address) as client:
        buf = bytearray()

        def on_notify(_, data: bytearray):
            nonlocal buf
            buf.extend(data)
            try:
                s = buf.decode("ascii", errors="ignore")
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    payload = s[start : end + 1]
                    obj = json.loads(payload)
                    if "ssid" in obj and "pwd" in obj:
                        creds["ssid"] = obj["ssid"]
                        creds["pwd"] = obj["pwd"]
            except Exception:
                pass

        await client.start_notify(CHAR_NOTIFY, on_notify)
        await client.write_gatt_char(CHAR_WRITE, WAKE_PAYLOAD, response=True)

        for _ in range(50):
            if creds["ssid"] and creds["pwd"]:
                break
            await asyncio.sleep(0.2)

        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass

    if not creds["ssid"] or not creds["pwd"]:
        raise RuntimeError("Did not parse SSID/PWD from BLE notifications")
    return creds  # type: ignore


class TrailCamClient:
    def __init__(self, local_port: int = LOCAL_PORT, timeout_s: float = 0.25):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", local_port))
        self.sock.settimeout(timeout_s)
        self.camera_addr: Optional[Tuple[str, int]] = None
        self._stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None
        self._seq8 = 0
        self.token_int: Optional[int] = None

    def close(self):
        self._stop.set()
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=1.0)
        self.sock.close()

    def send_raw(self, payload: bytes, addr: Optional[Tuple[str, int]] = None):
        if addr is None:
            if not self.camera_addr:
                raise RuntimeError("Camera addr not known yet")
            addr = self.camera_addr
        self.sock.sendto(payload, addr)

    def send_f1(self, opcode: int, body: bytes = b""):
        payload = bytes([0xF1, opcode]) + struct.pack("!H", len(body)) + body
        self.send_raw(payload)

    def send_beacons(self, count: int = 2):
        for _ in range(count):
            self.send_raw(bytes.fromhex("f1300000"), ("192.168.43.255", DISCOVERY_PORT))
            self.send_raw(bytes.fromhex("f1300000"), ("255.255.255.255", DISCOVERY_PORT))
            time.sleep(0.05)

    def recv(self) -> Optional[Tuple[Tuple[str, int], bytes]]:
        try:
            data, addr = self.sock.recvfrom(65535)
            return addr, data
        except socket.timeout:
            return None

    def learn_camera_port(self, max_wait_s: float = 5.0):
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            got = self.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            self.camera_addr = addr
            return
        raise TimeoutError("Did not see any inbound UDP from camera")

    def start_keepalive(self, interval_s: float = 1.0):
        def loop():
            while not self._stop.is_set():
                try:
                    if self.camera_addr:
                        self.send_f1(0xE0, b"")
                except Exception:
                    pass
                self._stop.wait(interval_s)

        self._keepalive_thread = threading.Thread(target=loop, daemon=True)
        self._keepalive_thread.start()

    def send_cmd_json(self, obj: Dict, art_ver: int = 2, art_typ: int = 1):
        payload_b64 = encrypt_cmd_json(obj)
        art = build_artemis_record(payload_b64, art_ver, art_typ)
        seq = self._seq8 & 0xFF
        self._seq8 = (self._seq8 + 1) & 0xFF
        body = bytes([0xD1, 0x00, 0x00, seq]) + art
        self.send_f1(0xD0, body)

    def handle_incoming_payload(self, data: bytes) -> List[Dict]:
        parsed = unpack_f1(data)
        if not parsed:
            return []
        opcode, body, _ = parsed
        if opcode != 0xD0:
            return []
        return decrypt_artemis_json(body)


# ---- Protocol helpers ----

def unpack_f1(pkt: bytes) -> Optional[Tuple[int, bytes, int]]:
    if len(pkt) < 4 or pkt[0] != 0xF1:
        return None
    opcode = pkt[1]
    blen = struct.unpack("!H", pkt[2:4])[0]
    if len(pkt) < 4 + blen:
        return None
    body = pkt[4 : 4 + blen]
    return opcode, body, blen


def make_ack_body_seq8(seqs8: List[int]) -> bytes:
    seqs = sorted(set(seqs8))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, 0x00, 0x00, count]) + seq16


def make_ack_body_seq16(seqs16: List[int]) -> bytes:
    seqs = sorted(set(seqs16))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, 0x04, 0x00, count]) + seq16


def parse_artemis_records(assembled: bytes):
    out = []
    pos = 0
    while True:
        i = assembled.find(b"ARTEMIS\x00", pos)
        if i == -1:
            break
        if i + 20 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8 : i + 12], "little")
        typ = int.from_bytes(assembled[i + 12 : i + 16], "little")
        ln = int.from_bytes(assembled[i + 16 : i + 20], "little")
        payload = assembled[i + 20 : i + 20 + ln]
        out.append((ver, typ, payload))
        pos = i + 1
    return out


def extract_gallery_records(assembled: bytes, out_dir: Optional[str] = None):
    records = []
    for ver, typ, payload in parse_artemis_records(assembled):
        if len(payload) < 72:
            continue
        header = payload[:72]
        mac = header[:17].decode("ascii", errors="ignore")
        record_id = struct.unpack("<H", header[34:36])[0]
        jpeg_len = struct.unpack("<H", header[36:38])[0]
        jpeg = payload[72 : 72 + jpeg_len]
        records.append((record_id, jpeg_len, ver, typ, mac, jpeg))

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for record_id, jpeg_len, ver, typ, mac, jpeg in records:
            if not jpeg.startswith(b"\xff\xd8\xff"):
                continue
            fname = f"thumb_{record_id}_type{typ}_ver{ver}_{mac.replace(':','')}.jpg"
            path = os.path.join(out_dir, fname)
            with open(path, "wb") as f:
                f.write(jpeg)

    return records


def _pad16(b: bytes) -> bytes:
    pad = (-len(b)) % 16
    if pad:
        b += b"\x00" * pad
    return b


def encrypt_cmd_json(obj: Dict) -> bytes:
    js = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    pt = _pad16(js)
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    enc = cipher.encryptor()
    ct = enc.update(pt) + enc.finalize()
    return base64.b64encode(ct)


def decrypt_cmd_b64(b64: bytes) -> Optional[Dict]:
    try:
        ct = base64.b64decode(b64)
    except Exception:
        return None
    if len(ct) % 16 != 0:
        return None
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    pt = pt.rstrip(b"\x00")
    if not pt.startswith(b"{"):
        return None
    try:
        return json.loads(pt.decode("utf-8", errors="replace"))
    except Exception:
        return None


def build_artemis_record(payload_b64: bytes, ver: int, typ: int) -> bytes:
    header = b"ARTEMIS\x00"
    header += struct.pack("<I", ver)
    header += struct.pack("<I", typ)
    header += struct.pack("<I", len(payload_b64))
    return header + payload_b64


def decrypt_artemis_json(body: bytes) -> List[Dict]:
    out: List[Dict] = []
    # D0 body may begin with D1 header
    if len(body) >= 4 and body[0] == 0xD1:
        body = body[4:]
    records = parse_artemis_records(body)
    for _ver, _typ, payload in records:
        obj = decrypt_cmd_b64(payload)
        if obj:
            out.append(obj)
    return out


def login_and_get_token(
    client: TrailCamClient,
    username: str,
    password: str,
    timeout_s: float = 5.0,
    retries: int = 3,
) -> Optional[int]:
    login_obj = {
        "cmdId": 0,
        "usrName": username,
        "password": password,
        "needVideo": 0,
        "needAudio": 0,
        "utcTime": int(time.time()),
        "supportHeartBeat": True,
    }
    for _ in range(retries):
        client.send_cmd_json(login_obj, art_ver=2, art_typ=1)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            got = client.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            objs = client.handle_incoming_payload(data)
            for obj in objs:
                if obj.get("cmdId") == 0 and "token" in obj:
                    return int(obj["token"])
    return None


def send_full_json_flow(
    client: TrailCamClient,
    token: int,
    page: int = 0,
    per_page: int = 45,
    listen_s: float = 8.0,
    repeats: int = 3,
):
    time.sleep(0.3)
    dev_info = {"cmdId": 512, "token": token}
    media_list = {"cmdId": 768, "itemCntPerPage": per_page, "pageNo": page, "token": token}

    # send a few times like the app does
    for i in range(repeats):
        print(f"TX JSON: dev info (attempt {i+1}/{repeats})")
        client.send_cmd_json(dev_info, art_ver=2, art_typ=2)
        time.sleep(0.05)
        print(f"TX JSON: media list (attempt {i+1}/{repeats})")
        client.send_cmd_json(media_list, art_ver=2, art_typ=4)
        time.sleep(0.1)

    # listen for any decrypted JSON responses
    end = time.time() + listen_s
    while time.time() < end:
        got = client.recv()
        if not got:
            continue
        addr, data = got
        if addr[0] != CAMERA_IP:
            continue
        parsed = unpack_f1(data)
        if parsed:
            opcode, body, _ = parsed
            if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                seq8 = body[3]
                client.send_f1(0xD1, make_ack_body_seq8([seq8]))
                # show ARTEMIS metadata for visibility
                for ver, typ, payload in parse_artemis_records(body[4:]):
                    print(f"RX ARTEMIS ver={ver} typ={typ} len={len(payload)}")
            elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x04:
                seq16 = (body[2] << 8) | body[3]
                client.send_f1(0xD1, make_ack_body_seq16([seq16]))
                for ver, typ, payload in parse_artemis_records(body[4:]):
                    print(f"RX ARTEMIS ver={ver} typ={typ} len={len(payload)}")

        objs = client.handle_incoming_payload(data)
        for obj in objs:
            print("RX JSON:", obj)


async def main():
    parser = argparse.ArgumentParser(
        description="TrailCam client: BLE wake, connect, JSON login, and media list."
    )
    parser.add_argument(
        "--ble-address",
        default=DEFAULT_BLE_ADDRESS,
        help="BLE MAC address of the camera (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-ble",
        action="store_true",
        help="Skip BLE wake/credentials. Assumes you are already connected to the camera AP.",
    )
    parser.add_argument(
        "--ifname",
        default=WIFI_IFNAME,
        help="Wi-Fi interface to use (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=LOCAL_PORT,
        help="Local UDP port to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--thumbs",
        action="store_true",
        help="(Legacy) write thumbnails to out/thumbnails (legacy flow removed)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging of incoming packets",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Perform JSON login only and exit",
    )
    parser.add_argument(
        "--json-flow",
        action="store_true",
        help="After login, send dev info (cmdId=512) and media list (cmdId=768)",
    )
    args = parser.parse_args()

    if not args.skip_ble:
        creds = await ble_wake_and_get_creds(args.ble_address)
        ssid = creds["ssid"]
        pwd = creds["pwd"]

        if not ssid or not pwd:
            raise SystemExit("SSID/PWD not returned from BLE wake")

        print(f"SSID={ssid}")
        print("Waiting for SSID to appear in scans...")
        for t in range(1, 61):
            nmcli_rescan()
            ssids = nmcli_list_ssids()
            if ssid in ssids:
                print(f"SSID visible after {t}s")
                break
            await asyncio.sleep(1)
        else:
            raise SystemExit("SSID not visible after 60s")

        print("Connecting to camera Wi-Fi...")
        if not nmcli_connect(ssid, pwd, args.ifname):
            raise SystemExit("nmcli connect failed")

    # wait for DHCP
    for _ in range(30):
        if wifi_has_camera_ip(args.ifname):
            break
        await asyncio.sleep(0.2)
    if not wifi_has_camera_ip(args.ifname):
        raise SystemExit("Connected but did not get 192.168.43.x address")

    print("Connected to camera AP. Starting UDP session...")
    client = TrailCamClient(local_port=args.port)
    try:
        # send initial discovery beacons
        client.send_beacons(count=4)

        # learn camera port
        client.learn_camera_port()
        print(f"Camera addr: {client.camera_addr}")
        # periodic beacons during prelude
        def beacon_loop():
            end = time.time() + 8.0
            while time.time() < end:
                try:
                    client.send_beacons(count=1)
                except Exception:
                    pass
                time.sleep(0.5)

        t_beacon = threading.Thread(target=beacon_loop, daemon=True)
        t_beacon.start()

        # start keepalive loop
        client.start_keepalive(interval_s=1.0)

        # prelude: wait for handshake/status and echo 0x41/0x42
        seen_ops = {}
        start = time.time()
        while time.time() - start < 3.0:
            got = client.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            parsed = unpack_f1(data)
            if not parsed:
                continue
            opcode, body, _ = parsed
            seen_ops[opcode] = seen_ops.get(opcode, 0) + 1
            if args.debug:
                print(f"RX opcode=0x{opcode:02x} len={len(body)}")
            if opcode in (0x41, 0x42):
                # echo back twice like app
                client.send_f1(opcode, body)
                time.sleep(0.02)
                client.send_f1(opcode, body)
            elif opcode == 0xE0:
                client.send_f1(0xE1, b"")
            elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                # ACK small seq8 chunks even during handshake
                seq8 = body[3]
                ack = make_ack_body_seq8([seq8])
                client.send_f1(0xD1, ack)

        if args.debug:
            print("Handshake opcodes seen:", {hex(k): v for k, v in seen_ops.items()})

        token = login_and_get_token(client, "admin", "admin")
        if token is None:
            print("Login token not found yet.")
        else:
            client.token_int = token
            print(f"Login token: {token}")
            if args.login_only:
                return
            if args.json_flow:
                send_full_json_flow(client, token)

        large_chunks: Dict[int, bytes] = {}
        small_chunks: Dict[int, bytes] = {}

        def pump_incoming(duration_s: float):
            end = time.time() + duration_s
            while time.time() < end:
                got = client.recv()
                if not got:
                    continue
                addr, data = got
                if addr[0] != CAMERA_IP:
                    continue
                parsed = unpack_f1(data)
                if not parsed:
                    continue
                opcode, body, _ = parsed
                if args.debug:
                    print(f"RX opcode=0x{opcode:02x} len={len(body)}")
                if opcode in (0x41, 0x42):
                    client.send_f1(opcode, body)
                elif opcode == 0xE0:
                    client.send_f1(0xE1, b"")
                elif opcode == 0xD0 and len(body) >= 4:
                    if args.debug and len(body) >= 1000:
                        print("D0 large head:", body[:8].hex())
                    if body[0] == 0xD1 and body[1] == 0x00:
                        seq8 = body[3]
                        small_chunks.setdefault(seq8, body[4:])
                        client.send_f1(0xD1, make_ack_body_seq8(list(small_chunks.keys())))
                    elif body[0] == 0xD1 and body[1] == 0x04:
                        seq16 = (body[2] << 8) | body[3]
                        large_chunks.setdefault(seq16, body[4:])
                        client.send_f1(0xD1, make_ack_body_seq16(list(large_chunks.keys())))

        # Legacy D0 packet sequence removed; JSON flow above is the only supported path now.

    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
