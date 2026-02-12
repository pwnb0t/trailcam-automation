# JSON Commands

The control plane uses encrypted JSON carried in ARTEMIS records (typically over `D0 subtype=0x00`).

## Login (`cmdId=0`)

Client sends:
- `cmdId=0`
- `usrName="admin"`
- `password="admin"`
- plus flags like `supportHeartBeat`

Camera replies with:
- `cmdId=0`
- `result=0`
- `token=<u32>`

We refer to this as `login_token_u32`. It is not the same as the older “32-byte token” term we used early on.

## Heartbeat (`cmdId=525`)

Client periodically sends `{"cmdId":525}` during longer operations (media list, downloads).

## Device Info (`cmdId=512`)

Client sends:
- `{"cmdId":512,"token":<login_token_u32>}`

Response includes device fields (varies by firmware).

## Media List (`cmdId=768`)

Client sends:
- `{"cmdId":768,"itemCntPerPage":45,"pageNo":0,"token":<login_token_u32>}`

Response includes:
- `mediaFiles`: list of entries
- fields: `fileType`, `mediaDirNum`, `mediaNum`, optional `mediaId`, optional `mediaTime`, `durationMs` for videos

## Thumbnails (`cmdId=772`)

Client sends:
- `{"cmdId":772,"thumbnailReqs":[{"fileType":0/1,"dirNum":...,"mediaNum":...}, ...],"token":<login_token_u32>}`

Response data often arrives on a large bulk stream (commonly `D0 subtype=0x04`) and is parsed as ARTEMIS records that embed a thumbnail JPEG.

## File Download (`cmdId=1285`)

Client sends:
- `{"cmdId":1285,"downloadReqs":[{"fileType":0/1,"dirNum":...,"mediaNum":...}],"token":<login_token_u32>}`

Camera ACK (JSON) looks like:
- `{"cmdRet":0,"result":0,"cmdId":1285}`

The actual media payload is then delivered via bulk streams (not inside that JSON).

