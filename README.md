# Agent devops (agent-devops-perso)

## Mission

S'occuper de la mise en ligne des agents hébergés sur Render : dire si ce qui est en ligne correspond
au code, et régler leurs variables d'environnement.

C'est un agent à part entière, avec son dépôt et ses tests. **Pour l'instant il tourne dans le
processus de l'agent chef**, qui installe ce dépôt comme dépendance (la limite de services Render est
atteinte). Il sera hébergé à part quand un NAS sera disponible : le serveur HTTP est déjà prêt.

## Ce qu'il fait

### Vérifier les déploiements (lecture seule)

Pour chaque agent suivi, il interroge Render (`GET /v1/services/{id}/deploys`), lit le dernier commit
de `main` sur GitHub (ou prend un commit précis) et rend un verdict :

| Verdict | Sens |
|---|---|
| `a_jour` | le commit attendu est en ligne (Live) |
| `commit_different` | ce qui est en ligne n'est pas le commit attendu |
| `echec` | le dernier déploiement a échoué (le commit resté en ligne est indiqué) |
| `en_cours` | un déploiement est en cours |
| `inconnu` / `erreur` / `non_configure` | pas assez d'informations, Render injoignable, variable manquante |

Agents suivis (`agent_devops/config.py`) : `manager` (agent chef), `emploi`, `perso`. L'agent
développeur (GitHub Actions) et l'agent Instagram (Supabase) ne sont pas sur Render : ils ne sont pas suivis.

### Régler une variable d'environnement (sa seule écriture)

Il crée une variable d'un agent suivi, ou remplace sa valeur
(`PUT /v1/services/{id}/env-vars/{nom}`), puis s'assure qu'un déploiement l'applique : celui que Render
lance de lui-même s'il y en a un, sinon il en demande un (`POST /v1/services/{id}/deploys`).

Cela se fait en deux temps, pour que l'appelant demande une confirmation : `preparer_variable` vérifie
la demande sans rien modifier, `definir_variable` l'exécute. Sont refusés :

- un agent non suivi, ou dont le service Render n'est pas configuré ;
- un nom qui ressemble à un secret (`PASSWORD`, `TOKEN`, `SECRET`, `KEY`, `OAUTH`, `DATABASE_URL`…) :
  les secrets se règlent à la main dans Render ;
- une variable réservée (`PORT`, `RENDER_...`) ;
- une valeur vide, sur plusieurs lignes ou de plus de 2 000 caractères.

## Ce qu'il ne fait jamais

- **Écrire autre chose qu'une variable de réglage.** Aucune suppression de variable, aucun redémarrage ni
  suppression de service, aucun changement de configuration, aucun commit. Il ne lance un déploiement que
  pour appliquer la variable qu'il vient d'enregistrer. Sur GitHub, il est en lecture seule.
- **Écrire sans confirmation.** Le réglage d'une variable n'est pas servi par le serveur HTTP, qui refuse
  tout sauf GET : il passe par l'agent chef, qui montre l'agent, le nom et la valeur, et attend un « oui ».
- **Lire ou montrer un secret.** Les valeurs des variables en place ne sont jamais lues. Ni la clé Render
  ni un jeton n'apparaît dans une réponse, une erreur ou un journal.
- **Sortir de son domaine.** Il ne modifie pas le code (rôle d'agent-dev) et ne parle pas à l'utilisateur
  (rôle de l'agent chef).

Les règles qui s'imposent à toute modification du code sont dans [CLAUDE.md](CLAUDE.md).

## Qui l'appelle

**L'agent chef** ([agent-manager](https://github.com/AnthonyStocko/agent-manager)), et lui seul : dans
sa discussion (« est-ce que le correctif de l'agent emploi est en ligne ? », « ajoute la variable
JOB_ALERT_SENDERS à l'agent perso avec linkedin.com ») et par le bouton **Vérifier les déploiements** de
son onglet Développeur.

### Aujourd'hui : en bibliothèque, dans l'agent chef

```python
import agent_devops

resultat = agent_devops.verifier_deploiements(agent="emploi")   # agent="" : tous ; commit="<sha>" : ce commit
print(agent_devops.texte(resultat))                             # texte prêt pour une discussion

demande = agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")   # ne modifie rien
print(demande["resume"])                                        # à montrer, puis attendre un « oui »
resultat = agent_devops.definir_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")
print(resultat["resume"])
```

`ErreurDevops` est levée quand une demande est refusée ou impossible (clé Render absente, agent inconnu,
nom ou valeur refusés, variable non enregistrée). Ces cinq noms sont l'interface utilisée par l'agent
chef : ne pas les renommer sans le modifier aussi.

L'agent chef fixe la version qu'il installe par un commit, dans son `requirements.txt` :

    agent-devops @ https://github.com/AnthonyStocko/agent-devops-perso/archive/<sha du commit>.zip

**Une modification de ce dépôt n'arrive donc dans l'agent chef que lorsque ce commit y est mis à
jour.** Le dépôt doit rester public pour que cette installation fonctionne sans jeton.

### Plus tard : en serveur autonome

    python app.py            # port lu dans PORT, sinon 8796 ; aucune dépendance à installer

```
GET /healthz                                   public, sert au contrôle de démarrage
GET /agent/devops/deploiements                 tous les agents
GET /agent/devops/deploiements?agent=emploi    un seul (manager, emploi, perso)
GET /agent/devops/deploiements?commit=<sha>    vérifie ce commit (SHA complet ou début)
```

L'appel exige l'en-tête `Authorization: Bearer <HUB_TOKEN>`. La réponse est la même que celle de
`verifier_deploiements` ; une demande impossible renvoie `{"erreur": "..."}`. Le serveur est en lecture
seule : le réglage des variables n'y est pas servi.

## Variables d'environnement

Elles sont lues dans le processus où l'agent tourne : aujourd'hui, le service Render de l'agent chef.

| Variable | Rôle |
|---|---|
| `RENDER_API_KEY` | clé API Render (Account Settings > API Keys) ; elle donne accès à tout le compte, en lecture et en écriture |
| `RENDER_SERVICE_AGENT_EMPLOI`, `RENDER_SERVICE_AGENT_PERSO` | identifiants `srv-...` des services Render ; un agent sans variable est signalé `non_configure` |
| `RENDER_SERVICE_AGENT_MANAGER` | identifiant du service de l'agent chef ; inutile tant que l'agent tourne dans l'agent chef (Render fournit `RENDER_SERVICE_ID`) |
| `GITHUB_TOKEN` | facultatif : dépôt privé ou limite de l'API GitHub ; à défaut, `DEV_GITHUB_TOKEN` est utilisé |
| `HUB_TOKEN` | serveur autonome seulement : jeton que l'appelant présente ; sans lui, tout appel est refusé |

## Ajouter une tâche devops

Tâche en lecture seule : créer `agent_devops/taches/<nom>.py` avec une fonction `executer(params) -> dict`,
l'enregistrer dans `agent_devops/taches/__init__.py` (`TACHES`) : elle est servie sur
`/agent/devops/<nom>`. Pour que l'agent chef puisse l'appeler en bibliothèque, l'exposer aussi dans
`agent_devops/__init__.py`.

Une tâche qui écrit ne s'ajoute pas ainsi : c'est un changement de cadrage, qui se décide d'abord dans ce
README et dans `CLAUDE.md`.

## Tests

    python -m unittest discover -p 'test_*.py'

## Fichiers

- `agent_devops/__init__.py` : interface appelée par l'agent chef
- `agent_devops/config.py` : agents suivis et variables — `agent_devops/clients.py` : appels Render et GitHub
- `agent_devops/taches/deploiements.py` : vérification des déploiements
- `agent_devops/taches/variables.py` : réglage d'une variable d'environnement
- `agent_devops/serveur.py` : serveur HTTP autonome — `app.py` : son lancement
- `pyproject.toml` : rend le dépôt installable — `test_devops.py` : tests
