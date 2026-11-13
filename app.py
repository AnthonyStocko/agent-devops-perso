"""Agent devops : serveur HTTP en lecture seule appelé par l'agent chef.

  GET /healthz                              -> {"ok": true}
  GET /agent/devops/<tache>?agent=&commit=  -> résultat de la tâche (en-tête Authorization: Bearer HUB_TOKEN)

Seule la bibliothèque standard est utilisée. Démarrage : python app.py [port] (PORT sinon 8796).
"""
import hmac
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from taches import TACHES


class Gestionnaire(BaseHTTPRequestHandler):
    def _repondre(self, code, corps):
        data = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _autorise(self):
        attendu = config.jeton_acces()
        recu = self.headers.get("Authorization", "")
        return bool(attendu) and hmac.compare_digest(recu.encode(), ("Bearer " + attendu).encode())

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/healthz":
            return self._repondre(200, {"ok": True})
        prefixe = "/agent/devops/"
        if not url.path.startswith(prefixe):
            return self._repondre(404, {"erreur": "Introuvable."})
        if not self._autorise():
            return self._repondre(401, {"erreur": "Non autorisé."})
        tache = TACHES.get(url.path[len(prefixe):].strip("/"))
        if not tache:
            return self._repondre(404, {"erreur": "Tâche inconnue.", "taches": sorted(TACHES)})
        params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            self._repondre(200, tache(params))
        except Exception as e:  # une tâche en panne ne doit pas faire tomber le serveur
            self._repondre(500, {"erreur": f"La tâche a échoué ({type(e).__name__})."})

    def do_POST(self):
        self._repondre(405, {"erreur": "Lecture seule : seul GET est accepté."})

    do_PUT = do_PATCH = do_DELETE = do_POST

    def log_message(self, format, *args):  # pas de requête (ni paramètre) dans les journaux
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", "8796"))
    print(f"Agent devops à l'écoute sur le port {port}.", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Gestionnaire).serve_forever()


if __name__ == "__main__":
    main()
