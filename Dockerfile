# Agent devops en serveur autonome (lecture seule, GET) : python app.py, port lu dans PORT (8796 par défaut).
# Image multi-architecture (arm64 pour la VM Oracle, amd64 pour un PC) : bibliothèque standard seulement.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8796

WORKDIR /app
COPY agent_devops ./agent_devops
COPY app.py ./

# Pas de droits root dans le conteneur.
RUN useradd --system --no-create-home devops
USER devops

EXPOSE 8796

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.getenv('PORT','8796'), timeout=4)"

CMD ["python", "app.py"]
