# TrailCam Automation Status

## Works Now
- BLE wake and retrieve AP credentials (`ssid`/`pwd`).
- Join camera AP via `nmcli`.
- UDP handshake + login to obtain `login_token_u32`.
- Media list (`cmdId=768`) and thumbnails (`cmdId=772`).
- Photo download (`cmdId=1285`) and reconstruction of full-resolution JPEG.
- Video download/playback (`cmdId=769` start, `D0 subtype=0x02` decrypt, `cmdId=770` stop) and reconstruction of MP4 (H.264 + AAC).

## Next Steps
1. Config
Remove --page-no from config.yaml

Change --download-photo and --download-video to be --download-single MEDIA_NUM (remove --media-num)
--dir-num should default to 100

Check how --list-max-pages works. Does it force listing 200 or does it know when to stop?

rename the "defaults" section

2. Use alias (front/back, or whatever is defined in config.yaml) to connect to camera instead of SSID or MAC.

3. Do CONNECT_D0_PACKETS and REFRESH_D0_PACKETS still make sense in constants? Do we still need this as constants? Are they not reverse engineered to be determined?

4. Docs and Cleanup
Update docs to reflect current architecture:
- CLI/config parsing now lives in `src/config.py` (not `src/runner_inputs.py`).
- Commands own behavior; flows should trend toward packet-level helpers.




## Potential Steps
* Connection logic (partly done I think in connection.py, but I'm not sure I see it being used)
  * Currently does BLE wake -> AP join -> UDP handshake -> login.
  * If already on AP, then it skips BLE wake and AP join. But it is possible the trailcam has gone to sleep and we receive "TimeoutError: Did not see any inbound UDP from camera"
  * In this case, it should instead go back to BLE wake.
* /mnt/trailcam is hooked up.
    * Need to send files to /mnt/trailcam/staging then the final output to /mnt/trailcam/media
* Need an orchestration script (trailcam_sync.py)
    * Resumable state file (perhaps a manifest of items to download and what is downloaded)
* File structure and naming/renaming
    * Download files to staging. Move files from staging to media and rename
    * front_YYYYMMDD_HHMMSS.jpg, back_20260213_132127.mp4, ...
    * Split by week: /mnt/trailcam/media/YYYY-WW/front_YYYYMMDD_HHMMSS.jpg
    * Week cutoff should be Sundays at 8am. (I'll be running the script daily at 10am)

* Code reorg
    * Rename trailcam_client.py to trailcam_client_runner.py
    * Add trailcam_sync.py (orchestrator)
    * All the trailcam_client related files go in src/client/
    * All the trailcam_sync related files go in src/sync/
    * Could also have src/common/ or just better named dirs as we go.

* Tests
    * Add offline “replay from pcap” tests for parsers and reassembly to prevent regressions in photo/video parsing.
    * Add other tests to prevent regressions. Highest priority would be around


## Ultimate Goal
- From my two trailcams, I need all the media (photos and videos) downloaded periodically and then deleted.
- The downloaded media organized on my NAS.


## Docs
- `docs/overview.md`
- `docs/flows.md`
- `docs/opcodes.md`
- `docs/packet-format.md`
- `docs/json-commands.md`
- `docs/download-photo.md`
- `docs/download-video.md`
- `pcap/details.md`


-----

# quick testing note

ran:
python3 trailcam_client.py --ssid TrailCam_5DBD --list-media-all

appeared to work and get all contents after quite some time (10+ minutes?)
more output than the terminal buffer stored, but here's the tail end:

```
...
  dir=100 media=14 fileType=0 name= time=1768489956 durMs=
  dir=100 media=13 fileType=1 name= time=1768489962 durMs=10300
  dir=100 media=12 fileType=0 name= time=1768489920 durMs=
  dir=100 media=11 fileType=1 name= time=1768489926 durMs=10333
  dir=100 media=10 fileType=0 name= time=1768489824 durMs=
  dir=100 media=9 fileType=1 name= time=1768489830 durMs=10333
  dir=100 media=8 fileType=0 name= time=1768489790 durMs=
  dir=100 media=7 fileType=1 name= time=1768489796 durMs=10300
  dir=100 media=6 fileType=0 name= time=1768489742 durMs=
  dir=100 media=5 fileType=1 name= time=1768489748 durMs=10333
  dir=100 media=4 fileType=0 name= time=1768488948 durMs=
  dir=100 media=3 fileType=1 name= time=1768488954 durMs=10300
  dir=100 media=2 fileType=0 name= time=1768488742 durMs=
  dir=100 media=1 fileType=1 name= time=1768488748 durMs=10320
```
