"""Agent devops : la partie devops des autres agents, en lecture seule.

Deux façons de l'appeler :
- comme bibliothèque, depuis le processus d'un autre agent (c'est ce que fait l'agent chef) :
      import agent_devops
      resultat = agent_devops.verifier_deploiements(agent="emploi")
      print(agent_devops.texte(resultat))
- comme serveur HTTP autonome : `python app.py` (voir agent_devops/serveur.py).
"""
from agent_devops.taches.deploiements import ErreurDevops, texte
from agent_devops.taches.deploiements import verifier as verifier_deploiements

__all__ = ["ErreurDevops", "texte", "verifier_deploiements"]
