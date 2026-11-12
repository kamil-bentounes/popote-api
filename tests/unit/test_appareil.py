"""Le résumé de l'agent utilisateur (security/appareil.py) et les jetons neufs (security/jeton.py)."""

import re

import pytest

from popote_api.security.appareil import NAVIGATEURS, SYSTEMES, Appareil, resume_agent
from popote_api.security.jeton import FORME_DU_JETON, empreinte_du_jeton, jeton_neuf

CHROME_WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
EDGE_WINDOWS = CHROME_WINDOWS + " Edg/126.0.0.0"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"
SAFARI_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15"
)
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0.0.0 Mobile Safari/537.36"
)


@pytest.mark.parametrize(
    ("agent", "attendu"),
    [
        (CHROME_WINDOWS, Appareil("chrome", "windows")),
        (EDGE_WINDOWS, Appareil("edge", "windows")),
        (FIREFOX_LINUX, Appareil("firefox", "linux")),
        (SAFARI_MAC, Appareil("safari", "macos")),
        (SAFARI_IPHONE, Appareil("safari", "ios")),
        (CHROME_ANDROID, Appareil("chrome", "android")),
        (None, Appareil("autre", "autre")),
        ("", Appareil("autre", "autre")),
        ("curl/8.5.0", Appareil("autre", "autre")),
    ],
)
def test_resume_agent_reconnait_les_familles(agent: str | None, attendu: Appareil) -> None:
    assert resume_agent(agent) == attendu


def test_resume_agent_ne_garde_que_des_familles_connues_meme_sur_une_valeur_hostile() -> None:
    appareil = resume_agent("Chrome/1 " + "A" * 100_000 + "\x00 DROP TABLE")
    assert appareil.navigateur in NAVIGATEURS
    assert appareil.systeme in SYSTEMES


def test_resume_agent_ne_lit_pas_au_dela_de_la_borne() -> None:
    assert resume_agent("x" * 600 + " Firefox/1") == Appareil("autre", "autre")


def test_un_jeton_neuf_se_reconnait_et_son_empreinte_est_celle_du_jeton() -> None:
    jeton, empreinte = jeton_neuf()
    assert FORME_DU_JETON.fullmatch(jeton)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", jeton)
    assert empreinte_du_jeton(jeton) == empreinte
    assert len(empreinte) == 32


def test_deux_jetons_neufs_different() -> None:
    assert jeton_neuf()[0] != jeton_neuf()[0]
