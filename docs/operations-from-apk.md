# Operations From APK

This is a cleaned list of communication operations defined in the decompiled app (`apk/jadx_full_v2/...`), primarily from:
- `com/xlink/arlink/ArCommandId.java`
- `com/xlink/arlink/Ar*Command.java`
- `com/xlink/arlink/ArLinkApi.java`

## Core Session / Transport
- `cmdId=0` login (`EC_CMD_ID_LOGIN`)
- `cmdId=1` logout (`EC_CMD_ID_LOGOUT`)
- native login/logout entrypoints also exist via `ArLinkApi.logIn(...)` / `ArLinkApi.logOut(...)`

## Gallery / Media
- `cmdId=768` get media list (`EC_CMD_ID_GET_MEDIA_LIST`)
- `cmdId=772` get thumbnails (`EC_CMD_ID_GET_THUMBNAILS`)
- `cmdId=1285` start file download (`EC_CMD_ID_START_FILE_DOWNLOAD`)
- `cmdId=1286` stop file download (`EC_CMD_ID_STOP_FILE_DOWNLOAD`)
- `cmdId=769` start play record (`EC_CMD_ID_START_PLAY_RECORD`)
- `cmdId=770` stop play record (`EC_CMD_ID_STOP_PLAY_RECORD`)
- `cmdId=771` play-record control (`EC_CMD_ID_CMD_PLAY_RECORD`) (constant defined; no direct command wrapper identified)
- `cmdId=773` delete single media (`EC_CMD_ID_DELETE_MEDIA`)
- `cmdId=774` delete all media (`EC_CMD_ID_DELETE_MEDIA_ALL`)

## Live View / Capture / Audio
- `cmdId=258` start AV (`EC_CMD_ID_START_AV`)
- `cmdId=259` stop AV (`EC_CMD_ID_STOP_AV`)
- `cmdId=641` trigger snap (`EC_CMD_ID_TRIGGER_SNAP`)
- `cmdId=643` trigger record (`EC_CMD_ID_TRIGGER_RECORD`)
- `cmdId=644` stop record (`EC_CMD_ID_STOP_RECORD`)
- `cmdId=256` open talk (`EC_CMD_ID_OPEN_TALK`)
- `cmdId=257` close talk (`EC_CMD_ID_CLOSE_TALK`)
- `cmdId=260` start audio (`EC_CMD_ID_START_AUDIO`)
- `cmdId=261` stop audio (`EC_CMD_ID_STOP_AUDIO`)

## Device Settings / Maintenance
- `cmdId=512` get device info (`EC_CMD_ID_GET_DEV_INFO`)
- `cmdId=513` set device info (`EC_CMD_ID_SET_DEV_INFO`)
- `cmdId=514` change password (`EC_CMD_ID_CHANGE_PASSWORD`)
- `cmdId=515` video mirror (`EC_CMD_ID_VIDEO_MIRROR`)
- `cmdId=516` video flip (`EC_CMD_ID_VIDEO_FLIP`)
- `cmdId=517` restore factory (`EC_CMD_ID_RESTORE_TO_FACTORY`)
- `cmdId=518` format SD card (`EC_CMD_ID_FORMAT_SD_CARD`)
- `cmdId=522` red lamp (`EC_CMD_ID_RED_LAMP`)
- `cmdId=523` change stream type (`EC_CMD_ID_CHANGE_STREAM_TYPE`)
- `cmdId=1024` firmware upgrade (`EC_CMD_ID_FW_UPGRADE`)

## Factory / Diagnostics / Logs
- `cmdId=1280` set factory data (`EC_CMD_ID_SET_FACTORY_DATA`)
- `cmdId=1281` start sleep (`EC_CMD_ID_START_SLEEP`)
- `cmdId=1282` get log file list (`EC_CMD_ID_GET_LOG_FILE_LIST`)
- `cmdId=1283` get log config (`EC_CMD_ID_GET_LOG_CONFIG`)
- `cmdId=1284` set log config (`EC_CMD_ID_SET_LOG_CONFIG`)
- `cmdId=1288` set factory NV mode (`EC_CMD_ID_SET_FACTORY_TEST_NV_MODE`)
- `cmdId=1289` start factory test bluetooth (`EC_CMD_ID_START_FACTORY_TEST_BLUETOOTH`)
- `cmdId=1290` stop factory test bluetooth (`EC_CMD_ID_STOP_FACTORY_TEST_BLUETOOTH`)
- `cmdId=1291` start factory test scan QR (`EC_CMD_ID_START_FACTORY_TEST_SCAN_QR`)
- `cmdId=1292` stop factory test scan QR (`EC_CMD_ID_STOP_FACTORY_TEST_SCAN_QR`)

## Mapping To Current Project Goals
- List gallery: `768`
- Get thumbnails: `772`
- Download photo/file: `1285`
- Video playback/download flow: `769` + `770`
- Delete single item: `773`
- Delete all (APK operation): `774`
- Format SD card: `518`

Notes:
- In this repo, `--delete-media-all` currently maps to format (`cmdId=518`) in runtime flow.
- Not every APK-defined command is implemented in this project.
