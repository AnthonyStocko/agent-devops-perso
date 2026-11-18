"""Lance un workflow GitHub Actions de la liste blanche (config.WORKFLOWS, copie de celle de CLAUDE.md).

Seconde écriture de l'agent devops. Elle n'est pas servie par le serveur HTTP (qui reste en lecture seule) :
elle s'appelle en bibliothèque, en deux temps, pour que l'appelant puisse demander une confirmation.

    demande = preparer("instagram-supabase", {"etape": "deployer"})   # vérifie tout, n'appelle rien
    ...                                                                # l'appelant montre demande["resume"]
    resultat = declencher("instagram-supabase", {"etape": "deployer"}) # lance un seul run

Garde-fous : workflows et valeurs d'entrée de la liste blanche seulement, branche main, jeton dédié
DEVOPS_ACTIONS_TOKEN (jamais GITHUB_TOKEN ni DEV_GITHUB_TOKEN), un seul run par appel, aucune relance.
"""
from agent_devops import clients, config
from agent_devops.taches.deploiements import ErreurDevops


def _liste():
    return ", ".join(f"{cle} ({w['nom']})" for cle, w in config.WORKFLOWS.items())


def _verifier(cle, entrees):
    cle = str(cle or "").strip()
    if cle not in config.WORKFLOWS:
        raise ErreurDevops("Workflow non autorisé. Workflows que je peux lancer : " + _liste() + ".")
    w = config.WORKFLOWS[cle]
    if entrees is None:
        entrees = {}
    if not isinstance(entrees, dict):
        raise ErreurDevops("Les entrées du workflow doivent être un dictionnaire nom -> valeur.")
    entrees = {str(k).strip(): str(v if v is not None else "").strip() for k, v in entrees.items()}
    inconnues = sorted(set(entrees) - set(w["entrees"]))
    if inconnues:
        raise ErreurDevops(f"Entrée non autorisée pour « {w['nom']} » : {', '.join(inconnues)}.")
    for nom, valeurs in w["entrees"].items():
        valeur = entrees.get(nom, "")
        if valeur not in valeurs:
            raise ErreurDevops(f"Pour « {w['nom']} », l'entrée {nom} doit valoir "
                               + " ou ".join(sorted(valeurs)) + (f" (reçu : {valeur[:40]})." if valeur else "."))
    if not config.jeton_actions():
        raise ErreurDevops("Lancement des workflows non configuré : ajoute la variable DEVOPS_ACTIONS_TOKEN "
                           "(jeton GitHub à granularité fine, limité au dépôt mon-guide-agent-instagram, "
                           "permission Actions en lecture et écriture).")
    return cle, w, entrees


def _lien(w):
    return f"https://github.com/{w['depot']}/actions/workflows/{w['workflow']}"


def preparer(cle, entrees=None):
    """Vérifie la demande sans appeler aucun service ni rien modifier. Renvoie de quoi demander confirmation."""
    cle, w, entrees = _verifier(cle, entrees)
    effets = "\n".join(f"- {nom} = {valeur} : {w['entrees'][nom][valeur]}" for nom, valeur in entrees.items())
    resume = (f"- Workflow : {w['nom']} ({w['workflow']}, dépôt {w['depot']}, branche {config.BRANCHE_WORKFLOWS})\n"
              f"{effets}\nUn seul run est lancé, sans relance automatique ; il se suit dans GitHub Actions.")
    return {"cle": cle, "nom": w["nom"], "entrees": entrees, "resume": resume}


def declencher(cle, entrees=None):
    """Lance un seul run du workflow. Aucune relance, même en cas d'échec ou de réponse incertaine."""
    cle, w, entrees = _verifier(cle, entrees)
    try:
        clients.lancer_workflow_github(w["depot"], w["workflow"], config.BRANCHE_WORKFLOWS, entrees)
    except clients.ErreurApi as e:
        message = str(e)
        if "injoignable" in message:
            raise ErreurDevops(f"Pas de réponse de GitHub ({message}) : le run a peut-être été lancé. Vérifie dans "
                               f"GitHub Actions avant de redemander : {_lien(w)}") from None
        if "401" in message or "403" in message:
            cause = "GitHub refuse le jeton DEVOPS_ACTIONS_TOKEN (expiré, ou sans la permission Actions en écriture)"
        elif "404" in message:
            cause = "workflow introuvable, ou DEVOPS_ACTIONS_TOKEN n'a pas accès à ce dépôt"
        elif "422" in message:
            cause = "GitHub refuse les entrées ou la branche"
        else:
            cause = message
        raise ErreurDevops(f"« {w['nom']} » n'a pas été lancé ({cause}). Rien n'a changé.") from None
    valeurs = ", ".join(f"{k} = {v}" for k, v in entrees.items())
    return {"cle": cle, "nom": w["nom"], "entrees": entrees, "lien": _lien(w),
            "resume": (f"✅ « {w['nom']} » lancé ({valeurs}). Le run prend quelques minutes ; "
                       f"suis-le dans GitHub Actions : {_lien(w)}")}
