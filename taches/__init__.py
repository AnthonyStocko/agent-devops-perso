"""Tâches devops. Chaque tâche est une fonction `executer(params) -> dict` enregistrée dans TACHES :
pour en ajouter une (santé, redémarrage, erreurs 502...), créer un module ici et l'ajouter au registre."""
from taches import deploiements

TACHES = {
    "deploiements": deploiements.executer,
}
