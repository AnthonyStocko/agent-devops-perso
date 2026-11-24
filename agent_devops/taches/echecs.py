"""Détecte les exécutions GitHub Actions en échec sur les dépôts du périmètre, pour les remonter à l'agent chef.

Lecture seule : uniquement des GET sur GitHub. Rien n'est corrigé, relancé ni annulé ici : c'est l'agent chef
qui décide si un correctif est nécessaire et le demande à l'agent développeur.

Pas de doublon : chaque échec porte une clé stable (`dépôt#run#tentative`). L'appelant (l'agent chef) garde les
clés déjà traitées et les repasse dans `deja_signales` ; elles ne sont alors plus renvoyées. L'agent ne garde
aucun état : un appel est sans effet de bord.
"""
import datetime

from agent_devops import clients, config
from agent_devops.taches.deploiements import ErreurDevops

HEURES_PAR_DEFAUT = 24
HEURES_MAX = 24 * 14
MAX_RESUME = 400


def cle_echec(depot, run):
    return f"{depot}#{run.get('id')}#{run.get('run_attempt') or 1}"


def _date(texte):
    try:
        return datetime.datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None


def _une_ligne(texte, maxi=MAX_RESUME):
    texte = " ".join(str(texte or "").split())
    return texte if len(texte) <= maxi else texte[: maxi - 1] + "…"


def _cause(depot, run):
    """(cause, résumé) d'une exécution : job et étape en échec, puis message d'annotation s'il y en a un.
    Les journaux bruts ne sont pas lus (ils peuvent contenir des secrets) ; un échec de lecture ne bloque pas."""
    try:
        jobs = clients.jobs_du_run(depot, run["id"])
    except clients.ErreurApi:
        jobs = []
    ko = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out")]
    if not ko:
        return "cause indéterminée", f"Conclusion : {run.get('conclusion') or 'failure'} (détail des jobs indisponible)."
    job = ko[0]
    etape = next((s for s in (job.get("steps") or []) if s.get("conclusion") in ("failure", "timed_out")), None)
    cause = f"job « {job.get('name')} »" + (f", étape « {etape.get('name')} »" if etape else "")
    if job.get("conclusion") == "timed_out":
        cause += " (délai dépassé)"
    messages = []
    try:
        for a in clients.annotations_du_job(depot, job["id"]):
            if a.get("annotation_level") == "failure" and a.get("message"):
                messages.append(_une_ligne(a["message"], 200))
    except clients.ErreurApi:
        pass
    resume = " ; ".join(messages[:2]) or f"Échec du {cause}, sans message d'erreur explicite."
    if len(ko) > 1:
        resume += f" ({len(ko)} jobs en échec.)"
    return cause, _une_ligne(resume)


def depots_surveilles():
    """Dépôts du périmètre : agents suivis et dépôts des workflows de la liste blanche, sans doublon."""
    depots = [a["depot"] for a in config.AGENTS.values()] + [w["depot"] for w in config.WORKFLOWS.values()]
    return list(dict.fromkeys(depots))


def detecter(deja_signales=(), depuis_heures=HEURES_PAR_DEFAUT, depot=""):
    """Échecs récents de GitHub Actions (branche main) pas encore signalés.

    `deja_signales` : clés déjà remontées, à ne pas renvoyer. `depuis_heures` : fenêtre de recherche.
    `depot` : un seul dépôt du périmètre, sinon tous."""
    depot = str(depot or "").strip()
    depots = depots_surveilles()
    if depot and depot not in depots:
        raise ErreurDevops("Dépôt hors périmètre. Dépôts surveillés : " + ", ".join(depots) + ".")
    try:
        heures = int(depuis_heures or HEURES_PAR_DEFAUT)
    except (TypeError, ValueError):
        raise ErreurDevops("`depuis_heures` doit être un nombre d'heures.") from None
    heures = max(1, min(heures, HEURES_MAX))
    vus = {str(c).strip() for c in (deja_signales or ()) if str(c).strip()}
    limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=heures)
    nouveaux, ignores, controles = [], 0, []
    for d in ([depot] if depot else depots):
        try:
            runs = clients.runs_en_echec(d, config.BRANCHE_WORKFLOWS)
        except clients.ErreurApi as e:
            controles.append({"depot": d, "etat": "erreur", "detail": str(e)})
            continue
        controles.append({"depot": d, "etat": "ok"})
        for run in runs:
            date = _date(run.get("updated_at") or run.get("created_at"))
            if date and date < limite:
                continue
            cle = cle_echec(d, run)
            if cle in vus:
                ignores += 1
                continue
            vus.add(cle)  # un même run n'est jamais renvoyé deux fois dans une réponse
            cause, resume = _cause(d, run)
            nouveaux.append({
                "cle": cle, "depot": d, "workflow": run.get("name") or run.get("path") or "",
                "run_id": run.get("id"), "tentative": run.get("run_attempt") or 1,
                "evenement": run.get("event") or "", "branche": run.get("head_branch") or "",
                "commit": run.get("head_sha") or "", "date": run.get("updated_at") or run.get("created_at") or "",
                "url": run.get("html_url") or "", "cause": cause, "resume": resume,
            })
    erreurs = [c for c in controles if c["etat"] == "erreur"]
    if nouveaux:
        phrase = f"{len(nouveaux)} nouvelle(s) exécution(s) GitHub Actions en échec."
    else:
        phrase = "Aucune nouvelle exécution en échec."
    if erreurs:
        phrase += f" {len(erreurs)} dépôt(s) n'ont pas pu être lus."
    return {"echecs": nouveaux, "deja_signales": ignores, "depots": controles, "resume": phrase}


def texte(resultat):
    """Résultat lisible : un échec par ligne, avec dépôt, workflow, cause et résumé."""
    lignes = [f"- ❌ **{e['depot']}** · {e['workflow']} : {e['cause']}. {e['resume']} {e['url']}".rstrip()
              for e in resultat["echecs"]]
    return "\n".join([f"**GitHub Actions** : {resultat['resume']}"] + lignes)


def executer(params):
    """Tâche du serveur HTTP (GET). params : `deja_signales` (clés séparées par des virgules),
    `depuis_heures`, `depot`."""
    try:
        return detecter([c for c in str(params.get("deja_signales") or "").split(",")],
                        params.get("depuis_heures"), params.get("depot"))
    except ErreurDevops as e:
        return {"erreur": str(e), "depots_possibles": depots_surveilles()}
