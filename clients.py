"""Appels HTTP vers Render et GitHub (lecture seule). Aucun jeton n'est jamais écrit dans un message d'erreur."""
import json
import urllib.error
import urllib.parse
import urllib.request

import config

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
