"""Appels HTTP vers Render et GitHub. Aucun jeton n'est jamais écrit dans un message d'erreur.

Tout est en lecture seule (GET), sauf deux écritures sur Render, réservées à la tâche `variables` :
enregistrer une variable d'environnement et lancer le déploiement qui l'applique.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from agent_devops import config

RENDER_API = "https://api.render.com/v1"
GITHUB_API = "https://api.github.com"


class ErreurApi(Exception):
    """Erreur d'un service externe, avec un message sans secret."""


def _get(url, jeton, timeout=20):
    entetes = {"Accept": "application/json", "User-Agent": "agent-devops/1.0"}
    if jeton:
        entetes["Authorization"] = "Bearer " + jeton
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=entetes), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise ErreurApi(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ErreurApi("service injoignable ou réponse illisible") from None


def deploiements_render(service, limite=5):
    """Derniers déploiements d'un service Render, du plus récent au plus ancien (GET /v1/services/{id}/deploys)."""
    if not config.cle_render():
        raise ErreurApi("RENDER_API_KEY absente")
    url = f"{RENDER_API}/services/{urllib.parse.quote(service, safe='')}/deploys?limit={int(limite)}"
    try:
        brut = _get(url, config.cle_render()) or []
    except ErreurApi as e:
        raise ErreurApi(f"Render : {e}") from None
    # Render renvoie soit [{"deploy": {...}, "cursor": ...}], soit directement les déploiements
    return [d.get("deploy", d) for d in brut if isinstance(d, dict)]


def dernier_commit_github(depot, branche="main"):
    """SHA et message du dernier commit de la branche d'un dépôt GitHub."""
    url = f"{GITHUB_API}/repos/{depot}/commits/{urllib.parse.quote(branche, safe='')}"
    try:
        c = _get(url, config.jeton_github()) or {}
    except ErreurApi as e:
        raise ErreurApi(f"GitHub : {e}") from None
    return {"sha": c.get("sha") or "", "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0]}


def _ecrire(methode, url, jeton, corps, timeout=30):
    """Écriture sur Render (PUT ou POST, corps JSON). Seules les deux fonctions ci-dessous l'appellent."""
    entetes = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "agent-devops/1.0",
               "Authorization": "Bearer " + jeton}
    requete = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise ErreurApi(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ErreurApi("service injoignable ou réponse illisible") from None


def definir_variable_render(service, nom, valeur):
    """Crée la variable d'environnement d'un service Render, ou remplace sa valeur
    (PUT /v1/services/{id}/env-vars/{nom}). Les valeurs existantes ne sont jamais lues."""
    if not config.cle_render():
        raise ErreurApi("RENDER_API_KEY absente")
    url = (f"{RENDER_API}/services/{urllib.parse.quote(service, safe='')}"
           f"/env-vars/{urllib.parse.quote(nom, safe='')}")
    try:
        _ecrire("PUT", url, config.cle_render(), {"value": valeur})
    except ErreurApi as e:
        raise ErreurApi(f"Render : {e}") from None


def lancer_deploiement_render(service):
    """Lance un déploiement du service Render, sans vider le cache (POST /v1/services/{id}/deploys)."""
    if not config.cle_render():
        raise ErreurApi("RENDER_API_KEY absente")
    url = f"{RENDER_API}/services/{urllib.parse.quote(service, safe='')}/deploys"
    try:
        _ecrire("POST", url, config.cle_render(), {"clearCache": "do_not_clear"})
    except ErreurApi as e:
        raise ErreurApi(f"Render : {e}") from None
