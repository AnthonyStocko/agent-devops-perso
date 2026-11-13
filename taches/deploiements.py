"""Vérifie qu'un correctif est bien déployé : dernier déploiement Render comparé au dernier commit GitHub."""
import clients
import config

ECHECS = {"build_failed", "update_failed", "pre_deploy_failed"}
EN_COURS = {"created", "queued", "build_in_progress", "update_in_progress", "pre_deploy_in_progress"}
LIBELLES = {
    "live": "Live", "deactivated": "Remplacé", "canceled": "Annulé", "created": "Créé", "queued": "En file",
    "build_in_progress": "Build en cours", "update_in_progress": "Mise en ligne en cours",
    "pre_deploy_in_progress": "Pré-déploiement en cours", "build_failed": "Échec pendant le build",
    "update_failed": "Échec pendant la mise en ligne", "pre_deploy_failed": "Échec du pré-déploiement",
}


def _resume(d):
    commit = d.get("commit") or {}
    statut = d.get("status") or "inconnu"
    return {"commit": commit.get("id") or "", "message": (commit.get("message") or "").split("\n")[0],
            "statut": statut, "statut_libelle": LIBELLES.get(statut, statut),
            "date": d.get("finishedAt") or d.get("createdAt") or ""}


def _meme(a, b):
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def verdict(dernier, en_ligne, reference):
    """Renvoie (code, phrase) : le correctif est-il en ligne ? `reference` = commit attendu (SHA ou préfixe)."""
    if dernier is None:
        return "inconnu", "Aucun déploiement trouvé sur Render."
    statut = dernier["statut"]
    if statut in ECHECS:
        return "echec", f"⚠️ Le dernier déploiement a échoué ({dernier['statut_libelle']}, commit {dernier['commit'][:7]})."
    if statut in EN_COURS:
        return "en_cours", f"Déploiement en cours ({dernier['statut_libelle']}), commit {dernier['commit'][:7]}."
    if statut != "live" or en_ligne is None:
        return "inconnu", f"Statut du dernier déploiement : {dernier['statut_libelle']}."
    if not reference:
        return "inconnu", "Commit de référence introuvable : comparaison impossible."
    if _meme(en_ligne["commit"], reference):
        return "a_jour", f"✅ Le commit {reference[:7]} est en ligne (Live)."
    return "commit_different", (f"⚠️ Commit en ligne {en_ligne['commit'][:7]} ≠ commit attendu {reference[:7]}.")


def verifier_agent(cle, commit_attendu=""):
    agent = config.AGENTS[cle]
    res = {"agent": cle, "nom": agent["nom"], "depot": agent["depot"]}
    service = config.service_id(cle)
    if not service:
        res.update(verdict="non_configure", resume=f"Variable {agent['service_env']} non définie.")
        return res
    try:
        deploys = clients.deploiements_render(service)
    except clients.ErreurApi as e:
        res.update(verdict="erreur", resume=str(e))
        return res
    dernier = _resume(deploys[0]) if deploys else None
    live = next((_resume(d) for d in deploys if d.get("status") == "live"), None)
    res["dernier_deploiement"] = dernier
    res["en_ligne"] = live
    reference, erreur_github = commit_attendu, ""
    if not reference:
        try:
            gh = clients.dernier_commit_github(agent["depot"])
            reference = gh["sha"]
            res["dernier_commit_github"] = gh
        except clients.ErreurApi as e:
            erreur_github = str(e)
    code, phrase = verdict(dernier, live, reference)
    if erreur_github and code != "echec":
        phrase += f" ({erreur_github})"
    res.update(verdict=code, resume=phrase)
    return res


def executer(params):
    """params : `agent` (une clé, sinon tous) et `commit` (SHA attendu, sinon le dernier commit GitHub)."""
    cle = params.get("agent") or ""
    if cle and cle not in config.AGENTS:
        return {"erreur": f"Agent inconnu : {cle}.", "agents_possibles": sorted(config.AGENTS)}
    cles = [cle] if cle else list(config.AGENTS)
    agents = [verifier_agent(c, params.get("commit") or "") for c in cles]
    return {"agents": agents, "tout_est_a_jour": all(a["verdict"] == "a_jour" for a in agents)}
