"""Aides des tests de suppression de compte (T14a) : un foyer semé avec ses charges, ses dépenses, ses
factures et sa clôture, et le geste d'une personne connectée (rôle `authenticated`, revendication `sub`).
Données inventées."""

import json
from dataclasses import dataclass
from uuid import UUID

import psycopg
from _fabrique import Fabrique, Personne

MOIS = "2026-10-01"
ANNEE = 2026


@dataclass(frozen=True)
class FoyerSeme:
    foyer_id: UUID
    a: Personne
    b: Personne | None


def en_tant_que(admin: psycopg.Connection[tuple[object, ...]], personne: UUID) -> None:
    """Dans la transaction en cours : le rôle `authenticated` et l'identité de la personne."""
    admin.execute("set local role authenticated")
    admin.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": str(personne), "role": "authenticated"}),),
    )


def seme_foyer(fabrique: Fabrique, *, a_deux: bool, cloture: bool = True) -> FoyerSeme:
    admin = fabrique.admin
    foyer = fabrique.foyer()
    a = fabrique.personne(foyer)
    b = fabrique.personne(foyer) if a_deux else None
    membres = [a, *([b] if b else [])]
    for membre in membres:
        admin.execute("update public.user_profile set entre_le = '2026-01-01' where id = %s", (membre.id,))
        admin.execute(
            "insert into public.revenu (household_id, user_profile_id, net_mensuel_cents, valid_from)"
            " values (%s, %s, 400000, '2026-01-01')",
            (foyer, membre.id),
        )
    compte = admin.execute(
        "insert into public.compte (household_id, nom, genre) values (%s, 'Commun', 'commun') returning id",
        (foyer,),
    ).fetchone()
    assert compte is not None

    def charge(libelle: str, cents: int, mode: str, periodicite: str, participants: list[Personne]) -> UUID:
        ligne = admin.execute(
            "insert into public.charge (household_id, libelle, montant_cents, mode, periodicite, categorie,"
            " commun, debut, compte_id) values (%s, %s, %s, %s, %s, 'autre', %s, '2026-01-01', %s)"
            " returning id",
            (foyer, libelle, cents, mode, periodicite, len(participants) > 1, compte[0]),
        ).fetchone()
        assert ligne is not None
        for participant in participants:
            admin.execute(
                "insert into public.charge_participant (charge_id, user_profile_id, household_id)"
                " values (%s, %s, %s)",
                (ligne[0], participant.id, foyer),
            )
        return UUID(str(ligne[0]))

    charge("Loyer", 80000, "fixe", "mensuel", membres)
    charge("Courses de A", 1500, "au_fil", "mensuel", [a])
    if b:
        charge("Abonnement de B", 1200, "fixe", "mensuel", [b])
    assurance = charge("Assurance", 36000, "facture", "annuel", [a])

    with admin.transaction():
        en_tant_que(admin, a.id)
        admin.execute("select public.ouvre_le_mois(%s)", (MOIS,))
    for mois in range(1, 13):
        admin.execute(
            "select public.ouvre_la_charge(%s, %s, %s)", (assurance, foyer, f"{ANNEE}-{mois:02d}-01")
        )
    admin.execute(
        "insert into public.releve_annuel (household_id, charge_id, annee, reel_cents, prevu_cents,"
        " ecart_cents, saisi_par) values (%s, %s, %s, 36500, 36000, 500, %s)",
        (foyer, assurance, ANNEE, a.id),
    )
    admin.execute(
        "insert into public.facture (id, household_id, charge_id, annee, paye_le, montant_cents,"
        " origine, saisi_par)"
        " values (gen_random_uuid(), %s, %s, %s, '2026-09-25', 36500, 'releve', %s)",
        (foyer, assurance, ANNEE, a.id),
    )
    ligne = admin.execute(
        "select d.id from public.depense d join public.charge c on c.id = d.charge_id"
        " where d.household_id = %s and d.mois = %s and c.libelle = 'Courses de A'",
        (foyer, MOIS),
    ).fetchone()
    assert ligne is not None
    admin.execute(
        "insert into public.saisie (id, household_id, depense_id, fait_le, montant_cents, saisi_par)"
        " values (gen_random_uuid(), %s, %s, '2026-10-05', 1500, %s)",
        (foyer, ligne[0], a.id),
    )
    if cloture:
        poche = admin.execute(
            "insert into public.poche_epargne (household_id, libelle, genre, objectif_cents)"
            " values (%s, 'Imprévus', 'urgence', 400000) returning id",
            (foyer,),
        ).fetchone()
        assert poche is not None
        with admin.transaction():
            en_tant_que(admin, a.id)
            admin.execute(
                "select public.cloture_le_mois(%s, '[]'::jsonb, '{}'::uuid[], null, %s)", (MOIS, poche[0])
            )
    return FoyerSeme(foyer, a, b)


def nombre(admin: psycopg.Connection[tuple[object, ...]], requete: str, *parametres: object) -> int:
    ligne = admin.execute(requete, parametres).fetchone()
    assert ligne is not None
    assert isinstance(ligne[0], int)
    return ligne[0]
