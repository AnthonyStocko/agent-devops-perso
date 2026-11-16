# Agent devops (agent-devops-perso)

## Mission

Dire si ce qui est en ligne correspond au code : pour chaque agent hébergé sur Render, comparer le
commit déployé au dernier commit de `main` sur GitHub.

C'est un agent à part entière, avec son dépôt et ses tests. **Pour l'instant il tourne dans le
processus de l'agent chef**, qui installe ce dépôt comme dépendance (la limite de services Render est
atteinte). Il sera hébergé à part quand un NAS sera disponible : le serveur HTTP est déjà prêt.

## Ce qu'il fait

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

## Ce qu'il ne fait jamais

- **Modifier quoi que ce soit.** Lecture seule sur Render et sur GitHub : aucun redéploiement, aucun
  redémarrage, aucun commit. Le serveur HTTP refuse tout sauf GET.
- **Montrer un secret.** Ni la clé Render ni un jeton n'apparaît dans une réponse, une erreur ou un journal.
- **Sortir de son domaine.** Il ne modifie pas le code (rôle d'agent-dev) et ne parle pas à l'utilisateur
  (rôle de l'agent chef).

Les règles qui s'imposent à toute modification du code sont dans [CLAUDE.md](CLAUDE.md).

## Qui l'appelle

**L'agent chef** ([agent-manager](https://github.com/AnthonyStocko/agent-manager)), et lui seul : dans
sa discussion (« est-ce que le correctif de l'agent emploi est en ligne ? ») et par le bouton
**Vérifier les déploiements** de son onglet Développeur.

### Aujourd'hui : en bibliothèque, dans l'agent chef

```python
import agent_devops

resultat = agent_devops.verifier_deploiements(agent="emploi")   # agent="" : tous ; commit="<sha>" : ce commit
print(agent_devops.texte(resultat))                             # texte prêt pour une discussion
```

`ErreurDevops` est levée si `RENDER_API_KEY` manque ou si l'agent est inconnu. Ces trois noms sont
l'interface utilisée par l'agent chef : ne pas les renommer sans le modifier aussi.

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
`verifier_deploiements` ; une demande impossible renvoie `{"erreur": "..."}`.

## Variables d'environnement

Elles sont lues dans le processus où l'agent tourne : aujourd'hui, le service Render de l'agent chef.

| Variable | Rôle |
|---|---|
| `RENDER_API_KEY` | clé API Render (Account Settings > API Keys) ; elle donne accès à tout le compte |
| `RENDER_SERVICE_AGENT_EMPLOI`, `RENDER_SERVICE_AGENT_PERSO` | identifiants `srv-...` des services Render ; un agent sans variable est signalé `non_configure` |
| `RENDER_SERVICE_AGENT_MANAGER` | identifiant du service de l'agent chef ; inutile tant que l'agent tourne dans l'agent chef (Render fournit `RENDER_SERVICE_ID`) |
| `GITHUB_TOKEN` | facultatif : dépôt privé ou limite de l'API GitHub ; à défaut, `DEV_GITHUB_TOKEN` est utilisé |
| `HUB_TOKEN` | serveur autonome seulement : jeton que l'appelant présente ; sans lui, tout appel est refusé |

## Ajouter une tâche devops

Créer `agent_devops/taches/<nom>.py` avec une fonction `executer(params) -> dict`, l'enregistrer dans
`agent_devops/taches/__init__.py` (`TACHES`) : elle est servie sur `/agent/devops/<nom>`. Pour que
l'agent chef puisse l'appeler en bibliothèque, l'exposer aussi dans `agent_devops/__init__.py`.

## Tests

    python -m unittest discover -p 'test_*.py'

## Fichiers

- `agent_devops/__init__.py` : interface appelée par l'agent chef
- `agent_devops/config.py` : agents suivis et variables — `agent_devops/clients.py` : appels Render et GitHub
- `agent_devops/taches/deploiements.py` : vérification des déploiements
- `agent_devops/serveur.py` : serveur HTTP autonome — `app.py` : son lancement
- `pyproject.toml` : rend le dépôt installable — `test_devops.py` : tests
