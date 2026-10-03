# Mont Serein — a computer watching a mountain road

*[Version française](README.md) · Live stream: [YouTube](https://www.youtube.com/watch?v=OwLQpSJLs-I) · Site: [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/)*

A computer watches a mountain road and tries to say what just went past.

The camera looks down on the Mont Serein pass, at 1,389 m on Mont Ventoux, in
Provence. One frame a second goes to a Raspberry Pi 5 sitting on a desk in Los
Angeles. The Pi finds what moved, cuts that patch out of the picture, asks a
small neural network what it is, and then — this is the part that takes the
work — decides whether the answer is worth believing.

The aim is everything that moves. Cars, vans and walkers today. Aircraft
overhead, cross-checked against live flight data. Birds, eventually, which are
the hard ones: fast, small, and shaped like nothing a camera at this distance
can resolve. We are not there yet. When we do not know, the screen says so.

![Mont Serein at night: roundabout, road, slope and the summit beacon](docs/mont-serein-nuit.png)

*24 September 2026, 23:41 Paris time. The photograph was taken at 14:41 in Los Angeles.*

## How it decides

Nothing on screen is a guess dressed up as a fact.

Sizes are measured, not inferred from pixels. The camera's position, bearing,
tilt and field of view were solved against landmarks in the terrain, to about a
hundredth of a radian. From that pose, any patch of the image can be projected
onto a public elevation model and read back in metres. So the watcher does not
ask "does this look like a lorry" — it asks how wide the thing is on the
ground. Above 5.5 m it is not a car, whatever the network says. Below two
metres it is not a bus.

When the measurement cannot be trusted, it is thrown away rather than used.
Where the camera grazes its own foreground, three metres of error in the
terrain model move a subject by half its own length; past that threshold the
size rules simply switch off and the watcher says less. Zero is the word for
"we do not know", and every size rule is guarded by it.

The same honesty applies to the sun. Its position comes from the date and the
latitude, which is why the overlay can tell you the slope falls into the
mountain's own shadow a good hour before sunset. That is arithmetic, not
weather forecasting.

Naming is held to the same standard elsewhere. An aircraft only gets its
callsign when a single one sits in the OpenSky window, or one clearly lower
than the rest. A coach only takes a Trans'CoVe or ZOU line number when exactly
one service is due within fifteen minutes. Everything else stays in the history
with a plain reading: day or night, the weather, and whatever could honestly be
said about it.

## What it gets wrong

Plenty, and the failures are logged, replayed and counted. `data/observed.jsonl`
keeps the full set of inputs each decision consumed, so any change can be
replayed against the same scenes rather than against a different day's weather.

A favourite: a car filling the frame was read as a *boat*, confidently, at
0.77, while "car" never rose above 0.077. The network had never seen an object
touching all four edges of a picture — there is always scenery around things in
the photographs it was trained on. We had been cropping tight to the subject,
and worse, clipping that crop against the edge of the frame, which jams the
subject into the corner of the canvas. More than half of all road crossings sit
in the bottom fifteen percent of the picture, so more than half were shown in
the worst possible way.

The fix is a square window, sized so the subject always occupies the same share
of the model's view, overflowing the image rather than being cut by it. A
proportion rather than a pixel count, so it holds for a thirty-pixel blob and a
six-hundred-pixel one alike — and for the next camera, whatever its resolution.
Measured over two days of archive: road crossings went from 63% named to 86%,
mean confidence 0.394 to 0.593, thirty-seven gained against one lost.

That is the whole method: find the mistake, find why, fix the cause, measure
again. Never patch the symptom.

## The music

Free music only, 24 hours a day, with the licence on screen for every track.
Nothing here forbids commercial use or editing, because the stream cuts music
into slices and ducks it under a voice — both of which are edits, and taking a
licence seriously means not using the ones that say no.

Most of it comes from [Dogmazic](https://play.dogmazic.net/), a French
free-music library running since 2004. Some of it is written for this channel,
including [Mont Serein 002](https://play.dogmazic.net/albums.php?action=show&album=11242)
by [thepriben](https://play.dogmazic.net/artists.php?action=show&artist=7208),
which is a thing you can do when you run the radio.

## The machine

One Raspberry Pi 5. Four cores. It reads the webcam, runs the detector, keeps
the archive, composes the picture, mixes the music, and pushes the whole thing
to YouTube, continuously. Nothing runs in a cloud. The detector takes 334 ms
per look on this hardware, and that is the budget everything else is built
around.

The pipeline, the install, the secrets and the hardware are documented in the
[French README](README.md), with the outages in [`incidents.md`](incidents.md)
and where this is going in [`plan.md`](plan.md).

## Credits

Webcam: Vision Environnement, Mont Serein. The stream is the one already used
by [dataroads-fr84.info](https://dataroads-fr84.info/); this project displays it
and does not rehost it.
Terrain and place names: OpenStreetMap contributors and public elevation data.
Aircraft: the OpenSky Network. Weather: Open-Meteo.

This is a camera and a curiosity. It is not a monitoring service, it raises no
alarm of any kind, and nothing it says should be acted upon.
