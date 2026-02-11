Summaries of certain pcap files.



# trailcam_9-connect-thru-download-photo.pcap
Closed out TrailCam Go app.
Created a new photo on the trailcam to ensure that it would be a completely new photo that the phone has not yet seen.

Started tcpdump with:
adb shell su -c "/data/local/tmp/tcpdump -i wlan0 -s 0 -p -n -vv -w /sdcard/caps/trailcam_9-connect-thru-download-photo.pcap"

Opened TrailCam Go app
Connected to trailcam.
Waited for connection and for the gallery to be refreshed.
Tapped on the new photo, which does a preview.
Tapped to download the photo.
Waited around ~30 seconds after the download was complete just to be sure.
Went to the photos app, viewed the photo, and recorded information about the photo.
Stopped tcpdump.

Photo downloaded from the app: DSCF0938.JPG
Stored: /storage/emulated/0/DCIM/TrailCam Go/TrailCam Go-Images/2026-02-11_11.51.29.646_4B5805A2.jpg
Size: 5.7 MB
Pixels: 5120x2880 (14.7 MP)

Photo is stored in this folder along side trailcam_9 pcap.

