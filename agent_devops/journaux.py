"""Traitement des journaux GitHub Actions : masquage des secrets, puis extrait court autour de l'erreur.

Un journal est une donnée non fiable : il est seulement lu comme du texte, jamais exécuté, et les instructions
qu'il pourrait contenir ne sont pas suivies. Le masquage se fait AVANT tout extrait remonté.
"""
import re

LIGNES_EXTRAIT = 40      # lignes gardées autour de l'erreur
MAX_LIGNE = 300          # caractères par ligne
MAX_EXTRAIT = 5000       # caractères au total
MASQUE = "***"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_HORODATAGE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_MOTS_SECRETS = (r"[A-Za-z0-9_.-]*(?:TOKEN|SECRET|PASSW(?:OR)?D|PASSPHRASE|PHRASE|CREDENTIAL|API[_-]?KEY|ACCESS[_-]?KEY|"
                 r"PRIVATE[_-]?KEY|AUTH|COOKIE|SIGNATURE|DATABASE_URL|DB_URL|AGENT_URL|CRON_SECRET|SAUVEGARDE|"
                 r"PGPASSWORD|JWT|KEY)[A-Za-z0-9_.-]*")
_REGLES = (
    # blocs de clé privée
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), MASQUE),
    # URL avec identifiants : schéma://utilisateur:mot_de_passe@hôte
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@:]*:?[^\s/@]*@"), r"\1" + MASQUE + "@"),
    # URL de base de données ou de l'agent : le reste de l'URL est masqué
    (re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://\S+", re.I), MASQUE),
    # en-têtes d'autorisation
    (re.compile(r"(?i)\b(Authorization\s*[:=]\s*(?:Bearer|Basic|token)?\s*)[^\s\"']+"), r"\1" + MASQUE),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASQUE),
    # jetons à préfixe connu
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|"
                r"sb[a-z]?_[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|"
                r"glpat-[A-Za-z0-9_-]{16,})"), MASQUE),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), MASQUE),
    # NOM_SENSIBLE=valeur, NOM_SENSIBLE: valeur, "nom_sensible": "valeur" (la valeur, quotée ou non, est masquée)
    (re.compile(r"(?i)(\b" + _MOTS_SECRETS + r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"), r"\1" + MASQUE),
    # option de ligne de commande : --password valeur, --token=valeur
    (re.compile(r"(?i)(--[a-z-]*(?:token|secret|passw(?:or)?d|key)[a-z-]*[ =])[^\s]+"), r"\1" + MASQUE),
    # longues chaînes opaques (hexadécimal ou base64 de 40 caractères et plus)
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), MASQUE),
    (re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{48,}={0,2}(?![A-Za-z0-9+/=_-])"), MASQUE),
)
_GENERIQUE = re.compile(r"process completed with exit code \d+|^error: process completed", re.I)


def masquer(texte):
    """Remplace par *** tout ce qui ressemble à un secret (jeton, mot de passe, URL avec identifiants…)."""
    texte = str(texte or "")
    for regle, remplacement in _REGLES:
        texte = regle.sub(remplacement, texte)
    return texte


def _lignes_propres(brut):
    """Lignes du journal sans horodatage ni codes de couleur ; marqueurs GitHub conservés pour l'erreur seule."""
    lignes = []
    for ligne in str(brut or "").replace("\r", "").split("\n"):
        ligne = _HORODATAGE.sub("", _ANSI.sub("", ligne)).rstrip()
        if ligne.startswith(("##[group]", "##[endgroup]")):
            continue
        if ligne.startswith("##[error]"):
            ligne = "ERREUR : " + ligne[len("##[error]"):].strip()
        elif ligne.startswith(("##[warning]", "##[notice]", "##[debug]", "##[command]")):
            ligne = ligne.split("]", 1)[1].strip()
        lignes.append(ligne)
    return lignes


def analyser(brut):
    """(extrait, message) d'un journal brut, tous deux masqués.

    L'extrait : les LIGNES_EXTRAIT dernières lignes jusqu'à la dernière erreur signalée (`##[error]`) et quelques
    lignes après ; sans erreur signalée, la fin du journal. Le message : la dernière erreur précise, sinon la
    ligne qui précède l'erreur générique (« Process completed with exit code 1 »), sinon chaîne vide."""
    lignes = [masquer(l) for l in _lignes_propres(brut)]
    while lignes and not lignes[-1].strip():
        lignes.pop()
    if not lignes:
        return "", ""
    erreurs = [i for i, l in enumerate(lignes) if l.startswith("ERREUR :")]
    fin = min(len(lignes), erreurs[-1] + 3) if erreurs else len(lignes)
    extrait = [l[:MAX_LIGNE] for l in lignes[max(0, fin - LIGNES_EXTRAIT):fin]]
    texte = "\n".join(extrait)
    if len(texte) > MAX_EXTRAIT:
        texte = "…" + texte[-(MAX_EXTRAIT - 1):]
    message = ""
    for i in reversed(erreurs):
        contenu = lignes[i][len("ERREUR :"):].strip()
        if contenu and not _GENERIQUE.search(contenu):
            message = contenu
            break
    if not message and erreurs:
        precedentes = [l.strip() for l in lignes[:erreurs[-1]] if l.strip() and not l.startswith("ERREUR :")]
        message = precedentes[-1] if precedentes else ""
    return texte, message[:MAX_LIGNE]
