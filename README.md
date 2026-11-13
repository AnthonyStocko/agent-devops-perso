# agent-devops-perso

L'agent devops : il s'occupe de la partie devops des autres agents (agent chef, développeur, Instagram,
emploi, perso). Premier besoin couvert : **vérifier qu'un correctif est bien déployé sur Render**.
L'agent chef l'appelle en lecture seule ; rien n'est jamais modifié sur Render ni sur GitHub.

## Ce qu'il fait

Pour chaque agent, il interroge Render (`GET /v1/services/{id}/deploys`) et renvoie, pour le dernier
déploiement : le commit, le statut (Live, échec pendant le build…) et la date. Il compare ensuite le commit
en ligne au dernier commit de `main` du dépôt GitHub (ou à un commit précis) et rend un verdict :

| Verdict | Sens |
|---|---|
| `a_jour` | le commit attendu est en ligne (Live) |
| `commit_different` | ce qui est en ligne n'est pas le commit attendu |
| `echec` | le dernier déploiement a échoué (le commit encore en ligne est donné dans `en_ligne`) |
| `en_cours` | un déploiement est en cours |
| `inconnu` / `erreur` / `non_configure` | pas assez d'informations, Render injoignable, variable manquante |

## Point d'entrée

```
GET /agent/devops/deploiements                      tous les agents
GET /agent/devops/deploiements?agent=agent_emploi   un seul (agent_manager, agent_dev, agent_insta, agent_emploi, agent_perso)
GET /agent/devops/deploiements?commit=<sha>         vérifie ce commit (SHA complet ou début) au lieu du dernier commit GitHub
GET /healthz                                        public, sert au contrôle de démarrage
```

L'appel exige l'en-tête `Authorization: Bearer <HUB_TOKEN>`. Seul GET est accepté. Réponse JSON : par agent,
`verdict`, `resume` (une phrase), `dernier_deploiement`, `en_ligne`, `dernier_commit_github`.

## Variables d'environnement (à définir sur Render, service de cet agent)

| Variable | Rôle |
|---|---|
| `RENDER_API_KEY` | clé API Render (Account Settings > API Keys) |
| `HUB_TOKEN` | jeton que l'agent chef présente (même valeur que dans l'agent chef) ; sans lui, tout appel est refusé |
| `RENDER_SERVICE_AGENT_MANAGER`, `RENDER_SERVICE_AGENT_DEV`, `RENDER_SERVICE_AGENT_INSTA`, `RENDER_SERVICE_AGENT_EMPLOI`, `RENDER_SERVICE_AGENT_PERSO` | identifiants `srv-...` des services Render (visibles dans l'URL du tableau de bord du service) ; un agent sans variable est signalé `non_configure` |
| `GITHUB_TOKEN` | facultatif : seulement si un dépôt est privé ou pour éviter la limite de l'API GitHub (lecture seule suffit) |

Aucun secret n'est écrit dans le code, ni dans les journaux ni dans les réponses (les erreurs ne donnent que « HTTP 401 » par exemple).

Render : service Web Python, commande de démarrage `python app.py` (aucune dépendance à installer, port lu dans `PORT`).

## Ajouter une tâche devops

Créer `taches/<nom>.py` avec une fonction `executer(params) -> dict`, puis l'enregistrer dans `taches/__init__.py`
(`TACHES`) : elle est aussitôt servie sur `/agent/devops/<nom>`. Les agents suivis sont listés dans `config.py`,
les appels Render/GitHub dans `clients.py` (à étendre pour la santé des services, le redémarrage ou le suivi des 502).

## Fichiers

- `app.py` : serveur HTTP — `config.py` : agents et variables — `clients.py` : appels Render et GitHub
- `taches/deploiements.py` : vérification des déploiements
- `test_devops.py` : tests (`python -m unittest discover -p 'test_*.py'`)
