# Agent devops

Lire `README.md` avant toute modification : il fixe la mission de l'agent et ses limites.

Règles non négociables :
- Lecture seule sur GitHub, et sur Render à une exception près : `agent_devops/taches/variables.py`
  enregistre une variable d'environnement d'un agent suivi, puis lance le déploiement qui l'applique.
  Aucune autre écriture : ni suppression de variable, ni redémarrage, ni suppression ou reconfiguration
  d'un service. Ne pas ajouter de tâche qui écrit.
- Cette écriture garde ses garde-fous : en deux temps (`preparer`, sans effet, puis `definir`), jamais
  servie par le serveur HTTP (GET seul), refus des noms de secrets et des variables réservées, et les
  valeurs déjà en place ne sont jamais lues. Ne pas les affaiblir.
- Aucun secret (clé Render, jeton) dans le dépôt, dans une réponse, dans un message d'erreur ni dans
  un journal.
- Bibliothèque standard uniquement : aucune dépendance à installer.
- L'agent chef importe `agent_devops.verifier_deploiements`, `agent_devops.texte`,
  `agent_devops.preparer_variable`, `agent_devops.definir_variable` et `agent_devops.ErreurDevops` :
  ne pas les renommer ni changer la forme de leur résultat.
- Le paquet `agent_devops` reste importable depuis un autre projet : imports absolus
  (`from agent_devops import ...`), aucun module à la racine en dehors de `app.py` et des tests.
- Avant de terminer : `python -m unittest discover -p 'test_*.py'`.
