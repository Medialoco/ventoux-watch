# Mont Serein

*[Version française](README.md)*

#FREETECHNORADIO

A Raspberry Pi 5 on a desk in Los Angeles watches the webcam at the Mont Serein pass, 1,389 m up Mont Ventoux. One frame a second. OpenCV finds what moved, YOLO names the crop, and the Pi rebuilds the picture: the photograph, the rectangle, the overlays, the music. The watch is the work. The stream is the show.

On 6 October 2026 at 08:49 Paris time the Mont Serein playlist closed (`#EXT-X-ENDLIST`, last segment at 06:49:04 UTC). Since then Cannes is the backup: the municipal live on Boulevard du Midi, aimed at Les plages du Midi. The Ventoux playlist is read again every 60 s. End of list, or a last segment older than 120 s, and the picture becomes Cannes, opened 60 s behind the live edge. When Mont Serein returns, the next frame goes back without restarting the YouTube output. While it is up, Cannes appears in turn, 90 s, first 75 s after open, then 900 s after it ends. Once, the Ventoux page with Cannes in its place: the right card becomes Cannes, the counter stays at the bottom right, and the disc is the Hôtel Le Splendid. The next time, one row: Los Angeles, Mont Serein, Beaumont, Cannes, and the right cartouche for Cannes. The cards keep their width, the two pictures are narrower, and each picture keeps its frame. The ratios stay on Los Angeles and Beaumont. The Cannes decoder runs only while that picture is on screen. In the row, #FREETECHNORADIO sits under each picture, and the wire between the two sides is left out.

Mont Serein has a distance grid from OpenStreetMap, from node [6410397171](https://www.openstreetmap.org/node/6410397171). Cannes is node [14255983894](https://www.openstreetmap.org/node/14255983894), at 43.5467593, 6.9754344, bearing 190°, on a pole on Boulevard du Midi. The node has no height, and no distance grid has been fitted: nothing has been matched between the picture and the map. The frame is cut into road (a short piece, bottom right), sidewalk, beach, sea and sky. Sea and beach are not sent to YOLO. A change over 35% of the frame is dropped. Bear, carpet, submarine, piste, elephant and buildings are drawn on the Mont Serein picture, and also when Cannes fills the frame. The page’s 3D view opens this same node, beside the Mont Serein one.

The watch sees a lot of motion. The model is asked only from time to time, and not at all at night once the crest has gone: the motion rectangle stays, the name would be fog. A published class counts as soon as it is named. The green cheer, a good catch, waits for 0.60. Under each card, three digits show that day’s ratio times one hundred, with the raw count in small type. Los Angeles is on the left, Beaumont-du-Ventoux on the right. A class counts for both. Each side returns to 000 at its own midnight, and the two midnights are not the same hour.

Watcher **v0.6.38**.

The live picture is on [YouTube](https://www.youtube.com/watch?v=OwLQpSJLs-I). The site is [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/). The ways the picture changes are written there, each one from the code that is running.

![Mont Serein at night: roundabout, road, slope and the summit beacon](docs/mont-serein-nuit.png)

*24 September 2026, 23:41 Paris time. The photograph was taken at 14:41 in Los Angeles.*

The music is free, around the clock, with the licence on screen for every track. It comes from [Dogmazic](https://play.dogmazic.net/), and the stream’s playlist is [public](https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id=4803). Fourteen hours and thirteen minutes, one hundred and fifty-eight tracks. Four hours of that are the album [Mont Serein 002](https://play.dogmazic.net/albums.php?action=show&album=11242), written for this project by [thepriben](https://play.dogmazic.net/artists.php?action=show&artist=7208).

Sizes are read in metres, from the camera’s pose and a terrain model. Above 5.5 m it is not a car, whatever the network says. Below two metres it is not a bus. When the measurement cannot be trusted, it is thrown away. Zero means we do not know.

This is a camera and a curiosity. Nothing it says is an alarm, and nothing it says should be acted upon.

## Running it

On the Mac:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-export.txt
.venv/bin/python scripts/export_model.py
.venv/bin/python -m unittest discover -s tests -v
```

`models/yolo11s.onnx` ships with the code. The Pi does not install PyTorch.

On the Pi, one command, safe to run again:

```bash
ssh ventoux 'bash -s' < scripts/pi_install.sh
```

Secrets are not in the repository. `config/local.json` is copied by hand, once, and git ignores it. OpenSky and Drive are optional. The hardware, the card, the disk and the watchdog are in [`infra.md`](infra.md). Outages are in [`incidents.md`](incidents.md). Where this is going is in [`plan.md`](plan.md).
