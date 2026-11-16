"""Lance l'agent devops comme serveur HTTP autonome : python app.py [port] (PORT sinon 8796).

Le code est dans le paquet agent_devops ; ce fichier ne sert qu'au démarrage.
"""
from agent_devops.serveur import Gestionnaire, main  # noqa: F401

if __name__ == "__main__":
    main()
