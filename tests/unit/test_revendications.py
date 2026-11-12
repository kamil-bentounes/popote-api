"""Les revendications que le SQL lit, et celles que le contexte personne pose (spec § 5.1, A8).

L'inventaire est écrit ici, fichier de migration par fichier. Une migration qui lit une revendication
absente de la liste fait échouer le test : il faut alors l'ajouter au contexte personne
(`revendications_personne`).
"""

import re
from pathlib import Path
from uuid import uuid4

import pytest
from _commun import reglages
from pydantic import ValidationError

from popote_api.infra.db import revendications_personne

MIGRATIONS = Path(__file__).parents[2] / "supabase" / "migrations"
LECTURE = re.compile(r"request\.jwt\.claim|request\.headers|auth\.(jwt|role|email)\(\)")
# Les migrations qui lisent une revendication (ou la posent, pour 0126), et ce qu'elles y lisent.
LECTEURS = {
    "0006_triggers.sql": {"role"},  # is_service_role(), avant 0131
    "0121_photo_des_plats.sql": {"iss"},  # tg_recipe_photo : le projet d'où vient l'adresse de la photo
    "0126_rappels.sql": {"role"},  # pose `service_role` le temps d'un appel interne, puis restaure
    "0131_porte_du_service.sql": {"role"},  # is_service_role() lit `role` pour authenticator seulement
}
# `auth.uid()` lit `sub` : il sert partout, et le contexte personne le pose.
LUES = {"sub"} | set().union(*LECTEURS.values())


def migrations_qui_lisent_une_revendication() -> set[str]:
    trouvees = set()
    for fichier in MIGRATIONS.glob("*.sql"):
        code = "\n".join(
            ligne for ligne in fichier.read_text().splitlines() if not ligne.lstrip().startswith("--")
        )
        if LECTURE.search(code):
            trouvees.add(fichier.name)
    return trouvees


def test_aucune_migration_ne_lit_une_revendication_hors_de_l_inventaire() -> None:
    inconnues = migrations_qui_lisent_une_revendication() - LECTEURS.keys()
    assert not inconnues, (
        f"revendication lue sans être inventoriée (et posée par le contexte personne) : {inconnues}"
    )


def test_le_contexte_personne_pose_toutes_les_revendications_lues() -> None:
    posees = set(revendications_personne(uuid4(), "https://p.supabase.co/auth/v1"))
    assert LUES - {"role"} <= posees  # `role` : posée aussi, mais pour `authenticated`
    assert "role" in posees


def test_le_contexte_personne_pose_sub_role_et_iss_comme_postgrest() -> None:
    personne = uuid4()
    assert revendications_personne(personne, "https://p.supabase.co/auth/v1") == {
        "sub": str(personne),
        "role": "authenticated",
        "iss": "https://p.supabase.co/auth/v1",
    }


def test_sans_emetteur_iss_n_est_pas_pose() -> None:
    assert "iss" not in revendications_personne(uuid4(), None)


@pytest.mark.parametrize("adresse", ["https://p.supabase.co", "https://p.supabase.co/"])
def test_l_emetteur_se_deduit_de_l_adresse_du_projet(adresse: str) -> None:
    assert reglages("essai", supabase_url=adresse).emetteur_des_jetons == "https://p.supabase.co/auth/v1"


def test_sans_adresse_de_projet_il_n_y_a_pas_d_emetteur() -> None:
    assert reglages("local").emetteur_des_jetons is None


@pytest.mark.parametrize(
    "adresse", ["https://p.supabase.co/rest/v1", "https://p.supabase.co/?a=1", "https://p.supabase.co/#x"]
)
def test_une_adresse_de_projet_avec_chemin_ou_requete_echoue_au_demarrage(adresse: str) -> None:
    with pytest.raises(ValidationError, match="supabase_url"):
        reglages("essai", supabase_url=adresse)


def test_une_adresse_de_projet_vide_vaut_absente() -> None:
    assert reglages("essai", supabase_url="").emetteur_des_jetons is None
