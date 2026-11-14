"""Les clés d'accès de la personne connectée : demander un défi, enregistrer la clé (S8b), les gérer (S10).

`POST /api/v1/me/passkey-challenges` rend les options de `navigator.credentials.create()`.
`POST /api/v1/me/passkeys` vérifie la réponse du navigateur et écrit la clé. L'une et l'autre exigent une
**preuve de moins de 5 minutes** (la clé ouvre ensuite le compte sans mot de passe) ; la base la relit sous le
verrou de personne avec la session (migration 0153). Contexte « personne » : les fonctions SQL lisent
`auth.uid()`, la route ne passe jamais l'identifiant.

L'ordre de l'enregistrement : preuve, défi consommé (lié à la personne et à la session), vérification de la
réponse en Python (sans réseau, quelques millisecondes), écriture. Un refus lève `Probleme` : la transaction
s'annule, le défi redevient valable jusqu'à son échéance (10 minutes) ; seule une clé écrite le consomme.
Les journaux n'écrivent jamais la réponse, l'identifiant de clé ni le défi : seul le type de la cause
d'un refus.

La gestion (migration 0155) : `GET /me/passkeys` (une carte par clé, dix au plus, jamais la clé publique),
`PATCH /me/passkeys/{id}` (le nom, `application/merge-patch+json`), `DELETE /me/passkeys/{id}` (preuve de
moins de 5 minutes ; ferme les sessions que la clé a ouvertes). Ni `If-Match` ni `ETag` : une personne édite
ses clés, deux onglets qui renomment la même clé se départagent par le dernier écrit, sans perte qui compte.
"""

import logging
from typing import Annotated, Final, assert_never
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response

from popote_api.errors import (
    DEFI_D_AUTHENTIFICATION,
    PAS_DE_SESSION,
    REAUTHENTIFICATION_REQUISE,
    Probleme,
    reponses_erreur,
)
from popote_api.formats import PARIS
from popote_api.infra.webauthn import (
    PartieDeConfiance,
    ReponseDeCleRefusee,
    defi_de_la_reponse,
    verifie_l_enregistrement,
)
from popote_api.pagination import Page
from popote_api.schemas.cles import (
    ChangementDeCle,
    CleDeLaPersonne,
    DefiDeCle,
    EnregistrementDeCle,
    OptionsDeCle,
)
from popote_api.schemas.cles import CleAjoutee as CleAjouteeSortie
from popote_api.security.cles_d_acces import (
    CleAjoutee,
    CleSupprimee,
    Refus,
    consomme_le_defi,
    demande_un_defi_d_enregistrement,
    enregistre_la_cle,
    liste_les_cles,
    renomme_la_cle,
    supprime_la_cle,
)
from popote_api.security.cookie import efface_le_cookie_de_session
from popote_api.security.idempotence import RouteIdempotente
from popote_api.security.reauth import EXIGE_UNE_REAUTHENTIFICATION, exige_reauth
from popote_api.security.session import PersonneDeLaSession

journal = logging.getLogger(__name__)

# Deux routeurs : le défi n'a pas d'`Idempotency-Key` (à usage unique, 10 minutes : rejouer en crée un autre),
# l'enregistrement en a une (effet durable).
routeur_des_defis = APIRouter(prefix="/me/passkey-challenges", tags=["cles"])
routeur_des_cles = APIRouter(prefix="/me/passkeys", tags=["cles"], route_class=RouteIdempotente)
# La lecture et la suppression : naturellement idempotentes, sans `Idempotency-Key` (comme les appareils).
routeur_de_gestion = APIRouter(prefix="/me/passkeys", tags=["cles"])

CLE_INTROUVABLE: Final = "Cette clé n'existe pas."
# Un UUID : autre chose est un `422`, avant tout accès à la base.
IdentifiantDeCle = Annotated[UUID, Path(description="UUID de la clé.")]

ORIGINE_NON_ADMISE: Final = (
    "Les clés d'accès ne sont pas disponibles à cette adresse : utilise le code reçu par mail."
)
TROP_DE_CLES: Final = "Tu as déjà dix clés d'accès : supprime-en une avant d'en ajouter une autre."
CLE_DEJA_ENREGISTREE: Final = "Cette clé est déjà enregistrée."
CLE_REFUSEE: Final = "Cette clé n'a pas pu être enregistrée : recommence depuis le début."


def _session_perimee() -> Probleme:
    return Probleme(
        401, "pas_de_session", PAS_DE_SESSION, headers={"WWW-Authenticate": DEFI_D_AUTHENTIFICATION}
    )


def _probleme_d_un_refus(refus: Refus) -> Probleme:
    match refus:
        case Refus.session_perimee:
            return _session_perimee()
        case Refus.preuve_perimee:
            # Même réponse que la garde de la route : la preuve a vieilli entre la garde et le verrou.
            return Probleme(403, "reauthentification_requise", REAUTHENTIFICATION_REQUISE)
        case Refus.trop_de_cles:
            return Probleme(409, "trop_de_cles", TROP_DE_CLES)
        case Refus.cle_deja_enregistree:
            return Probleme(409, "cle_deja_enregistree", CLE_DEJA_ENREGISTREE)
        case Refus.inconnue:
            return Probleme(404, "cle_introuvable", CLE_INTROUVABLE)


@routeur_des_defis.post(
    "",
    operation_id="create_my_passkey_challenge",
    summary="Demander les options pour créer une clé d'accès",
    description=(
        "Rend les options de `navigator.credentials.create()` : défi de 32 octets valable 10 minutes, "
        "clé découvrable, vérification de l'utilisateur exigée, attestation `none`, clés déjà enregistrées "
        "exclues. Exige une preuve de moins de 5 minutes (`403 reauthentification_requise`) et une page de "
        "Popote dont l'adresse admet les clés d'accès (`403 cle_origine_non_admise` : les aperçus de fusion "
        "n'offrent que le code). Dix clés au plus par personne (`409 trop_de_cles`). Sans "
        "`Idempotency-Key` : le défi est à usage unique, rejouer en crée un autre."
    ),
    response_model=OptionsDeCle,
    responses=reponses_erreur(403, 409, 422),
)
async def demande_un_defi(corps: DefiDeCle, request: Request, personne: PersonneDeLaSession) -> OptionsDeCle:
    reglages = request.app.state.settings
    if request.headers.get("origin") not in reglages.origines_webauthn:
        raise Probleme(403, "cle_origine_non_admise", ORIGINE_NON_ADMISE)
    await exige_reauth(request, personne)
    # L'adresse et le prénom que l'appareil montrera dans sa liste de clés : ceux de la personne.
    await personne.curseur.execute(
        "select public.mon_email() as email, p.display_name"
        " from (select 1) as moi left join public.user_profile p on p.id = auth.uid()"
    )
    ligne = await personne.curseur.fetchone()
    assert ligne is not None  # noqa: S101  # `select … from (select 1)` rend toujours une ligne
    nom_affiche: str = ligne["display_name"] or ligne["email"] or "Popote"
    resultat = await demande_un_defi_d_enregistrement(
        personne.curseur,
        PartieDeConfiance.des_reglages(reglages),
        empreinte_de_session=personne.empreinte_de_session,
        nom_d_utilisateur=ligne["email"] or nom_affiche,
        nom_affiche=nom_affiche,
    )
    if isinstance(resultat, Refus):
        raise _probleme_d_un_refus(resultat)
    return OptionsDeCle(options=resultat.options)


@routeur_des_cles.post(
    "",
    operation_id="register_my_passkey",
    summary="Enregistrer une clé d'accès",
    description=(
        "Vérifie la réponse de `navigator.credentials.create()` contre le défi demandé (à usage unique, lié "
        "à la personne et à la session) et écrit la clé. Preuve de moins de 5 minutes exigée, de nouveau à "
        "l'écriture (`403 reauthentification_requise`). `422 cle_refusee` : réponse fausse, défi inconnu, "
        "échu ou déjà servi. Dix clés au plus (`409 trop_de_cles`) ; un identifiant de clé est unique pour "
        "tout le monde (`409 cle_deja_enregistree`). Sans nom : « Clé du JJ/MM/AAAA »."
    ),
    status_code=201,
    response_model=CleAjouteeSortie,
    responses={201: {"description": "La clé est enregistrée."}, **reponses_erreur(403, 409)},
    dependencies=[EXIGE_UNE_REAUTHENTIFICATION],
)
async def enregistre_une_cle(
    corps: EnregistrementDeCle, request: Request, personne: PersonneDeLaSession
) -> CleAjouteeSortie:
    app = request.app
    try:
        annonce = defi_de_la_reponse(corps.credential)
    except ReponseDeCleRefusee as erreur:
        raise _cle_refusee(erreur) from erreur
    defi = await consomme_le_defi(
        personne.curseur, empreinte_de_session=personne.empreinte_de_session, defi=annonce
    )
    if defi is None:
        raise Probleme(422, "cle_refusee", CLE_REFUSEE)
    try:
        cle = verifie_l_enregistrement(
            PartieDeConfiance.des_reglages(app.state.settings), reponse=corps.credential, defi=defi
        )
    except ReponseDeCleRefusee as erreur:
        raise _cle_refusee(erreur) from erreur
    nom = corps.name or f"Clé du {app.state.horloge().astimezone(PARIS):%d/%m/%Y}"
    resultat = await enregistre_la_cle(
        personne.curseur,
        empreinte_de_session=personne.empreinte_de_session,
        cle=cle,
        nom=nom,
        request_id=getattr(request.state, "request_id", None),
    )
    match resultat:
        case Refus():
            raise _probleme_d_un_refus(resultat)
        case CleAjoutee():
            return CleAjouteeSortie(id=resultat.id, name=nom, created_at=resultat.created_at)
        case _:
            assert_never(resultat)


def _cle_refusee(erreur: ReponseDeCleRefusee) -> Probleme:
    # Le message d'un refus est fixe ; le type de sa cause seul, jamais le texte de la cause : il recopie la
    # réponse du navigateur (origine, identifiants).
    journal.info("Clé refusée : %s (%s)", erreur, erreur.type_de_la_cause)
    return Probleme(422, "cle_refusee", CLE_REFUSEE)


@routeur_de_gestion.get(
    "",
    operation_id="list_my_passkeys",
    summary="Mes clés d'accès",
    description=(
        "Les clés de la personne, de la plus ancienne à la plus récente (dix au plus : `next_cursor` est "
        "toujours vide). Chaque clé montre son nom, sa création, sa dernière utilisation et si elle se "
        "synchronise ; jamais la clé publique, l'identifiant de clé ni l'AAGUID. Fermer toutes les sessions "
        "ne retire pas les clés : `last_used_at` dit lesquelles servent encore."
    ),
    response_model=Page[CleDeLaPersonne],
)
async def liste_mes_cles(personne: PersonneDeLaSession) -> Page[CleDeLaPersonne]:
    cles = [CleDeLaPersonne.model_validate(ligne) for ligne in await liste_les_cles(personne.curseur)]
    return Page(items=cles, next_cursor=None)


@routeur_des_cles.patch(
    "/{id}",
    operation_id="rename_my_passkey",
    summary="Renommer une clé d'accès",
    description=(
        "`application/merge-patch+json` : seul `name` (1 à 40 caractères visibles) se change ; un corps vide "
        "ne change rien ; `name: null` est un `422` (le nom ne se retire pas). Une clé d'une autre personne "
        "ou inconnue est un `404`. Pas d'`If-Match` : une personne édite ses clés."
    ),
    response_model=CleDeLaPersonne,
    responses=reponses_erreur(404, 422),
)
async def renomme_une_cle(
    id: IdentifiantDeCle, corps: ChangementDeCle, personne: PersonneDeLaSession
) -> CleDeLaPersonne:
    if corps.name is not None and not await renomme_la_cle(personne.curseur, identifiant=id, nom=corps.name):
        raise Probleme(404, "cle_introuvable", CLE_INTROUVABLE)
    cles = {cle["id"]: cle for cle in await liste_les_cles(personne.curseur)}
    if id not in cles:
        raise Probleme(404, "cle_introuvable", CLE_INTROUVABLE)
    return CleDeLaPersonne.model_validate(cles[id])


@routeur_de_gestion.delete(
    "/{id}",
    operation_id="delete_my_passkey",
    summary="Supprimer une clé d'accès",
    description=(
        "Supprime la clé et ferme les sessions qu'elle a ouvertes (les autres restent) : une clé compromise "
        "s'invalide aussitôt. Preuve de moins de 5 minutes exigée, de nouveau sous le verrou "
        "(`403 reauthentification_requise`). Supprimer la dernière clé est permis : le code reçu par mail "
        "reste. Une clé d'une autre personne ou inconnue est un `404` (la supprimer deux fois aussi). Si la "
        "session qui fait la requête avait été ouverte par cette clé, elle est fermée et le cookie est vidé. "
        "Pas d'`Idempotency-Key` : la suppression est naturellement idempotente."
    ),
    status_code=204,
    response_class=Response,
    responses={
        204: {
            "description": "La clé est supprimée.",
            "headers": {
                "Set-Cookie": {
                    "description": "Si la session courante avait été ouverte par cette clé : le cookie vidé.",
                    "schema": {"type": "string"},
                }
            },
        },
        **reponses_erreur(403, 404, 422),
    },
    dependencies=[EXIGE_UNE_REAUTHENTIFICATION],
)
async def supprime_une_cle(id: IdentifiantDeCle, request: Request, personne: PersonneDeLaSession) -> Response:
    resultat = await supprime_la_cle(
        personne.curseur,
        empreinte_de_session=personne.empreinte_de_session,
        identifiant=id,
        request_id=getattr(request.state, "request_id", None),
    )
    match resultat:
        case Refus():
            raise _probleme_d_un_refus(resultat)
        case CleSupprimee():
            reponse = Response(status_code=204)
            if resultat.session_courante_fermee:
                efface_le_cookie_de_session(reponse, request.app.state.settings)
            return reponse
        case _:
            assert_never(resultat)
