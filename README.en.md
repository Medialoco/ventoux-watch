# Mont Serein

*[Version française](README.md)*

#FREETECHNORADIO

A Raspberry Pi 5 on a desk in Los Angeles watches the webcam at the Mont Serein pass, 1,389 m up Mont Ventoux. One frame a second. OpenCV finds what moved, YOLO names the crop, and the Pi rebuilds the picture: the photograph, the rectangle, the overlays, the music. The watch is the work. The stream is the show.

The watch sees a lot of motion. A class is published, a good catch, only when it is sure enough. The number on each card is those sure catches per hundred motions. Los Angeles is on the left, Beaumont-du-Ventoux on the right. A catch counts for both. Each side resets at its own midnight, and the two midnights are not the same hour.

The live picture is on [YouTube](https://www.youtube.com/watch?v=OwLQpSJLs-I). The site is [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/). Twenty ways the picture changes are written there, each one from the code that is running.

![Mont Serein at night: roundabout, road, slope and the summit beacon](docs/mont-serein-nuit.png)

*24 September 2026, 23:41 Paris time. The photograph was taken at 14:41 in Los Angeles.*

The music is free, around the clock, with the licence on screen for every track. It comes from [Dogmazic](https://play.dogmazic.net/), and the stream’s playlist is [public](https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id=4803). Fourteen hours, one hundred and fifty-three tracks. Four of those hours are the album [Mont Serein](https://play.dogmazic.net/albums.php?action=show&album=11242), written for this slope by [thepriben](https://play.dogmazic.net/artists.php?action=show&artist=7208).

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
