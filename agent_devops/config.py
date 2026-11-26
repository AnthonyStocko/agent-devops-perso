"""Configuration de l'agent devops : tout vient des variables d'environnement, rien n'est écrit en dur."""
import os

# Agents suivis : ceux qui tournent sur le serveur P2 (dépôt serveur-agents, Docker Compose). L'agent
# développeur (GitHub Actions) et l'agent Instagram (Supabase) n'y sont pas.
# Clé -> nom, dépôt GitHub et service Docker Compose.
AGENTS = {
    "manager": {"nom": "Agent chef", "depot": "AnthonyStocko/agent-manager", "service": "agent-manager"},
    "emploi": {"nom": "Agent emploi", "depot": "AnthonyStocko/agent-emploi", "service": "agent-emploi"},
    "perso": {"nom": "Agent perso", "depot": "AnthonyStocko/agent-perso", "service": "agent-perso"},
    "devops": {"nom": "Agent devops", "depot": "AnthonyStocko/agent-devops-perso", "service": "agent-devops"},
}

# Agents dont l'agent devops peut régler une variable (par une demande appliquée par le serveur)
AGENTS_VARIABLES = ("manager", "emploi", "perso")


# Workflows GitHub que l'agent peut lancer (workflow_dispatch, branche main). Copie de la liste blanche de
# CLAUDE.md, qui fait foi : un test vérifie qu'elles sont identiques. Clé -> dépôt, fichier du workflow et,
# pour chaque entrée, les valeurs autorisées avec ce que chacune fait (affiché dans la demande de confirmation).
WORKFLOWS = {
    "instagram-supabase": {
        "nom": "Déploiement Supabase de l'agent Instagram",
        "depot": "AnthonyStocko/mon-guide-agent-instagram",
        "workflow": "deploy-supabase.yml",
        "entrees": {
            "etape": {
                "apercu": "liste les migrations en attente, sans rien appliquer ni déployer",
                "deployer": ("APPLIQUE les migrations en attente à la base, puis déploie toutes les Edge Functions, "
                             "sur le projet Supabase de l'agent Instagram (jamais celui de Mon guide)"),
            },
        },
    },
}
BRANCHE_WORKFLOWS = "main"


def fichier_etat():
    """État des déploiements écrit par le serveur (mettre-a-jour.sh), monté en lecture seule."""
    return (os.getenv("DEVOPS_ETAT") or "/etat/deploiements.json").strip()


def dossier_demandes():
    """Dossier où sont déposées les demandes de variables, appliquées par le serveur (appliquer-demandes.py)."""
    return (os.getenv("DEVOPS_DEMANDES") or "/demandes").strip()


def jeton_github():
    """Facultatif : nécessaire seulement si un dépôt est privé (ou pour éviter la limite de l'API publique).
    À défaut de GITHUB_TOKEN, le jeton de l'agent développeur (DEV_GITHUB_TOKEN) est utilisé."""
    return (os.getenv("GITHUB_TOKEN") or os.getenv("DEV_GITHUB_TOKEN") or "").strip()


def jeton_actions():
    """Seul jeton utilisé pour lancer un workflow : DEVOPS_ACTIONS_TOKEN, limité au dépôt de l'agent Instagram
    avec la permission Actions en écriture. Jamais de repli sur GITHUB_TOKEN ni DEV_GITHUB_TOKEN."""
    return (os.getenv("DEVOPS_ACTIONS_TOKEN") or "").strip()


def jeton_acces():
    """Jeton exigé par le serveur HTTP de cet agent (même valeur que HUB_TOKEN côté agent chef)."""
    return os.getenv("HUB_TOKEN") or ""
