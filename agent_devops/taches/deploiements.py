"""Vérifie qu'un correctif est bien déployé sur le serveur P2 : commit en service comparé au dernier commit GitHub.

L'état vient du fichier écrit par le serveur (`mettre-a-jour.sh` du dépôt serveur-agents), monté en lecture
seule dans le conteneur : l'agent devops n'a aucun accès à Docker. Lecture seule : rien n'est jamais modifié.

Forme du fichier (une entrée par service Docker Compose) :

    {"genere_le": "2026-11-26T16:40:00+01:00",
     "services": {"agent-emploi": {
         "commit_en_service": "<sha>",            # commit de l'image qui tourne
         "derniere_tentative": {"commit": "<sha>", "statut": "reussi" | "echec" | "en_cours",
                                "date": "...", "erreur": "..."},
         "conteneur": {"etat": "running", "sante": "healthy" | "unhealthy" | "starting" | ""}}}}
"""
import datetime
import json

from agent_devops import clients, config

ICONES = {"a_jour": "✅", "commit_different": "⚠️", "echec": "❌", "en_cours": "⏳", "hors_service": "🛑"}
ETAT_PERIME_MINUTES = 15   # le serveur réécrit l'état toutes les 5 minutes


class ErreurDevops(Exception):
    """Demande impossible à traiter (non configuré, agent inconnu), avec un message sans secret."""


def lire_etat():
    """Contenu du fichier d'état, ou ErreurDevops s'il est absent ou illisible."""
    chemin = config.fichier_etat()
    try:
        with open(chemin, encoding="utf-8") as f:
            etat = json.load(f)
    except FileNotFoundError:
        raise ErreurDevops("État des déploiements introuvable : le dossier etat/ du serveur n'est pas monté, ou "
                           "la mise à jour automatique (mettre-a-jour.sh) n'a pas encore tourné.") from None
    except (OSError, ValueError):
        raise ErreurDevops("État des déploiements illisible sur le serveur.") from None
    if not isinstance(etat, dict) or not isinstance(etat.get("services"), dict):
        raise ErreurDevops("État des déploiements illisible sur le serveur.")
    return etat


def age_minutes(etat, maintenant=None):
    """Âge du fichier d'état en minutes, ou None si sa date est absente."""
    try:
        genere = datetime.datetime.fromisoformat(str(etat.get("genere_le")))
    except ValueError:
        return None
    if genere.tzinfo is None:
        genere = genere.replace(tzinfo=datetime.timezone.utc)
    maintenant = maintenant or datetime.datetime.now(datetime.timezone.utc)
    return max(0, int((maintenant - genere).total_seconds() // 60))


def _meme(a, b):
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def verdict(service, reference):
    """Renvoie (code, phrase) : le commit attendu (`reference`, SHA ou début de SHA) est-il en service ?"""
    if not service:
        return "inconnu", "absent de l'état du serveur."
    en_service = str(service.get("commit_en_service") or "")
    tentative = service.get("derniere_tentative") or {}
    conteneur = service.get("conteneur") or {}
    if tentative.get("statut") == "en_cours":
        return "en_cours", f"mise à jour en cours vers le commit {str(tentative.get('commit') or '')[:7]}."
    if conteneur.get("etat") != "running":
        return "hors_service", f"le conteneur ne tourne pas (état : {conteneur.get('etat') or 'inconnu'})."
    if conteneur.get("sante") == "unhealthy":
        return "hors_service", "le conteneur tourne mais ne répond plus (contrôle de santé en échec)."
    if tentative.get("statut") == "echec":
        erreur = str(tentative.get("erreur") or "").strip()
        detail = f" : {erreur[:200]}" if erreur else ""
        reste = f" Toujours en service : {en_service[:7]}." if en_service else ""
        return "echec", (f"la dernière mise à jour a échoué (commit {str(tentative.get('commit') or '')[:7]})"
                         f"{detail}.{reste}")
    if not en_service:
        return "inconnu", "commit en service inconnu."
    if not reference:
        return "inconnu", f"commit {en_service[:7]} en service, mais commit de référence introuvable."
    if _meme(en_service, reference):
        return "a_jour", f"le commit {reference[:7]} est en service."
    return "commit_different", f"commit en service {en_service[:7]}, commit attendu {reference[:7]}."


def verifier_agent(cle, etat, commit_attendu=""):
    agent = config.AGENTS[cle]
    res = {"agent": cle, "nom": agent["nom"], "depot": agent["depot"], "service": agent["service"]}
    service = etat["services"].get(agent["service"])
    if isinstance(service, dict):
        res.update(en_service=service.get("commit_en_service") or "",
                   derniere_tentative=service.get("derniere_tentative") or {},
                   conteneur=service.get("conteneur") or {})
    reference, erreur_github = commit_attendu, ""
    if not reference:
        try:
            gh = clients.dernier_commit_github(agent["depot"])
            reference, res["dernier_commit_github"] = gh["sha"], gh
        except clients.ErreurApi as e:
            erreur_github = str(e)
    code, phrase = verdict(service if isinstance(service, dict) else None, reference)
    if erreur_github and code not in ("echec", "hors_service"):
        phrase += f" ({erreur_github})"
    res.update(verdict=code, resume=phrase)
    return res


def verifier(agent="", commit=""):
    """Vérifie un agent (clé de config.AGENTS) ou tous. `commit` : SHA attendu, sinon le dernier commit GitHub."""
    agent, commit = str(agent or "").strip(), str(commit or "").strip()
    if agent and agent not in config.AGENTS:
        raise ErreurDevops("Agent inconnu. Agents suivis : "
                           + ", ".join(a["nom"] for a in config.AGENTS.values()) + ".")
    etat = lire_etat()
    agents = [verifier_agent(c, etat, commit) for c in ([agent] if agent else config.AGENTS)]
    age = age_minutes(etat)
    return {"agents": agents, "tout_est_a_jour": all(a["verdict"] == "a_jour" for a in agents),
            "etat_genere_le": etat.get("genere_le") or "", "etat_age_minutes": age,
            "etat_perime": age is None or age > ETAT_PERIME_MINUTES}


def texte(resultat):
    """Résultat lisible dans une discussion."""
    lignes = [f"- {ICONES.get(a['verdict'], '❔')} **{a['nom']}** : {a['resume']}" for a in resultat["agents"]]
    tete = ("**Serveur P2 : tout est à jour.**" if resultat["tout_est_a_jour"] else "**Serveur P2** :")
    if resultat.get("etat_perime"):
        age = resultat.get("etat_age_minutes")
        quand = f"il y a {age} min" if age is not None else "à une date inconnue"
        lignes.append(f"⚠️ État relevé {quand} : la mise à jour automatique du serveur est peut-être arrêtée.")
    return tete + "\n" + "\n".join(lignes)


def executer(params):
    """Tâche du serveur HTTP. params : `agent` (une clé, sinon tous) et `commit` (SHA attendu)."""
    try:
        return verifier(params.get("agent"), params.get("commit"))
    except ErreurDevops as e:
        return {"erreur": str(e), "agents_possibles": sorted(config.AGENTS)}
