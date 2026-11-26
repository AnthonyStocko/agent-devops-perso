# Agent devops (agent-devops-perso)

## Mission

S'occuper de la mise en ligne des agents : dire si ce qui tourne sur le serveur P2 correspond au code,
faire régler les variables d'environnement des agents, et lancer les workflows de déploiement autorisés
sur GitHub.

Depuis le 26 novembre 2026, les agents tournent sur le serveur **P2** (un PC sous Windows avec WSL2 et
Docker), décrit par le dépôt [serveur-agents](https://github.com/AnthonyStocko/serveur-agents), et non plus
sur Render. L'agent devops y tourne de deux façons : **en bibliothèque dans l'agent chef**, qui installe ce
dépôt comme dépendance et s'en sert pour les écritures (après confirmation), et **en serveur autonome**
(conteneur `agent-devops`, lecture seule).

Il n'a **aucun accès à Docker ni aux secrets du serveur**. Le serveur lui donne deux dossiers :

| Dossier | Accès | Contenu |
|---|---|---|
| `/etat` | lecture seule | `deploiements.json`, réécrit toutes les 5 minutes par `mettre-a-jour.sh` |
| `/demandes` | écriture (agent chef seulement) | les demandes de variables, appliquées par `appliquer-demandes.py` |

## Ce qu'il fait

### Vérifier les déploiements (lecture seule)

Pour chaque agent suivi, il lit l'état écrit par le serveur (commit de l'image en service, résultat de la
dernière mise à jour, état et santé du conteneur), lit le dernier commit de `main` sur GitHub (ou prend un
commit précis) et rend un verdict :

| Verdict | Sens |
|---|---|
| `a_jour` | le commit attendu est en service |
| `commit_different` | ce qui est en service n'est pas le commit attendu |
| `echec` | la dernière mise à jour a échoué (le commit resté en service est indiqué) |
| `en_cours` | une mise à jour est en cours |
| `hors_service` | le conteneur est arrêté, ou ne répond plus à son contrôle de santé |
| `inconnu` | pas assez d'informations (agent absent de l'état, GitHub injoignable) |

Si l'état date de plus de 15 minutes, il le signale : la mise à jour automatique du serveur est
peut-être arrêtée. Sans fichier d'état, il le dit (dossier non monté).

Agents suivis (`agent_devops/config.py`) : `manager` (agent chef), `emploi`, `perso`, `devops`. L'agent
développeur (GitHub Actions) et l'agent Instagram (Supabase) ne sont pas sur le serveur : ils ne sont pas suivis.

### Détecter les workflows GitHub Actions en échec (lecture seule)

Il consulte les exécutions de GitHub Actions (`GET /repos/{dépôt}/actions/runs?status=failure`, branche
`main`) de chaque dépôt de son périmètre : les agents suivis (`manager`, `emploi`, `perso`) et le dépôt de
l'agent Instagram. Pour chaque exécution en échec, il lit les jobs (et l'annotation d'erreur du job, quand le
workflow en produit une) et rend : le **dépôt**, le **workflow**, la **cause** (job et étape en échec), un
**résumé** de l'erreur, le lien du run et une **clé** stable `dépôt#run#tentative`. Les journaux bruts ne
sont pas lus.

Il ne corrige rien, ne relance rien et n'écrit rien : c'est l'agent chef qui décide si un correctif est
nécessaire, puis le demande à l'agent développeur.

**Pas de doublon.** L'agent devops ne garde aucun état. L'agent chef conserve les clés qu'il a déjà
traitées et les repasse à chaque appel (`deja_signales`) : une exécution déjà remontée n'est plus renvoyée.
Une relance du même run (nouvelle tentative) en échec compte comme un nouvel échec. Seuls les échecs des
dernières 24 h sont cherchés (`depuis_heures`, 336 au maximum).

### Demander le réglage d'une variable d'environnement (première écriture)

Il crée une variable d'un agent, ou remplace sa valeur, **par une demande** : un fichier JSON déposé dans
`/demandes`. Il ne touche lui-même à aucun fichier de secrets ni à Docker. Sur le serveur, le script
`appliquer-demandes.py` (dépôt serveur-agents), lancé chaque minute, refait toutes les vérifications,
écrit la variable dans `env/<agent>.env`, redémarre l'agent concerné et range la demande avec son
résultat.

Cela se fait en deux temps, pour que l'appelant demande une confirmation : `preparer_variable` vérifie
la demande sans rien déposer, `definir_variable` la dépose. Sont refusés, ici et par le serveur :

- un agent autre que `manager`, `emploi` ou `perso` ;
- un nom qui ressemble à un secret (`PASSWORD`, `TOKEN`, `SECRET`, `KEY`, `OAUTH`, `DATABASE_URL`…) :
  les secrets se règlent à la main dans `env/` sur le serveur ;
- une variable réservée : celles du système, celles que `docker-compose.yml` règle lui-même (`PORT`,
  `HOST`, `DATA_DIR`, `HUB_URL`, `EMPLOI_URL`, `PERSO_URL`, `TZ`…) et `RENDER`, `RENDER_...` ;
- une valeur vide, sur plusieurs lignes ou de plus de 2 000 caractères.

### Déclencher un workflow en liste blanche (seconde écriture)

Il lance un workflow GitHub Actions (`workflow_dispatch`, branche `main`), mais seulement ceux de la
liste blanche, avec les valeurs d'entrée prévues :

| Dépôt | Workflow | Entrée | Valeurs autorisées |
|---|---|---|---|
| `AnthonyStocko/mon-guide-agent-instagram` | `deploy-supabase.yml` | `etape` | `apercu`, `deployer` |

`apercu` montre les migrations en attente sans rien appliquer. `deployer` applique ces migrations, puis
déploie toutes les Edge Functions sur le projet Supabase de l'agent Instagram (jamais celui de Mon
guide).

Comme pour les variables, cela se fait en deux temps : `preparer_workflow` vérifie la demande sans rien
appeler, puis `declencher_workflow` lance un seul run (`POST /repos/{dépôt}/actions/workflows/{fichier}/dispatches`),
sans relance automatique : en cas d'erreur ou de réponse incertaine, il le dit et donne le lien du workflow
dans GitHub Actions. La confirmation dit ce
que fait l'étape choisie. Le déclenchement utilise un jeton dédié, `DEVOPS_ACTIONS_TOKEN` ; sans lui,
il est refusé.

La liste blanche fait foi dans [CLAUDE.md](CLAUDE.md) : le code en garde une copie identique
(`config.WORKFLOWS`), et un test échoue dès qu'elles diffèrent. L'élargir est une décision de cadrage, pas
une modification de code.

## Ce qu'il ne fait jamais

- **Écrire autre chose que ses deux écritures.** Sur le serveur : rien d'autre qu'un fichier de demande
  dans `/demandes` ; aucun accès à Docker, aucun arrêt, aucune mise à jour, aucune suppression. Sur GitHub : aucun commit, aucune pull
  request, aucun workflow hors de la liste blanche, aucune annulation ni relance de run, aucune
  modification de workflow, de secret ou de variable.
- **Écrire sans confirmation.** Ses deux écritures ne sont pas servies par le serveur HTTP, qui refuse
  tout sauf GET : elles passent par l'agent chef, qui montre ce qui sera fait et attend un « oui ».
- **Lire ou montrer un secret.** Les valeurs des variables en place ne sont jamais lues. Ni un mot de passe
  ni un jeton n'apparaît dans une réponse, une erreur ou un journal.
- **Sortir de son domaine.** Il ne modifie pas le code (rôle d'agent-dev) et ne parle pas à l'utilisateur
  (rôle de l'agent chef).

Les règles qui s'imposent à toute modification du code sont dans [CLAUDE.md](CLAUDE.md).

## Qui l'appelle

**L'agent chef** ([agent-manager](https://github.com/AnthonyStocko/agent-manager)), et lui seul : dans
sa discussion (« est-ce que le correctif de l'agent emploi est en ligne ? », « ajoute la variable
JOB_ALERT_SENDERS à l'agent perso avec linkedin.com », « déploie les fonctions Supabase de l'agent
Instagram ») et par le bouton **Vérifier les déploiements** de son onglet Développeur.

### En bibliothèque, dans l'agent chef

```python
import agent_devops

resultat = agent_devops.verifier_deploiements(agent="emploi")   # agent="" : tous ; commit="<sha>" : ce commit
print(agent_devops.texte(resultat))                             # texte prêt pour une discussion

demande = agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")   # ne modifie rien
print(demande["resume"])                                        # à montrer, puis attendre un « oui »
resultat = agent_devops.definir_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")
print(resultat["resume"])

demande = agent_devops.preparer_workflow("instagram-supabase", {"etape": "deployer"})   # ne lance rien
print(demande["resume"])                                        # à montrer, puis attendre un « oui »
resultat = agent_devops.declencher_workflow("instagram-supabase", {"etape": "deployer"})
print(resultat["resume"])

echecs = agent_devops.detecter_echecs_actions(deja_signales=cles_deja_traitees)   # lecture seule
for e in echecs["echecs"]:                                      # dépôt, workflow, cause, résumé, url, cle
    print(e["depot"], e["workflow"], e["cause"], e["resume"])
```

`ErreurDevops` est levée quand une demande est refusée ou impossible (état ou dossier des demandes absents, jeton absent, agent ou
workflow inconnus, nom, valeur ou entrée refusés, écriture refusée par GitHub). Ces sept noms
(plus `detecter_echecs_actions` et `texte_echecs_actions`, en lecture seule) sont l'interface utilisée par l'agent chef : ne pas les renommer sans le modifier aussi.

L'agent chef fixe la version qu'il installe par un commit, dans son `requirements.txt` :

    agent-devops @ https://github.com/AnthonyStocko/agent-devops-perso/archive/<sha du commit>.zip

**Une modification de ce dépôt n'arrive donc dans l'agent chef que lorsque ce commit y est mis à
jour.** Le dépôt doit rester public pour que cette installation fonctionne sans jeton.

### En serveur autonome (conteneur `agent-devops` du serveur P2)

    python app.py            # port lu dans PORT, sinon 8796 ; aucune dépendance à installer

```
GET /healthz                                   public, sert au contrôle de démarrage
GET /agent/devops/deploiements                 tous les agents
GET /agent/devops/deploiements?agent=emploi    un seul (manager, emploi, perso, devops)
GET /agent/devops/deploiements?commit=<sha>    vérifie ce commit (SHA complet ou début)
GET /agent/devops/echecs                       nouveaux workflows GitHub Actions en échec
GET /agent/devops/echecs?deja_signales=<cle>,<cle>&depuis_heures=24&depot=<proprietaire/depot>
```

En conteneur (service `agent-devops` du serveur P2) : le `Dockerfile` construit
une image arm64 ou amd64, sans dépendance, qui lance `python app.py` et se contrôle sur `/healthz`. Le
workflow `Image Docker` vérifie à chaque push que l'image se construit pour les deux architectures et
démarre. Variables à fournir au conteneur : celles du tableau ci-dessous, dont `HUB_TOKEN`.

L'appel exige l'en-tête `Authorization: Bearer <HUB_TOKEN>`. La réponse est la même que celle de
`verifier_deploiements` ; une demande impossible renvoie `{"erreur": "..."}`. Le serveur est en lecture
seule : ni le réglage des variables ni le déclenchement des workflows n'y sont servis.

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `DEVOPS_ETAT` | chemin du fichier d'état écrit par le serveur ; par défaut `/etat/deploiements.json` |
| `DEVOPS_DEMANDES` | dossier des demandes de variables ; par défaut `/demandes` (monté seulement dans l'agent chef) |
| `GITHUB_TOKEN` | facultatif, lecture seule (dernier commit, échecs GitHub Actions) : dépôt privé ou limite de l'API GitHub ; à défaut, `DEV_GITHUB_TOKEN` est utilisé |
| `DEVOPS_ACTIONS_TOKEN` | déclenchement des workflows uniquement : jeton GitHub à granularité fine, limité au dépôt `mon-guide-agent-instagram`, avec la seule permission « Actions » en lecture et écriture ; jamais remplacé par `GITHUB_TOKEN` ni `DEV_GITHUB_TOKEN` |
| `HUB_TOKEN` | serveur autonome seulement : jeton que l'appelant présente ; sans lui, tout appel est refusé |

## Ajouter une tâche devops

Tâche en lecture seule : créer `agent_devops/taches/<nom>.py` avec une fonction `executer(params) -> dict`,
l'enregistrer dans `agent_devops/taches/__init__.py` (`TACHES`) : elle est servie sur
`/agent/devops/<nom>`. Pour que l'agent chef puisse l'appeler en bibliothèque, l'exposer aussi dans
`agent_devops/__init__.py`.

Une tâche qui écrit ne s'ajoute pas ainsi : c'est un changement de cadrage, qui se décide d'abord dans ce
README et dans `CLAUDE.md`. Les deux seules écritures autorisées aujourd'hui sont la demande de réglage d'une
variable et le déclenchement d'un workflow de la liste blanche.

## Tests

    python -m unittest discover -p 'test_*.py'

## Fichiers

- `agent_devops/__init__.py` : interface appelée par l'agent chef
- `agent_devops/config.py` : agents suivis et variables — `agent_devops/clients.py` : appels GitHub
- `agent_devops/taches/deploiements.py` : vérification des déploiements
- `agent_devops/taches/echecs.py` : détection des workflows GitHub Actions en échec
- `agent_devops/taches/variables.py` : demande de réglage d'une variable d'environnement
- `agent_devops/taches/workflows.py` : lancement d'un workflow de la liste blanche
- `agent_devops/serveur.py` : serveur HTTP autonome — `app.py` : son lancement
- `pyproject.toml` : rend le dépôt installable — `test_devops.py` : tests
