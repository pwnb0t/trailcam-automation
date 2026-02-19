# TrailCam Automation Status

## Works Now
- BLE wake and retrieve AP credentials (`ssid`/`pwd`).
- Join camera AP via `nmcli`.
- UDP handshake + login to obtain `login_token_u32`.
- Media list (`cmdId=768`).
- Photo download (`cmdId=1285`) and reconstruction of full-resolution JPEG.
- Video download/playback (`cmdId=769` start, `D0 subtype=0x02` decrypt, `cmdId=770` stop) and reconstruction of MP4 (H.264 + AAC).
- Reverse engineered commands for delete (`cmdId=773`) and SD format (`cmdId=518`) from new pcaps.

## Next Steps
??

## Potential Steps
* Tests
    * Add offline “replay from pcap” tests for parsers and reassembly to prevent regressions in photo/video parsing.
    * Add other tests to prevent regressions. Highest priority would be around


## Ultimate Goal
- From my two trailcams, I need all the media (photos and videos) downloaded periodically and then deleted.
- The downloaded media organized on my NAS.


