# trailcam-automation

Reverse engineering a bluetooth Trail Cam.

I'm using this camera:
https://www.amazon.com/MAXDONE-Bluetooth-5200mAh-Rechargeable-Activated/dp/B0DHRYCZKF
"MAXDONE Solar Trail Camera WiFi Bluetooth - 48MP 30fps Game Camera with 5200mAh Rechargeable Battery, 0.1s Trigger Speed Motion Activated Trail Cam IP66 with 32GB TF Card for Wildlife Monitoring"

Used some of the info of the previous dude's article around hacking his BLE trail cam:
https://geekitguide.com/wifi-ble-trailcam-investigation-part-1/

This got me part of the way there, but the way the info on my cam worked was not quite the same.
I needed to use a rooted android device to get the BT wakeup command. I also had to use tcpdump on a rooted android device to capture the wifi UDP traffic. I was not able to sniff the traffic.


Anyway, not done yet, unless I am and I didn't update this file. But that totally wouldn't happen.
I've probably left some passwords and stuff in here so uhh, don't come to my house and hack my camera lol. (though if you actually understand all that's in this repo then you'll know that pw doesn't matter)


-----

## pcap/ dir files
These are all captures of packets from a rooted Android device using the TrailCam Go app.

trailcam_1.pcap is a capture of packets from the start of connecting to the trailcam, then refreshing the gallery, downloading a photo, downloading a video, etc... and necessarily in that order (I don't remember the order).

trailcam_2-* files are isolated captures of traffic.

trailcam_3-2-refresh.pcap is just another capture of the refresh operation.


## ble_wake_and_get_creds.py
Original script written that is able to wake the TrailCam and get the AP credentials. It now has some work around trying to get the first communication with the TrailCam to work but that's not working yet.

## trailcam_refresh_gallery.py
This was an erroneous attempt to jump ahead in the communication of the TrailCam.