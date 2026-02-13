Summaries of certain pcap files.

# trailcam_1.pcap 
trailcam_1.pcap is a capture of packets from the start of connecting to the trailcam, then refreshing the gallery, downloading a photo, downloading a video, etc... and necessarily in that order (I don't remember the order).

# trailcam_2-*.pcap
trailcam_2-* files are isolated captures of traffic.

# trailcam_3-2-refresh.pcap
trailcam_3-2-refresh.pcap is just another capture of the refresh operation.


# trailcam_8-3-view-and-download-video.pcap

From pcap/trailcam_8-3-view-and-download-video.pcap, the app’s start playback request (cmdId=769) is in frame 1715 and decrypts to:
  - fileType: 1 (video)
  - dirNum: 102
  - mediaNum: 935
  - sessionNo: 37946

I stored the original DSCF0935.MPG in the folder as a sibling.


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

I have now stored DSCF0938.JPG in this folder along side.


# trailcam_10-connect-thru-download-photo.pcap

Same steps as trailcam_9-connect-thru-download-photo.pcap

Photo downloaded from the app: DSCF0940.JPG
Stored: /storage/emulated/0/DCIM/TrailCam Go/TrailCam Go-Images/2026-02-11_12.51.46.448_CC164BCE.jpg
Size: 5.4 MB
Pixels: 5120x2880 (14.7 MP)

I have now stored DSCF0940.JPG in this folder along side.
