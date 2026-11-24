"""Agent devops : la partie devops des autres agents.

Deux façons de l'appeler :
- comme bibliothèque, depuis le processus d'un autre agent (c'est ce que fait l'agent chef) :
      import agent_devops
      resultat = agent_devops.verifier_deploiements(agent="emploi")
      print(agent_devops.texte(resultat))
      demande = agent_devops.preparer_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")   # ne modifie rien
      agent_devops.definir_variable("perso", "JOB_ALERT_SENDERS", "linkedin.com")              # après un « oui »
      demande = agent_devops.preparer_workflow("instagram-supabase", {"etape": "apercu"})    # ne lance rien
      agent_devops.declencher_workflow("instagram-supabase", {"etape": "apercu"})            # après un « oui »
      echecs = agent_devops.detecter_echecs_actions(deja_signales=[...])   # lecture seule : échecs GitHub Actions à remonter
- comme serveur HTTP autonome, en lecture seule : `python app.py` (voir agent_devops/serveur.py).
"""
from agent_devops.taches.deploiements import ErreurDevops, texte
from agent_devops.taches.deploiements import verifier as verifier_deploiements
from agent_devops.taches.echecs import detecter as detecter_echecs_actions
from agent_devops.taches.echecs import texte as texte_echecs_actions
from agent_devops.taches.variables import definir as definir_variable
from agent_devops.taches.variables import preparer as preparer_variable
from agent_devops.taches.workflows import declencher as declencher_workflow
from agent_devops.taches.workflows import preparer as preparer_workflow

__all__ = ["ErreurDevops", "declencher_workflow", "definir_variable", "detecter_echecs_actions", "preparer_variable", "preparer_workflow",
           "texte", "texte_echecs_actions", "verifier_deploiements"]
