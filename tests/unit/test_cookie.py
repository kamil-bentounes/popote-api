"""Le cookie de session : ses attributs, lus sur l'en-tête brut (spec § 4, « Session »)."""

import pytest
from _commun import reglages
from fastapi import Response
from pydantic import ValidationError

from popote_api.security.cookie import DUREE_DU_COOKIE_S, pose_le_cookie_de_session

JETON = "J" * 43


def en_tete(env: str = "local", **autres: object) -> str:
    reponse = Response()
    pose_le_cookie_de_session(reponse, reglages(env, **autres), JETON)
    return reponse.headers["set-cookie"]


def attributs(brut: str) -> set[str]:
    return {a.strip().lower() for a in brut.partition(";")[2].split(";")}


def test_les_attributs_exacts() -> None:
    brut = en_tete()
    assert brut.startswith(f"__Host-popote_session={JETON};")
    assert attributs(brut) == {"max-age=7776000", "path=/", "httponly", "secure", "samesite=lax"}
    assert DUREE_DU_COOKIE_S == 90 * 24 * 3600


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_hors_local_le_nom_host_et_secure_sont_poses(env: str) -> None:
    brut = en_tete(env)
    assert brut.startswith("__Host-")
    assert {"secure", "httponly", "path=/"} <= attributs(brut)
    assert "domain" not in brut.lower()


def test_en_local_le_nom_et_secure_se_changent() -> None:
    brut = en_tete(session_cookie_name="popote_session", session_cookie_secure=False)
    assert brut.startswith("popote_session=")
    assert "secure" not in attributs(brut)
    assert "httponly" in attributs(brut)  # jamais configurable


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_le_demarrage_est_refuse_sans_secure_hors_local(env: str) -> None:
    with pytest.raises(ValidationError, match="session_cookie_secure"):
        reglages(env, session_cookie_secure=False)


@pytest.mark.parametrize("env", ["essai", "prod"])
def test_le_demarrage_est_refuse_sans_le_prefixe_host_hors_local(env: str) -> None:
    with pytest.raises(ValidationError, match="session_cookie_name"):
        reglages(env, session_cookie_name="popote_session")
