"""Configuration de l'agent devops : tout vient des variables d'environnement, rien n'est écrit en dur."""
import os

# Agents suivis : seulement ceux qui sont hébergés sur Render. L'agent développeur (GitHub Actions) et
# l'agent Instagram (Supabase) n'y sont pas. Clé -> dépôt GitHub et variables d'environnement qui portent
# l'identifiant du service Render (la première définie est retenue).
# RENDER_SERVICE_ID est fournie par Render au service en cours : tant que cet agent tourne dans l'agent
# chef, le service de l'agent chef est donc reconnu sans réglage.
AGENTS = {
    "manager": {"nom": "Agent chef", "depot": "AnthonyStocko/agent-manager",
                "service_env": ("RENDER_SERVICE_AGENT_MANAGER", "RENDER_SERVICE_ID")},
    "emploi": {"nom": "Agent emploi", "depot": "AnthonyStocko/agent-emploi",
               "service_env": ("RENDER_SERVICE_AGENT_EMPLOI",)},
    "perso": {"nom": "Agent perso", "depot": "AnthonyStocko/agent-perso",
              "service_env": ("RENDER_SERVICE_AGENT_PERSO",)},
}


def cle_render():
    return (os.getenv("RENDER_API_KEY") or "").strip()


def jeton_github():
    """Facultatif : nécessaire seulement si un dépôt est privé (ou pour éviter la limite de l'API publique).
    À défaut de GITHUB_TOKEN, le jeton de l'agent développeur (DEV_GITHUB_TOKEN) est utilisé."""
    return (os.getenv("GITHUB_TOKEN") or os.getenv("DEV_GITHUB_TOKEN") or "").strip()


def jeton_acces():
    """Jeton exigé par le serveur HTTP de cet agent (même valeur que HUB_TOKEN côté agent chef)."""
    return os.getenv("HUB_TOKEN") or ""


def service_id(cle):
    """Identifiant srv-... du service Render de l'agent, ou chaîne vide s'il n'est pas configuré."""
    for nom in AGENTS[cle]["service_env"]:
        valeur = (os.getenv(nom) or "").strip()
        if valeur:
            return valeur
    return ""
