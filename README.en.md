# #FREETECHNORADIO

*[Français](README.md)*

Web radio. **Free music only** ([Dogmazic](https://play.dogmazic.net/)). Track selection, mix, voice, encode and publish on a **Raspberry Pi 5** in Los Angeles. **Associated YouTube feed**: Mont Serein webcam (1 frame/s, OpenCV MOG2, YOLO11s ONNX); Cannes backup when the pass HLS playlist closes.

Watcher **v0.6.47**.

## Listen

| Role | URL / file |
| --- | --- |
| Audio (directories, VLC) | `https://freetechnoradio.benoit-prieur.fr/index.m3u8` |
| Player page (browser) | [freetechnoradio.benoit-prieur.fr](https://freetechnoradio.benoit-prieur.fr/) (same path; `Accept: text/html` negotiation) |
| Site | [medialoco.github.io/ventoux-watch](https://medialoco.github.io/ventoux-watch/) |
| YouTube | id in `data/direct.json` · [channel](https://www.youtube.com/channel/UCvN0sNcj5JM9tklIkAlGi7g) |
| Dogmazic playlist | `data/dogmazic_playlist.json` on the Pi · sync: `scripts/dogmazic_playlist.py --verifie` |

ffmpeg **tees the same mix** to RTMP (YouTube) and HLS (`data/radio/`). Credits: on-stream console (image clock), `now.json`, `#EXTINF` titles and the player page. YouTube is muted on the radio page; audio is HLS.

A camera and a curiosity, not an alert.

## Development

Mac:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-export.txt
.venv/bin/python scripts/export_model.py
.venv/bin/python -m unittest discover -s tests -v
```

`models/yolo11s.onnx` is in the repo. The Pi never installs PyTorch.

Pi:

```bash
ssh ventoux 'bash -s' < scripts/pi_install.sh
```

Deploy: `.venv/bin/python -m scripts.deploie` (watch) · `--flux` when `watcher/stream.py` or the radio server changes (≥ 1 h between `--flux`, or `--quand-meme`).

## Radio HTTPS

- Server: `watcher/radio_serveur.py`, port **8767**, segments in `data/radio/`.
- Public URL: `config/radio_public.env` or `radio.public_url` → `data/radio.json`.
- Stable host: **freetechnoradio.benoit-prieur.fr** (`radio.tunnel_hostname`), Cloudflare tunnel `ventoux-radio`, unit `ventoux-radio-tunnel`.
- Tunnel setup: see git history and `config/cloudflared-radio.yml.example`. Token in `config/radio_tunnel.token` (not in git).

## Elsewhere

[`infra.md`](infra.md) · [`incidents.md`](incidents.md) · [`plan.md`](plan.md)

Secrets: `config/local.json` (gitignored).
