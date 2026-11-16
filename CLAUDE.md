# Agent devops

Lire `README.md` avant toute modification : il fixe la mission de l'agent et ses limites.

Règles non négociables :
- Lecture seule sur Render et sur GitHub : uniquement des requêtes GET. Aucune tâche ne redéploie,
  ne redémarre ni ne modifie un service ou un dépôt.
- Aucun secret (clé Render, jeton) dans le dépôt, dans une réponse, dans un message d'erreur ni dans
  un journal.
- Bibliothèque standard uniquement : aucune dépendance à installer.
- L'agent chef importe `agent_devops.verifier_deploiements`, `agent_devops.texte` et
  `agent_devops.ErreurDevops` : ne pas les renommer ni changer la forme de leur résultat.
- Le paquet `agent_devops` reste importable depuis un autre projet : imports absolus
  (`from agent_devops import ...`), aucun module à la racine en dehors de `app.py` et des tests.
- Avant de terminer : `python -m unittest discover -p 'test_*.py'`.
