"""Agent devops : la partie devops des autres agents.

Deux façons de l'appeler :
- comme bibliothèque, depuis le processus d'un autre agent (c'est ce que fait l'agent chef) :
      import agent_devops
      resultat = agent_devops.verifier_deploiements(agent="emploi")
      print(agent_devops.texte(resultat))
      demande = agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")   # ne modifie rien
      agent_devops.definir_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")              # après un « oui »
- comme serveur HTTP autonome, en lecture seule : `python app.py` (voir agent_devops/serveur.py).
"""
from agent_devops.taches.deploiements import ErreurDevops, texte
from agent_devops.taches.deploiements import verifier as verifier_deploiements
from agent_devops.taches.variables import definir as definir_variable
from agent_devops.taches.variables import preparer as preparer_variable

__all__ = ["ErreurDevops", "definir_variable", "preparer_variable", "texte", "verifier_deploiements"]
