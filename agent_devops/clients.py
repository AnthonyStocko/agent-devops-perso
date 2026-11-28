"""Appels HTTP vers GitHub. Aucun jeton n'est jamais écrit dans un message d'erreur.

Tout est en lecture seule (GET), sauf une écriture, réservée à la tâche `workflows` : lancer un workflow de
la liste blanche.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from agent_devops import config

GITHUB_API = "https://api.github.com"


class ErreurApi(Exception):
    """Erreur d'un service externe, avec un message sans secret. `code` : code HTTP, quand il y en a un."""

    def __init__(self, message="", code=None):
        super().__init__(message)
        self.code = code


def _get(url, jeton, timeout=20):
    entetes = {"Accept": "application/json", "User-Agent": "agent-devops/1.0"}
    if jeton:
        entetes["Authorization"] = "Bearer " + jeton
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=entetes), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise ErreurApi(f"HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ErreurApi("service injoignable ou réponse illisible") from None


def dernier_commit_github(depot, branche="main"):
    """SHA et message du dernier commit de la branche d'un dépôt GitHub."""
    url = f"{GITHUB_API}/repos/{depot}/commits/{urllib.parse.quote(branche, safe='')}"
    try:
        c = _get(url, config.jeton_github()) or {}
    except ErreurApi as e:
        raise ErreurApi(f"GitHub : {e}") from None
    return {"sha": c.get("sha") or "", "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0]}


def _ecrire(methode, url, jeton, corps, timeout=30):
    """Écriture (POST, corps JSON). Seule lancer_workflow_github l'appelle."""
    entetes = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "agent-devops/1.0",
               "Authorization": "Bearer " + jeton}
    requete = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise ErreurApi(f"HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ErreurApi("service injoignable ou réponse illisible") from None


def lancer_workflow_github(depot, workflow, branche, entrees):
    """Lance un workflow GitHub Actions (POST /repos/{depot}/actions/workflows/{workflow}/dispatches), avec
    DEVOPS_ACTIONS_TOKEN uniquement. GitHub répond 204 sans corps ; il ne donne pas le numéro du run."""
    jeton = config.jeton_actions()
    if not jeton:
        raise ErreurApi("DEVOPS_ACTIONS_TOKEN absent")
    url = (f"{GITHUB_API}/repos/{depot}/actions/workflows/"
           f"{urllib.parse.quote(workflow, safe='')}/dispatches")
    try:
        _ecrire("POST", url, jeton, {"ref": branche, "inputs": dict(entrees)})
    except ErreurApi as e:
        raise ErreurApi(f"GitHub : {e}") from None


def _get_github(chemin):
    """GET sur l'API GitHub (lecture seule), avec le jeton de lecture facultatif."""
    try:
        return _get(GITHUB_API + chemin, config.jeton_github())
    except ErreurApi as e:
        raise ErreurApi(f"GitHub : {e}") from None


def runs_en_echec(depot, branche="main", limite=30):
    """Dernières exécutions de workflows terminées en échec sur une branche
    (GET /repos/{depot}/actions/runs?status=failure), de la plus récente à la plus ancienne."""
    chemin = (f"/repos/{depot}/actions/runs?status=failure&branch={urllib.parse.quote(branche, safe='')}"
              f"&per_page={int(limite)}")
    return [r for r in ((_get_github(chemin) or {}).get("workflow_runs") or []) if isinstance(r, dict)]


def jobs_du_run(depot, run_id):
    """Jobs d'une exécution, avec leurs étapes (GET /repos/{depot}/actions/runs/{id}/jobs)."""
    chemin = f"/repos/{depot}/actions/runs/{int(run_id)}/jobs?per_page=30"
    return [j for j in ((_get_github(chemin) or {}).get("jobs") or []) if isinstance(j, dict)]


def annotations_du_job(depot, job_id):
    """Annotations d'un job : message d'erreur explicite s'il y en a (GET /repos/{depot}/check-runs/{id}/annotations)."""
    chemin = f"/repos/{depot}/check-runs/{int(job_id)}/annotations?per_page=10"
    return [a for a in (_get_github(chemin) or []) if isinstance(a, dict)]


MAX_JOURNAL = 5_000_000  # octets : au-delà, le journal d'un job est jugé trop volumineux et n'est pas lu


class _RedirectionSansJeton(urllib.request.HTTPRedirectHandler):
    """Suit la redirection vers le stockage des journaux sans lui transmettre le jeton GitHub (https seulement)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            return None
        nouvelle = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nouvelle is not None:
            for h in ("Authorization", "authorization"):
                nouvelle.headers.pop(h, None)
                nouvelle.unredirected_hdrs.pop(h, None)
        return nouvelle


def _get_texte(url, jeton, timeout=30, maxi=MAX_JOURNAL):
    """GET d'un texte brut (lecture seule), avec redirection sans jeton. Donnée non fiable : jamais interprétée."""
    entetes = {"Accept": "application/vnd.github+json", "User-Agent": "agent-devops/1.0"}
    if jeton:
        entetes["Authorization"] = "Bearer " + jeton
    ouvreur = urllib.request.build_opener(_RedirectionSansJeton)
    try:
        with ouvreur.open(urllib.request.Request(url, headers=entetes), timeout=timeout) as resp:
            brut = resp.read(maxi + 1)
    except urllib.error.HTTPError as e:
        raise ErreurApi(f"HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ErreurApi("service injoignable ou réponse illisible") from None
    if len(brut) > maxi:
        raise ErreurApi("journal trop volumineux")
    return brut.decode("utf-8", errors="replace")


def journal_du_job(depot, job_id):
    """Journal brut d'un job (GET /repos/{depot}/actions/jobs/{id}/logs, redirigé vers un fichier temporaire).
    Demande la permission « Actions » en lecture. Lecture seule ; le texte est une donnée non fiable."""
    return _get_texte(f"{GITHUB_API}/repos/{depot}/actions/jobs/{int(job_id)}/logs", config.jeton_github())
