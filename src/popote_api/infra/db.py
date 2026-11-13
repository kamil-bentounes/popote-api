"""Accès à Postgres : deux pools et deux contextes (spec § 5.1, § 8.2).

- `Base.personne(id)` : pool `popote_api`, `set local role authenticated`, identité de la personne.
- `Base.session(empreinte)` : le contexte « personne » d'une requête portée par une session. Lit la session
  SANS écrire ni verrouiller (`lit_la_session`, exécutable par `popote_api` seul) puis emprunte
  `authenticated`, dans la MÊME transaction. L'activité d'une session vue depuis plus de 5 minutes s'écrit
  dans sa propre transaction courte, validée AVANT celle de la route : aucun verrou de personne ni de ligne
  de session n'est tenu quand la route prend le sien (foyer, invitation, personne, lignes ; migration 0148).
- `Base.connexion()` : pool `popote_api`, ni rôle emprunté ni identité (`current_user = popote_api`). Réservé
  aux fonctions `security definer` dont seul `popote_api` a l'`execute` : connexion, limites, sessions,
  vérification d'un mot de passe (liste fermée).
- `Base.service()` : pool `popote_internal`, `set local role service_role`. Réservé aux routes internes,
  à l'invitation et aux purges (liste fermée).

Chaque contexte est UNE transaction, ouverte dans le bon rôle : `commit` en sortie normale, `rollback` sur
exception ou annulation. Tout ce qui est posé (rôle, identité, délais) l'est par `set local` ou
`set_config(..., true)`, donc meurt avec la transaction : une connexion rendue au pool, que le pooler en mode
transaction peut passer à un autre client, ne garde rien.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, LiteralString, Self
from uuid import UUID

import psycopg
from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

journal = logging.getLogger(__name__)

DELAI_TOTAL_S = 3  # connexion et requête de la sonde comprises
DUREE_DU_CACHE_S = 5.0
ATTENTE_D_UNE_CONNEXION_S = 2.0  # au-delà : PoolTimeout, que la frontière rend en 503 base_indisponible
DELAI_DE_CONNEXION_S = 5
TAILLE_MAX_API = 5
TAILLE_MAX_INTERNE = 2

# Lit une vraie table, c'est ce qui garde le projet Supabase éveillé (spec § 3.11). `instance_setting` :
# sa politique `true` la rend lisible par `authenticated` sans foyer, et la migration 0009 y sème
# toujours une ligne.
REQUETE_DE_SONDE: LiteralString = "select 1 from public.instance_setting limit 1"

# Délais côté base, posés par `set local` en tête de chaque transaction. Ils doublent `alter role` de la
# migration 0132 (un test compare les deux) : `set role` n'applique pas les réglages du rôle emprunté, et seul
# le rôle de connexion porte les siens. Valeurs et raisons : voir la migration.
DELAIS_API: LiteralString = (
    "set local statement_timeout = '8s'; set local lock_timeout = '5s'; "
    "set local idle_in_transaction_session_timeout = '15s'"
)
DELAIS_INTERNE: LiteralString = (
    "set local statement_timeout = '30s'; set local lock_timeout = '10s'; "
    "set local idle_in_transaction_session_timeout = '15s'"
)
# Le contexte service coupe plus tôt que le rôle (30 s, migration 0132) : l'API répond à 25 s
# (`limites.Delai`), et sous Supavisor l'annulation de la requête ne la coupe pas côté base. Sans cette
# borne, le travail continuerait après la `503`.
DELAI_DE_LA_BASE_DU_SERVICE = "20s"
ROLE_PERSONNE: LiteralString = "set local role authenticated"
PREAMBULE_PERSONNE: LiteralString = f"{ROLE_PERSONNE}; {DELAIS_API}"
# La personne de la session, ou null. Se lit sous le rôle de connexion : `authenticated` n'a pas le droit.
# Lecture seule : ni écriture de l'activité, ni verrou (voir `NOTE_L_ACTIVITE`).
LIT_LA_SESSION: LiteralString = (
    "select person_id, session_id, reauth_at, activite_perimee from public.lit_la_session(%s)"
)
# L'activité d'une session vue depuis plus de 5 minutes : la personne d'abord, la ligne ensuite, en une
# transaction à part que rien ne retient.
NOTE_L_ACTIVITE: LiteralString = "select public.note_l_activite_de_la_session(%s)"
PREAMBULE_CONNEXION: LiteralString = DELAIS_API  # pas de `set role` : la transaction reste `popote_api`
# L'écriture de l'activité attend la personne 1 s au plus : elle est facultative.
PREAMBULE_ACTIVITE: LiteralString = f"{DELAIS_API}; set local lock_timeout = '1s'"
PREAMBULE_SERVICE: LiteralString = (
    f"set local role service_role; {DELAIS_INTERNE}; "
    f"set local statement_timeout = '{DELAI_DE_LA_BASE_DU_SERVICE}'"
)


class FiltreDuPool(logging.Filter):
    """Ne laisse passer des journaux de psycopg et de son pool que le modèle du message, jamais ses valeurs.

    Ils écrivent l'erreur de libpq (« connection to server at "<hôte>", port … ») et la représentation de la
    connexion (hôte, port, base, rôle) : l'adresse de la base n'a pas à finir dans un journal. On garde le
    texte jusqu'au premier `%` (« error connecting in », « discarding expired connection »), sans arguments ni
    pile.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = str(record.msg).partition("%")[0].rstrip(" :")
        record.args = None
        record.exc_info = None
        record.exc_text = None
        return True


FILTRE_DU_POOL = FiltreDuPool()
# Les journaux de psycopg et de son pool (un filtre de logger ne vaut pas pour ses enfants : liste explicite).
JOURNAUX_A_FILTRER = (
    "psycopg",
    "psycopg.pool",
    "psycopg.transaction",
    "psycopg.waiting",
    "psycopg_pool.sched",
    "psycopg_pool.sched_async",
)

type Curseur = AsyncCursor[DictRow]
type Pool = AsyncConnectionPool[AsyncConnection[Any]]


class BaseError(Exception):
    """Racine des échecs d'accès à la base qui ne viennent pas de psycopg."""


@dataclass(frozen=True, slots=True)
class SessionCourante:
    """Ce que rend la lecture d'une session valide : personne, session, dernière réauthentification."""

    personne: UUID
    session: UUID
    reauth_at: datetime


class SessionRefuseeError(Exception):
    """Aucune session valide n'a cette empreinte (inconnue, échue, révoquée, personne bannie ou supprimée).

    Ce n'est pas une panne de la base : la frontière HTTP en fait un `401`. Un seul type pour tous les refus,
    la base ne les distingue pas non plus.
    """


class BaseIndisponibleError(BaseError):
    """Aucune base n'est configurée pour le pool `popote_api`."""


class ServiceIndisponibleError(BaseError):
    """Le pool `popote_internal` n'est pas configuré : `POPOTE_DATABASE_URL_INTERNAL` manque."""


def revendications_personne(personne_id: UUID, emetteur: str | None) -> dict[str, str]:
    """Ce que PostgREST pose dans `request.jwt.claims` pour une personne connectée, et que le SQL lit.

    Inventaire des migrations (`tests/unit/test_revendications.py` le garde) : `sub` (via `auth.uid()`),
    `role` (`is_service_role()`, `auth.role()`) et `iss` (`tg_recipe_photo`). Le JWT de GoTrue porte aussi
    `aud`, `exp`, `iat`, `email`, `phone`, `app_metadata`, `user_metadata`, `aal`, `amr`, `session_id` et
    `is_anonymous` : aucune requête ne les lit, on ne les invente pas.
    """
    revendications = {"sub": str(personne_id), "role": "authenticated"}
    if emetteur:
        revendications["iss"] = emetteur
    return revendications


def cree_pool(dsn: str, taille_max: int, attente_s: float = ATTENTE_D_UNE_CONNEXION_S) -> Pool:
    """Un pool fermé, sans connexion ouverte : le conteneur dort à zéro instance (`min_size=0`).

    Pas d'instruction préparée : le pooler en mode transaction change de serveur d'une transaction à l'autre.
    `autocommit` : la transaction est celle, explicite, de chaque contexte, et une connexion qui rentre au
    pool n'a jamais de transaction implicite ouverte. `check` : Supavisor ferme les connexions inactives, on
    ne remet pas au code une connexion morte.
    """
    return AsyncConnectionPool(
        dsn,
        min_size=0,
        max_size=taille_max,
        open=False,
        timeout=attente_s,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": DELAI_DE_CONNEXION_S},
    )


class Base:
    """Les deux pools et les deux contextes. Une instance par application, fermée à l'arrêt."""

    def __init__(self, api: Pool | None, interne: Pool | None, *, emetteur: str | None = None) -> None:
        for nom in JOURNAUX_A_FILTRER:
            logging.getLogger(nom).addFilter(FILTRE_DU_POOL)  # sans doublon : même instance
        self._api = api
        self._interne = interne
        self._emetteur = emetteur

    @classmethod
    def depuis_dsn(cls, dsn_api: str | None, dsn_interne: str | None, *, emetteur: str | None = None) -> Self:
        return cls(
            cree_pool(dsn_api, TAILLE_MAX_API) if dsn_api else None,
            cree_pool(dsn_interne, TAILLE_MAX_INTERNE) if dsn_interne else None,
            emetteur=emetteur,
        )

    @property
    def service_configure(self) -> bool:
        return self._interne is not None

    async def ouvre(self) -> None:
        """Ouvre les pools : `wait=False` ne bloque jamais, et `min_size=0` n'ouvre aucune connexion."""
        for pool in (self._api, self._interne):
            if pool is not None:
                await pool.open(wait=False)

    async def ferme(self) -> None:
        for pool in (self._api, self._interne):
            if pool is not None:
                await pool.close()

    def personne(self, personne_id: UUID) -> AbstractAsyncContextManager[Curseur]:
        """Une transaction qui agit comme cette personne : la RLS et les gardes jouent comme pour elle."""
        revendications = revendications_personne(personne_id, self._emetteur)
        return _contexte(self._api, PREAMBULE_PERSONNE, revendications, BaseIndisponibleError())

    def session(self, empreinte: bytes) -> AbstractAsyncContextManager[tuple[SessionCourante, Curseur]]:
        """Une transaction qui lit la session, puis agit comme sa personne ; `SessionRefuseeError` sinon.

        Cas courant : un seul emprunt au pool, la lecture de la session (sans écriture ni verrou) et tout
        le travail de la requête partagent la transaction, que le contexte valide en sortie normale. Activité
        périmée (plus de 5 minutes) : la lecture est abandonnée, l'activité s'écrit dans une transaction
        courte validée tout de suite (un deuxième emprunt, jamais en même temps que le premier), puis la
        requête recommence (un troisième). Rien n'est tenu quand la route démarre.
        """
        return _contexte_de_session(self._api, empreinte, self._emetteur)

    def connexion(self) -> AbstractAsyncContextManager[Curseur]:
        """Une transaction `popote_api` sans rôle emprunté ni revendication : aucune table n'y est lisible.

        Elle ne sert qu'à appeler les fonctions `security definer` réservées à `popote_api` (rien n'y
        identifie une personne : aucune revendication, et le schéma `auth` lui est fermé).
        Seul le code de la liste fermée l'appelle.
        """
        return _contexte(self._api, PREAMBULE_CONNEXION, None, BaseIndisponibleError())

    def service(self) -> AbstractAsyncContextManager[Curseur]:
        """Une transaction `service_role`. Seul le code de la liste fermée l'appelle."""
        revendications = {"role": "service_role"}
        return _contexte(self._interne, PREAMBULE_SERVICE, revendications, ServiceIndisponibleError())

    async def repond(self) -> bool:
        """Vrai si la table de référence rend une ligne ; la ligne n'est ni gardée ni journalisée."""
        try:
            async with asyncio.timeout(DELAI_TOTAL_S):
                # Sans revendication : la politique de `instance_setting` ne regarde personne.
                async with _contexte(self._api, PREAMBULE_PERSONNE, None, BaseIndisponibleError()) as curseur:
                    await curseur.execute(REQUETE_DE_SONDE)
                    ligne = await curseur.fetchone()
        except (psycopg.Error, BaseError, TimeoutError) as erreur:
            # Le type seulement : le message de libpq peut contenir l'hôte de la base.
            journal.warning("Base indisponible : %s", type(erreur).__name__)
            return False
        if ligne is None:
            journal.warning("Base indisponible : aucune ligne lisible dans la table de référence")
        return ligne is not None


@asynccontextmanager
async def _transaction(pool: Pool | None, absente: BaseError) -> AsyncIterator[Curseur]:
    """Une connexion du pool, une transaction, un curseur : la transaction se valide en sortie normale."""
    if pool is None:
        raise absente
    async with pool.connection() as connexion, connexion.transaction():
        async with connexion.cursor(row_factory=dict_row) as curseur:
            yield curseur


async def _pose_les_revendications(curseur: Curseur, revendications: dict[str, str]) -> None:
    await curseur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(revendications),))


@asynccontextmanager
async def _contexte(
    pool: Pool | None,
    preambule: LiteralString,
    revendications: dict[str, str] | None,
    absente: BaseError,
) -> AsyncIterator[Curseur]:
    async with _transaction(pool, absente) as curseur:
        await curseur.execute(preambule)
        if revendications is not None:
            await _pose_les_revendications(curseur, revendications)
        yield curseur


class _ActivitePerimee(Exception):
    """La session lue n'a pas été vue depuis plus de 5 minutes : à écrire avant la transaction de la route."""


@asynccontextmanager
async def _contexte_de_session(
    pool: Pool | None, empreinte: bytes, emetteur: str | None
) -> AsyncIterator[tuple[SessionCourante, Curseur]]:
    activite_notee = False
    while True:
        try:
            async with _transaction(pool, BaseIndisponibleError()) as curseur:
                # Les délais d'abord : la lecture de la session est elle aussi bornée. Elle se fait encore
                # sous le rôle de connexion, seul à pouvoir exécuter `lit_la_session` ; `authenticated` après.
                await curseur.execute(DELAIS_API)
                await curseur.execute(LIT_LA_SESSION, (empreinte,))
                ligne = await curseur.fetchone()
                if ligne is None:
                    raise SessionRefuseeError
                if ligne["activite_perimee"] and not activite_notee:
                    raise _ActivitePerimee  # rien n'est tenu : la lecture ne verrouille rien
                session = SessionCourante(ligne["person_id"], ligne["session_id"], ligne["reauth_at"])
                await curseur.execute(ROLE_PERSONNE)
                await _pose_les_revendications(curseur, revendications_personne(session.personne, emetteur))
                yield session, curseur
            return
        except _ActivitePerimee:
            # Une fois : si l'activité reste périmée (écriture concurrente, session fermée entre-temps), la
            # requête continue sans elle ; la suivante réessaiera.
            await _note_l_activite(pool, empreinte)
            activite_notee = True


async def _note_l_activite(pool: Pool | None, empreinte: bytes) -> None:
    """Écrit l'activité en sa propre transaction, validée tout de suite : rien n'est tenu pendant la route.

    Au mieux : l'activité ne fait pas échouer une requête dont la session est valide. Un verrou qui n'a pas
    lâché en 1 s (une fermeture longue), un interblocage ou un délai de requête laissent l'activité périmée ;
    la requête suivante réessaiera. Seuls ces trois cas sont avalés, et journalisés par leur type.
    """
    try:
        async with _contexte(pool, PREAMBULE_ACTIVITE, None, BaseIndisponibleError()) as curseur:
            await curseur.execute(NOTE_L_ACTIVITE, (empreinte,))
    except (
        psycopg.errors.LockNotAvailable,
        psycopg.errors.DeadlockDetected,
        psycopg.errors.QueryCanceled,
    ) as erreur:
        journal.warning("Activité de session non écrite : %s", type(erreur).__name__)


class SondeBase:
    """La disponibilité de la base, mise en cache pour ne pas emprunter une connexion par sondage.

    Le résultat, succès ou échec, reste valable `DUREE_DU_CACHE_S` secondes, et un seul sondage
    est en vol à la fois : un afflux de requêtes sur /readyz n'épuise pas les connexions.
    """

    def __init__(
        self,
        verifie: Callable[[], Awaitable[bool]] | None,
        *,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._verifie = verifie
        self._horloge = horloge
        self._verrou = asyncio.Lock()
        self._valable_jusqu_a: float | None = None
        self._resultat = False

    async def disponible(self) -> bool:
        if self._verifie is None:
            return False
        async with self._verrou:
            if self._valable_jusqu_a is not None and self._horloge() < self._valable_jusqu_a:
                return self._resultat
            self._resultat = await self._verifie()
            self._valable_jusqu_a = self._horloge() + DUREE_DU_CACHE_S
            return self._resultat
