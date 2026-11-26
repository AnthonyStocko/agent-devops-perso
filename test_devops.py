import datetime
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import agent_devops
from agent_devops import clients, config, serveur
from agent_devops.taches import deploiements

SHA = "a" * 40
AUTRE = "b" * 40


def service(commit=SHA, statut="reussi", etat="running", sante="healthy", tentative=None, erreur=""):
    return {"commit_en_service": commit,
            "derniere_tentative": {"commit": tentative or commit, "statut": statut, "date": "2026-11-26T16:00:00+01:00",
                                   "erreur": erreur},
            "conteneur": {"etat": etat, "sante": sante}}


class AvecEtat(unittest.TestCase):
    """Fichier d'état du serveur (écrit par mettre-a-jour.sh) dans un dossier temporaire, GitHub simulé."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.chemin = os.path.join(self.dossier.name, "deploiements.json")
        self.services = {s: service() for s in ("agent-manager", "agent-emploi", "agent-perso", "agent-devops")}
        self.genere_le = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.github = {a["depot"]: SHA for a in config.AGENTS.values()}
        self.appels = []

        def faux_get(url, jeton, timeout=20):
            self.appels.append((url, jeton))
            depot = url.split("/repos/")[1].split("/commits/")[0]
            if self.github.get(depot) is None:
                raise clients.ErreurApi("HTTP 404")
            return {"sha": self.github[depot], "commit": {"message": "Correctif\ndétail"}}

        env = {"DEVOPS_ETAT": self.chemin, "DEV_GITHUB_TOKEN": "ghp_dev"}
        for p in (mock.patch.object(clients, "_get", faux_get), mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def ecrire_etat(self):
        with open(self.chemin, "w", encoding="utf-8") as f:
            json.dump({"genere_le": self.genere_le, "services": self.services}, f)

    def verifier(self, **kw):
        self.ecrire_etat()
        return agent_devops.verifier_deploiements(**kw)

    def verdicts(self, **kw):
        return {a["agent"]: a["verdict"] for a in self.verifier(**kw)["agents"]}


class TestDeploiements(AvecEtat):
    def test_tout_a_jour(self):
        r = self.verifier()
        self.assertTrue(r["tout_est_a_jour"])
        self.assertEqual(set(self.verdicts()), {"manager", "emploi", "perso", "devops"})
        self.assertIn("tout est à jour", agent_devops.texte(r))
        self.assertFalse(r["etat_perime"])

    def test_commit_different(self):
        self.github["AnthonyStocko/agent-emploi"] = AUTRE
        self.assertEqual(self.verdicts(agent="emploi"), {"emploi": "commit_different"})

    def test_mise_a_jour_en_cours(self):
        self.services["agent-perso"] = service(statut="en_cours", tentative=AUTRE)
        r = self.verifier(agent="perso")["agents"][0]
        self.assertEqual(r["verdict"], "en_cours")
        self.assertIn(AUTRE[:7], r["resume"])

    def test_echec_dit_ce_qui_reste_en_service(self):
        self.services["agent-perso"] = service(statut="echec", tentative=AUTRE, erreur="pip install a échoué")
        r = self.verifier(agent="perso")["agents"][0]
        self.assertEqual(r["verdict"], "echec")
        self.assertIn("Toujours en service : " + SHA[:7], r["resume"])
        self.assertIn("pip install", r["resume"])

    def test_conteneur_arrete_ou_malade(self):
        self.services["agent-emploi"] = service(etat="exited", sante="")
        self.services["agent-perso"] = service(sante="unhealthy")
        v = self.verdicts()
        self.assertEqual((v["emploi"], v["perso"]), ("hors_service", "hors_service"))

    def test_commit_attendu_prefixe_sans_appel_a_github(self):
        r = self.verifier(agent="emploi", commit=SHA[:7])["agents"][0]
        self.assertEqual(r["verdict"], "a_jour")
        self.assertEqual(self.appels, [])

    def test_service_absent_de_l_etat(self):
        del self.services["agent-devops"]
        self.assertEqual(self.verdicts(agent="devops"), {"devops": "inconnu"})

    def test_github_injoignable(self):
        self.github["AnthonyStocko/agent-emploi"] = None
        r = self.verifier(agent="emploi")["agents"][0]
        self.assertEqual(r["verdict"], "inconnu")
        self.assertIn("HTTP 404", r["resume"])

    def test_etat_perime_signale(self):
        self.genere_le = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        r = self.verifier()
        self.assertTrue(r["etat_perime"])
        self.assertIn("peut-être arrêtée", agent_devops.texte(r))

    def test_etat_absent_ou_illisible(self):
        with self.assertRaises(agent_devops.ErreurDevops) as c:
            agent_devops.verifier_deploiements()
        self.assertIn("introuvable", str(c.exception))
        with open(self.chemin, "w") as f:
            f.write("pas du json")
        with self.assertRaises(agent_devops.ErreurDevops) as c:
            agent_devops.verifier_deploiements()
        self.assertIn("illisible", str(c.exception))
        self.assertIn("erreur", deploiements.executer({}))

    def test_agent_inconnu(self):
        self.ecrire_etat()
        with self.assertRaises(agent_devops.ErreurDevops):
            agent_devops.verifier_deploiements(agent="instagram")
        self.assertIn("agents_possibles", deploiements.executer({"agent": "instagram"}))

    def test_jeton_github_de_lecture(self):
        self.verifier(agent="emploi")
        self.assertEqual({j for u, j in self.appels}, {"ghp_dev"})


class TestVariables(unittest.TestCase):
    """Réglage d'une variable : une demande déposée dans le dossier partagé, appliquée par le serveur."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        env = mock.patch.dict(os.environ, {"DEVOPS_DEMANDES": self.dossier.name}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def demandes(self):
        return sorted(os.listdir(self.dossier.name))

    def test_preparer_ne_depose_rien(self):
        d = agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", " linkedin.com ")
        self.assertEqual((d["agent"], d["nom"], d["valeur"]), ("perso", "JOB_ALERT_SENDERS", "linkedin.com"))
        self.assertIn("redémarre", d["resume"])
        self.assertEqual(self.demandes(), [])

    def test_definir_depose_une_demande(self):
        r = agent_devops.definir_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com, indeed.com")
        self.assertEqual(r["deploiement"], "en_file")
        self.assertIn("Demande enregistrée", r["resume"])
        fichiers = self.demandes()
        self.assertEqual(fichiers, [r["demande"] + ".json"])   # aucun fichier temporaire restant
        chemin = os.path.join(self.dossier.name, fichiers[0])
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["agent"], d["service"], d["nom"], d["valeur"]),
                         ("perso", "agent-perso", "JOB_ALERT_SENDERS", "linkedin.com, indeed.com"))
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600)

    def test_deux_demandes_ne_s_ecrasent_pas(self):
        a = agent_devops.definir_variable("emploi", "MA_VAR", "1")
        b = agent_devops.definir_variable("emploi", "MA_VAR", "2")
        self.assertNotEqual(a["demande"], b["demande"])
        self.assertEqual(len(self.demandes()), 2)

    def test_refus(self):
        cas = [
            ("perso", "APP_PASSWORD", "x", "secret"),
            ("perso", "CLAUDE_CODE_OAUTH_TOKEN", "x", "secret"),
            ("perso", "RENDER_API_KEY", "x", "secret"),
            ("perso", "DATABASE_URL", "x", "secret"),
            ("perso", "RENDER_SERVICE_AGENT_PERSO", "srv-x", "réservée"),
            ("perso", "RENDER", "true", "réservée"),
            ("perso", "PORT", "80", "réservée"),
            ("manager", "PERSO_URL", "http://ailleurs", "réservée"),
            ("emploi", "DATA_DIR", "/tmp", "réservée"),
            ("perso", "job_alert", "x", "invalide"),
            ("perso", "A B", "x", "invalide"),
            ("perso", "JOB_ALERT_SENDERS", "", "valeur"),
            ("perso", "JOB_ALERT_SENDERS", "a\nb", "Valeur refusée"),
            ("perso", "JOB_ALERT_SENDERS", "x" * 2001, "Valeur refusée"),
            ("instagram", "JOB_ALERT_SENDERS", "x", "Agent inconnu"),
            ("devops", "JOB_ALERT_SENDERS", "x", "Agent inconnu"),
        ]
        for agent, nom, valeur, attendu in cas:
            for fonction in (agent_devops.preparer_variable, agent_devops.definir_variable):
                with self.subTest(nom=nom, valeur=valeur[:10], agent=agent), \
                        self.assertRaises(agent_devops.ErreurDevops) as c:
                    fonction(agent, nom, valeur)
                self.assertIn(attendu, str(c.exception))
        self.assertEqual(self.demandes(), [])   # aucun refus n'a rien déposé

    def test_dossier_des_demandes_absent(self):
        with mock.patch.dict(os.environ, {"DEVOPS_DEMANDES": os.path.join(self.dossier.name, "absent")}):
            with self.assertRaises(agent_devops.ErreurDevops) as c:
                agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "x")
        self.assertIn("pas monté", str(c.exception))

    def test_le_serveur_http_ne_sert_pas_cette_ecriture(self):
        from agent_devops.taches import TACHES
        self.assertEqual(sorted(TACHES), ["deploiements", "echecs"])


class TestWorkflows(unittest.TestCase):
    """Lancement d'un workflow de la liste blanche : seconde écriture de l'agent, en deux temps."""

    def setUp(self):
        self.ecritures = []
        self.echec = None

        def faux_ecrire(methode, url, jeton, corps, timeout=30):
            self.ecritures.append((methode, url, jeton, corps))
            if self.echec:
                raise self.echec
            return None   # GitHub répond 204 sans corps

        env = {"DEVOPS_ACTIONS_TOKEN": "ghp_actions", "GITHUB_TOKEN": "ghp_lecture", "DEV_GITHUB_TOKEN": "ghp_dev"}
        for p in (mock.patch.object(clients, "_ecrire", faux_ecrire), mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_liste_blanche_identique_a_claude_md(self):
        # CLAUDE.md fait foi et l'agent développeur ne peut pas le modifier : le code n'a pas le droit de s'élargir seul
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "CLAUDE.md"), encoding="utf-8") as f:
            lignes = [l.strip() for l in f if l.strip().startswith("| `")]
        regles = set()
        for ligne in lignes:
            depot, workflow, entree, valeurs = [c.strip() for c in ligne.strip("|").split("|")]
            regles |= {(depot.strip("`"), workflow.strip("`"), entree.strip("`"), v.strip().strip("`"))
                       for v in valeurs.split(",")}
        code = {(w["depot"], w["workflow"], nom, v) for w in config.WORKFLOWS.values()
                for nom, valeurs in w["entrees"].items() for v in valeurs}
        self.assertTrue(regles)
        self.assertEqual(code, regles)
        self.assertEqual(config.BRANCHE_WORKFLOWS, "main")

    def test_preparer_ne_lance_rien(self):
        d = agent_devops.preparer_workflow(" instagram-supabase ", {"etape": " deployer "})
        self.assertEqual((d["cle"], d["entrees"]), ("instagram-supabase", {"etape": "deployer"}))
        for mot in ("deploy-supabase.yml", "AnthonyStocko/mon-guide-agent-instagram", "branche main", "APPLIQUE les migrations",
                    "Edge Functions", "jamais celui de Mon guide", "Un seul run"):
            self.assertIn(mot, d["resume"])
        self.assertIn("sans rien appliquer", agent_devops.preparer_workflow("instagram-supabase", {"etape": "apercu"})["resume"])
        self.assertEqual(self.ecritures, [])

    def test_declencher_un_seul_run_avec_le_jeton_dedie(self):
        r = agent_devops.declencher_workflow("instagram-supabase", {"etape": "deployer"})
        self.assertEqual(self.ecritures, [(
            "POST", "https://api.github.com/repos/AnthonyStocko/mon-guide-agent-instagram/actions/workflows/"
                    "deploy-supabase.yml/dispatches", "ghp_actions", {"ref": "main", "inputs": {"etape": "deployer"}})])
        self.assertIn("✅", r["resume"])
        self.assertIn("actions/workflows/deploy-supabase.yml", r["lien"])
        self.assertNotIn("ghp_", str(r))

    def test_pas_de_repli_sur_les_jetons_de_lecture(self):
        with mock.patch.dict(os.environ, {"DEVOPS_ACTIONS_TOKEN": ""}):
            for fonction in (agent_devops.preparer_workflow, agent_devops.declencher_workflow):
                with self.assertRaises(agent_devops.ErreurDevops) as c:
                    fonction("instagram-supabase", {"etape": "apercu"})
                self.assertIn("DEVOPS_ACTIONS_TOKEN", str(c.exception))
            with self.assertRaises(clients.ErreurApi):
                clients.lancer_workflow_github("AnthonyStocko/mon-guide-agent-instagram", "deploy-supabase.yml",
                                               "main", {"etape": "apercu"})
        self.assertEqual(self.ecritures, [])

    def test_refus(self):
        cas = [
            ("ig-veille", {"etape": "apercu"}, "non autorisé"),
            ("", {"etape": "apercu"}, "non autorisé"),
            ("instagram-supabase", {}, "doit valoir"),
            ("instagram-supabase", None, "doit valoir"),
            ("instagram-supabase", {"etape": "detruire"}, "doit valoir"),
            ("instagram-supabase", {"etape": "deployer", "ref": "dev"}, "non autorisée"),
            ("instagram-supabase", "deployer", "dictionnaire"),
        ]
        for cle, entrees, attendu in cas:
            for fonction in (agent_devops.preparer_workflow, agent_devops.declencher_workflow):
                with self.subTest(cle=cle, entrees=entrees), self.assertRaises(agent_devops.ErreurDevops) as c:
                    fonction(cle, entrees)
                self.assertIn(attendu, str(c.exception))
        self.assertEqual(self.ecritures, [])

    def test_erreurs_github_sans_relance(self):
        for code, attendu in (("HTTP 401", "refuse le jeton"), ("HTTP 403", "refuse le jeton"),
                              ("HTTP 404", "introuvable"), ("HTTP 422", "refuse les entrées"),
                              ("service injoignable ou réponse illisible", "peut-être été lancé")):
            self.ecritures.clear()
            self.echec = clients.ErreurApi(code)
            with self.subTest(code=code), self.assertRaises(agent_devops.ErreurDevops) as c:
                agent_devops.declencher_workflow("instagram-supabase", {"etape": "apercu"})
            self.assertIn(attendu, str(c.exception))
            self.assertNotIn("ghp_", str(c.exception))
            self.assertEqual(len(self.ecritures), 1)   # jamais de seconde tentative

    def test_client_github_sans_secret_dans_l_erreur(self):
        mock.patch.stopall()
        with mock.patch.dict(os.environ, {"DEVOPS_ACTIONS_TOKEN": "ghp_actions"}, clear=True):
            vu = {}

            class Rep:
                def __enter__(s): return s
                def __exit__(s, *a): pass
                def read(s): return b""

            def faux(req, timeout=0):
                vu.update(url=req.full_url, methode=req.get_method(), corps=json.loads(req.data),
                          auth=req.get_header("Authorization"))
                return Rep()
            with mock.patch("urllib.request.urlopen", faux):
                clients.lancer_workflow_github("AnthonyStocko/mon-guide-agent-instagram", "deploy-supabase.yml",
                                               "main", {"etape": "apercu"})
            self.assertEqual((vu["methode"], vu["auth"]), ("POST", "Bearer ghp_actions"))
            self.assertEqual(vu["corps"], {"ref": "main", "inputs": {"etape": "apercu"}})
            err = urllib.error.HTTPError("https://x/?t=ghp_actions", 403, "no", {}, None)
            with mock.patch("urllib.request.urlopen", side_effect=err), self.assertRaises(clients.ErreurApi) as c:
                clients.lancer_workflow_github("AnthonyStocko/mon-guide-agent-instagram", "deploy-supabase.yml",
                                               "main", {"etape": "apercu"})
            self.assertNotIn("ghp_actions", str(c.exception))


class TestEchecsActions(unittest.TestCase):
    """Détection des workflows en échec : GitHub simulé, lecture seule, sans doublon."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.maintenant = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        self.runs = {"AnthonyStocko/mon-guide-agent-instagram": [self.faux_run(11, "ig-veille")]}
        self.appels = []

        def faux_get(url, jeton, timeout=20):
            self.appels.append(url)
            depot = url.split("/repos/")[1].split("/actions/")[0].split("/check-runs/")[0]
            if "/annotations" in url:
                return [{"annotation_level": "failure", "message": "Module introuvable : veille.py"}]
            if "/jobs" in url:
                return {"jobs": [{"id": 5, "name": "veille", "conclusion": "failure",
                                  "steps": [{"name": "Checkout", "conclusion": "success"},
                                            {"name": "Lancer", "conclusion": "failure"}]}]}
            if depot == "AnthonyStocko/agent-perso":
                raise clients.ErreurApi("HTTP 404")
            return {"workflow_runs": self.runs.get(depot, [])}

        p = mock.patch.object(clients, "_get", faux_get)
        p.start()
        self.addCleanup(p.stop)

    def faux_run(self, id_, nom, heures=1):
        date = (self.maintenant - __import__("datetime").timedelta(hours=heures)).isoformat()
        return {"id": id_, "name": nom, "run_attempt": 1, "event": "schedule", "head_branch": "main",
                "head_sha": SHA, "updated_at": date, "created_at": date,
                "html_url": f"https://github.com/x/y/actions/runs/{id_}", "conclusion": "failure"}

    def test_remonte_depot_workflow_cause_et_resume(self):
        r = agent_devops.detecter_echecs_actions()
        self.assertEqual(len(r["echecs"]), 1)
        e = r["echecs"][0]
        self.assertEqual(e["depot"], "AnthonyStocko/mon-guide-agent-instagram")
        self.assertEqual(e["workflow"], "ig-veille")
        self.assertIn("Lancer", e["cause"])
        self.assertIn("Module introuvable", e["resume"])
        self.assertIn("ig-veille", agent_devops.texte_echecs_actions(r))

    def test_pas_de_doublon(self):
        premier = agent_devops.detecter_echecs_actions()
        cles = [e["cle"] for e in premier["echecs"]]
        second = agent_devops.detecter_echecs_actions(deja_signales=cles)
        self.assertEqual(second["echecs"], [])
        self.assertEqual(second["deja_signales"], 1)

    def test_run_en_double_dans_la_reponse(self):
        self.runs["AnthonyStocko/mon-guide-agent-instagram"].append(self.faux_run(11, "ig-veille"))
        self.assertEqual(len(agent_devops.detecter_echecs_actions()["echecs"]), 1)

    def test_nouvelle_tentative_est_une_nouvelle_cle(self):
        r = self.faux_run(11, "ig-veille")
        r["run_attempt"] = 2
        self.runs["AnthonyStocko/mon-guide-agent-instagram"].append(r)
        self.assertEqual(len(agent_devops.detecter_echecs_actions()["echecs"]), 2)

    def test_echec_trop_ancien_ignore(self):
        self.runs["AnthonyStocko/mon-guide-agent-instagram"] = [self.faux_run(12, "vieux", heures=100)]
        self.assertEqual(agent_devops.detecter_echecs_actions()["echecs"], [])
        self.assertEqual(len(agent_devops.detecter_echecs_actions(depuis_heures=200)["echecs"]), 1)

    def test_depot_illisible_signale_sans_bloquer(self):
        r = agent_devops.detecter_echecs_actions()
        self.assertIn("erreur", [d["etat"] for d in r["depots"]])
        self.assertEqual(len(r["echecs"]), 1)

    def test_depot_hors_perimetre_refuse(self):
        with self.assertRaises(agent_devops.ErreurDevops):
            agent_devops.detecter_echecs_actions(depot="Autre/depot")

    def test_lecture_seule_get_uniquement(self):
        with mock.patch.object(clients, "_ecrire", side_effect=AssertionError("écriture")):
            agent_devops.detecter_echecs_actions()
        self.assertTrue(self.appels)

    def test_tache_http(self):
        from agent_devops.taches import echecs
        cle = "AnthonyStocko/mon-guide-agent-instagram#11#1"
        self.assertEqual(echecs.executer({"deja_signales": cle})["echecs"], [])
        self.assertEqual(len(echecs.executer({})["echecs"]), 1)
        self.assertIn("erreur", echecs.executer({"depot": "x/y"}))


class TestServeur(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"HUB_TOKEN": "hub", "DEVOPS_ETAT": "/nulle/part.json"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), serveur.Gestionnaire)
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
        code, corps = self.appel("/agent/devops/deploiements?agent=perso", "hub")
        self.assertEqual(code, 200)
        self.assertIn("introuvable", corps["erreur"])   # pas de fichier d'état : erreur lisible, pas de 500


if __name__ == "__main__":
    unittest.main()
