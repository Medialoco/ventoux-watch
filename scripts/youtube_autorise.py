"""Donne une fois au veilleur le droit de rouvrir le direct YouTube.

À lancer sur le Mac, qui a un navigateur, avec le fichier d'identifiants OAuth
téléchargé depuis Google Cloud (type « Application de bureau ») :

    python3 -m scripts.youtube_autorise ~/Downloads/client_secret_XXX.json

Le navigateur s'ouvre, on choisit le compte de la chaîne, on accepte. Le
résultat s'écrit dans « secrets/youtube_oauth.json », en mode 600, que git
ignore. On le recopie ensuite sur le Pi, au même endroit :

    scp secrets/youtube_oauth.json ventoux:/opt/ventoux-watch/secrets/

Rien ne s'affiche du secret : ni l'identifiant, ni le jeton.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets as hasard
import stat
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.youtube_api import JETON_URL, PORTEE  # noqa: E402

AUTORISE_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _client(chemin: Path) -> tuple[str, str]:
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    client = brut.get("installed") or brut.get("web") or brut
    return client["client_id"], client["client_secret"]


def _attends_le_code(etat: str) -> tuple[http.server.HTTPServer, dict]:
    recu: dict = {}

    class Retour(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if params.get("state", [""])[0] == etat and params.get("code"):
                recu["code"] = params["code"][0]
                message = "Autorisation reçue. Vous pouvez fermer cet onglet."
            else:
                recu["erreur"] = params.get("error", ["réponse inattendue"])[0]
                message = "Autorisation refusée ou incomplète."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *_):
            pass

    serveur = http.server.HTTPServer(("127.0.0.1", 0), Retour)
    return serveur, recu


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    client_id, client_secret = _client(Path(sys.argv[1]).expanduser())
    etat = hasard.token_urlsafe(24)
    serveur, recu = _attends_le_code(etat)
    retour = f"http://127.0.0.1:{serveur.server_port}"
    url = AUTORISE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": retour,
        "response_type": "code",
        "scope": PORTEE,
        # « offline » et « consent » : sans eux, Google ne rend pas le jeton
        # de rafraîchissement, et l'autorisation meurt au bout d'une heure.
        "access_type": "offline",
        "prompt": "consent",
        "state": etat,
    })
    print("Le navigateur s'ouvre. Choisissez le compte de la chaîne et acceptez.")
    print("S'il ne s'ouvre pas, collez cette adresse :\n" + url)
    webbrowser.open(url)
    serveur.serve_forever()
    if "code" not in recu:
        print(f"Pas d'autorisation : {recu.get('erreur')}")
        return 1
    corps = urllib.parse.urlencode({
        "code": recu["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": retour, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen(JETON_URL, data=corps, timeout=20) as reponse:
        jetons = json.loads(reponse.read())
    if not jetons.get("refresh_token"):
        print("Google n'a pas rendu de jeton de rafraîchissement. Retirez l'accès "
              "de l'application dans votre compte Google, puis recommencez.")
        return 1
    chemin = ROOT / "secrets" / "youtube_oauth.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": jetons["refresh_token"],
    }, indent=2) + "\n", encoding="utf-8")
    os.chmod(chemin, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Autorisation écrite dans {chemin.relative_to(ROOT)}, en mode 600.")
    print("À recopier sur le Pi :")
    print("    ssh ventoux mkdir -p /opt/ventoux-watch/secrets")
    print("    scp secrets/youtube_oauth.json ventoux:/opt/ventoux-watch/secrets/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
