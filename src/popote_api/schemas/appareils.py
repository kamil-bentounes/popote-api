from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from popote_api.schemas.base import Sortie

Navigateur = Literal["chrome", "firefox", "safari", "edge", "autre"]
Systeme = Literal["windows", "macos", "linux", "android", "ios", "autre"]


class Appareil(Sortie):
    """Un appareil connecté : ce que la personne reconnaît, jamais ce qui permettrait de le retrouver."""

    id: UUID
    browser: Navigateur = Field(description="Famille de navigateur (`autre` si non reconnue).")
    os: Systeme = Field(description="Famille de système (`autre` si non reconnue).")
    created_at: datetime = Field(description="Ouverture de la session.")
    last_seen_at: datetime = Field(description="Dernière activité.")
    current: bool = Field(description="Vrai pour la session qui fait cette requête (une seule par page).")
