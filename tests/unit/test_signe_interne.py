"""Tests de ops/signe_interne.py : la valeur produite est celle que la dépendance accepte."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))

import signe_interne as outil

from popote_api.security import signature

SECRET = "i" * 32
T0 = 1_700_000_000
ENV = {outil.VARIABLE: SECRET}


def test_l_outil_ecrit_une_signature_que_la_verification_accepte(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    corps = tmp_path / "corps.json"
    corps.write_bytes(b'{"a":1}')
    code = outil.main(["post", "/internal/purges", "--corps", str(corps)], ENV, T0)
    en_tete = signature.lit_l_en_tete(capsys.readouterr().out.strip(), T0)
    signature.verifie([SECRET.encode()], en_tete, "POST", b"/internal/purges", b'{"a":1}')
    assert code == 0


def test_sans_corps_le_corps_est_vide(capsys: pytest.CaptureFixture[str]) -> None:
    outil.main(["GET", "/internal/x"], ENV, T0)
    en_tete = signature.lit_l_en_tete(capsys.readouterr().out.strip(), T0)
    signature.verifie([SECRET.encode()], en_tete, "GET", b"/internal/x", b"")


@pytest.mark.parametrize("environ", [{}, {outil.VARIABLE: "court"}, {outil.VARIABLE: "é" * 32}])
def test_un_secret_absent_ou_invalide_est_refuse_sans_etre_ecrit(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert outil.main(["GET", "/internal/x"], environ, T0) == 2
    sortie = capsys.readouterr()
    assert sortie.out == ""
    assert "court" not in sortie.err


@pytest.mark.parametrize("chemin", ["/api/healthz", "/internalx", "/internal/x?a=1"])
def test_un_chemin_hors_de_l_interne_ou_avec_requete_est_refuse(chemin: str) -> None:
    assert outil.main(["GET", chemin], ENV, T0) == 2


def test_un_corps_illisible_est_refuse(tmp_path: Path) -> None:
    assert outil.main(["POST", "/internal/x", "--corps", str(tmp_path / "absent")], ENV, T0) == 2
