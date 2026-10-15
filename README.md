# #FREETECHNORADIO

*[In English](README.en.md)*

Webradio. **Musique libre uniquement** ([Dogmazic](https://play.dogmazic.net/)). Sélection, mix, voix, encodage et publication sur un **Raspberry Pi 5** à Los Angeles. **Flux YouTube associé** : webcam du Mont Serein (1 image/s, OpenCV MOG2, YOLO11s ONNX) ; relais Cannes si la playlist HLS du col se ferme.

**Écouter (HLS)** : `https://freetechnoradio.tech/index.m3u8`

Veilleur **v0.6.48**.

## Écouter

| Rôle | URL / fichier |
| --- | --- |
| Audio (annuaires, VLC) | `https://freetechnoradio.tech/index.m3u8` |
| Écoute dans le navigateur | [freetechnoradio.tech](https://freetechnoradio.tech/) (même URL ; le navigateur reçoit la page joueur via `Accept: text/html`) |
| Site | [watch.freetechnoradio.tech](https://watch.freetechnoradio.tech/) |
| YouTube | id dans `data/direct.json` · [chaîne](https://www.youtube.com/channel/UCvN0sNcj5JM9tklIkAlGi7g) |
| Playlist Dogmazic | [play.dogmazic.net …4803](https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id=4803) · sync : `scripts/dogmazic_playlist.py --verifie` |

ffmpeg envoie le **même mix** vers RTMP (YouTube) et HLS (`data/radio/`). Crédits : console sous l’image (horloge image), `now.json`, titres `#EXTINF` et page joueur. YouTube muet sur la page radio ; le son est le HLS.

Caméra de curiosité, pas une alerte.

## Développement

Mac :

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-export.txt
.venv/bin/python scripts/export_model.py
.venv/bin/python -m unittest discover -s tests -v
```

`models/yolo11s.onnx` est versionné. Le Pi n’installe pas PyTorch.

Pi :

```bash
ssh ventoux 'bash -s' < scripts/pi_install.sh
```

Déploiement : `.venv/bin/python -m scripts.deploie` (veille) · `--flux` si `watcher/stream.py` ou le serveur radio change (≥ 1 h entre deux `--flux`, ou `--quand-meme`).

La page radio lit `data/release.json` pour le numéro affiché, l’URL HLS (`stream`), la page joueur (`player`) et les liens (repo, site) : on peut le bumper dans git sans redémarrer le flux sur le Pi.

## Radio HTTPS

- Serveur : `watcher/radio_serveur.py`, port **8767**, segments `data/radio/`.
- URL publique : `config/radio_public.env` ou `radio.public_url` → `data/radio.json`.
- Hôte stable : **freetechnoradio.tech** (`radio.tunnel_hostname`) ; l'ancien hôte freetechnoradio.benoit-prieur.fr est servi par le même tunnel, tunnel Cloudflare `ventoux-radio`, service `ventoux-radio-tunnel`.
- Recréation tunnel : README historique dans git ; exemple `config/cloudflared-radio.yml.example`. Token dans `config/radio_tunnel.token` (hors git).

## Ailleurs

[`infra.md`](infra.md) · [`incidents.md`](incidents.md) · [`plan.md`](plan.md)

Secrets : `config/local.json` (ignoré par git).
