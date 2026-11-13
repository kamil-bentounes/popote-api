"""Les clés d'accès (WebAuthn) : les options à donner au navigateur et la vérification de ses réponses.

Ce module est sans base et sans réseau : il bâtit des options, vérifie une réponse, et rend ce qu'il faut
écrire. Garder le défi à usage unique, lire et écrire la clé, ouvrir la session sous le verrou de personne :
c'est le travail des tâches suivantes (S8b, S9).

La bibliothèque `webauthn` (py_webauthn 3.0.1) fait la cryptographie ; ce module lui impose ce que Popote
exige et ajoute ce qu'elle ne fait pas. Sources : W3C Web Authentication niveau 3 (Recommandation du
25/08/2026), § 7.1 (enregistrement), § 7.2 (assertion), § 13.4.3 (défi), § 13.4.9 (origine), § 14.6.1
(identifiant d'utilisateur).

Ce que la bibliothèque fait : défi, type, origine (liste exacte), hachage du RP ID, UP, UV si demandée,
signature, BS sans BE refusé, attestation « none » sans contenu. Ce que ce module ajoute :
- l'attestation doit être `none` : Popote ne filtre pas les modèles d'authentificateur (aucune racine de
  confiance), donc ne lit pas les autres formats ;
- `crossOrigin` et `topOrigin` sont refusés : la clé ne sert pas dans un cadre d'une autre origine ;
- la clé de la réponse est celle qu'on a lue en base, et le `userHandle` est celui de la personne (§ 7.2) ;
- l'éligibilité à la sauvegarde (BE) d'une clé ne change jamais (§ 7.2) ;
- le compteur de signature qui ne croît pas est refusé APRÈS la vérification de la signature, avec sa propre
  erreur : sans signature valide, ce n'est que du bruit, pas un signal de clonage (§ 6.1.1, § 7.2).

Une réponse refusée lève `ReponseDeCleRefusee`, au message fixe : rien de la réponse n'y entre, ni clé, ni
identifiant, ni défi. La cause (l'erreur de la bibliothèque) reste chaînée pour le journal du serveur.
"""

import hmac
import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    options_to_json_dict,
    parse_attestation_object,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AttestationFormat,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    CredentialDeviceType,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from popote_api.config import Settings

# W3C § 13.4.3 : au moins 16 octets ; 32 est la valeur du plan (0.4bis S8).
TAILLE_DU_DEFI = 32
# Valable aussi longtemps que la cérémonie (W3C § 15.1 : de 5 à 10 minutes) ; la base le fait respecter (S8b).
DELAI_DE_LA_CEREMONIE_MS = 300_000
VALIDITE_DU_DEFI_S = 600
# W3C § 4 « Credential ID » : 16 octets au moins pour être inattendu, 1023 au plus.
TAILLE_MINIMALE_D_UN_IDENTIFIANT = 16
TAILLE_MAXIMALE_D_UN_IDENTIFIANT = 1023
# W3C § 5.4.3 : l'identifiant d'utilisateur fait de 1 à 64 octets.
TAILLE_MAXIMALE_D_UN_IDENTIFIANT_D_UTILISATEUR = 64


# Ce que la bibliothèque lève sur des octets qu'elle ne sait pas lire : ses propres erreurs, mais aussi
# `KeyError` et `IndexError` d'une clé COSE incomplète (`decode_credential_public_key`). Toutes veulent dire
# « cette entrée ne se vérifie pas » ; toute autre exception est un bogue et doit remonter.
ERREURS_DE_LA_BIBLIOTHEQUE = (WebAuthnException, ValueError, TypeError, KeyError, IndexError)


class ErreurDeCle(Exception):
    """Racine des erreurs de ce module."""


class ReponseDeCleRefusee(ErreurDeCle):
    """La réponse du navigateur ne passe pas : mal formée, fausse, d'ailleurs ou trop faible.

    Le message est fixe : la réponse porte des identifiants de clé et des signatures, qui n'ont rien à faire
    dans un journal. La cause reste dans `__cause__`.
    """


class CompteurDeCleRegresse(ReponseDeCleRefusee):
    """Signature valide, mais le compteur n'a pas crû : « a signal, but not proof » de clonage (W3C § 7.2).

    Seul un refus qui porte une signature VALIDE peut l'être : une réponse fausse ne dit rien de la clé.
    """


@dataclass(frozen=True, slots=True)
class PartieDeConfiance:
    """Qui nous sommes pour le navigateur : le RP ID, un nom lisible, les origines exactes admises."""

    identifiant: str
    nom: str
    origines: frozenset[str]

    @classmethod
    def des_reglages(cls, reglages: Settings) -> "PartieDeConfiance":
        return cls(reglages.rp_id_webauthn, reglages.webauthn_rp_name, reglages.origines_webauthn)


@dataclass(frozen=True, slots=True)
class CleExistante:
    """Une clé déjà enregistrée, pour que le navigateur n'en crée pas une seconde sur le même appareil."""

    identifiant: bytes
    transports: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OptionsDeCeremonie:
    """`options` : la forme JSON que le navigateur lit (`parse…OptionsFromJSON`) ; `defi` : à garder."""

    options: dict[str, Any]
    defi: bytes


@dataclass(frozen=True, slots=True)
class CleEnregistree:
    """Ce qu'une réponse d'enregistrement valide donne à écrire en base."""

    identifiant: bytes
    cle_publique: bytes
    compteur: int
    peut_etre_sauvegardee: bool
    est_sauvegardee: bool
    verification_initialisee: bool
    aaguid: str
    transports: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleDeConnexion:
    """La clé telle que la base la tient, pour vérifier une assertion."""

    identifiant: bytes
    cle_publique: bytes
    compteur: int
    peut_etre_sauvegardee: bool
    identifiant_utilisateur: bytes


@dataclass(frozen=True, slots=True)
class ConnexionVerifiee:
    """Ce qu'une assertion valide donne à écrire : le nouveau compteur et l'état de sauvegarde."""

    compteur: int
    est_sauvegardee: bool
    verification_utilisateur: bool


def _defi() -> bytes:
    # `generate_challenge` de la bibliothèque tire 64 octets ; le plan en veut 32.
    return secrets.token_bytes(TAILLE_DU_DEFI)


def _descripteurs(cles: Sequence[CleExistante]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(
            id=cle.identifiant,
            transports=[
                AuthenticatorTransport(transport)
                for transport in cle.transports
                if transport in AuthenticatorTransport
            ]
            or None,
        )
        for cle in cles
    ]


def options_d_enregistrement(
    partie: PartieDeConfiance,
    *,
    identifiant_utilisateur: bytes,
    nom_d_utilisateur: str,
    nom_affiche: str,
    cles_existantes: Sequence[CleExistante] = (),
) -> OptionsDeCeremonie:
    """Les options de `navigator.credentials.create()` : clé découvrable, vérification exigée.

    `identifiant_utilisateur` : l'identifiant opaque de la personne (64 octets aléatoires, jamais un e-mail
    ni un identifiant de compte : W3C § 14.6.1). `nom_d_utilisateur` et `nom_affiche` sont ce que l'appareil
    montre dans sa liste de clés.
    """
    # La bibliothèque remplace un identifiant vide par un tirage au hasard : une personne sans identifiant
    # stable se retrouverait avec un `userHandle` que la base ne connaît pas.
    if not 1 <= len(identifiant_utilisateur) <= TAILLE_MAXIMALE_D_UN_IDENTIFIANT_D_UTILISATEUR:
        raise ValueError("identifiant d'utilisateur : de 1 à 64 octets")
    defi = _defi()
    options = generate_registration_options(
        rp_id=partie.identifiant,
        rp_name=partie.nom,
        user_id=identifiant_utilisateur,
        user_name=nom_d_utilisateur,
        user_display_name=nom_affiche,
        challenge=defi,
        timeout=DELAI_DE_LA_CEREMONIE_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descripteurs(cles_existantes),
    )
    return OptionsDeCeremonie(options_to_json_dict(options), defi)


def options_de_connexion(partie: PartieDeConfiance) -> OptionsDeCeremonie:
    """Les options de `navigator.credentials.get()` : aucune clé nommée (le navigateur propose les siennes).

    Sans nom d'utilisateur au départ, la cérémonie ne dit pas si un compte existe (W3C § 14.6.2).
    """
    defi = _defi()
    options = generate_authentication_options(
        rp_id=partie.identifiant,
        challenge=defi,
        timeout=DELAI_DE_LA_CEREMONIE_MS,
        allow_credentials=[],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return OptionsDeCeremonie(options_to_json_dict(options), defi)


def _verifie_le_defi(defi: bytes) -> None:
    # Une erreur du code appelant, pas un refus : un défi vide ou court validerait presque n'importe quoi.
    if len(defi) < TAILLE_DU_DEFI:
        raise ValueError("défi trop court : celui que `options_*` a rendu, en entier")


def _refuse_un_cadre_etranger(donnees_du_client: bytes) -> None:
    """`crossOrigin` vrai ou `topOrigin` présent : la clé servirait dans un cadre d'une autre origine."""
    try:
        contenu = json.loads(donnees_du_client)
    except ValueError as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : données du client illisibles") from erreur
    if (
        not isinstance(contenu, dict)
        or contenu.get("crossOrigin", False) is not False
        or "topOrigin" in contenu
    ):
        raise ReponseDeCleRefusee("réponse de clé refusée : cadre d'une autre origine")


def identifiant_de_la_cle(reponse: dict[str, Any]) -> bytes:
    """L'identifiant de la clé que la réponse prétend utiliser : de quoi la lire en base avant de vérifier."""
    try:
        return parse_authentication_credential_json(reponse).raw_id
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : mal formée") from erreur


def verifie_l_enregistrement(
    partie: PartieDeConfiance, *, reponse: dict[str, Any], defi: bytes
) -> CleEnregistree:
    """Vérifie la réponse à `create()` (W3C § 7.1) et rend la clé à écrire.

    Exige : le défi donné, l'origine exacte et le RP ID de la partie de confiance, UP, UV (la clé ne sert
    sans mot de passe que si l'appareil a vérifié la personne), une attestation `none`, un algorithme que la
    bibliothèque accepte (EdDSA, ES256, RS256).
    """
    _verifie_le_defi(defi)
    try:
        credential = parse_registration_credential_json(reponse)
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : mal formée") from erreur
    if not TAILLE_MINIMALE_D_UN_IDENTIFIANT <= len(credential.raw_id) <= TAILLE_MAXIMALE_D_UN_IDENTIFIANT:
        raise ReponseDeCleRefusee("réponse de clé refusée : identifiant de clé de taille inadmise")
    _refuse_un_cadre_etranger(credential.response.client_data_json)
    try:
        format_d_attestation = parse_attestation_object(credential.response.attestation_object).fmt
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : attestation illisible") from erreur
    if format_d_attestation != AttestationFormat.NONE:
        raise ReponseDeCleRefusee("réponse de clé refusée : attestation autre que none")
    try:
        verifiee = verify_registration_response(
            credential=credential,
            expected_challenge=defi,
            expected_rp_id=partie.identifiant,
            expected_origin=sorted(partie.origines),
            require_user_presence=True,
            require_user_verification=True,
        )
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : enregistrement non vérifié") from erreur
    # L'identifiant écrit dans l'attestation est celui que le navigateur annoncera ensuite (`rawId`) : s'ils
    # diffèrent, la clé enregistrée ne se retrouverait jamais à la connexion.
    if not hmac.compare_digest(verifiee.credential_id, credential.raw_id):
        raise ReponseDeCleRefusee("réponse de clé refusée : identifiant de clé incohérent")
    return CleEnregistree(
        identifiant=verifiee.credential_id,
        cle_publique=verifiee.credential_public_key,
        compteur=verifiee.sign_count,
        peut_etre_sauvegardee=verifiee.credential_device_type is CredentialDeviceType.MULTI_DEVICE,
        est_sauvegardee=verifiee.credential_backed_up,
        verification_initialisee=verifiee.user_verified,
        aaguid=verifiee.aaguid,
        transports=tuple(sorted({transport.value for transport in credential.response.transports or ()})),
    )


def verifie_la_connexion(
    partie: PartieDeConfiance, *, reponse: dict[str, Any], defi: bytes, cle: CleDeConnexion
) -> ConnexionVerifiee:
    """Vérifie une assertion (W3C § 7.2) contre la clé lue en base et rend ce qu'il faut écrire.

    Exige, en plus de ce que fait `verifie_l_enregistrement` : que la réponse porte l'identifiant de CETTE
    clé, un `userHandle` égal à celui de la personne (la cérémonie part sans nom d'utilisateur : c'est lui
    qui lie la clé à la personne), la même éligibilité à la sauvegarde qu'à l'enregistrement, et un compteur
    qui croît (sauf une clé qui reste à 0).
    """
    _verifie_le_defi(defi)
    try:
        credential = parse_authentication_credential_json(reponse)
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : mal formée") from erreur
    if not hmac.compare_digest(credential.raw_id, cle.identifiant):
        raise ReponseDeCleRefusee("réponse de clé refusée : ce n'est pas la clé attendue")
    poignee = credential.response.user_handle
    if poignee is None or not hmac.compare_digest(poignee, cle.identifiant_utilisateur):
        raise ReponseDeCleRefusee("réponse de clé refusée : userHandle absent ou d'une autre personne")
    _refuse_un_cadre_etranger(credential.response.client_data_json)
    try:
        # `credential_current_sign_count=0` : la bibliothèque refuserait un compteur en recul AVANT de
        # vérifier la signature ; on le contrôle nous-mêmes plus bas, une fois la signature prouvée.
        verifiee = verify_authentication_response(
            credential=credential,
            expected_challenge=defi,
            expected_rp_id=partie.identifiant,
            expected_origin=sorted(partie.origines),
            credential_public_key=cle.cle_publique,
            credential_current_sign_count=0,
            require_user_verification=True,
        )
    except ERREURS_DE_LA_BIBLIOTHEQUE as erreur:
        raise ReponseDeCleRefusee("réponse de clé refusée : assertion non vérifiée") from erreur
    if (verifiee.credential_device_type is CredentialDeviceType.MULTI_DEVICE) != cle.peut_etre_sauvegardee:
        raise ReponseDeCleRefusee("réponse de clé refusée : l'éligibilité à la sauvegarde a changé")
    nouveau = verifiee.new_sign_count
    if (nouveau > 0 or cle.compteur > 0) and nouveau <= cle.compteur:
        raise CompteurDeCleRegresse("réponse de clé refusée : le compteur n'a pas crû")
    return ConnexionVerifiee(
        compteur=nouveau,
        est_sauvegardee=verifiee.credential_backed_up,
        verification_utilisateur=verifiee.user_verified,
    )
