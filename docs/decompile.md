# Decompile Tooling Notes

This file is a quick reference for local APK/native reverse-engineering setup.

## JADX

Install (Ubuntu example):
```bash
sudo apt install -y zip
JADX_VERSION=$(curl -s "https://api.github.com/repos/skylot/jadx/releases/latest" | grep -Po '"tag_name": "v\\K[0-9.]+"')
curl -Lo jadx.zip "https://github.com/skylot/jadx/releases/latest/download/jadx-${JADX_VERSION}.zip"
unzip jadx.zip -d jadx-temp
sudo mkdir -p /opt/jadx/bin
sudo mv jadx-temp/bin/jadx /opt/jadx/bin
sudo mv jadx-temp/bin/jadx-gui /opt/jadx/bin
sudo mv jadx-temp/lib /opt/jadx
echo 'export PATH=$PATH:/opt/jadx/bin' | sudo tee -a /etc/profile
source /etc/profile
jadx --version
rm -rf jadx.zip jadx-temp
```

## Ghidra (headless)

If installed via snap, `analyzeHeadless` is commonly here:
```bash
/snap/ghidra/current/ghidra_12.0_PUBLIC/support/analyzeHeadless
```

Example usage:
```bash
/snap/ghidra/current/ghidra_12.0_PUBLIC/support/analyzeHeadless \
  /tmp/ghproj trailcam \
  -import apk/apk_unzip_v2_armeabi/lib/armeabi-v7a/libArLink.so
```

## Notes
- Decompiled Java sources live under `apk/jadx_full_v2/sources/`.
- Native protocol behavior is primarily in `libArLink.so`.
