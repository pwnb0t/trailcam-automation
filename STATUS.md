# TrailCam Automation Status

## Works Now
- BLE wake and retrieve AP credentials (`ssid`/`pwd`).
- Join camera AP via `nmcli`.
- UDP handshake + login to obtain `login_token_u32`.
- Media list (`cmdId=768`).
- Photo download (`cmdId=1285`) and reconstruction of full-resolution JPEG.
- Video download/playback (`cmdId=769` start, `D0 subtype=0x02` decrypt, `cmdId=770` stop) and reconstruction of MP4 (H.264 + AAC).

## Next Steps
* Need an orchestration script (trailcam_sync.py)
  * Resumable state file (perhaps a manifest of items to download and what is downloaded)

* trailcam_sync.py architecture; Option 1
  * Utilizes client_runner.py
  * Load config
  * Create/resume state file (sync_state.yaml or sync_state.json)
    * Determine which is better for storing the state of the app
  * State: download
    * If session.staging_manifest is None
      * Build a session.staging_manifest of items currently in staging dir (cfg.paths.media_out_dir)
    * If session.trailcam_manifest is None
      * Build a session.trailcam_manifest of items on the trailcam
    * Determine which items are missing from the staging dir and download them from the trailcam using client_runner.py
    * client_runner.py should download pages of items and skip items that are already downloaded itself
    * set state=verify and clear session.staging_manifest and session.trailcam_manifest
  * State: verify
    * If session.staging_manifest is None
      * Build a session.staging_manifest of items currently in staging dir (cfg.paths.media_out_dir)
    * If session.trailcam_manifest is None
      * Build a session.trailcam_manifest of items on the trailcam
    * If there are any non-downloaded items (items on trailcam_manifest that are not on staging_manifest)
      * move back to state=download so they will get copied.
    * If all items are downloaded, then set state=clear and continue
  * State: clear
    * If session.trailcam_manifest is None, error out
      * This would be an unrecoverable state without human intervention -- but I might need to see how it gets in this state to diagnose
    * I have not implemented delete photo or format disk, so this is not ready. But I'm going to assume I will do the format because it is much faster
    * For now, print "TODO - format cam: <alias>"
    * move to state=organize
  * State: organize
    * Ensure session.staging_manifest is not None, otherwise error out
    * Moves items from staging dir (cfg.paths.media_out_dir, /mnt/trailcam/staging) to final dir (/mnt/trailcam/media/YYYY-WW/<alias>_YYYYMMDD_HHMMSS_<dirNum>-<mediaNum>.<jpg|mp4>)
      * e.g. /mnt/trailcam/staging/back/102/media940.jpg -> /mnt/trailcam/media/2026-01/back_20260101_144523_102-940.jpg
    * Rather than overwriting, we probably ought to make a `/mnt/trailcam/dupes` folder and dump anything in there in some sort of organized fashion
      * /mnt/trailcam/dupes/<todays-run-datetime>/102/media940.jpg

# sync_state arch
  cameras:
    <alias>:
      status: download, verify, clear, organize
    back
    front



## Potential Steps
* Connection logic (partly done I think in connection.py, but I'm not sure I see it being used)
  * Currently does BLE wake -> AP join -> UDP handshake -> login.
  * If already on AP, then it skips BLE wake and AP join. But it is possible the trailcam has gone to sleep and we receive "TimeoutError: Did not see any inbound UDP from camera"
  * In this case, it should instead go back to BLE wake.
* File structure and naming/renaming
    * Download files to staging. Move files from staging to media and rename
    * front_YYYYMMDD_HHMMSS.jpg, back_20260213_132127.mp4, ...
    * Split by week: /mnt/trailcam/media/YYYY-WW/front_YYYYMMDD_HHMMSS.jpg
    * Week cutoff should be Sundays at 8am. (I'll be running the script daily at 10am)

* Code reorg
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

Requires `config.yaml` (see `config.example.yaml`) with a `cameras:` entry for the alias you pass.

ran:
python3 client_runner.py --camera back --list-media-all

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
