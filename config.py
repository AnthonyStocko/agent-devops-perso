"""Configuration de l'agent devops : tout vient des variables d'environnement, rien n'est écrit en dur."""
import os

# Agents suivis : clé -> dépôt GitHub et variable d'environnement qui porte l'identifiant du service Render
AGENTS = {
    "agent_manager": {"nom": "Agent chef", "depot": "AnthonyStocko/agent-manager", "service_env": "RENDER_SERVICE_AGENT_MANAGER"},
    "agent_dev": {"nom": "Agent développeur", "depot": "AnthonyStocko/agent-dev", "service_env": "RENDER_SERVICE_AGENT_DEV"},
    "agent_insta": {"nom": "Agent Instagram", "depot": "AnthonyStocko/mon-guide-agent-instagram", "service_env": "RENDER_SERVICE_AGENT_INSTA"},
    "agent_emploi": {"nom": "Agent emploi", "depot": "AnthonyStocko/agent-emploi", "service_env": "RENDER_SERVICE_AGENT_EMPLOI"},
    "agent_perso": {"nom": "Agent perso", "depot": "AnthonyStocko/agent-perso", "service_env": "RENDER_SERVICE_AGENT_PERSO"},
}


def cle_render():
    return os.getenv("RENDER_API_KEY") or ""


def jeton_github():
    """Facultatif : nécessaire seulement si un dépôt est privé (ou pour éviter la limite de l'API publique)."""
    return os.getenv("GITHUB_TOKEN") or ""


def jeton_acces():
    """Jeton que l'agent chef présente pour appeler cet agent (même valeur que HUB_TOKEN côté chef)."""
    return os.getenv("HUB_TOKEN") or ""


def service_id(cle):
    """Identifiant srv-... du service Render de l'agent, ou chaîne vide s'il n'est pas configuré."""
    return (os.getenv(AGENTS[cle]["service_env"]) or "").strip()
