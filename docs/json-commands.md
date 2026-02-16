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
  - Note: camera returns an error for `itemCntPerPage >= 50` ("need less than 50").

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

## Start Play Record (`cmdId=769`)

Client sends:
- `{"cmdId":769,"fileType":1,"dirNum":...,"mediaNum":...,"sessionNo":...,"token":<login_token_u32>}`

Camera replies with:
- `{"cmdId":769,"startPbRet":0,"videoWidth":1920,"videoHeight":1080,"totalFrame":304,"totalTime":10333,"result":0}`

The actual media payload is then delivered via bulk streams (commonly `D0 subtype=0x02`).

## Stop Play Record (`cmdId=770`)

Client sends:
- `{"cmdId":770,"token":<login_token_u32>}`

## Delete Media (`cmdId=773`)

Observed in:
- `pcap/trailcam_11-2-delete-photo2.pcap`
- `pcap/trailcam_11-3-delete-video.pcap`

Client sends:
- `{"cmdId":773,"fileType":0/1,"dirNum":...,"mediaNum":...,"token":<login_token_u32>}`

Camera replies:
- `{"delRet":0,"result":0,"cmdId":773}` on success.

## Format SD Card (`cmdId=518`)

Observed in:
- `pcap/trailcam_12-format.pcap`

Client sends:
- `{"cmdId":518,"token":<login_token_u32>}`
- Commonly sent more than once (retries/redundant sends observed).

Camera replies:
- `{"errorMsg":"Success","sdTotalMB":...,"sdFreeMB":...,"formatRet":0,"result":0,"cmdId":518}` on success.
