"""Vérifie qu'un correctif est bien déployé : dernier déploiement Render comparé au dernier commit GitHub.

Lecture seule : rien n'est jamais modifié, ni sur Render ni sur GitHub.
"""
from agent_devops import clients, config

ECHECS = {"build_failed", "update_failed", "pre_deploy_failed"}
EN_COURS = {"created", "queued", "build_in_progress", "update_in_progress", "pre_deploy_in_progress"}
LIBELLES = {
    "live": "Live", "deactivated": "Remplacé", "canceled": "Annulé", "created": "Créé", "queued": "En file",
    "build_in_progress": "Build en cours", "update_in_progress": "Mise en ligne en cours",
    "pre_deploy_in_progress": "Pré-déploiement en cours", "build_failed": "Échec pendant le build",
    "update_failed": "Échec pendant la mise en ligne", "pre_deploy_failed": "Échec du pré-déploiement",
}
ICONES = {"a_jour": "✅", "commit_different": "⚠️", "echec": "❌", "en_cours": "⏳"}


class ErreurDevops(Exception):
    """Demande impossible à traiter (non configuré, agent inconnu), avec un message sans secret."""


def _resume(d):
    commit = d.get("commit") or {}
    statut = d.get("status") or "inconnu"
    return {"commit": commit.get("id") or "", "message": (commit.get("message") or "").split("\n")[0],
            "statut": statut, "statut_libelle": LIBELLES.get(statut, statut),
            "date": d.get("finishedAt") or d.get("createdAt") or ""}


def _meme(a, b):
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def verdict(dernier, en_ligne, reference):
    """Renvoie (code, phrase) : le commit attendu (`reference`, SHA ou début de SHA) est-il en ligne ?"""
    if dernier is None:
        return "inconnu", "aucun déploiement trouvé sur Render."
    statut = dernier["statut"]
    if statut in ECHECS:
        reste = f" Toujours en ligne : {en_ligne['commit'][:7]}." if en_ligne else ""
        return "echec", (f"le dernier déploiement a échoué ({dernier['statut_libelle']}, "
                         f"commit {dernier['commit'][:7]}).{reste}")
    if statut in EN_COURS:
        return "en_cours", f"déploiement en cours ({dernier['statut_libelle']}), commit {dernier['commit'][:7]}."
    if statut != "live" or en_ligne is None:
        return "inconnu", f"statut du dernier déploiement : {dernier['statut_libelle']}."
    if not reference:
        return "inconnu", f"commit {en_ligne['commit'][:7]} en ligne, mais commit de référence introuvable."
    if _meme(en_ligne["commit"], reference):
        return "a_jour", f"le commit {reference[:7]} est en ligne."
    return "commit_different", f"commit en ligne {en_ligne['commit'][:7]}, commit attendu {reference[:7]}."


def verifier_agent(cle, commit_attendu=""):
    agent = config.AGENTS[cle]
    res = {"agent": cle, "nom": agent["nom"], "depot": agent["depot"]}
    service = config.service_id(cle)
    if not service:
        res.update(verdict="non_configure", resume=f"variable {agent['service_env'][0]} non définie.")
        return res
    try:
        deploys = clients.deploiements_render(service)
    except clients.ErreurApi as e:
        res.update(verdict="erreur", resume=f"{e}.")
        return res
    dernier = _resume(deploys[0]) if deploys else None
    live = next((_resume(d) for d in deploys if d.get("status") == "live"), None)
    res.update(dernier_deploiement=dernier, en_ligne=live)
    reference, erreur_github = commit_attendu, ""
    if not reference:
        try:
            gh = clients.dernier_commit_github(agent["depot"])
            reference, res["dernier_commit_github"] = gh["sha"], gh
        except clients.ErreurApi as e:
            erreur_github = str(e)
    code, phrase = verdict(dernier, live, reference)
    if erreur_github and code != "echec":
        phrase += f" ({erreur_github})"
    res.update(verdict=code, resume=phrase)
    return res


def verifier(agent="", commit=""):
    """Vérifie un agent (clé de config.AGENTS) ou tous. `commit` : SHA attendu, sinon le dernier commit GitHub."""
    agent, commit = str(agent or "").strip(), str(commit or "").strip()
    if not config.cle_render():
        raise ErreurDevops("Vérification des déploiements non configurée : ajoute la variable RENDER_API_KEY "
                           "(Render > Account Settings > API Keys).")
    if agent and agent not in config.AGENTS:
        raise ErreurDevops("Agent inconnu. Agents suivis : "
                           + ", ".join(a["nom"] for a in config.AGENTS.values()) + ".")
    agents = [verifier_agent(c, commit) for c in ([agent] if agent else config.AGENTS)]
    return {"agents": agents, "tout_est_a_jour": all(a["verdict"] == "a_jour" for a in agents)}


def texte(resultat):
    """Résultat lisible dans une discussion."""
    lignes = [f"- {ICONES.get(a['verdict'], '❔')} **{a['nom']}** : {a['resume']}" for a in resultat["agents"]]
    tete = ("**Déploiements Render : tout est à jour.**" if resultat["tout_est_a_jour"]
            else "**Déploiements Render** :")
    return tete + "\n" + "\n".join(lignes)


def executer(params):
    """Tâche du serveur HTTP. params : `agent` (une clé, sinon tous) et `commit` (SHA attendu)."""
    try:
        return verifier(params.get("agent"), params.get("commit"))
    except ErreurDevops as e:
        return {"erreur": str(e), "agents_possibles": sorted(config.AGENTS)}
