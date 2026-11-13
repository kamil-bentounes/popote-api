#!/usr/bin/env python3
"""Prouve, sur l'essai seulement, qu'Auth hébergé écrit un compte sans mot de passe (plan 0.4bis, S1).

Ce que le script établit, l'un après l'autre, et vérifie lui-même (sortie non nulle au premier écart) :
1. `createUser` sans `password` réussit : un hachage est écrit en base, l'e-mail est confirmé, aucun mail
   n'est parti (`confirmation_sent_at` vide) ;
2. la connexion publique de GoTrue (`/auth/v1/token`, mot de passe vide ou deviné) est refusée pour lui ;
3. `updateUserById` pose un mot de passe aléatoire de 64 caractères (minuscules, majuscules, chiffres,
   symboles) : le hachage change ;
4. une deuxième création de la même adresse, puis de sa variante en majuscules, rend `email_exists` ;
5. à la fin, aucun compte de test ne reste, même si une étape a échoué.

Usage :
    set -a; . ~/.config/popote/secrets.env; set +a     # lu sans rien afficher
    uv run python ops/preuve_auth_sans_mot_de_passe.py --a-blanc   # lectures seules, rien n'est écrit
    uv run python ops/preuve_auth_sans_mot_de_passe.py             # la preuve, avec écritures sur l'essai

Environnement : `ESSAI_REF` et `SUPABASE_ESSAI_TOKEN` (jeton de l'API de gestion). Les clés d'API de l'essai
se lisent par l'API de gestion ; `ESSAI_SUPABASE_SECRET_KEY` et `ESSAI_SUPABASE_PUBLISHABLE_KEY`, si elles
sont posées, les remplacent. Le script ne lit aucune autre variable.
Réseau qui inspecte le TLS (WSL d'entreprise) : `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`, sinon la
vérification du certificat de `<réf>.supabase.co` échoue (`ConnectError`, sortie 2). Rien n'est désactivé.
Garde-fous : refuse la prod (référence écrite en dur) et tout projet qui ne s'appelle pas `popote-essai`.
Il n'affiche aucune clé, adresse, identifiant, mot de passe ni hachage : seulement le préfixe et le coût du
hachage, des statuts HTTP et des codes d'erreur d'Auth. Un compte de test porte une adresse
`preuve-auth-<hex>@example.com` et la marque `app_metadata.cree_par = preuve-auth-s1` : le nettoyage ne
touche que les comptes qui ont les deux.
Codes de sortie : 0 preuve complète (ou à blanc réussi), 1 écart constaté ou compte de test restant,
2 accès impossible ou refus d'un garde-fou.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import string
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from aligne_droits import FORBIDDEN_PROJECT_REF, PROJECT_REF_PATTERN

API_DE_GESTION = "https://api.supabase.com"
NOM_DU_PROJET_D_ESSAI = "popote-essai"
MARQUE = "preuve-auth-s1"
PREFIXE_D_ADRESSE = "preuve-auth-"
ADRESSE_DE_TEST = re.compile(r"preuve-auth-[0-9a-f]{12}@example\.com", re.IGNORECASE)
MOTIF_D_ADRESSE_EN_SQL = "preuve-auth-%@example.com"
LONGUEUR_DU_MOT_DE_PASSE = 64
SYMBOLES = "!#$%&*+-=?@^_"
# Un refus de connexion est un 400 (identifiants invalides), un 401 ou un 422 ; un 429 ne prouve rien.
STATUTS_DE_REFUS = frozenset({400, 401, 422})
CODES_COMPTE_EXISTANT = frozenset({"email_exists", "user_already_exists"})
MOTS_DE_PASSE_DEVINES = ("", "motdepasse")
FORME_D_UN_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
FORME_D_UN_HACHAGE = re.compile(r"\$(2[abxy])\$(\d{2})\$.+")
DELAI_CONNEXION_S = 3.0
DELAI_LECTURE_S = 20.0
OCTETS_MAX_REPONSE = 256 * 1024

Sortie = Callable[[str], None]


class PreuveError(Exception):
    """Base des erreurs du script. Le texte n'en contient ni clé, ni adresse, ni mot de passe."""


class AccesError(PreuveError):
    """Un accès est impossible ou un garde-fou refuse de continuer : sortie 2."""


class EcartError(PreuveError):
    """Une vérification de la preuve échoue : sortie 1."""


@dataclass(frozen=True)
class Acces:
    """Où et avec quoi agir sur l'essai. Le jeton n'entre ni dans `repr` ni dans un message."""

    ref: str
    jeton: str = field(repr=False)


@dataclass(frozen=True)
class Reponse:
    """Ce qu'un appel a rendu : le statut et le corps lu, déjà borné."""

    status: int
    corps: bytes

    def objet(self) -> dict[str, Any]:
        """Le corps s'il est un objet JSON, sinon un objet vide."""
        try:
            contenu: Any = json.loads(self.corps)
        except (ValueError, RecursionError):
            return {}
        return contenu if isinstance(contenu, dict) else {}

    def contenu(self) -> Any:
        """Le corps décodé, ou `None` s'il n'est pas du JSON."""
        try:
            return json.loads(self.corps)
        except (ValueError, RecursionError):
            return None

    def code(self) -> str | None:
        """Le `error_code` d'Auth, s'il a la forme d'un code (jamais un message : il cite l'adresse)."""
        code = self.objet().get("error_code")
        return code if isinstance(code, str) and FORME_D_UN_CODE.fullmatch(code) else None

    def decrit(self) -> str:
        return f"HTTP {self.status}, code={self.code()}"


@dataclass(frozen=True)
class EtatDuCompte:
    """Ce que la base de l'essai dit d'un compte. Le hachage n'est gardé que sous forme d'empreinte."""

    empreinte: str
    schema: str
    cout: int | None
    confirme: bool
    mail_parti: bool

    def decrit_le_hachage(self) -> str:
        return f"{self.schema}, coût {self.cout}" if self.cout is not None else self.schema


def acces_depuis(environnement: Mapping[str, str]) -> Acces:
    """Lit l'essai dans l'environnement et refuse la prod. Ne lit aucune autre variable."""
    ref = environnement.get("ESSAI_REF", "")
    jeton = environnement.get("SUPABASE_ESSAI_TOKEN", "")
    for nom, valeur in (("ESSAI_REF", ref), ("SUPABASE_ESSAI_TOKEN", jeton)):
        if not valeur:
            raise AccesError(f"Variable d'environnement absente : {nom}.")
    if ref == FORBIDDEN_PROJECT_REF:
        raise AccesError("La prod n'est jamais une cible.")
    if not PROJECT_REF_PATTERN.fullmatch(ref):
        raise AccesError("ESSAI_REF n'a pas la forme d'une référence de projet.")
    return Acces(ref, jeton)


def mot_de_passe_aleatoire() -> str:
    """64 caractères tirés par `secrets`, dont une minuscule, une majuscule, un chiffre et un symbole."""
    classes = (string.ascii_lowercase, string.ascii_uppercase, string.digits, SYMBOLES)
    tous = "".join(classes)
    caracteres = [secrets.choice(classe) for classe in classes]
    caracteres += [secrets.choice(tous) for _ in range(LONGUEUR_DU_MOT_DE_PASSE - len(caracteres))]
    secrets.SystemRandom().shuffle(caracteres)
    return "".join(caracteres)


def adresse_de_test() -> str:
    return f"{PREFIXE_D_ADRESSE}{secrets.token_hex(6)}@example.com"


class Essai:
    """Les appels à l'essai : API de gestion (clés, base) et Auth (administration, connexion publique).

    Chaque réponse est rendue telle quelle ; aucun message d'erreur ne reprend un corps de réponse.
    """

    def __init__(self, acces: Acces, http: httpx.Client, environnement: Mapping[str, str]) -> None:
        self._acces = acces
        self._http = http
        self._url_d_auth = f"https://{acces.ref}.supabase.co"
        self._cle_secrete = environnement.get("ESSAI_SUPABASE_SECRET_KEY", "")
        self._cle_publiable = environnement.get("ESSAI_SUPABASE_PUBLISHABLE_KEY", "")

    def __repr__(self) -> str:
        return "Essai(<projet d'essai>)"

    def _envoie(
        self,
        methode: str,
        url: str,
        en_tetes: dict[str, str],
        corps: dict[str, Any] | None = None,
        parametres: dict[str, str] | None = None,
    ) -> Reponse:
        try:
            reponse = self._http.request(methode, url, headers=en_tetes, json=corps, params=parametres)
        except httpx.HTTPError as erreur:
            raise AccesError(f"Appel impossible ({type(erreur).__name__}).") from erreur
        if len(reponse.content) > OCTETS_MAX_REPONSE:
            raise AccesError("Réponse trop grosse : ce n'est pas le service attendu.")
        return Reponse(reponse.status_code, reponse.content)

    def _gestion(
        self, methode: str, chemin: str, corps: dict[str, Any] | None = None, **parametres: str
    ) -> Reponse:
        en_tetes = {"Authorization": f"Bearer {self._acces.jeton}", "User-Agent": "popote-preuve-auth/1.0"}
        return self._envoie(methode, API_DE_GESTION + chemin, en_tetes, corps, parametres or None)

    def _administration(self, methode: str, chemin: str, corps: dict[str, Any] | None = None) -> Reponse:
        en_tetes = {"apikey": self._cle_secrete, "Accept": "application/json"}
        return self._envoie(methode, self._url_d_auth + chemin, en_tetes, corps)

    # --- garde-fous et clés -------------------------------------------------------------------------

    def exige_le_projet_d_essai(self) -> None:
        reponse = self._gestion("GET", f"/v1/projects/{self._acces.ref}")
        if reponse.status != 200:
            raise AccesError(f"Le projet n'est pas lisible par l'API de gestion ({reponse.decrit()}).")
        if reponse.objet().get("name") != NOM_DU_PROJET_D_ESSAI:
            raise AccesError(f"Le projet ne s'appelle pas {NOM_DU_PROJET_D_ESSAI} : refus.")

    def charge_les_cles(self) -> None:
        if self._cle_secrete and self._cle_publiable:
            return
        reponse = self._gestion("GET", f"/v1/projects/{self._acces.ref}/api-keys", reveal="true")
        liste = reponse.contenu()
        if reponse.status != 200 or not isinstance(liste, list):
            raise AccesError(
                f"Les clés de l'essai ne sont pas lisibles ({reponse.decrit()}) : poser "
                "ESSAI_SUPABASE_SECRET_KEY et ESSAI_SUPABASE_PUBLISHABLE_KEY, ou donner au jeton le droit de "
                "les lire."
            )
        cles = [entree for entree in liste if isinstance(entree, dict)]
        self._cle_secrete = self._cle_secrete or _cle_de_type(cles, "secret")
        self._cle_publiable = self._cle_publiable or _cle_de_type(cles, "publishable")
        for nom, valeur in (("secrète", self._cle_secrete), ("publiable", self._cle_publiable)):
            if not valeur:
                raise AccesError(f"Aucune clé {nom} lisible pour l'essai.")

    # --- la base de l'essai -------------------------------------------------------------------------

    def _sql(self, requete: str) -> list[dict[str, Any]]:
        reponse = self._gestion("POST", f"/v1/projects/{self._acces.ref}/database/query", {"query": requete})
        lignes = reponse.contenu()
        if reponse.status not in (200, 201) or not isinstance(lignes, list):
            raise AccesError(f"Lecture de la base de l'essai impossible ({reponse.decrit()}).")
        return [ligne for ligne in lignes if isinstance(ligne, dict)]

    def comptes_de_test(self) -> list[UUID]:
        """Les comptes qui portent à la fois l'adresse et la marque d'un compte de test."""
        lignes = self._sql(
            "select id from auth.users "  # noqa: S608 - constantes du module, aucune entrée
            f"where lower(email) like '{MOTIF_D_ADRESSE_EN_SQL}' "
            f"and raw_app_meta_data->>'cree_par' = '{MARQUE}'"
        )
        try:
            return [UUID(str(ligne["id"])) for ligne in lignes]
        except (KeyError, ValueError) as erreur:
            raise AccesError("Réponse inattendue à la liste des comptes de test.") from erreur

    def nombre_de_comptes_a_l_adresse(self, adresse: str) -> int:
        _exige_une_adresse_de_test(adresse)
        lignes = self._sql(
            f"select count(*)::int as n from auth.users where lower(email) = lower('{adresse}')"  # noqa: S608 - adresse validée
        )
        if len(lignes) != 1 or not isinstance(lignes[0].get("n"), int):
            raise AccesError("Réponse inattendue au comptage des comptes.")
        return int(lignes[0]["n"])

    def etat_du_compte(self, identifiant: UUID) -> EtatDuCompte:
        if not isinstance(identifiant, UUID):
            raise TypeError("L'identifiant d'un compte est un UUID.")
        lignes = self._sql(
            "select encrypted_password, email_confirmed_at is not null as confirme, "  # noqa: S608 - UUID typé
            "confirmation_sent_at is not null as mail_parti "
            f"from auth.users where id = '{identifiant}'"
        )
        if len(lignes) != 1:
            raise EcartError("Le compte créé n'est pas dans la base de l'essai.")
        hachage = lignes[0].get("encrypted_password") or ""
        if not isinstance(hachage, str):
            raise AccesError("Réponse inattendue à la lecture du compte.")
        forme = FORME_D_UN_HACHAGE.fullmatch(hachage)
        if hachage == "":
            schema, cout = "vide", None
        elif forme is None:
            schema, cout = "inconnu", None
        else:
            schema, cout = forme.group(1), int(forme.group(2))
        return EtatDuCompte(
            empreinte=hashlib.sha256(hachage.encode()).hexdigest(),
            schema=schema,
            cout=cout,
            confirme=lignes[0].get("confirme") is True,
            mail_parti=lignes[0].get("mail_parti") is True,
        )

    # --- Auth ---------------------------------------------------------------------------------------

    def cree(self, adresse: str, mot_de_passe: str | None = None) -> Reponse:
        _exige_une_adresse_de_test(adresse)
        corps: dict[str, Any] = {
            "email": adresse,
            "email_confirm": True,
            "app_metadata": {"cree_par": MARQUE},
        }
        if mot_de_passe is not None:
            corps["password"] = mot_de_passe
        return self._administration("POST", "/auth/v1/admin/users", corps)

    def remplace_le_mot_de_passe(self, identifiant: UUID, mot_de_passe: str) -> Reponse:
        return self._administration("PUT", f"/auth/v1/admin/users/{identifiant}", {"password": mot_de_passe})

    def supprime(self, identifiant: UUID) -> Reponse:
        return self._administration("DELETE", f"/auth/v1/admin/users/{identifiant}")

    def lit_un_compte_au_hasard(self) -> Reponse:
        """Une lecture d'administration (à blanc) : prouve que la clé secrète passe, sans rien écrire."""
        return self._administration("GET", "/auth/v1/admin/users?per_page=1")

    def connexion_publique(self, adresse: str, mot_de_passe: str) -> Reponse:
        en_tetes = {"apikey": self._cle_publiable, "Accept": "application/json"}
        return self._envoie(
            "POST",
            self._url_d_auth + "/auth/v1/token",
            en_tetes,
            {"email": adresse, "password": mot_de_passe},
            {"grant_type": "password"},
        )


def _cle_de_type(cles: Sequence[Mapping[str, Any]], type_de_cle: str) -> str:
    for entree in cles:
        valeur = entree.get("api_key")
        if entree.get("type") == type_de_cle and isinstance(valeur, str) and valeur:
            return valeur
    return ""


def _exige_une_adresse_de_test(adresse: str) -> None:
    """L'adresse entre dans une requête SQL : seule la forme que ce script fabrique passe."""
    if not ADRESSE_DE_TEST.fullmatch(adresse):
        raise ValueError("Ce n'est pas une adresse de test du script.")


def verifie(condition: bool, message: str) -> None:
    if not condition:
        raise EcartError(message)


def _a_ete_cree(reponse: Reponse) -> UUID | None:
    try:
        return UUID(str(reponse.objet()["id"])) if reponse.status in (200, 201) else None
    except (KeyError, ValueError):
        return None


@dataclass
class Deroulement:
    """Ce qu'une exécution a créé, pour que le nettoyage le retrouve même après un échec."""

    essai: Essai
    sortie: Sortie
    comptes_crees: list[UUID] = field(default_factory=list)

    def ok(self, message: str) -> None:
        self.sortie(f"ok      {message}")

    def cree(self, adresse: str, mot_de_passe: str | None = None) -> Reponse:
        """Crée un compte et le note tout de suite : un `201` perdu plus loin ne le ferait pas oublier."""
        reponse = self.essai.cree(adresse, mot_de_passe)
        identifiant = _a_ete_cree(reponse)
        if identifiant is not None:
            self.comptes_crees.append(identifiant)
        return reponse


def etape_creation_sans_mot_de_passe(d: Deroulement, adresse: str) -> tuple[UUID, EtatDuCompte]:
    reponse = d.cree(adresse)
    verifie(
        reponse.status in (200, 201),
        f"createUser sans mot de passe est refusé ({reponse.decrit()}) : S13 enverra un mot de passe "
        "aléatoire jeté (noter dans la doc).",
    )
    identifiant = _a_ete_cree(reponse)
    if identifiant is None:
        raise EcartError("createUser n'a pas rendu d'identifiant lisible.")
    etat = d.essai.etat_du_compte(identifiant)
    verifie(etat.schema != "vide", "Aucun hachage n'a été écrit pour le compte sans mot de passe.")
    verifie(etat.confirme, "L'e-mail du compte créé n'est pas confirmé.")
    verifie(not etat.mail_parti, "Auth a envoyé un mail de confirmation (confirmation_sent_at renseigné).")
    d.ok(
        f"création sans mot de passe : hachage écrit ({etat.decrit_le_hachage()}), "
        "e-mail confirmé, aucun mail parti"
    )
    return identifiant, etat


def etape_connexion_publique_refusee(d: Deroulement, adresse: str) -> None:
    for essai in MOTS_DE_PASSE_DEVINES:
        reponse = d.essai.connexion_publique(adresse, essai)
        verifie(
            reponse.status != 429, "La connexion publique répond 429 : la preuve est à reprendre plus tard."
        )
        verifie("access_token" not in reponse.objet(), "La connexion publique a ouvert une session.")
        verifie(
            reponse.status in STATUTS_DE_REFUS,
            f"La connexion publique ne refuse pas comme attendu ({reponse.decrit()}).",
        )
    d.ok(f"connexion publique refusée pour mot de passe vide et deviné ({reponse.decrit()})")


def etape_mot_de_passe_pose(d: Deroulement, identifiant: UUID, adresse: str, avant: EtatDuCompte) -> None:
    mot_de_passe = mot_de_passe_aleatoire()
    reponse = d.essai.remplace_le_mot_de_passe(identifiant, mot_de_passe)
    verifie(reponse.status == 200, f"updateUserById refuse le mot de passe aléatoire ({reponse.decrit()}).")
    apres = d.essai.etat_du_compte(identifiant)
    verifie(apres.empreinte != avant.empreinte, "Le hachage n'a pas changé après la pose du mot de passe.")
    d.ok(
        f"mot de passe aléatoire de {LONGUEUR_DU_MOT_DE_PASSE} caractères posé : "
        f"hachage changé ({apres.decrit_le_hachage()})"
    )
    # Contrôle positif, non bloquant : le refus plus haut ne vaut que si la route accepte un bon mot de passe.
    controle = d.essai.connexion_publique(adresse, mot_de_passe)
    ouverte = "access_token" in controle.objet()
    d.sortie(
        f"info    connexion avec le mot de passe posé : {'acceptée' if ouverte else 'refusée'}"
        f" ({controle.decrit()})"
    )


def etape_email_deja_pris(d: Deroulement, adresse: str) -> None:
    for libelle, variante in (("même casse", adresse), ("autre casse", adresse.upper())):
        # La variante en majuscules est aussi une adresse de test : l'expression est insensible à la casse.
        reponse = d.cree(variante)
        verifie(
            reponse.status == 422 and reponse.code() in CODES_COMPTE_EXISTANT,
            f"Une deuxième création ({libelle}) n'est pas refusée en email_exists ({reponse.decrit()}).",
        )
        d.ok(f"deuxième création, {libelle} : refusée ({reponse.decrit()})")
    verifie(d.essai.nombre_de_comptes_a_l_adresse(adresse) == 1, "Plus d'un compte porte l'adresse de test.")
    d.ok("un seul compte porte l'adresse, quelle que soit la casse")


def _supprime_les_comptes(d: Deroulement, identifiants: set[UUID]) -> None:
    for identifiant in identifiants:
        try:
            reponse = d.essai.supprime(identifiant)
        except AccesError as erreur:
            d.sortie(f"erreur  suppression d'un compte de test impossible : {erreur}")
            continue
        supprime = reponse.status in (200, 204) or (
            reponse.status == 404 and reponse.code() == "user_not_found"
        )
        if not supprime:
            d.sortie(f"erreur  suppression d'un compte de test refusée ({reponse.decrit()})")


def nettoie(d: Deroulement) -> int:
    """Supprime les comptes créés, puis balaie ceux qu'une exécution précédente a oubliés.

    Les comptes créés partent d'abord : la base illisible ne doit pas les laisser en place.
    Rend le nombre de comptes de test qui restent.
    """
    _supprime_les_comptes(d, set(d.comptes_crees))
    d.comptes_crees.clear()
    _supprime_les_comptes(d, set(d.essai.comptes_de_test()))
    return len(d.essai.comptes_de_test())


def joue_la_preuve(essai: Essai, sortie: Sortie) -> int:
    d = Deroulement(essai, sortie)
    code = 0
    try:
        essai.exige_le_projet_d_essai()
        essai.charge_les_cles()
        anciens = len(essai.comptes_de_test())
        if anciens:
            sortie(f"info    {anciens} compte(s) de test d'une exécution précédente, balayé(s) d'abord")
            nettoie(d)
        adresse = adresse_de_test()
        identifiant, avant = etape_creation_sans_mot_de_passe(d, adresse)
        etape_connexion_publique_refusee(d, adresse)
        etape_mot_de_passe_pose(d, identifiant, adresse, avant)
        etape_email_deja_pris(d, adresse)
    except EcartError as erreur:
        sortie(f"ÉCART   {erreur}")
        code = 1
    except AccesError as erreur:
        sortie(f"ACCÈS   {erreur}")
        code = 2
    finally:
        try:
            restants = nettoie(d)
        except AccesError as erreur:
            sortie(f"ACCÈS   nettoyage impossible : {erreur}")
            restants = -1
    if restants != 0:
        sortie("ÉCART   des comptes de test restent (ou leur liste est illisible) : relancer le script.")
        return max(code, 1)
    sortie("ok      aucun compte de test ne reste")
    if code == 0:
        sortie("PREUVE COMPLÈTE")
    return code


def joue_a_blanc(essai: Essai, sortie: Sortie) -> int:
    """Lectures seules : garde-fous, clés, administration d'Auth et base. Rien n'est écrit sur l'essai."""
    try:
        essai.exige_le_projet_d_essai()
        sortie(f"ok      le projet est bien {NOM_DU_PROJET_D_ESSAI}")
        essai.charge_les_cles()
        sortie("ok      clés secrète et publiable lues")
        lecture = essai.lit_un_compte_au_hasard()
        verifie(lecture.status == 200, f"L'administration d'Auth refuse la clé secrète ({lecture.decrit()}).")
        sortie("ok      l'administration d'Auth accepte la clé secrète")
        restants = len(essai.comptes_de_test())
    except EcartError as erreur:
        sortie(f"ÉCART   {erreur}")
        return 1
    except AccesError as erreur:
        sortie(f"ACCÈS   {erreur}")
        return 2
    sortie(f"ok      {restants} compte(s) de test présent(s) avant la preuve")
    sortie("A BLANC terminé : la preuve réelle créera un compte, le modifiera, puis le supprimera.")
    return 0


def main(
    argv: Sequence[str], environnement: Mapping[str, str], *, transport: httpx.BaseTransport | None = None
) -> int:
    analyseur = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    analyseur.add_argument(
        "--a-blanc", action="store_true", help="lectures seules : rien n'est écrit sur l'essai"
    )
    arguments = analyseur.parse_args(argv)
    try:
        acces = acces_depuis(environnement)
    except AccesError as erreur:
        print(f"ACCÈS   {erreur}", file=sys.stderr)
        return 2
    delais = httpx.Timeout(DELAI_LECTURE_S, connect=DELAI_CONNEXION_S, pool=DELAI_CONNEXION_S)
    # trust_env=False : ni proxy ni certificats du poste ne détournent les clés ; aucune redirection suivie.
    # Le magasin de certificats du système, pas celui de certifi : un réseau qui inspecte le TLS y pose son
    # autorité (WSL d'entreprise). La vérification des certificats reste entière.
    contexte = ssl.create_default_context()
    with httpx.Client(
        timeout=delais, transport=transport, follow_redirects=False, trust_env=False, verify=contexte
    ) as http:
        essai = Essai(acces, http, environnement)
        if arguments.a_blanc:
            return joue_a_blanc(essai, print)
        return joue_la_preuve(essai, print)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
