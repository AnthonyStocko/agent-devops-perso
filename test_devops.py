import json
import os
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
            return deploiements.verifier_agent("emploi", commit)

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
        r = deploiements.verifier_agent("perso")
        self.assertEqual(r["verdict"], "non_configure")

    def test_erreur_render_sans_secret(self):
        with mock.patch.object(clients, "deploiements_render", side_effect=clients.ErreurApi("Render : HTTP 401")):
            r = deploiements.verifier_agent("emploi")
        self.assertEqual(r["verdict"], "erreur")
        self.assertNotIn("cle-secrete", json.dumps(r))

    def test_agent_inconnu(self):
        r = deploiements.executer({"agent": "x"})
        self.assertIn("erreur", r)
        self.assertEqual(r["agents_possibles"], ["emploi", "manager", "perso"])
        with self.assertRaises(agent_devops.ErreurDevops):
            agent_devops.verifier_deploiements(agent="instagram")

    def test_sans_cle_render(self):
        with mock.patch.dict(os.environ, {"RENDER_API_KEY": ""}):
            with self.assertRaises(agent_devops.ErreurDevops) as c:
                agent_devops.verifier_deploiements()
            self.assertIn("RENDER_API_KEY", deploiements.executer({})["erreur"])
        self.assertIn("RENDER_API_KEY", str(c.exception))

    def test_echec_dit_ce_qui_reste_en_ligne(self):
        r = self.verifier([deploy("build_failed"), deploy("live", AUTRE)])
        self.assertIn("Toujours en ligne : bbbbbbb", r["resume"])

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


class TestBibliotheque(unittest.TestCase):
    """L'appel en bibliothèque, tel que le fait l'agent chef : Render et GitHub simulés au niveau HTTP."""

    def setUp(self):
        self.render = {"srv-chef": [{"deploy": deploy("live")}], "srv-emploi": [{"deploy": deploy("live")}],
                       "srv-perso": [{"deploy": deploy("live")}]}
        self.github = {"AnthonyStocko/agent-manager": SHA, "AnthonyStocko/agent-emploi": SHA,
                       "AnthonyStocko/agent-perso": SHA}
        self.appels = []

        def faux_get(url, jeton, timeout=20):
            self.appels.append((url, jeton))
            if url.startswith(clients.RENDER_API):
                service = url.split("/services/")[1].split("/")[0]
                if service not in self.render:
                    raise clients.ErreurApi("HTTP 404")
                return self.render[service]
            depot = url.split("/repos/")[1].split("/commits/")[0]
            return {"sha": self.github[depot], "commit": {"message": "Correctif"}}

        env = {"RENDER_API_KEY": "cle-secrete", "RENDER_SERVICE_ID": "srv-chef",
               "RENDER_SERVICE_AGENT_EMPLOI": "srv-emploi", "RENDER_SERVICE_AGENT_PERSO": "srv-perso",
               "DEV_GITHUB_TOKEN": "ghp_dev"}
        for p in (mock.patch.object(clients, "_get", faux_get), mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def verdicts(self, **kw):
        return {a["agent"]: a["verdict"] for a in agent_devops.verifier_deploiements(**kw)["agents"]}

    def test_tout_a_jour(self):
        r = agent_devops.verifier_deploiements()
        self.assertTrue(r["tout_est_a_jour"])
        # seuls les agents hébergés sur Render sont suivis ; le service de l'agent chef vient de RENDER_SERVICE_ID
        self.assertEqual([a["agent"] for a in r["agents"]], ["manager", "emploi", "perso"])
        self.assertIn("tout est à jour", agent_devops.texte(r))
        # Render est lu avec sa clé, GitHub avec le jeton de l'agent développeur à défaut de GITHUB_TOKEN
        self.assertEqual({j for u, j in self.appels if u.startswith(clients.RENDER_API)}, {"cle-secrete"})
        self.assertEqual({j for u, j in self.appels if u.startswith(clients.GITHUB_API)}, {"ghp_dev"})

    def test_commit_pas_encore_en_ligne(self):
        self.github["AnthonyStocko/agent-emploi"] = AUTRE
        r = agent_devops.verifier_deploiements()
        self.assertFalse(r["tout_est_a_jour"])
        self.assertEqual(self.verdicts(), {"manager": "a_jour", "emploi": "commit_different", "perso": "a_jour"})
        self.assertIn("aaaaaaa", agent_devops.texte(r))
        self.assertIn("bbbbbbb", agent_devops.texte(r))

    def test_commit_precis_sans_appel_a_github(self):
        self.assertEqual(self.verdicts(agent="perso", commit="aaaaaaa"), {"perso": "a_jour"})
        self.assertEqual(self.verdicts(agent="perso", commit="bbbbbbb"), {"perso": "commit_different"})
        self.assertFalse(any(u.startswith(clients.GITHUB_API) for u, _ in self.appels))

    def test_service_non_configure_ou_en_erreur(self):
        self.render.pop("srv-perso")
        with mock.patch.dict(os.environ, {"RENDER_SERVICE_AGENT_EMPLOI": ""}):
            r = agent_devops.verifier_deploiements()
        self.assertEqual({a["agent"]: a["verdict"] for a in r["agents"]},
                         {"manager": "a_jour", "emploi": "non_configure", "perso": "erreur"})
        self.assertIn("RENDER_SERVICE_AGENT_EMPLOI", r["agents"][1]["resume"])
        self.assertNotIn("cle-secrete", str(r))

    def test_reponse_render_sans_enveloppe(self):
        self.render["srv-emploi"] = [{"commit": {"id": SHA}, "status": "live"}]
        self.assertEqual(self.verdicts(agent="emploi"), {"emploi": "a_jour"})


class TestVariables(unittest.TestCase):
    """Réglage d'une variable Render : seule écriture de l'agent, en deux temps (préparer, puis définir)."""

    def setUp(self):
        self.ecritures, self.lectures = [], []
        self.deploys = []            # ce que Render répond à la lecture des déploiements, après l'écriture
        self.echec = {}              # méthode -> ErreurApi à lever

        def faux_ecrire(methode, url, jeton, corps, timeout=30):
            self.ecritures.append((methode, url, jeton, corps))
            if methode in self.echec:
                raise self.echec[methode]
            return {}

        def faux_get(url, jeton, timeout=20):
            self.lectures.append(url)
            return self.deploys

        env = {"RENDER_API_KEY": "cle-secrete", "RENDER_SERVICE_AGENT_PERSO": "srv-perso"}
        for p in (mock.patch.object(clients, "_ecrire", faux_ecrire), mock.patch.object(clients, "_get", faux_get),
                  mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def definir(self, nom="JOB_ALERT_SENDERS", valeur="linkedin.com, indeed.com", agent="perso"):
        return agent_devops.definir_variable(agent, nom, valeur, attente=0)

    def test_preparer_ne_touche_a_rien(self):
        d = agent_devops.preparer_variable("perso", " JOB_ALERT_SENDERS ", " linkedin.com, indeed.com ")
        self.assertEqual((d["agent"], d["nom"], d["valeur"]), ("perso", "JOB_ALERT_SENDERS", "linkedin.com, indeed.com"))
        for mot in ("Agent perso", "JOB_ALERT_SENDERS", "linkedin.com, indeed.com", "redéployé"):
            self.assertIn(mot, d["resume"])
        self.assertEqual((self.ecritures, self.lectures), ([], []))

    def test_definir_enregistre_puis_lance_le_deploiement(self):
        r = self.definir()
        self.assertEqual([(m, u) for m, u, _, _ in self.ecritures], [
            ("PUT", "https://api.render.com/v1/services/srv-perso/env-vars/JOB_ALERT_SENDERS"),
            ("POST", "https://api.render.com/v1/services/srv-perso/deploys")])
        self.assertEqual(self.ecritures[0][3], {"value": "linkedin.com, indeed.com"})
        self.assertEqual({j for _, _, j, _ in self.ecritures}, {"cle-secrete"})
        self.assertEqual(r["deploiement"], "lance")
        self.assertIn("✅", r["resume"])
        self.assertNotIn("cle-secrete", str(r))
        # aucune lecture des variables existantes : seule la liste des déploiements est consultée
        self.assertTrue(all("/deploys" in u and "env-vars" not in u for u in self.lectures))

    def test_pas_de_second_deploiement_si_render_en_a_lance_un(self):
        self.deploys = [{"deploy": deploy("build_in_progress")}]
        r = self.definir()
        self.assertEqual([m for m, *_ in self.ecritures], ["PUT"])
        self.assertEqual(r["deploiement"], "en_cours")

    def test_variable_non_enregistree(self):
        self.echec["PUT"] = clients.ErreurApi("HTTP 401")
        with self.assertRaises(agent_devops.ErreurDevops) as c:
            self.definir()
        self.assertIn("Rien n'a changé", str(c.exception))
        self.assertEqual([m for m, *_ in self.ecritures], ["PUT"])
        self.assertNotIn("cle-secrete", str(c.exception))

    def test_deploiement_non_lance_est_signale(self):
        self.echec["POST"] = clients.ErreurApi("HTTP 500")
        r = self.definir()
        self.assertEqual(r["deploiement"], "a_lancer")
        self.assertIn("⚠️", r["resume"])
        self.assertIn("enregistrée", r["resume"])

    def test_refus(self):
        cas = [
            ("perso", "APP_PASSWORD", "x", "secret"),
            ("perso", "CLAUDE_CODE_OAUTH_TOKEN", "x", "secret"),
            ("perso", "RENDER_API_KEY", "x", "secret"),
            ("perso", "DATABASE_URL", "x", "secret"),
            ("perso", "RENDER_SERVICE_AGENT_PERSO", "srv-x", "réservée"),
            ("perso", "PORT", "80", "réservée"),
            ("perso", "job_alert", "x", "invalide"),
            ("perso", "A B", "x", "invalide"),
            ("perso", "JOB_ALERT_SENDERS", "", "valeur"),
            ("perso", "JOB_ALERT_SENDERS", "a\nb", "Valeur refusée"),
            ("perso", "JOB_ALERT_SENDERS", "x" * 2001, "Valeur refusée"),
            ("instagram", "JOB_ALERT_SENDERS", "x", "Agent inconnu"),
            ("emploi", "JOB_ALERT_SENDERS", "x", "RENDER_SERVICE_AGENT_EMPLOI"),   # service non configuré
        ]
        for agent, nom, valeur, attendu in cas:
            for fonction in (agent_devops.preparer_variable, lambda *a: agent_devops.definir_variable(*a, attente=0)):
                with self.subTest(nom=nom, valeur=valeur[:10], agent=agent), \
                        self.assertRaises(agent_devops.ErreurDevops) as c:
                    fonction(agent, nom, valeur)
                self.assertIn(attendu, str(c.exception))
        self.assertEqual(self.ecritures, [])   # aucun refus n'a écrit quoi que ce soit

    def test_sans_cle_render(self):
        with mock.patch.dict(os.environ, {"RENDER_API_KEY": ""}), self.assertRaises(agent_devops.ErreurDevops) as c:
            agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "x")
        self.assertIn("RENDER_API_KEY", str(c.exception))

    def test_le_serveur_http_ne_sert_pas_cette_ecriture(self):
        from agent_devops.taches import TACHES
        self.assertEqual(sorted(TACHES), ["deploiements", "echecs"])

    def test_client_ecriture_sans_secret_dans_l_erreur(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.stopall()
        with mock.patch.dict(os.environ, {"RENDER_API_KEY": "cle-secrete"}, clear=True):
            vu = {}

            class Rep:
                def __enter__(s): return s
                def __exit__(s, *a): pass
                def read(s): return b"{}"

            def faux(req, timeout=0):
                vu.update(url=req.full_url, methode=req.get_method(), corps=json.loads(req.data),
                          auth=req.get_header("Authorization"))
                return Rep()
            with mock.patch("urllib.request.urlopen", faux):
                clients.definir_variable_render("srv-1", "MA_VAR", "é à")
            self.assertEqual((vu["methode"], vu["corps"], vu["auth"]), ("PUT", {"value": "é à"}, "Bearer cle-secrete"))
            self.assertTrue(vu["url"].endswith("/services/srv-1/env-vars/MA_VAR"))
            err = urllib.error.HTTPError("https://x/?k=cle-secrete", 403, "no", {}, None)
            with mock.patch("urllib.request.urlopen", side_effect=err), self.assertRaises(clients.ErreurApi) as c:
                clients.lancer_deploiement_render("srv-1")
            self.assertNotIn("cle-secrete", str(c.exception))


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

        env = {"DEVOPS_ACTIONS_TOKEN": "ghp_actions", "GITHUB_TOKEN": "ghp_lecture", "DEV_GITHUB_TOKEN": "ghp_dev",
               "RENDER_API_KEY": "cle-secrete"}
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
        env = mock.patch.dict(os.environ, {"HUB_TOKEN": "hub", "RENDER_API_KEY": "cle-secrete"}, clear=True)
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
        self.assertEqual(corps["agents"][0]["verdict"], "non_configure")


if __name__ == "__main__":
    unittest.main()
