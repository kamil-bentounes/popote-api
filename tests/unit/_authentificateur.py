"""Un authentificateur WebAuthn logiciel, pour tester l'enregistrement et la connexion sans navigateur.

Il lit les options que l'API rend (la forme JSON de WebAuthn niveau 3) et fabrique la réponse que
`PublicKeyCredential.toJSON()` donnerait : un enregistrement (attestation `none`) ou une assertion. Chaque
champ qu'un test voudrait fausser se règle à l'appel : origine, RP ID, défi, indicateurs UP / UV / BE / BS,
compteur, `userHandle`, signature. Il sert à tous les tests des clés d'accès (S8 à S16).

Les clés sont celles des trois algorithmes de la bibliothèque serveur : ES256 (le cas courant), EdDSA et RS256
(Windows Hello). Rien ici ne sert en production : ce fichier ne vit que dans `tests/`.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40
# Ce que le test passe pour dire « le `userHandle` que cette clé a mémorisé à sa création ».
MEMORISE = object()


class Algorithme(Enum):
    ES256 = -7
    EDDSA = -8
    RS256 = -257


@dataclass
class Authentificateur:
    """Une clé d'accès logicielle : une paire de clés, un identifiant, un compteur, des indicateurs."""

    rp_id: str
    origine: str
    algorithme: Algorithme = Algorithme.ES256
    identifiant: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    aaguid: bytes = bytes(range(16))
    compteur: int = 0
    # Les indicateurs d'éligibilité (BE) et d'état (BS) de la sauvegarde ; BS suppose BE.
    peut_etre_sauvegardee: bool = False
    est_sauvegardee: bool = False
    transports: tuple[str, ...] = ("internal",)
    identifiant_utilisateur: bytes | None = None  # mémorisé à l'enregistrement : la clé est découvrable

    def __post_init__(self) -> None:
        self._cle_privee: ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey
        match self.algorithme:
            case Algorithme.ES256:
                self._cle_privee = ec.generate_private_key(ec.SECP256R1())
            case Algorithme.EDDSA:
                self._cle_privee = ed25519.Ed25519PrivateKey.generate()
            case Algorithme.RS256:
                self._cle_privee = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # ---- la clé publique, au format COSE que l'authentificateur écrit dans l'attestation ----

    def cle_publique_cose(self) -> bytes:
        match self._cle_privee:
            case ec.EllipticCurvePrivateKey():
                nombres = self._cle_privee.public_key().public_numbers()
                cle: dict[int, Any] = {
                    1: 2,
                    3: -7,
                    -1: 1,
                    -2: nombres.x.to_bytes(32, "big"),
                    -3: nombres.y.to_bytes(32, "big"),
                }
            case ed25519.Ed25519PrivateKey():
                brute = self._cle_privee.public_key().public_bytes_raw()
                cle = {1: 1, 3: -8, -1: 6, -2: brute}
            case rsa.RSAPrivateKey():
                nombres_rsa = self._cle_privee.public_key().public_numbers()
                cle = {
                    1: 3,
                    3: -257,
                    -1: nombres_rsa.n.to_bytes(256, "big"),
                    -2: nombres_rsa.e.to_bytes(3, "big"),
                }
        return cbor2.dumps(cle)

    def _signe(self, donnees: bytes) -> bytes:
        match self._cle_privee:
            case ec.EllipticCurvePrivateKey():
                return self._cle_privee.sign(donnees, ec.ECDSA(hashes.SHA256()))
            case ed25519.Ed25519PrivateKey():
                return self._cle_privee.sign(donnees)
            case rsa.RSAPrivateKey():
                return self._cle_privee.sign(donnees, padding.PKCS1v15(), hashes.SHA256())

    def _indicateurs(self, *, up: bool, uv: bool, be: bool | None, bs: bool | None, avec_cle: bool) -> int:
        drapeaux = 0
        drapeaux |= UP if up else 0
        drapeaux |= UV if uv else 0
        drapeaux |= BE if (self.peut_etre_sauvegardee if be is None else be) else 0
        drapeaux |= BS if (self.est_sauvegardee if bs is None else bs) else 0
        drapeaux |= AT if avec_cle else 0
        return drapeaux

    # ---- les deux cérémonies ----

    def cree(
        self,
        options: dict[str, Any],
        *,
        origine: str | None = None,
        rp_id: str | None = None,
        defi: bytes | None = None,
        up: bool = True,
        uv: bool = True,
        be: bool | None = None,
        bs: bool | None = None,
        compteur: int | None = None,
        type_de_donnees: str = "webauthn.create",
        cross_origin: Any = False,
        top_origin: str | None = None,
        format_d_attestation: str = "none",
        declaration: Any = None,
        identifiant_brut_different: bool = False,
        identifiant_de_l_attestation: bytes | None = None,
        cle_cose: bytes | None = None,
        attestation_brute: bytes | None = None,
    ) -> dict[str, Any]:
        """La réponse à `navigator.credentials.create()` pour ces options ; tout se règle à l'appel.

        `identifiant_de_l_attestation` et `cle_cose` remplacent ce que l'attestation porte (identifiant,
        clé publique COSE) sans changer `id` ni la vraie clé ; `attestation_brute` remplace tout l'objet.
        """
        rp_id = options["rp"]["id"] if rp_id is None else rp_id
        self.identifiant_utilisateur = base64url_to_bytes(options["user"]["id"])
        if compteur is not None:
            self.compteur = compteur
        ecrit = self.identifiant if identifiant_de_l_attestation is None else identifiant_de_l_attestation
        donnees = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([self._indicateurs(up=up, uv=uv, be=be, bs=bs, avec_cle=True)])
            + self.compteur.to_bytes(4, "big")
            + self.aaguid
            + len(ecrit).to_bytes(2, "big")
            + ecrit
            + (self.cle_publique_cose() if cle_cose is None else cle_cose)
        )
        attestation = attestation_brute or cbor2.dumps(
            {
                "fmt": format_d_attestation,
                "attStmt": {} if declaration is None else declaration,
                "authData": donnees,
            }
        )
        return {
            "id": bytes_to_base64url(self.identifiant),
            "rawId": bytes_to_base64url(
                self.identifiant + b"x" if identifiant_brut_different else self.identifiant
            ),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(
                    self._donnees_du_client(
                        type_de_donnees, options["challenge"], defi, origine, cross_origin, top_origin
                    )
                ),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": list(self.transports),
            },
        }

    def signe(
        self,
        options: dict[str, Any],
        *,
        origine: str | None = None,
        rp_id: str | None = None,
        defi: bytes | None = None,
        up: bool = True,
        uv: bool = True,
        be: bool | None = None,
        bs: bool | None = None,
        compteur: int | None = None,
        identifiant_utilisateur: object = MEMORISE,
        type_de_donnees: str = "webauthn.get",
        cross_origin: Any = False,
        top_origin: str | None = None,
        signature_fausse: bool = False,
        identifiant_brut_different: bool = False,
    ) -> dict[str, Any]:
        """La réponse à `navigator.credentials.get()` : une assertion signée.

        Sans `compteur`, le compteur monte de un (une clé synchronisée qui reste à 0 : `compteur=0`).
        `identifiant_utilisateur=None` : la réponse ne porte aucun `userHandle`.
        """
        rp_id = options["rpId"] if rp_id is None else rp_id
        self.compteur = self.compteur + 1 if compteur is None else compteur
        donnees = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([self._indicateurs(up=up, uv=uv, be=be, bs=bs, avec_cle=False)])
            + self.compteur.to_bytes(4, "big")
        )
        client = self._donnees_du_client(
            type_de_donnees, options["challenge"], defi, origine, cross_origin, top_origin
        )
        signature = self._signe(donnees + hashlib.sha256(client).digest())
        if signature_fausse:
            signature = signature[:-1] + bytes([signature[-1] ^ 0x01])
        poignee = (
            self.identifiant_utilisateur if identifiant_utilisateur is MEMORISE else identifiant_utilisateur
        )
        assert poignee is None or isinstance(poignee, bytes)
        reponse: dict[str, Any] = {
            "clientDataJSON": bytes_to_base64url(client),
            "authenticatorData": bytes_to_base64url(donnees),
            "signature": bytes_to_base64url(signature),
        }
        if poignee is not None:
            reponse["userHandle"] = bytes_to_base64url(poignee)
        return {
            "id": bytes_to_base64url(self.identifiant),
            "rawId": bytes_to_base64url(
                self.identifiant + b"x" if identifiant_brut_different else self.identifiant
            ),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": reponse,
        }

    def _donnees_du_client(
        self,
        type_de_donnees: str,
        defi_des_options: str,
        defi: bytes | None,
        origine: str | None,
        cross_origin: Any,
        top_origin: str | None,
    ) -> bytes:
        contenu: dict[str, Any] = {
            "type": type_de_donnees,
            "challenge": defi_des_options if defi is None else bytes_to_base64url(defi),
            "origin": self.origine if origine is None else origine,
        }
        if cross_origin is not None:
            contenu["crossOrigin"] = cross_origin
        if top_origin is not None:
            contenu["topOrigin"] = top_origin
        return json.dumps(contenu, separators=(",", ":")).encode()
