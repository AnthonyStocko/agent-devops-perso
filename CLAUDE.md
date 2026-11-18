# Agent devops

Lire `README.md` avant toute modification : il fixe la mission de l'agent et ses limites.

Règles non négociables :
- Deux écritures autorisées, et aucune autre. Partout ailleurs, lecture seule (GET) sur Render et sur
  GitHub. Ne pas ajouter d'autre tâche qui écrit : ce serait un changement de cadrage, qui se décide
  dans ce fichier.
  1. **Render : régler une variable d'environnement** (`agent_devops/taches/variables.py`). Elle
     enregistre une variable d'un agent suivi, puis lance le déploiement qui l'applique. Ni suppression
     de variable, ni redémarrage, ni suppression ou reconfiguration d'un service.
  2. **GitHub : déclencher un workflow en liste blanche** (`workflow_dispatch`). Seulement les workflows
     et les valeurs d'entrée de la liste ci-dessous, sur la branche `main`. Ni commit, ni pull request,
     ni annulation ou relance d'un run, ni modification d'un workflow, d'un secret ou d'une variable
     GitHub.
- Liste blanche des workflows. Le code en contient une copie, qui doit être identique ; l'élargir se
  décide ici, jamais dans le code seul.

  | Dépôt | Workflow | Entrée | Valeurs autorisées |
  |---|---|---|---|
  | `AnthonyStocko/mon-guide-agent-instagram` | `deploy-supabase.yml` | `etape` | `apercu`, `deployer` |

  `apercu` ne modifie rien. `deployer` applique les migrations en attente puis déploie toutes les Edge
  Functions sur le projet Supabase de l'agent Instagram (jamais celui de Mon guide) : la demande de
  confirmation le dit en toutes lettres.
- Les deux écritures gardent les mêmes garde-fous. Elles se font en deux temps : une fonction
  `preparer_...` vérifie la demande sans rien modifier ni appeler, puis `definir_variable` ou
  `declencher_workflow` l'exécute. Elles ne sont jamais servies par le serveur HTTP, qui reste en GET
  seul. Un déclenchement confirmé lance un seul run, sans relance automatique. Pour les variables, les
  noms de secrets et les variables réservées sont refusés et les valeurs en place ne sont jamais lues.
  Ne pas affaiblir ces garde-fous.
- Jetons. Le déclenchement d'un workflow utilise uniquement `DEVOPS_ACTIONS_TOKEN`, un jeton à
  granularité fine limité au dépôt `mon-guide-agent-instagram`, avec la seule permission « Actions » en
  lecture et écriture. Sans lui, le déclenchement est refusé : jamais de repli sur `GITHUB_TOKEN` ni sur
  `DEV_GITHUB_TOKEN`, qui ne servent qu'à lire.
- Aucun secret (clé Render, jeton) dans le dépôt, dans une réponse, dans un message d'erreur ni dans
  un journal.
- Bibliothèque standard uniquement : aucune dépendance à installer.
- L'agent chef importe `agent_devops.verifier_deploiements`, `agent_devops.texte`,
  `agent_devops.preparer_variable`, `agent_devops.definir_variable`, `agent_devops.preparer_workflow`,
  `agent_devops.declencher_workflow` et `agent_devops.ErreurDevops` : ne pas les renommer ni changer
  la forme de leur résultat (dictionnaire avec une clé `resume`).
- Le paquet `agent_devops` reste importable depuis un autre projet : imports absolus
  (`from agent_devops import ...`), aucun module à la racine en dehors de `app.py` et des tests.
- Avant de terminer : `python -m unittest discover -p 'test_*.py'`.
