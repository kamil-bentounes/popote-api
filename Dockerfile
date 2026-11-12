# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
# pip ne sert pas à l'exécution (uv installe dans .venv) et ses paquets embarqués portent des CVE
# (Trivy, 12/11/2026) : on le retire de l'image.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev \
    && python -m pip uninstall --yes pip \
    && useradd --uid 10001 --no-create-home popote
USER 10001
# La valeur la plus stricte par défaut : l'essai la remplace au déploiement.
ENV POPOTE_ENV=prod
# Le SHA du commit, rendu par /api/healthz : le déploiement vérifie que c'est cette image qui répond.
# En dernier, pour que sa variation n'invalide aucune couche de dépendances.
ARG POPOTE_VERSION=inconnue
ENV POPOTE_VERSION=$POPOTE_VERSION
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "--factory", "popote_api.main:create_app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--no-access-log"]
