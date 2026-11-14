"""L'envoi réel par Scaleway TEM (0.4bis S4), contre un faux transport : aucun appel réseau, jamais."""

import asyncio
import gzip
import json
import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
import pytest
from _commun import reglages
from pydantic import SecretStr, ValidationError

from popote_api.config import MailProvider, Settings
from popote_api.infra import mail_scaleway, mails_textes
from popote_api.infra.mail_scaleway import (
    EnvoiScaleway,
    Expediteur,
    cree_envoi_scaleway,
)
from popote_api.infra.mails import (
    EnvoiMail,
    EnvoiParEnveloppe,
    MailIndisponible,
    MessageCode,
    MessageInvitation,
    TypeDeMail,
    cree_envoi_mail,
    envoie_sans_remonter,
)
from popote_api.main import create_app

URL = "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/emails"
CLE = "11111111-aaaa-bbbb-cccc-" + "d" * 12
PROJET = UUID("22222222-3333-4444-5555-666666666666")
EXPEDITEUR = Expediteur("bonjour@notre-popote.fr", "Popote")
ADRESSE = "claire@example.org"
CODE = "482916"
LIEN = "https://essai.notre-popote.fr/invitation#jeton-secret"
# La demande du code a lieu à MAINTENANT et fixe son échéance une fois pour toutes ; l'envoi se fait quelques
# secondes plus tard (HORLOGE) : si `send_before` suivait l'horloge d'envoi, il dériverait.
MAINTENANT = datetime(2026, 11, 13, 9, 30, 15, 987654, tzinfo=UTC)
HORLOGE = MAINTENANT + timedelta(seconds=3)
ORIGINES = reglages("essai").origines
# Ce que TEM recopie dans ses réponses : l'adresse du destinataire. Elle ne doit sortir nulle part.
ACCEPTE = {"emails": [{"id": "e1", "status": "new", "mail_rcpt": ADRESSE, "status_details": ADRESSE}]}

Reponse = Callable[[httpx.Request], httpx.Response]


def message_code(validite_min: int = 10) -> MessageCode:
    return MessageCode(ADRESSE, CODE, validite_min, MAINTENANT + timedelta(minutes=validite_min))


def message_invitation() -> MessageInvitation:
    return MessageInvitation(ADRESSE, "Claire", "Marc", LIEN, datetime(2026, 11, 20, 10, 30, tzinfo=UTC))


def ok(statut: str = "new") -> httpx.Response:
    return httpx.Response(200, json={"emails": [{"id": "e1", "status": statut, "mail_rcpt": ADRESSE}]})


def envoi(
    reponse: Reponse, pauses: list[float] | None = None, cle: str = CLE
) -> tuple[EnvoiScaleway, list[httpx.Request]]:
    """Un envoi branché sur un faux TEM ; la liste reçoit chaque requête vue ; `pauses`, chaque attente."""
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return reponse(requete)

    async def pause(secondes: float) -> None:
        if pauses is not None:
            pauses.append(secondes)

    return (
        EnvoiScaleway(
            SecretStr(cle),
            PROJET,
            EXPEDITEUR,
            ORIGINES,
            transport=httpx.MockTransport(gestionnaire),
            maintenant=lambda: HORLOGE,
            pause=pause,
        ),
        vues,
    )


def reponses_dans_l_ordre(*reponses: Reponse | httpx.Response) -> Reponse:
    """Chaque appel reçoit la réponse suivante ; une exception de transport se lève au lieu de se rendre."""
    suite = iter(reponses)

    def suivante(requete: httpx.Request) -> httpx.Response:
        reponse = next(suite)
        if callable(reponse):
            return reponse(requete)
        return reponse

    return suivante


def coupure(requete: httpx.Request) -> httpx.Response:
    raise httpx.ReadError("coupure", request=requete)  # la requête est partie, la réponse manque


def connexion_impossible(requete: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("impossible", request=requete)  # la requête n'est jamais partie


def delai(requete: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("trop lent", request=requete)


def corps(requete: httpx.Request) -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(requete.content)
    return contenu


# --- La charge utile -----------------------------------------------------------------------------------


async def test_le_code_part_avec_la_charge_utile_exacte() -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code())
    (requete,) = vues
    assert requete.method == "POST"
    assert str(requete.url) == URL
    assert requete.headers["X-Auth-Token"] == CLE
    assert requete.headers["Content-Type"] == "application/json"
    assert corps(requete) == {
        "from": {"email": "bonjour@notre-popote.fr", "name": "Popote"},
        "to": [{"email": ADRESSE}],
        "subject": "Ton code de connexion Popote",
        "text": "Ton code Popote est 482916. Il est valable 10 minutes. "
        "Si tu n'as rien demandé, ignore ce message.",
        "project_id": str(PROJET),
        "send_before": "2026-11-13T09:40:15Z",
    }


async def test_l_invitation_part_avec_la_charge_utile_exacte_et_sans_send_before() -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_l_invitation(message_invitation())
    (requete,) = vues
    assert str(requete.url) == URL
    assert requete.headers["X-Auth-Token"] == CLE
    assert corps(requete) == {
        "from": {"email": "bonjour@notre-popote.fr", "name": "Popote"},
        "to": [{"email": ADRESSE}],
        "subject": "Marc t'a gardé une place en cuisine",
        "text": mails_textes.texte_de_l_invitation(message_invitation()),
        "project_id": str(PROJET),
    }


@pytest.mark.parametrize(("minutes", "attendu"), [(10, "09:40:15"), (7, "09:37:15"), (1, "09:31:15")])
async def test_send_before_est_l_echeance_du_message_jamais_recalculee_a_l_envoi(
    minutes: int, attendu: str
) -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code(minutes))
    # L'horloge d'envoi (HORLOGE) a trois secondes d'avance sur la demande : l'échéance ne bouge pas.
    assert corps(vues[0])["send_before"] == f"2026-11-13T{attendu}Z"


async def test_send_before_est_tronque_a_la_seconde_jamais_arrondi_vers_le_haut() -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code())
    # 09:40:15,987654 : la seconde entamée n'est pas comptée, le code n'est jamais livré trop tard.
    assert corps(vues[0])["send_before"].endswith("09:40:15Z")


async def test_send_before_garde_le_fuseau_de_l_echeance_et_s_ecrit_en_utc() -> None:
    paris = timezone(timedelta(hours=1))
    message = MessageCode(ADRESSE, CODE, 10, (MAINTENANT + timedelta(minutes=10)).astimezone(paris))
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message)
    assert corps(vues[0])["send_before"] == "2026-11-13T09:40:15Z"


@pytest.mark.parametrize("decalage_s", [0, -1, -600])
async def test_un_code_deja_expire_n_est_pas_envoye(decalage_s: int) -> None:
    echeance = HORLOGE + timedelta(seconds=decalage_s)
    boite, vues = envoi(lambda _: ok())
    with pytest.raises(MailIndisponible, match="expiré") as erreur:
        await boite.envoie_le_code(MessageCode(ADRESSE, CODE, 10, echeance))
    assert vues == []
    assert erreur.value.issue_inconnue is False


@pytest.mark.parametrize(
    ("horloge_us", "echeance_us", "part"),
    [
        (700_000, 900_000, False),  # même seconde tronquée : TEM le verrait déjà passé
        (0, 999_999, False),
        (900_000, 100_000 + 1_000_000, True),  # la seconde suivante
    ],
)
async def test_l_expiration_se_juge_a_la_seconde_comme_le_fournisseur(
    horloge_us: int, echeance_us: int, part: bool
) -> None:
    debut = datetime(2026, 11, 13, 9, 30, 15, tzinfo=UTC)
    boite, vues = envoi(lambda _: ok())
    boite._horloge = lambda: debut + timedelta(microseconds=horloge_us)
    message = MessageCode(ADRESSE, CODE, 10, debut + timedelta(microseconds=echeance_us))
    if part:
        await boite.envoie_le_code(message)
        assert corps(vues[0])["send_before"] == "2026-11-13T09:30:16Z"
    else:
        with pytest.raises(MailIndisponible, match="expiré"):
            await boite.envoie_le_code(message)
        assert vues == []


async def test_la_reprise_ne_reposte_pas_un_code_expire_pendant_la_pause() -> None:
    heures = iter([HORLOGE, HORLOGE + timedelta(seconds=3)])
    appels: list[httpx.Request] = []

    def tem(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(503)

    boite = EnvoiScaleway(
        SecretStr(CLE),
        PROJET,
        EXPEDITEUR,
        ORIGINES,
        transport=httpx.MockTransport(tem),
        maintenant=lambda: next(heures),
        pause=lambda _: asyncio.sleep(0),
    )
    echeance = HORLOGE + timedelta(seconds=2)  # valable à la première tentative, expiré après la pause
    with pytest.raises(MailIndisponible, match="expiré avant la reprise") as erreur:
        await boite.envoie_le_code(MessageCode(ADRESSE, CODE, 10, echeance))
    assert len(appels) == 1
    assert erreur.value.issue_inconnue is True  # le 503 du premier essai laisse un doute


async def test_la_reprise_d_un_code_encore_valable_part_avec_le_meme_send_before() -> None:
    boite, vues = envoi(reponses_dans_l_ordre(httpx.Response(503), ok()))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 2 and corps(vues[0])["send_before"] == corps(vues[1])["send_before"]


async def test_un_code_qui_expire_dans_une_seconde_part_encore() -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(MessageCode(ADRESSE, CODE, 10, HORLOGE + timedelta(seconds=1)))
    assert len(vues) == 1


async def test_le_sujet_envoye_est_celui_de_l_enveloppe(monkeypatch: pytest.MonkeyPatch) -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code())
    await boite.envoie_l_invitation(message_invitation())
    assert [corps(v)["subject"] for v in vues] == [
        mails_textes.OBJET_DU_CODE,
        "Marc t'a gardé une place en cuisine",
    ]
    assert CODE not in corps(vues[0])["subject"] and "Claire" not in corps(vues[1])["subject"]


async def test_le_prenom_refuse_de_l_hote_donne_l_objet_de_repli_dans_la_charge_utile() -> None:
    message = MessageInvitation(
        ADRESSE, "Claire", "Marc<b>", LIEN, datetime(2026, 11, 20, 10, 30, tzinfo=UTC)
    )
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_l_invitation(message)
    assert corps(vues[0])["subject"] == "Une place t'attend en cuisine"


async def test_un_lien_hors_des_origines_de_l_environnement_n_est_pas_envoye() -> None:
    boite, vues = envoi(lambda _: ok())
    prod = EnvoiScaleway(
        SecretStr(CLE),
        PROJET,
        EXPEDITEUR,
        reglages("prod").origines,
        transport=httpx.MockTransport(lambda r: vues.append(r) or ok()),  # type: ignore[func-returns-value]
    )
    with pytest.raises(ValueError, match="origine"):
        await prod.envoie_l_invitation(message_invitation())  # un lien de l'essai, un envoi de la prod
    assert vues == []
    assert boite is not None


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_la_fabrique_donne_les_origines_du_front_de_l_environnement(env: str) -> None:
    config = reglages(env, **COMPLET)
    envoi_reel = cree_envoi_mail(config)
    assert isinstance(envoi_reel, EnvoiScaleway)
    assert envoi_reel._origines == config.origines


def test_l_envoi_scaleway_est_une_realisation_par_enveloppe() -> None:
    assert issubclass(EnvoiScaleway, EnvoiParEnveloppe)


async def test_un_objet_de_moins_de_dix_caracteres_est_refuse_avant_l_appel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hors des gabarits, aucune enveloppe ne se fabrique : on élargit l'ensemble pour atteindre TEM.
    monkeypatch.setattr(mails_textes, "OBJET_DU_CODE", "Code")
    monkeypatch.setattr(mails_textes, "OBJETS_FIXES", frozenset({"Code"}))
    boite, vues = envoi(lambda _: ok())
    with pytest.raises(ValueError, match="objet"):
        await boite.envoie_le_code(message_code())
    assert vues == []


# --- Ce qui vaut un succès ------------------------------------------------------------------------------


@pytest.mark.parametrize("statut", ["new", "sending", "sent"])
async def test_un_mail_accepte_par_le_fournisseur_est_un_succes(statut: str) -> None:
    boite, vues = envoi(lambda _: ok(statut))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 1


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(200, json={"emails": [{"id": "e1", "status": "failed"}]}),
        httpx.Response(200, json={"emails": [{"id": "e1", "status": "canceled"}]}),
        httpx.Response(200, json={"emails": [{"id": "e1", "status": "unknown"}]}),
        httpx.Response(200, json={"emails": [{"id": "e1"}]}),
        httpx.Response(200, json={"emails": [{"id": "e1", "status": ["new"]}]}),
        httpx.Response(200, json={"emails": [{"id": "e1", "status": "NEW"}]}),
        httpx.Response(200, json={"emails": []}),
        httpx.Response(200, json={"emails": {"status": "new"}}),
        httpx.Response(200, json={"emails": ["new"]}),
        httpx.Response(200, json={"status": "new"}),
        httpx.Response(200, json=[{"status": "new"}]),
        httpx.Response(200, content=b"<html>portail captif</html>"),
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"[" * 200_000),
        httpx.Response(204),
    ],
)
async def test_une_reponse_qui_n_est_pas_un_mail_accepte_leve_sans_reprise(reponse: httpx.Response) -> None:
    boite, vues = envoi(lambda _: reponse)
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1  # un mail peut déjà être parti : jamais de reprise après un 2xx


async def test_une_reponse_trop_grosse_leve_et_n_est_pas_lue_en_entier() -> None:
    lus = 0

    async def flux() -> Any:
        nonlocal lus
        for _ in range(1000):
            lus += 1
            yield b"x" * 1024

    boite, vues = envoi(lambda _: httpx.Response(200, content=flux()))
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1
    assert lus <= mail_scaleway.OCTETS_MAX_REPONSE // 1024 + 2


class CorpsQuiCasse(httpx.AsyncByteStream):
    """Un corps annoncé (statut et en-têtes reçus) qui se coupe ou expire au milieu."""

    def __init__(self, erreur: Exception) -> None:
        self._erreur = erreur

    async def __aiter__(self) -> Any:
        yield b'{"emails": [{"sta'
        raise self._erreur


@pytest.mark.parametrize("statut", [200, 202, 400, 404])
@pytest.mark.parametrize(
    "erreur",
    [httpx.ReadError("coupé"), httpx.ReadTimeout("trop lent"), httpx.RemoteProtocolError("incomplet")],
)
async def test_un_corps_qui_casse_sous_un_2xx_ou_un_4xx_ne_se_reprend_jamais(
    statut: int, erreur: Exception
) -> None:
    boite, vues = envoi(lambda _: httpx.Response(statut, stream=CorpsQuiCasse(erreur)))
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1  # le mail a pu partir : envoyer deux fois est pire que d'échouer


async def test_un_corps_qui_casse_sous_un_5xx_se_reprend_une_fois() -> None:
    erreur = httpx.ReadError("coupé")
    boite, vues = envoi(reponses_dans_l_ordre(httpx.Response(502, stream=CorpsQuiCasse(erreur)), ok()))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 2


@pytest.mark.parametrize("encodage", ["gzip", "br", "deflate", "GZIP"])
async def test_une_reponse_compressee_est_refusee_sans_etre_decompressee(encodage: str) -> None:
    boite, vues = envoi(
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": encodage}, stream=httpx.ByteStream(b"\x1f\x8b corrompu")
        )
    )
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1


async def test_une_reponse_compressee_valide_n_est_pas_decompressee_non_plus() -> None:
    corps_valide = gzip.compress(json.dumps(ACCEPTE).encode())
    boite, vues = envoi(
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(corps_valide)
        )
    )
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1


async def test_la_requete_demande_l_identite_et_le_client_ignore_l_environnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avec un faux transport, httpx ne monte de toute façon aucun proxy : on lit donc les arguments du client.
    reglages_du_client: dict[str, Any] = {}
    vrai_client = httpx.AsyncClient

    def client_espion(**kwargs: Any) -> httpx.AsyncClient:
        reglages_du_client.update(kwargs)
        return vrai_client(**kwargs)

    monkeypatch.setattr(mail_scaleway.httpx, "AsyncClient", client_espion)
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code())
    assert reglages_du_client["trust_env"] is False
    assert reglages_du_client["follow_redirects"] is False
    assert vues[0].headers["Accept-Encoding"] == "identity"


async def test_un_retour_a_la_ligne_de_fin_ne_fait_pas_partie_de_la_cle() -> None:
    boite, vues = envoi(lambda _: ok(), cle=CLE + "\n")
    await boite.envoie_le_code(message_code())
    assert vues[0].headers["X-Auth-Token"] == CLE


# --- Les reprises ---------------------------------------------------------------------------------------


async def test_un_503_puis_un_200_envoie_un_seul_mail_en_deux_appels_au_meme_send_before() -> None:
    boite, vues = envoi(reponses_dans_l_ordre(httpx.Response(503), ok()))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 2
    assert corps(vues[0]) == corps(vues[1])  # même `send_before` : la reprise ne prolonge pas la vie du code


@pytest.mark.parametrize("statut", [500, 502, 503, 504])
async def test_un_5xx_deux_fois_leve_mail_indisponible(statut: int) -> None:
    boite, vues = envoi(lambda _: httpx.Response(statut, text=ADRESSE))
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 2


@pytest.mark.parametrize("statut", [301, 302, 307, 400, 401, 403, 404, 408, 409, 422, 429])
async def test_ni_4xx_ni_redirection_ne_se_reprend(statut: int) -> None:
    boite, vues = envoi(lambda _: httpx.Response(statut, headers={"Location": "https://pirate.example/"}))
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(vues) == 1  # une redirection n'est pas suivie : la clé ne quitte pas api.scaleway.com


@pytest.mark.parametrize("panne", [coupure, delai])
async def test_une_coupure_ou_un_delai_se_reprend_une_fois(panne: Reponse) -> None:
    boite, vues = envoi(reponses_dans_l_ordre(panne, ok()))
    await boite.envoie_l_invitation(message_invitation())
    assert len(vues) == 2


@pytest.mark.parametrize("panne", [coupure, delai])
async def test_une_coupure_ou_un_delai_deux_fois_leve_en_gardant_la_cause(panne: Reponse) -> None:
    boite, vues = envoi(lambda requete: panne(requete))
    with pytest.raises(MailIndisponible) as erreur:
        await boite.envoie_le_code(message_code())
    assert len(vues) == 2
    # La cause garde le type de l'erreur d'httpx, jamais l'erreur (elle porte la requête entière).
    assert str(erreur.value.__cause__) in {"ReadError", "ReadTimeout"}


async def test_la_reprise_attend_une_demi_seconde_par_defaut() -> None:
    pauses: list[float] = []
    boite, _ = envoi(reponses_dans_l_ordre(httpx.Response(503), ok()), pauses)
    await boite.envoie_le_code(message_code())
    assert pauses == [mail_scaleway.ATTENTE_AVANT_LA_REPRISE_S]


@pytest.mark.parametrize(
    ("retry_after", "attendu"), [("2", 2.0), ("0", 0.0), ("999", mail_scaleway.ATTENTE_MAX_S)]
)
async def test_la_reprise_respecte_retry_after_dans_la_limite(retry_after: str, attendu: float) -> None:
    pauses: list[float] = []
    reponse = httpx.Response(503, headers={"Retry-After": retry_after})
    boite, _ = envoi(reponses_dans_l_ordre(reponse, ok()), pauses)
    await boite.envoie_le_code(message_code())
    assert pauses == [attendu]


@pytest.mark.parametrize("retry_after", ["demain", "-5", "", "Wed, 21 Oct 2026 07:28:00 GMT", "1e3", "٣"])
async def test_un_retry_after_illisible_vaut_l_attente_par_defaut(retry_after: str) -> None:
    pauses: list[float] = []
    reponse = httpx.Response(503, headers={"Retry-After": retry_after.encode()})
    boite, _ = envoi(reponses_dans_l_ordre(reponse, ok()), pauses)
    await boite.envoie_le_code(message_code())
    assert pauses == [mail_scaleway.ATTENTE_AVANT_LA_REPRISE_S]


async def test_chaque_etape_a_un_delai_fini() -> None:
    boite, vues = envoi(lambda _: ok())
    await boite.envoie_le_code(message_code())
    assert vues[0].extensions["timeout"] == {"connect": 3.0, "read": 5.0, "write": 5.0, "pool": 3.0}


# --- Ce que le journal peut dire : « issue inconnue » quand le mail a pu partir ---------------------------


def une_panne(reponse: Reponse) -> MailIndisponible:
    async def envoyer() -> MailIndisponible:
        boite, _ = envoi(reponse)
        with pytest.raises(MailIndisponible) as erreur:
            await boite.envoie_le_code(message_code())
        return erreur.value

    return asyncio.run(envoyer())


@pytest.mark.parametrize(
    ("reponse", "inconnue"),
    [
        (coupure, True),
        (delai, True),
        (connexion_impossible, False),
        (lambda _: httpx.Response(500), True),
        (lambda _: httpx.Response(503), True),
        (lambda _: httpx.Response(504), True),
        (lambda _: httpx.Response(400), False),
        (lambda _: httpx.Response(429), False),
        (lambda _: httpx.Response(200, json={"emails": [{"status": "failed"}]}), False),
        (lambda _: httpx.Response(200, json={"emails": [{"status": "canceled"}]}), False),
        (lambda _: httpx.Response(200, content=b"<html>portail</html>"), True),
        (lambda _: httpx.Response(200, json={"emails": []}), True),
        (lambda _: httpx.Response(200, json={"emails": [{"id": "x"}]}), True),
        (lambda _: httpx.Response(200, stream=CorpsQuiCasse(httpx.ReadError("coupé"))), True),
        (lambda _: httpx.Response(200, content=b"x" * (mail_scaleway.OCTETS_MAX_REPONSE * 2)), True),
    ],
)
def test_l_erreur_dit_si_le_mail_a_pu_partir(reponse: Reponse, inconnue: bool) -> None:
    assert une_panne(reponse).issue_inconnue is inconnue


@pytest.mark.parametrize(
    ("premiere", "seconde", "inconnue"),
    [
        (coupure, lambda _: httpx.Response(400), True),
        (delai, lambda _: httpx.Response(400), True),
        (coupure, lambda _: httpx.Response(503), True),
        (delai, lambda _: httpx.Response(200, json={"emails": [{"status": "failed"}]}), True),
        (lambda _: httpx.Response(503), coupure, True),
        (connexion_impossible, lambda _: httpx.Response(400), False),
        (connexion_impossible, connexion_impossible, False),
        (connexion_impossible, coupure, True),
        (connexion_impossible, lambda _: httpx.Response(503), True),
        (lambda _: httpx.Response(503), lambda _: httpx.Response(400), True),
        (lambda _: httpx.Response(503), lambda _: httpx.Response(503), True),
        (lambda _: httpx.Response(502), lambda _: httpx.Response(400), True),
        (lambda _: httpx.Response(502), lambda _: httpx.Response(504), True),
        (lambda _: httpx.Response(504), lambda _: httpx.Response(504), True),
        (lambda _: httpx.Response(500), lambda _: httpx.Response(502), True),
    ],
)
def test_une_premiere_tentative_sans_reponse_laisse_l_issue_inconnue_quelle_que_soit_la_seconde(
    premiere: Reponse, seconde: Reponse, inconnue: bool
) -> None:
    assert une_panne(reponses_dans_l_ordre(premiere, seconde)).issue_inconnue is inconnue


def test_une_exception_etrangere_du_transport_n_est_pas_reprise_et_laisse_l_issue_inconnue() -> None:
    def tombe(requete: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"boom {CLE} {ADRESSE}")

    async def envoyer() -> tuple[MailIndisponible, int]:
        boite, vues = envoi(tombe)
        with pytest.raises(MailIndisponible) as erreur:
            await boite.envoie_le_code(message_code())
        return erreur.value, len(vues)

    erreur, appels = asyncio.run(envoyer())
    assert appels == 1 and erreur.issue_inconnue is True
    sortie = tout_ce_qui_sort(erreur)
    assert CLE not in sortie and ADRESSE not in sortie and "boom" not in sortie
    assert not any(isinstance(m, RuntimeError) for m in la_chaine_des_erreurs(erreur))


@pytest.mark.parametrize(
    ("premiere", "inconnue"),
    [(connexion_impossible, False), (coupure, True), (lambda _: httpx.Response(503), True)],
)
def test_le_delai_total_pendant_la_pause_garde_l_incertitude_de_la_premiere_tentative(
    premiere: Reponse, inconnue: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)

    async def pause_sans_fin(_: float) -> None:
        await asyncio.Event().wait()

    async def envoyer() -> MailIndisponible:
        boite = EnvoiScaleway(
            SecretStr(CLE),
            PROJET,
            EXPEDITEUR,
            ORIGINES,
            transport=httpx.MockTransport(premiere),
            maintenant=lambda: HORLOGE,
            pause=pause_sans_fin,
        )
        with pytest.raises(MailIndisponible) as erreur:
            await asyncio.wait_for(boite.envoie_le_code(message_code()), timeout=5)
        return erreur.value

    # Aucune requête en vol pendant la pause : seule la première tentative peut avoir laissé un doute.
    assert asyncio.run(envoyer()).issue_inconnue is inconnue


def test_un_503_puis_le_delai_total_pendant_la_seconde_requete_laisse_l_issue_inconnue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)
    appels = 0

    class UnPuisMuet(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal appels
            appels += 1
            if appels == 1:
                return httpx.Response(503)
            await asyncio.Event().wait()
            raise AssertionError("jamais atteint")

    async def envoyer() -> MailIndisponible:
        boite = EnvoiScaleway(
            SecretStr(CLE),
            PROJET,
            EXPEDITEUR,
            ORIGINES,
            transport=UnPuisMuet(),
            maintenant=lambda: HORLOGE,
            pause=lambda _: asyncio.sleep(0),
        )
        with pytest.raises(MailIndisponible) as erreur:
            await boite.envoie_le_code(message_code())
        return erreur.value

    assert asyncio.run(envoyer()).issue_inconnue is True


def test_un_etat_unknown_de_tem_laisse_l_issue_inconnue() -> None:
    assert une_panne(lambda _: httpx.Response(200, json={"emails": [{"status": "unknown"}]})).issue_inconnue


class CorpsQuiCasseALaFermeture(httpx.AsyncByteStream):
    async def __aiter__(self) -> Any:
        yield b""

    async def aclose(self) -> None:
        raise httpx.CloseError("fermeture cassée")


def test_un_503_dont_la_fermeture_casse_reste_un_503_qui_se_reprend() -> None:
    async def envoyer() -> int:
        boite, vues = envoi(
            reponses_dans_l_ordre(httpx.Response(503, stream=CorpsQuiCasseALaFermeture()), ok())
        )
        await boite.envoie_le_code(message_code())
        return len(vues)

    assert asyncio.run(envoyer()) == 2


def test_un_4xx_dont_la_fermeture_casse_reste_un_4xx_sans_reprise_ni_doute() -> None:
    # Le statut reçu décide : un 400 est un refus, la fermeture cassée n'en fait pas une coupure incertaine.
    erreur = une_panne(lambda _: httpx.Response(400, stream=CorpsQuiCasseALaFermeture()))
    assert erreur.issue_inconnue is False


def test_un_delai_total_depasse_laisse_l_issue_inconnue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)

    class Muet(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("jamais atteint")

    async def envoyer() -> MailIndisponible:
        boite = EnvoiScaleway(SecretStr(CLE), PROJET, EXPEDITEUR, ORIGINES, transport=Muet())
        with pytest.raises(MailIndisponible) as erreur:
            await boite.envoie_le_code(
                MessageCode(ADRESSE, CODE, 10, datetime.now(UTC) + timedelta(minutes=10))
            )
        return erreur.value

    assert asyncio.run(envoyer()).issue_inconnue is True


@pytest.mark.parametrize(
    ("reponse", "attendu"),
    [(coupure, "issue inconnue"), (lambda _: httpx.Response(400), "non envoyé")],
)
async def test_le_journal_distingue_issue_inconnue_et_non_envoye(
    reponse: Reponse, attendu: str, caplog: pytest.LogCaptureFixture
) -> None:
    boite, _ = envoi(reponse)
    with caplog.at_level(logging.DEBUG, logger="popote_api.infra.mails"):
        assert await envoie_sans_remonter(boite.envoie_le_code, message_code(), TypeDeMail.code) is False
    assert attendu in caplog.text
    assert ("non envoyé" in caplog.text) is (attendu == "non envoyé")


# --- Le délai total et l'annulation ----------------------------------------------------------------------


async def test_le_delai_total_borne_l_envoi_pause_comprise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)
    appels: list[httpx.Request] = []

    def lent(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(503)

    async def pause_sans_fin(_: float) -> None:
        await asyncio.Event().wait()

    boite = EnvoiScaleway(
        SecretStr(CLE),
        PROJET,
        EXPEDITEUR,
        ORIGINES,
        transport=httpx.MockTransport(lent),
        maintenant=lambda: HORLOGE,
        pause=pause_sans_fin,
    )
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())
    assert len(appels) == 1  # la pause n'a pas fini : pas de seconde tentative


async def test_une_reponse_qui_ne_vient_pas_est_coupee_par_le_delai_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)

    class Muet(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("jamais atteint")

    boite = EnvoiScaleway(
        SecretStr(CLE), PROJET, EXPEDITEUR, ORIGINES, transport=Muet(), maintenant=lambda: HORLOGE
    )
    with pytest.raises(MailIndisponible):
        await boite.envoie_le_code(message_code())


async def test_l_annulation_de_la_tache_n_est_ni_avalee_ni_reprise() -> None:
    entre = asyncio.Event()
    appels = 0

    class Bloque(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal appels
            appels += 1
            entre.set()
            await asyncio.Event().wait()
            raise AssertionError("jamais atteint")

    boite = EnvoiScaleway(
        SecretStr(CLE), PROJET, EXPEDITEUR, ORIGINES, transport=Bloque(), maintenant=lambda: HORLOGE
    )
    tache = asyncio.create_task(boite.envoie_le_code(message_code()))
    await entre.wait()
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    assert tache.cancelled()
    assert appels == 1


async def test_envoie_sans_remonter_rend_faux_sur_un_echec_de_tem_et_vrai_sur_un_succes() -> None:
    boite, _ = envoi(lambda _: httpx.Response(400))
    assert await envoie_sans_remonter(boite.envoie_le_code, message_code(), TypeDeMail.code) is False
    boite, _ = envoi(lambda _: ok())
    assert await envoie_sans_remonter(boite.envoie_le_code, message_code(), TypeDeMail.code) is True


# --- Le secret, l'adresse, le code : nulle part ----------------------------------------------------------

PANNES: dict[str, Reponse] = {
    "succes": lambda _: ok(),
    "400": lambda _: httpx.Response(400, json={"message": f"invalid {ADRESSE} {CODE} {CLE}"}),
    "503": lambda _: httpx.Response(503, text=f"{ADRESSE} {CODE}"),
    "failed": lambda _: httpx.Response(200, json={"emails": [{"status": "failed", "mail_rcpt": ADRESSE}]}),
    "illisible": lambda _: httpx.Response(200, text=f"<html>{ADRESSE} {CODE}</html>"),
    "coupure": coupure,
    "delai": delai,
}


def la_chaine_des_erreurs(erreur: BaseException) -> list[BaseException]:
    """L'erreur, ses causes et ses contextes, sans boucle."""
    vues: list[BaseException] = []
    file: list[BaseException | None] = [erreur]
    while file:
        courante = file.pop()
        if courante is None or any(courante is v for v in vues):
            continue
        vues.append(courante)
        file += [courante.__cause__, courante.__context__]
    return vues


def tout_ce_qui_sort(erreur: BaseException) -> str:
    return "\n".join([str(erreur), repr(erreur), *traceback.format_exception(erreur)])


@pytest.mark.parametrize("panne", PANNES)
async def test_ni_la_cle_ni_l_adresse_ni_le_code_ne_sortent_ni_en_journal_ni_en_exception(
    panne: str, caplog: pytest.LogCaptureFixture
) -> None:
    boite, _ = envoi(PANNES[panne])
    sortie = ""
    with caplog.at_level(logging.DEBUG):
        await envoie_sans_remonter(boite.envoie_le_code, message_code(), TypeDeMail.code)
        await envoie_sans_remonter(boite.envoie_l_invitation, message_invitation(), TypeDeMail.invitation)
        for appel in (boite.envoie_le_code(message_code()), boite.envoie_l_invitation(message_invitation())):
            try:
                await appel
            except MailIndisponible as erreur:
                sortie += tout_ce_qui_sort(erreur)
    for secret in (CLE, ADRESSE, CODE, LIEN, "jeton-secret", "Claire"):
        assert secret not in sortie + caplog.text


@pytest.mark.parametrize("panne", [p for p in PANNES if p != "succes"])
async def test_la_chaine_d_une_erreur_ne_porte_aucune_requete_ni_aucune_erreur_d_httpx(panne: str) -> None:
    # `httpx.HTTPError.request` tient la requête entière : en-tête de clé, adresse, texte (code ou lien).
    boite, _ = envoi(PANNES[panne])
    with pytest.raises(MailIndisponible) as erreur:
        await boite.envoie_le_code(message_code())
    for maillon in la_chaine_des_erreurs(erreur.value):
        assert not isinstance(maillon, httpx.HTTPError)
        assert not hasattr(maillon, "request")
        for secret in (CLE, ADRESSE, CODE):
            assert secret not in repr(vars(maillon)) + repr(maillon.args)


@pytest.mark.parametrize("panne", [p for p in PANNES if p != "succes"])
async def test_l_erreur_finale_n_a_ni_contexte_ni_cause_qui_garde_une_pile(panne: str) -> None:
    # Une exception retient sa pile, donc les variables locales : `charge` (adresse, code), l'en-tête de clé.
    boite, _ = envoi(PANNES[panne])
    with pytest.raises(MailIndisponible) as erreur:
        await boite.envoie_le_code(message_code())
    assert erreur.value.__context__ is None
    cause = erreur.value.__cause__
    assert cause is None or (type(cause).__name__ == "_CauseDeTransport" and cause.__traceback__ is None)


def test_l_erreur_du_delai_total_n_a_ni_contexte_ni_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail_scaleway, "DELAI_TOTAL_S", 0.05)

    class Muet(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("jamais atteint")

    async def envoyer() -> MailIndisponible:
        boite = EnvoiScaleway(
            SecretStr(CLE), PROJET, EXPEDITEUR, ORIGINES, transport=Muet(), maintenant=lambda: HORLOGE
        )
        with pytest.raises(MailIndisponible) as erreur:
            await asyncio.wait_for(boite.envoie_le_code(message_code()), timeout=5)
        return erreur.value

    erreur = asyncio.run(envoyer())
    assert erreur.__cause__ is None and erreur.__context__ is None


def test_le_repr_d_une_reponse_ne_porte_pas_le_corps() -> None:
    reponse = mail_scaleway._Reponse(200, 0.5, f"corps {ADRESSE} {CODE}".encode())
    assert ADRESSE not in repr(reponse) and CODE not in repr(reponse)


async def test_un_5xx_se_reprend_meme_si_son_corps_est_enorme_ou_compresse() -> None:
    enorme = httpx.Response(503, content=b"x" * (mail_scaleway.OCTETS_MAX_REPONSE * 4))
    compresse = httpx.Response(
        502, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"\x1f\x8b corrompu")
    )
    boite, vues = envoi(reponses_dans_l_ordre(enorme, ok()))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 2
    boite, vues = envoi(reponses_dans_l_ordre(compresse, ok()))
    await boite.envoie_le_code(message_code())
    assert len(vues) == 2


async def test_un_echec_journalise_la_classe_du_statut_et_rien_d_autre(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boite, _ = envoi(lambda _: httpx.Response(403, json={"message": f"{ADRESSE} {CLE}"}))
    with caplog.at_level(logging.DEBUG, logger=mail_scaleway.__name__):
        with pytest.raises(MailIndisponible):
            await boite.envoie_le_code(message_code())
    assert "4xx" in caplog.text
    assert "403" not in caplog.text
    assert ADRESSE not in caplog.text and CLE not in caplog.text


def test_la_cle_n_est_ni_dans_le_repr_de_l_envoi_ni_dans_celui_des_reglages() -> None:
    boite, _ = envoi(lambda _: ok())
    config = reglages("local", scaleway_tem_secret_key=CLE, scaleway_tem_project_id=str(PROJET))
    for texte in (
        repr(boite),
        str(boite),
        repr(vars(boite)),
        repr(config),
        str(config),
        config.model_dump_json(),
    ):
        assert CLE not in texte
    assert CLE not in repr(config.model_dump())


@pytest.mark.parametrize(
    "cle", ["", "avec espace" + "x" * 20, "clé-" + "x" * 20, "ligne\nsuivante", "tab\tulation"]
)
def test_une_cle_non_transmissible_dans_un_en_tete_est_refusee_sans_etre_recopiee(cle: str) -> None:
    with pytest.raises(ValueError, match="Clé") as erreur:
        EnvoiScaleway(SecretStr(cle), PROJET, EXPEDITEUR, ORIGINES)
    assert not cle or cle not in tout_ce_qui_sort(erreur.value)


# --- Les réglages ----------------------------------------------------------------------------------------

COMPLET = {
    "mail_provider": "scaleway",
    "scaleway_tem_secret_key": CLE,
    "scaleway_tem_project_id": str(PROJET),
}


@pytest.mark.parametrize(
    "cle", ["x", "1111 1111-aaaa-bbbb-cccc-dddddddddddd", "g" * 8 + "-aaaa-bbbb-cccc-" + "d" * 12, "d" * 36]
)
def test_une_cle_qui_n_est_pas_un_uuid_est_refusee_sans_etre_recopiee(cle: str) -> None:
    with pytest.raises(ValueError, match="UUID") as erreur:
        EnvoiScaleway(SecretStr(cle), PROJET, EXPEDITEUR, ORIGINES)
    assert cle not in tout_ce_qui_sort(erreur.value)


def test_la_fabrique_refuse_une_cle_qui_n_est_pas_un_uuid() -> None:
    with pytest.raises(ValueError, match="UUID"):
        cree_envoi_mail(reglages("local", **(COMPLET | {"scaleway_tem_secret_key": "x"})))


@pytest.mark.parametrize(
    "adresse", ["a@evil.example", "a@sub.notre-popote.fr", "a@notre-popote.fr.evil.example"]
)
def test_un_expediteur_hors_du_domaine_verifie_est_refuse(adresse: str) -> None:
    with pytest.raises(ValueError, match=r"notre-popote\.fr"):
        reglages("local", mail_from_address=adresse)
    with pytest.raises(ValueError, match=r"notre-popote\.fr"):
        Expediteur(adresse, "Popote")


@pytest.mark.parametrize(
    "contournement",
    [
        {"mail_from_address": "a@notre-popote.fr\r\nBcc: x@evil.example\r\n@notre-popote.fr"},
        {"mail_from_address": "a\r\n@notre-popote.fr"},
        {"mail_from_name": "Popote\r\nBcc: x@y.fr"},
        {"mail_from_name": "=?utf-8?b?UG9wb3Rl?="},
        {"scaleway_tem_project_id": str(PROJET)},  # une chaîne, pas un UUID
        {"scaleway_tem_project_id": None},
    ],
)
def test_la_fabrique_revalide_tous_les_reglages_meme_contournes(contournement: dict[str, Any]) -> None:
    config = reglages("local", **COMPLET).model_copy(update=contournement)
    with pytest.raises(ValueError):
        cree_envoi_scaleway(config)


@pytest.mark.parametrize("nom", ["=?utf-8?b?UG9wb3Rl?=", "Popote =? x"])
def test_un_nom_d_expediteur_qui_ressemble_a_un_mot_encode_est_refuse(nom: str) -> None:
    with pytest.raises(ValidationError, match="mail_from_name"):
        reglages("local", mail_from_name=nom)


def test_la_fabrique_refuse_un_expediteur_hors_du_domaine_meme_si_les_reglages_sont_contournes() -> None:
    config = reglages("local", **COMPLET).model_copy(update={"mail_from_address": "a@evil.example"})
    with pytest.raises(ValueError, match=r"notre-popote\.fr"):
        cree_envoi_scaleway(config)


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_le_fournisseur_scaleway_complet_est_admis_partout(env: str) -> None:
    config = reglages(env, **COMPLET)
    assert config.mail_provider == "scaleway"
    assert config.scaleway_tem_project_id == PROJET
    assert config.mail_from_address == "bonjour@notre-popote.fr"
    assert config.mail_from_name == "Popote"


@pytest.mark.parametrize("manquant", ["scaleway_tem_secret_key", "scaleway_tem_project_id"])
@pytest.mark.parametrize("vide", [None, ""])
@pytest.mark.parametrize("env", ["essai", "prod"])
def test_le_fournisseur_scaleway_sans_cle_ou_sans_projet_refuse_de_demarrer(
    env: str, vide: str | None, manquant: str
) -> None:
    valeurs = dict(COMPLET)
    valeurs[manquant] = vide  # type: ignore[assignment]
    with pytest.raises(ValidationError, match=manquant):
        reglages(env, **valeurs)


async def test_avec_scaleway_complet_le_demarrage_n_avertit_pas_du_mail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(reglages("essai", **COMPLET))
    with caplog.at_level(logging.WARNING, logger="popote_api.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "MAIL_PROVIDER" not in caplog.text
    assert type(app.state.mails) is EnvoiScaleway


def test_un_projet_qui_n_est_pas_un_uuid_est_refuse_sans_recopier_la_cle() -> None:
    with pytest.raises(ValidationError) as erreur:
        reglages("local", **(COMPLET | {"scaleway_tem_project_id": "pas-un-uuid"}))
    assert CLE not in tout_ce_qui_sort(erreur.value)


@pytest.mark.parametrize(
    "adresse",
    [
        "", "sans-arobase", "deux@@notre-popote.fr", "a b@notre-popote.fr",
        "a@notre-popote.fr\r\nBcc: x@y.fr",
        "a..b@notre-popote.fr", ".a@notre-popote.fr", "a.@notre-popote.fr", "a@", "@notre-popote.fr",
        "a@notre popote.fr", "é@notre-popote.fr", "<a@notre-popote.fr>", "x" * 65 + "@notre-popote.fr",
        "a@b.c", "a@notre-popote.f",
    ],
)  # fmt: skip
def test_une_adresse_d_expedition_mal_formee_est_refusee(adresse: str) -> None:
    with pytest.raises(ValidationError, match="mail_from_address"):
        reglages("local", mail_from_address=adresse)


@pytest.mark.parametrize(
    "nom",
    [
        "",
        "Po\npote",
        "Po\x00pote",
        "x" * 61,
        "   ",
        'Po"pote',
        "Po<pote>",
        "Po,pote",
        "Po;pote",
        "Popote @evil",
        "Popote:",
        "Po\\pote",
        " Popote",
        "Popote ",
        "Popote\u3164",
        "Po\u2800pote",
    ],
)
def test_un_nom_d_expediteur_mal_forme_est_refuse(nom: str) -> None:
    with pytest.raises(ValidationError, match="mail_from_name"):
        reglages("local", mail_from_name=nom)


def test_l_expediteur_se_regle() -> None:
    config = reglages("local", mail_from_address="hello@notre-popote.fr", mail_from_name="Popote & Cie")
    assert (config.mail_from_address, config.mail_from_name) == ("hello@notre-popote.fr", "Popote & Cie")


# --- Le choix de la réalisation ------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["local", "essai", "prod"])
def test_le_fournisseur_scaleway_choisit_la_realisation_scaleway(env: str) -> None:
    config = reglages(env, **COMPLET)
    assert type(cree_envoi_mail(config)) is EnvoiScaleway
    assert type(cree_envoi_scaleway(config)) is EnvoiScaleway


def test_la_realisation_scaleway_est_un_envoi_mail() -> None:
    boite: EnvoiMail = cree_envoi_scaleway(reglages("local", **COMPLET))
    assert boite is not None


@pytest.mark.parametrize("manquant", ["scaleway_tem_secret_key", "scaleway_tem_project_id"])
def test_la_fabrique_refuse_des_reglages_incomplets(manquant: str) -> None:
    valeurs = {"mail_provider": MailProvider.scaleway} | {
        "scaleway_tem_secret_key": SecretStr(CLE),
        "scaleway_tem_project_id": PROJET,
    }
    valeurs[manquant] = None  # type: ignore[assignment]
    config = Settings.model_construct(**valeurs)  # contourne la validation des réglages
    with pytest.raises(ValueError, match="scaleway"):
        cree_envoi_scaleway(config)


def test_la_fabrique_refuse_un_autre_fournisseur() -> None:
    config = Settings.model_construct(
        mail_provider=MailProvider.aucun,
        scaleway_tem_secret_key=SecretStr(CLE),
        scaleway_tem_project_id=PROJET,
    )
    with pytest.raises(ValueError, match="scaleway"):
        cree_envoi_scaleway(config)


def test_le_chemin_est_celui_de_la_region_de_paris_et_ne_se_regle_pas() -> None:
    assert mail_scaleway.URL_DES_MAILS == URL
    assert "scaleway_tem_url" not in Settings.model_fields
