"""Des foyers et des personnes de test, créés en direct dans la base puis retirés par `nettoie()`.

Données inventées seulement. La connexion est celle de l'administrateur local : c'est la préparation
des données, jamais le chemin éprouvé. Les sessions de connexion arrivent avec leur table (étape 0.3, T6).
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True)
class Personne:
    id: UUID
    foyer_id: UUID


class Fabrique:
    def __init__(self, admin: psycopg.Connection[tuple[object, ...]]) -> None:
        self._admin = admin
        self._foyers: list[UUID] = []
        self._utilisateurs: list[UUID] = []

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

    def nettoie(self) -> None:
        # Le foyer d'abord : la suppression emporte les profils et tout ce qui en dépend.
        self._admin.execute("delete from public.household where id = any(%s)", (self._foyers,))
        self._admin.execute("delete from auth.users where id = any(%s)", (self._utilisateurs,))
