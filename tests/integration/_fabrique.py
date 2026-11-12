"""Des foyers et des personnes de test, créés en direct dans la base puis retirés par `nettoie()`.

Données inventées seulement. La connexion est celle de l'administrateur local : c'est la préparation
des données, jamais le chemin éprouvé. Les sessions de connexion sont posées en direct dans leur table : la
création par la connexion est l'étape 0.4.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True)
class Personne:
    id: UUID
    foyer_id: UUID


@dataclass(frozen=True)
class SessionDeTest:
    """Le jeton tel que le cookie le porte, et l'empreinte que la base garde."""

    id: UUID
    jeton: str
    empreinte: bytes


def jeton_et_empreinte() -> tuple[str, bytes]:
    octets = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(octets).decode("ascii").rstrip("="), hashlib.sha256(octets).digest()


class Fabrique:
    def __init__(self, admin: psycopg.Connection[tuple[object, ...]]) -> None:
        self._admin = admin
        self._foyers: list[UUID] = []
        self._utilisateurs: list[UUID] = []
        self._recettes: list[UUID] = []

    @property
    def admin(self) -> psycopg.Connection[tuple[object, ...]]:
        """La connexion de préparation, pour relire ou fausser une ligne que le test inspecte."""
        return self._admin

    def foyer(self) -> UUID:
        foyer_id = uuid4()
        self._admin.execute(
            "insert into public.household (id, name) values (%s, %s)", (foyer_id, f"foyer-{foyer_id.hex[:8]}")
        )
        self._foyers.append(foyer_id)
        return foyer_id

    def personne(self, foyer_id: UUID) -> Personne:
        personne_id = uuid4()
        self._admin.execute(
            """
            insert into auth.users
              (instance_id, id, aud, role, email, email_confirmed_at, created_at, updated_at)
            values ('00000000-0000-0000-0000-000000000000', %s, 'authenticated', 'authenticated', %s,
                    now(), now(), now())
            """,
            (personne_id, f"{personne_id.hex[:12]}@test.local"),
        )
        self._utilisateurs.append(personne_id)
        self._admin.execute(
            "insert into public.user_profile (id, household_id, display_name) values (%s, %s, %s)",
            (personne_id, foyer_id, f"personne-{personne_id.hex[:6]}"),
        )
        return Personne(personne_id, foyer_id)

    def recette(self, foyer_id: UUID) -> UUID:
        """Une recette privée du foyer, sans photo."""
        recette_id = uuid4()
        self._admin.execute(
            "insert into public.recipe (id, owner_household_id, origin, visibility, title)"
            " values (%s, %s, 'manuelle', 'privee', %s)",
            (recette_id, foyer_id, f"recette-{recette_id.hex[:8]}"),
        )
        self._recettes.append(recette_id)
        return recette_id

    def session(
        self,
        personne_id: UUID,
        *,
        vue_il_y_a: timedelta = timedelta(0),
        echeance_dans: timedelta = timedelta(days=30),
        absolue_dans: timedelta = timedelta(days=90),
        revoquee: bool = False,
    ) -> SessionDeTest:
        """Une session posée en direct (la connexion est l'étape 0.4) ; elle part avec sa personne."""
        jeton, empreinte = jeton_et_empreinte()
        ligne = self._admin.execute(
            """
            insert into public.login_session
              (token_hash, person_id, created_at, last_seen_at, expires_at, absolute_expires_at, revoked_at)
            values (%s, %s, now() - %s, now() - %s, now() + %s, now() + %s,
                    case when %s then now() end)
            returning id
            """,
            (empreinte, personne_id, vue_il_y_a, vue_il_y_a, echeance_dans, absolue_dans, revoquee),
        ).fetchone()
        assert ligne is not None
        return SessionDeTest(ligne[0], jeton, empreinte)

    def nettoie(self) -> None:
        # Pas de clé étrangère de la recette vers le foyer : la suppression du foyer ne l'emporte pas.
        self._admin.execute("delete from public.recipe where id = any(%s)", (self._recettes,))
        # Le foyer ensuite : la suppression emporte les profils et tout ce qui en dépend.
        self._admin.execute("delete from public.household where id = any(%s)", (self._foyers,))
        self._admin.execute("delete from auth.users where id = any(%s)", (self._utilisateurs,))
