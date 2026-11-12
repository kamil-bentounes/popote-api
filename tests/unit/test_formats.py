"""Les formats communs (§ 3.8) : instant avec décalage, jour de Paris, somme en centimes."""

import random
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from popote_api import errors
from popote_api.formats import (
    CENTIMES_MAX,
    PARIS,
    Instant,
    Jour,
    Montant,
    aujourdhui_a_paris,
    jour_a_paris,
)


class Evenement(BaseModel):
    quand: Instant


class Anniversaire(BaseModel):
    le: Jour


class Depense(BaseModel):
    montant: Montant
    quand: Instant
    le: Jour


# --- Instant ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("2026-11-12T10:00:00Z", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12T10:00:00z", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12t10:00:00Z", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12T10:00:00+00:00", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12T11:00:00+01:00", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12T04:30:00-05:30", datetime(2026, 11, 12, 10, 0, tzinfo=UTC)),
        ("2026-11-12T10:00:00.5Z", datetime(2026, 11, 12, 10, 0, 0, 500000, tzinfo=UTC)),
        ("2026-11-12T10:00:00.123456Z", datetime(2026, 11, 12, 10, 0, 0, 123456, tzinfo=UTC)),
        ("2026-11-12T10:00:00.123456789Z", datetime(2026, 11, 12, 10, 0, 0, 123456, tzinfo=UTC)),
        ("2028-02-29T23:59:59-23:59", datetime(2028, 3, 1, 23, 58, 59, tzinfo=UTC)),
    ],
)
def test_un_instant_rfc3339_avec_decalage_est_accepte(texte: str, attendu: datetime) -> None:
    lu = Evenement.model_validate({"quand": texte}).quand
    assert lu == attendu
    assert lu.utcoffset() is not None


@pytest.mark.parametrize(
    "valeur",
    [
        "2026-11-12T10:00:00",  # sans décalage
        "2026-11-12T10:00:00.123",
        "2026-11-12",
        "2026-11-12 10:00:00Z",  # espace au lieu de T
        "2026-11-12T10:00Z",  # sans secondes
        "2026-11-12T10:00:00+0100",  # décalage sans deux-points
        "2026-11-12T10:00:00+01",
        "2026-11-12T10:00:00 Z",
        " 2026-11-12T10:00:00Z",
        "2026-11-12T10:00:00Z ",
        "2026-11-12T10:00:00.Z",
        "2026-11-12T10:00:00.1234567890Z",  # dix décimales
        "2026-11-12T10:00:60Z",  # seconde intercalaire : non représentable
        "2026-13-12T10:00:00Z",
        "2026-02-30T10:00:00Z",
        "2027-02-29T10:00:00Z",
        "2026-11-12T24:00:00Z",
        "2026-11-12T10:00:00+24:00",
        "2026-11-12T10:00:00+01:60",
        "0000-01-01T00:00:00Z",
        "\u0662\u0660\u0662\u0666-11-12T10:00:00Z",  # chiffres arabo-indiens
        "hier",
        "",
        1700000000,  # horodatage Unix
        1700000000.5,
        True,
        None,
        ["2026-11-12T10:00:00Z"],
        date(2026, 11, 12),
        datetime(2026, 11, 12, 10, 0),
    ],
)
def test_un_instant_sans_decalage_ou_hors_format_est_refuse(valeur: object) -> None:
    with pytest.raises(ValidationError) as erreur:
        Evenement.model_validate({"quand": valeur})
    assert erreur.value.errors()[0]["loc"] == ("quand",)


def test_un_instant_sans_decalage_est_refuse_aussi_dans_un_json() -> None:
    with pytest.raises(ValidationError):
        Evenement.model_validate_json('{"quand": "2026-11-12T10:00:00"}')
    with pytest.raises(ValidationError):
        Evenement.model_validate_json('{"quand": 1700000000}')


def test_un_instant_ecrit_toujours_un_decalage_et_en_utc() -> None:
    paris = datetime(2026, 7, 14, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    assert Evenement(quand=paris).model_dump_json() == '{"quand":"2026-07-14T10:30:00+00:00"}'
    assert Evenement(quand=datetime(2026, 11, 12, 10, 0, tzinfo=UTC)).model_dump_json() == (
        '{"quand":"2026-11-12T10:00:00+00:00"}'
    )
    assert Evenement(quand=datetime(2026, 1, 1, 0, 0, 0, 5, tzinfo=PARIS)).model_dump_json() == (
        '{"quand":"2025-12-31T23:00:00.000005+00:00"}'
    )


def test_un_instant_ecrit_se_relit_au_meme_instant() -> None:
    rng = random.Random(3)
    for _ in range(300):
        decalage = timezone(timedelta(minutes=rng.randrange(-23 * 60, 23 * 60 + 1)))
        instant = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(microseconds=rng.randrange(10**15))
        ecrit = Evenement(quand=instant.astimezone(decalage)).model_dump_json()
        assert Evenement.model_validate_json(ecrit).quand == instant


def test_le_schema_d_un_instant_est_une_date_heure_rfc3339() -> None:
    schema = Evenement.model_json_schema()["properties"]["quand"]
    assert (schema["type"], schema["format"]) == ("string", "date-time")


# --- Jour ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [("2026-11-12", date(2026, 11, 12)), ("2028-02-29", date(2028, 2, 29)), ("0001-01-01", date(1, 1, 1))],
)
def test_un_jour_aaaa_mm_jj_est_accepte(texte: str, attendu: date) -> None:
    assert Anniversaire.model_validate({"le": texte}).le == attendu
    assert Anniversaire.model_validate({"le": attendu}).le == attendu


@pytest.mark.parametrize(
    "valeur",
    [
        "2026-11-12T00:00:00Z",  # un instant n'est pas un jour
        "2026-11-12T00:00:00",
        "2026-11-12 ",
        " 2026-11-12",
        "2026-13-01",
        "2026-02-30",
        "2027-02-29",
        "2026-00-10",
        "20261112",
        "2026-W46-4",
        "2026-316",
        "12/11/2026",
        "2026-1-2",
        "\u0662\u0660\u0662\u0666-11-12",  # chiffres arabo-indiens
        "",
        20261112,
        1700000000,
        None,
        datetime(2026, 11, 12, tzinfo=UTC),  # un datetime : quel fuseau ? on ne devine pas
        datetime(2026, 11, 12),
    ],
)
def test_un_jour_hors_format_ou_avec_heure_est_refuse(valeur: object) -> None:
    with pytest.raises(ValidationError):
        Anniversaire.model_validate({"le": valeur})


def test_un_jour_s_ecrit_aaaa_mm_jj() -> None:
    assert Anniversaire(le=date(2026, 3, 5)).model_dump_json() == '{"le":"2026-03-05"}'
    assert Anniversaire.model_validate_json('{"le":"2026-03-05"}').le == date(2026, 3, 5)


def test_le_schema_d_un_jour_est_une_date() -> None:
    schema = Anniversaire.model_json_schema()["properties"]["le"]
    assert (schema["type"], schema["format"]) == ("string", "date")


# --- Le jour à Paris, autour des changements d'heure -----------------------------------------------


@pytest.mark.parametrize(
    ("instant", "attendu"),
    [
        # Heure d'été : dimanche 29 mars 2026, 01:00 UTC (02:00 -> 03:00 à Paris, 23 h ce jour-là).
        (datetime(2026, 3, 28, 22, 59, 59, tzinfo=UTC), date(2026, 3, 28)),  # 23:59:59 CET
        (datetime(2026, 3, 28, 23, 0, tzinfo=UTC), date(2026, 3, 29)),  # minuit CET
        (datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC), date(2026, 3, 29)),  # 01:59:59 CET
        (datetime(2026, 3, 29, 1, 0, tzinfo=UTC), date(2026, 3, 29)),  # 03:00 CEST
        (datetime(2026, 3, 29, 21, 59, 59, tzinfo=UTC), date(2026, 3, 29)),  # 23:59:59 CEST
        (datetime(2026, 3, 29, 22, 0, tzinfo=UTC), date(2026, 3, 30)),  # minuit CEST
        # Heure d'hiver : dimanche 25 octobre 2026, 01:00 UTC (03:00 -> 02:00, 25 h ce jour-là).
        (datetime(2026, 10, 24, 21, 59, 59, tzinfo=UTC), date(2026, 10, 24)),  # 23:59:59 CEST
        (datetime(2026, 10, 24, 22, 0, tzinfo=UTC), date(2026, 10, 25)),  # minuit CEST
        (datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC), date(2026, 10, 25)),  # 02:59:59 CEST
        (datetime(2026, 10, 25, 1, 0, tzinfo=UTC), date(2026, 10, 25)),  # 02:00 CET
        (datetime(2026, 10, 25, 22, 59, 59, tzinfo=UTC), date(2026, 10, 25)),  # 23:59:59 CET
        (datetime(2026, 10, 25, 23, 0, tzinfo=UTC), date(2026, 10, 26)),  # minuit CET
        # Le même instant, écrit avec un autre décalage, tombe le même jour à Paris.
        (datetime(2026, 11, 12, 23, 30, tzinfo=timezone(timedelta(hours=-8))), date(2026, 11, 13)),
        (datetime(2026, 11, 13, 6, 30, tzinfo=timezone(timedelta(hours=9))), date(2026, 11, 12)),
        # Fin d'année et jour bissextile.
        (datetime(2026, 12, 31, 23, 0, tzinfo=UTC), date(2027, 1, 1)),
        (datetime(2028, 2, 28, 23, 0, tzinfo=UTC), date(2028, 2, 29)),
    ],
)
def test_jour_a_paris_autour_des_changements_d_heure(instant: datetime, attendu: date) -> None:
    assert jour_a_paris(instant) == attendu


def test_jour_a_paris_refuse_un_instant_sans_decalage() -> None:
    with pytest.raises(ValueError, match="sans décalage"):
        jour_a_paris(datetime(2026, 11, 12, 10, 0))


def test_chaque_jour_de_paris_commence_a_minuit_local_sur_cinq_ans() -> None:
    """Invariant : minuit à Paris est le premier instant du jour, la microseconde d'avant est la veille."""
    jour = date(2026, 1, 1)
    while jour < date(2031, 1, 1):
        minuit = datetime(jour.year, jour.month, jour.day, tzinfo=PARIS)
        assert jour_a_paris(minuit) == jour
        assert jour_a_paris(minuit - timedelta(microseconds=1)) == jour - timedelta(days=1)
        jour += timedelta(days=1)


def test_les_journees_de_paris_durent_23_24_ou_25_heures() -> None:
    durees = set()
    jour = date(2026, 1, 1)
    while jour < date(2027, 1, 1):
        debut = datetime(jour.year, jour.month, jour.day, tzinfo=PARIS).astimezone(UTC)
        suivant = jour + timedelta(days=1)
        fin = datetime(suivant.year, suivant.month, suivant.day, tzinfo=PARIS).astimezone(UTC)
        durees.add((fin - debut).total_seconds() / 3600)
        jour = suivant
    assert durees == {23.0, 24.0, 25.0}


def test_jour_a_paris_ne_recule_jamais_quand_l_instant_avance() -> None:
    rng = random.Random(5)
    instants = sorted(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=rng.randrange(366 * 86400)) for _ in range(2000)
    )
    jours = [jour_a_paris(i) for i in instants]
    assert jours == sorted(jours)


@pytest.mark.parametrize(
    ("maintenant", "attendu"),
    [
        (datetime(2026, 11, 12, 22, 59, tzinfo=UTC), date(2026, 11, 12)),
        (datetime(2026, 11, 12, 23, 0, tzinfo=UTC), date(2026, 11, 13)),
        (datetime(2026, 6, 30, 22, 0, tzinfo=UTC), date(2026, 7, 1)),
    ],
)
def test_aujourdhui_a_paris_suit_l_horloge_injectee(maintenant: datetime, attendu: date) -> None:
    assert aujourdhui_a_paris(lambda: maintenant) == attendu


def test_aujourdhui_a_paris_sans_horloge_rend_le_jour_d_un_vrai_instant() -> None:
    avant = jour_a_paris(datetime.now(UTC))
    assert aujourdhui_a_paris() in {avant, avant + timedelta(days=1)}


# --- Montant ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("centimes", [0, 1, 1250, -350, CENTIMES_MAX, -CENTIMES_MAX])
def test_un_montant_en_centimes_entiers_et_en_euros_est_accepte(centimes: int) -> None:
    montant = Montant.model_validate({"amount_cents": centimes, "currency": "EUR"})
    assert montant.amount_cents == centimes
    assert montant.currency == "EUR"
    assert Montant.model_validate_json(montant.model_dump_json()) == montant


def test_un_montant_s_ecrit_en_centimes_et_en_devise() -> None:
    assert (
        Montant(amount_cents=1250, currency="EUR").model_dump_json()
        == '{"amount_cents":1250,"currency":"EUR"}'
    )


@pytest.mark.parametrize(
    "centimes",
    [
        12.5,
        12.0,
        1e2,
        "1250",
        "12.50",
        True,
        False,
        None,
        Decimal(1250),
        [1250],
        CENTIMES_MAX + 1,
        -CENTIMES_MAX - 1,
        2**64,
    ],
)
def test_un_montant_refuse_flottants_textes_et_valeurs_hors_bornes(centimes: object) -> None:
    with pytest.raises(ValidationError) as erreur:
        Montant.model_validate({"amount_cents": centimes, "currency": "EUR"})
    assert erreur.value.errors()[0]["loc"] == ("amount_cents",)


@pytest.mark.parametrize("devise", ["USD", "GBP", "eur", "Eur", "EUR ", "€", "", None, 978, ["EUR"]])
def test_un_montant_refuse_toute_autre_devise(devise: object) -> None:
    with pytest.raises(ValidationError) as erreur:
        Montant.model_validate({"amount_cents": 100, "currency": devise})
    assert erreur.value.errors()[0]["loc"] == ("currency",)


@pytest.mark.parametrize(
    "corps",
    [{"amount_cents": 100}, {"currency": "EUR"}, {}, {"amount_cents": 100, "currency": "EUR", "amount": 1}],
)
def test_un_montant_exige_les_deux_champs_et_refuse_les_champs_inconnus(corps: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Montant.model_validate(corps)


@pytest.mark.parametrize(
    "json_brut",
    [
        '{"amount_cents":12.5,"currency":"EUR"}',
        '{"amount_cents":1e2,"currency":"EUR"}',
        '{"amount_cents":100.0,"currency":"EUR"}',
        '{"amount_cents":"100","currency":"EUR"}',
    ],
)
def test_un_montant_refuse_les_flottants_ecrits_dans_un_json(json_brut: str) -> None:
    with pytest.raises(ValidationError):
        Montant.model_validate_json(json_brut)


def test_un_montant_est_immuable() -> None:
    montant = Montant(amount_cents=100, currency="EUR")
    with pytest.raises(ValidationError):
        montant.amount_cents = 200  # type: ignore[misc]


def test_le_schema_d_un_montant_ferme_la_devise_et_les_champs() -> None:
    schema = Montant.model_json_schema()
    assert schema["properties"]["currency"]["const"] == "EUR"
    assert schema["properties"]["amount_cents"]["type"] == "integer"
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["amount_cents", "currency"]


# --- Dans une route : le 422 parle français et pointe le champ -------------------------------------


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    errors.installe(app)

    @app.post("/depenses")
    async def cree(depense: Depense) -> dict[str, str]:
        return {"quand": depense.quand.isoformat(), "le": depense.le.isoformat()}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def corps_valide(**modifs: object) -> dict[str, object]:
    return {
        "montant": {"amount_cents": 1250, "currency": "EUR"},
        "quand": "2026-11-12T10:00:00+01:00",
        "le": "2026-11-12",
    } | modifs


async def test_une_route_accepte_les_trois_formats_valides(client: httpx.AsyncClient) -> None:
    r = await client.post("/depenses", json=corps_valide())
    assert r.status_code == 200
    assert r.json()["le"] == "2026-11-12"


@pytest.mark.parametrize(
    ("modifs", "pointeur", "message"),
    [
        (
            {"quand": "2026-11-12T10:00:00"},
            "/quand",
            "Un instant s'écrit AAAA-MM-JJThh:mm:ss avec un décalage (`Z` ou `+01:00`).",
        ),
        ({"quand": 1700000000}, "/quand", "Un instant s'écrit en texte RFC 3339, avec son décalage."),
        ({"le": "2026-11-12T00:00:00Z"}, "/le", "Un jour s'écrit AAAA-MM-JJ."),
        ({"le": "2026-02-30"}, "/le", "Ce jour n'existe pas dans le calendrier."),
        (
            {"montant": {"amount_cents": 12.5, "currency": "EUR"}},
            "/montant/amount_cents",
            "Un nombre entier est attendu.",
        ),
        (
            {"montant": {"amount_cents": 100, "currency": "USD"}},
            "/montant/currency",
            "Valeur attendue parmi : 'EUR'.",
        ),
    ],
)
async def test_une_route_rend_422_avec_le_champ_et_un_message_en_francais(
    client: httpx.AsyncClient, modifs: dict[str, object], pointeur: str, message: str
) -> None:
    r = await client.post("/depenses", json=corps_valide(**modifs))
    assert r.status_code == 422
    assert r.json()["errors"] == [{"pointer": pointeur, "message": message}]
