"""Règle une variable d'environnement d'un agent du serveur P2, par une demande que le serveur applique.

L'agent devops n'a aucun accès aux fichiers de secrets du serveur ni à Docker. Il dépose une demande (un
fichier JSON) dans le dossier partagé `/demandes` ; le script `appliquer-demandes.py` du dépôt
serveur-agents la vérifie de nouveau avec les mêmes garde-fous, l'écrit dans `env/<agent>.env`, puis
redémarre l'agent concerné.

Elle n'est pas servie par le serveur HTTP (qui reste en lecture seule) : elle s'appelle en bibliothèque, en
deux temps, pour que l'appelant puisse demander une confirmation.

    demande = preparer(agent, nom, valeur)   # vérifie tout, ne dépose rien
    ...                                      # l'appelant montre demande["resume"] et attend un « oui »
    resultat = definir(agent, nom, valeur)   # dépose la demande

Garde-fous : agents autorisés seulement, noms de réglage seulement (jamais un secret : mot de passe, jeton,
clé), aucune suppression, aucune variable réglée par docker-compose.yml, et les valeurs en place ne sont
jamais lues.
"""
import datetime
import json
import os
import re
import secrets

from agent_devops import config
from agent_devops.taches.deploiements import ErreurDevops

NOM_VALIDE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
# Un secret ne passe jamais par ici : la valeur est affichée pour confirmation et reste dans la discussion.
MOTS_SECRETS = ("PASSWORD", "PASSWD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "OAUTH", "PRIVATE", "DATABASE_URL")
# Variables du système, ou réglées par docker-compose.yml (adresses, ports, dossiers) : jamais modifiées ici.
# RENDER est réservée : la définir ferait croire aux agents qu'ils tournent sur Render.
RESERVEES = ("PORT", "HOST", "DATA_DIR", "HUB_URL", "EMPLOI_URL", "PERSO_URL", "TZ", "FORWARDED_ALLOW_IPS",
             "RENDER", "PATH", "HOME", "PYTHONPATH")
VALEUR_MAX = 2000


def _verifier(agent, nom, valeur):
    agent, nom = str(agent or "").strip(), str(nom or "").strip()
    valeur = "" if valeur is None else str(valeur).strip()
    if agent not in config.AGENTS_VARIABLES:
        raise ErreurDevops("Agent inconnu. Agents dont je peux régler une variable : "
                           + ", ".join(config.AGENTS[a]["nom"] for a in config.AGENTS_VARIABLES) + ".")
    infos = config.AGENTS[agent]
    if not NOM_VALIDE.fullmatch(nom):
        raise ErreurDevops("Nom de variable invalide : majuscules, chiffres et soulignés seulement, en commençant "
                           "par une lettre (par exemple JOB_ALERT_SENDERS).")
    if any(mot in nom for mot in MOTS_SECRETS):
        raise ErreurDevops(f"« {nom} » ressemble à un secret (mot de passe, jeton, clé) : je ne règle pas les "
                           f"secrets, modifie-le directement dans env/{infos['service']}.env sur le serveur.")
    if nom in RESERVEES or nom.startswith("RENDER_"):
        raise ErreurDevops(f"« {nom} » est une variable réservée : je ne la modifie pas.")
    if not valeur:
        raise ErreurDevops("Il manque la valeur de la variable (je ne vide ni ne supprime une variable).")
    if len(valeur) > VALEUR_MAX or any(ord(c) < 32 for c in valeur):
        raise ErreurDevops(f"Valeur refusée : une seule ligne, {VALEUR_MAX} caractères au plus.")
    dossier = config.dossier_demandes()
    if not os.path.isdir(dossier) or not os.access(dossier, os.W_OK):
        raise ErreurDevops("Réglage des variables indisponible : le dossier des demandes du serveur n'est pas "
                           "monté dans l'agent chef.")
    return agent, nom, valeur, infos, dossier


def preparer(agent, nom, valeur):
    """Vérifie la demande sans rien déposer. Renvoie de quoi demander confirmation."""
    agent, nom, valeur, infos, _ = _verifier(agent, nom, valeur)
    resume = (f"- Agent : {infos['nom']}\n- Variable : {nom}\n- Valeur : {valeur}\n"
              "La variable est créée, ou sa valeur remplacée si elle existe déjà (l'ancienne valeur n'est pas lue). "
              f"Le serveur l'applique dans la minute, puis redémarre « {infos['nom']} » : il est indisponible "
              "quelques secondes.")
    return {"agent": agent, "nom_agent": infos["nom"], "nom": nom, "valeur": valeur, "resume": resume}


def definir(agent, nom, valeur):
    """Dépose la demande dans le dossier partagé (écriture atomique). Le serveur l'applique ensuite."""
    agent, nom, valeur, infos, dossier = _verifier(agent, nom, valeur)
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    ident = maintenant.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    demande = {"id": ident, "agent": agent, "service": infos["service"], "nom": nom, "valeur": valeur,
               "demande_le": maintenant.isoformat(timespec="seconds")}
    temporaire = os.path.join(dossier, f".{ident}.tmp")
    final = os.path.join(dossier, f"{ident}.json")
    try:
        fd = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(demande, f, ensure_ascii=False)
        os.replace(temporaire, final)
    except OSError:
        try:
            os.unlink(temporaire)
        except OSError:
            pass
        raise ErreurDevops(f"La demande pour {nom} n'a pas pu être déposée sur le serveur. Rien n'a changé.") from None
    return {"agent": agent, "nom_agent": infos["nom"], "nom": nom, "valeur": valeur, "demande": ident,
            "deploiement": "en_file",
            "resume": (f"✅ Demande enregistrée : {nom} pour « {infos['nom']} ». Le serveur l'applique dans la "
                       "minute et redémarre l'agent ; demande-moi ensuite de vérifier les déploiements.")}
