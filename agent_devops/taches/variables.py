"""Règle une variable d'environnement d'un agent hébergé sur Render, puis lance le déploiement qui l'applique.

C'est la seule écriture de l'agent devops. Elle n'est pas servie par le serveur HTTP (qui reste en lecture
seule) : elle s'appelle en bibliothèque, en deux temps, pour que l'appelant puisse demander une confirmation.

    demande = preparer(agent, nom, valeur)   # vérifie tout, n'appelle aucun service, ne modifie rien
    ...                                      # l'appelant montre demande["resume"] et attend un « oui »
    resultat = definir(agent, nom, valeur)   # enregistre la variable et lance le déploiement

Garde-fous : agents suivis seulement, noms de réglage seulement (jamais un secret : mot de passe, jeton, clé),
aucune suppression, et les valeurs déjà en place ne sont jamais lues.
"""
import re
import time

from agent_devops import clients, config
from agent_devops.taches.deploiements import EN_COURS, ErreurDevops

NOM_VALIDE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
# Un secret ne passe jamais par ici : la valeur est affichée pour confirmation et reste dans la discussion.
MOTS_SECRETS = ("PASSWORD", "PASSWD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "OAUTH", "PRIVATE", "DATABASE_URL")
# Variables fournies ou réservées par Render, ou qui désignent les services eux-mêmes
RESERVEES = ("PORT", "RENDER", "PATH", "HOME", "PYTHONPATH")
VALEUR_MAX = 2000
ATTENTE = 3   # secondes laissées à Render pour lancer lui-même un déploiement après le changement


def _verifier(agent, nom, valeur):
    agent, nom = str(agent or "").strip(), str(nom or "").strip()
    valeur = "" if valeur is None else str(valeur).strip()
    if not config.cle_render():
        raise ErreurDevops("Réglage des variables non configuré : ajoute la variable RENDER_API_KEY "
                           "(Render > Account Settings > API Keys).")
    if agent not in config.AGENTS:
        raise ErreurDevops("Agent inconnu. Agents suivis : "
                           + ", ".join(a["nom"] for a in config.AGENTS.values()) + ".")
    infos = config.AGENTS[agent]
    service = config.service_id(agent)
    if not service:
        raise ErreurDevops(f"Service Render de « {infos['nom']} » inconnu : variable {infos['service_env'][0]} "
                           "non définie.")
    if not NOM_VALIDE.fullmatch(nom):
        raise ErreurDevops("Nom de variable invalide : majuscules, chiffres et soulignés seulement, en commençant "
                           "par une lettre (par exemple JOB_ALERT_SENDERS).")
    if any(mot in nom for mot in MOTS_SECRETS):
        raise ErreurDevops(f"« {nom} » ressemble à un secret (mot de passe, jeton, clé) : je ne règle pas les "
                           "secrets, fais-le directement dans Render.")
    if nom in RESERVEES or nom.startswith("RENDER_"):
        raise ErreurDevops(f"« {nom} » est une variable réservée : je ne la modifie pas.")
    if not valeur:
        raise ErreurDevops("Il manque la valeur de la variable (je ne vide ni ne supprime une variable).")
    if len(valeur) > VALEUR_MAX or any(ord(c) < 32 for c in valeur):
        raise ErreurDevops(f"Valeur refusée : une seule ligne, {VALEUR_MAX} caractères au plus.")
    return agent, nom, valeur, infos, service


def preparer(agent, nom, valeur):
    """Vérifie la demande sans appeler aucun service ni rien modifier. Renvoie de quoi demander confirmation."""
    agent, nom, valeur, infos, _ = _verifier(agent, nom, valeur)
    resume = (f"- Agent : {infos['nom']}\n- Variable : {nom}\n- Valeur : {valeur}\n"
              "La variable est créée, ou sa valeur remplacée si elle existe déjà (l'ancienne valeur n'est pas lue). "
              f"« {infos['nom']} » est ensuite redéployé pour l'appliquer : il est indisponible ou lent "
              "quelques minutes.")
    return {"agent": agent, "nom_agent": infos["nom"], "nom": nom, "valeur": valeur, "resume": resume}


def _deploiement_en_cours(service):
    try:
        deploys = clients.deploiements_render(service, limite=1)
    except clients.ErreurApi:
        return False
    return bool(deploys) and (deploys[0].get("status") or "") in EN_COURS


def definir(agent, nom, valeur, attente=ATTENTE):
    """Enregistre la variable sur Render, puis s'assure qu'un déploiement l'applique : celui que Render lance
    de lui-même après le changement s'il y en a un, sinon un déploiement demandé ici."""
    agent, nom, valeur, infos, service = _verifier(agent, nom, valeur)
    try:
        clients.definir_variable_render(service, nom, valeur)
    except clients.ErreurApi as e:
        raise ErreurDevops(f"La variable {nom} n'a pas été enregistrée ({e}). Rien n'a changé.") from None
    res = {"agent": agent, "nom_agent": infos["nom"], "nom": nom, "valeur": valeur}
    time.sleep(max(0, attente))
    if _deploiement_en_cours(service):
        res["deploiement"] = "en_cours"
    else:
        try:
            clients.lancer_deploiement_render(service)
            res["deploiement"] = "lance"
        except clients.ErreurApi as e:
            res.update(deploiement="a_lancer", resume=(
                f"⚠️ Variable {nom} enregistrée pour « {infos['nom']} », mais le déploiement n'a pas pu être lancé "
                f"({e}) : elle ne sera prise en compte qu'au prochain déploiement (Render > Manual Deploy)."))
            return res
    res["resume"] = (f"✅ Variable {nom} enregistrée pour « {infos['nom']} ». Le déploiement qui l'applique est "
                     "en cours : compte quelques minutes, puis demande-moi de vérifier les déploiements.")
    return res
