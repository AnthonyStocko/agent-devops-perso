import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import app
import clients
import config
from taches import deploiements

SHA = "a" * 40
AUTRE = "b" * 40


def deploy(statut, sha=SHA):
    return {"id": "dep-1", "status": statut, "createdAt": "2026-01-01T10:00:00Z", "finishedAt": "2026-01-01T10:05:00Z",
            "commit": {"id": sha, "message": "Correctif\ndétail"}}


class TestDeploiements(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"RENDER_API_KEY": "cle-secrete", "RENDER_SERVICE_AGENT_EMPLOI": "srv-1"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def verifier(self, deploys, github=SHA, commit=""):
        with mock.patch.object(clients, "deploiements_render", return_value=deploys), \
                mock.patch.object(clients, "dernier_commit_github", return_value={"sha": github, "message": "m"}):
            return deploiements.verifier_agent("agent_emploi", commit)

    def test_a_jour(self):
        r = self.verifier([deploy("live")])
        self.assertEqual(r["verdict"], "a_jour")
        self.assertEqual(r["dernier_deploiement"]["statut_libelle"], "Live")
        self.assertEqual(r["dernier_deploiement"]["message"], "Correctif")

    def test_commit_different(self):
        self.assertEqual(self.verifier([deploy("live", AUTRE)])["verdict"], "commit_different")

    def test_echec_signale_et_commit_en_ligne_conserve(self):
        r = self.verifier([deploy("build_failed"), deploy("live", AUTRE)])
        self.assertEqual(r["verdict"], "echec")
        self.assertEqual(r["en_ligne"]["commit"], AUTRE)

    def test_en_cours(self):
        self.assertEqual(self.verifier([deploy("build_in_progress")])["verdict"], "en_cours")

    def test_commit_attendu_prefixe(self):
        self.assertEqual(self.verifier([deploy("live")], github=AUTRE, commit="aaaaaaa")["verdict"], "a_jour")

    def test_aucun_deploiement(self):
        self.assertEqual(self.verifier([])["verdict"], "inconnu")

    def test_service_non_configure(self):
        r = deploiements.verifier_agent("agent_perso")
        self.assertEqual(r["verdict"], "non_configure")

    def test_erreur_render_sans_secret(self):
        with mock.patch.object(clients, "deploiements_render", side_effect=clients.ErreurApi("Render : HTTP 401")):
            r = deploiements.verifier_agent("agent_emploi")
        self.assertEqual(r["verdict"], "erreur")
        self.assertNotIn("cle-secrete", json.dumps(r))

    def test_agent_inconnu(self):
        self.assertIn("erreur", deploiements.executer({"agent": "x"}))

    def test_client_render_deballe_et_n_expose_pas_la_cle(self):
        class Rep:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s): return json.dumps([{"deploy": deploy("live"), "cursor": "c"}]).encode()
        vu = {}
        def faux(req, timeout=0):
            vu["url"], vu["auth"] = req.full_url, req.get_header("Authorization")
            return Rep()
        with mock.patch("urllib.request.urlopen", faux):
            d = clients.deploiements_render("srv-1")
        self.assertEqual(d[0]["status"], "live")
        self.assertIn("/services/srv-1/deploys", vu["url"])
        self.assertEqual(vu["auth"], "Bearer cle-secrete")

    def test_client_erreur_http_sans_secret(self):
        err = urllib.error.HTTPError("https://x/?k=cle-secrete", 401, "no", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(clients.ErreurApi) as c:
                clients.deploiements_render("srv-1")
        self.assertNotIn("cle-secrete", str(c.exception))


class TestServeur(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"HUB_TOKEN": "hub"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Gestionnaire)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def appel(self, chemin, jeton=None, methode="GET"):
        h = {"Authorization": "Bearer " + jeton} if jeton else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + chemin, headers=h, method=methode)) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_healthz_public(self):
        self.assertEqual(self.appel("/healthz"), (200, {"ok": True}))

    def test_jeton_requis(self):
        self.assertEqual(self.appel("/agent/devops/deploiements")[0], 401)
        self.assertEqual(self.appel("/agent/devops/deploiements", "mauvais")[0], 401)

    def test_sans_hub_token_configure_tout_est_refuse(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.appel("/agent/devops/deploiements", "")[0], 401)

    def test_tache_inconnue(self):
        self.assertEqual(self.appel("/agent/devops/nimporte", "hub")[0], 404)

    def test_lecture_seule(self):
        self.assertEqual(self.appel("/agent/devops/deploiements", "hub", "POST")[0], 405)

    def test_deploiements(self):
        code, corps = self.appel("/agent/devops/deploiements?agent=agent_perso", "hub")
        self.assertEqual(code, 200)
        self.assertEqual(corps["agents"][0]["verdict"], "non_configure")


if __name__ == "__main__":
    unittest.main()
