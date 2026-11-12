#!/usr/bin/env python3
"""Aligne les droits SQL d'un projet Supabase neuf sur ceux de la base locale.

Why: un projet hébergé neuf ne pose plus les privilèges par défaut classiques
(`pg_default_acl`), donc après `supabase db push` les tables n'accordent presque
rien à anon, authenticated et service_role. La base locale (migrations plus
privilèges par défaut classiques) est la référence, c'est aussi l'état de la prod.

L'outil lit les ACL des deux côtés, calcule les écarts et n'émet, pour chaque
écart, qu'un REVOKE ciblé puis des GRANT exacts. Il ne fait jamais de GRANT en
bloc : les REVOKE posés par les migrations (fonctions `security definer`,
catalogue protégé) seraient annulés.

Usage :
    python3 ops/aligne_droits.py                 # à blanc : compte et écrit le SQL
    python3 ops/aligne_droits.py --appliquer     # envoie le SQL, relit, exit 1 s'il reste un écart

Environnement : SUPABASE_ESSAI_TOKEN et ESSAI_REF (jamais affichés).
Codes de sortie : 0 aucun écart, 1 écart restant, 2 erreur d'utilisation ou d'accès.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_DSN = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DEFAULT_OUTPUT_PATH = Path("aligne_droits.sql")
DEFAULT_BATCH_SIZE = 200
API_TIMEOUT_SECONDS = 60
PSQL_TIMEOUT_SECONDS = 60

# La prod ne doit jamais être une cible, même par une erreur de variable d'environnement.
FORBIDDEN_PROJECT_REF = "mjlxfffdirlqmmjzhorg"
PROJECT_REF_PATTERN = re.compile(r"[a-z]{20}")

# Les seuls rôles que l'outil modifie. `postgres` et `supabase_admin` ne sont jamais touchés.
MANAGED_ROLES = ("anon", "authenticated", "service_role")
# Observé, jamais modifié : un écart sur PUBLIC est rapporté sans être corrigé.
PUBLIC_ROLE = "PUBLIC"
TRACKED_ROLES = (*MANAGED_ROLES, PUBLIC_ROLE)

EXCLUDED_SCHEMAS = frozenset(
    {
        "auth",
        "storage",
        "realtime",
        "extensions",
        "graphql",
        "graphql_public",
        "vault",
        "pgsodium",
        "pgsodium_masks",
        "net",
        "cron",
        "pgbouncer",
        "_realtime",
        "_analytics",
        "_supavisor",
        "information_schema",
    }
)
EXCLUDED_SCHEMA_PREFIXES = ("supabase_", "pg_")
# Schéma géré par Supabase : ses écarts sont rapportés, jamais corrigés.
REPORT_ONLY_SCHEMA = "storage"
DEFAULT_ACL_OWNER = "postgres"
DEFAULT_ACL_KIND_PREFIX = "default_acl_"

PRIVILEGE_NAMES = {
    "r": "SELECT",
    "a": "INSERT",
    "w": "UPDATE",
    "d": "DELETE",
    "D": "TRUNCATE",
    "x": "REFERENCES",
    "t": "TRIGGER",
    "m": "MAINTAIN",
    "X": "EXECUTE",
    "U": "USAGE",
    "C": "CREATE",
}
PRIVILEGE_ORDER = "arwdDxtmXUC"

RELATION_KINDS = {
    "r": "table",
    "p": "table",
    "f": "table",
    "v": "view",
    "m": "matview",
    "S": "sequence",
}
ROUTINE_KINDS = {"f": "function", "a": "function", "w": "function", "p": "procedure"}
DEFAULT_ACL_OBJECT_TYPES = {"r": "TABLES", "S": "SEQUENCES", "f": "FUNCTIONS", "T": "TYPES"}
# Mot-clé SQL de l'objet dans GRANT et REVOKE, par type d'écart.
SQL_OBJECT_KEYWORD = {
    "schema": "SCHEMA",
    "table": "TABLE",
    "view": "TABLE",
    "matview": "TABLE",
    "sequence": "SEQUENCE",
    "function": "FUNCTION",
    "procedure": "PROCEDURE",
}
# Privilèges comparés : pour un schéma, seulement USAGE ; pour le reste, tous.
COMPARED_PRIVILEGES = {"schema": "U"}

# Une seule requête, exécutée à l'identique sur la source et sur la cible. Le search_path
# réduit à pg_catalog force des signatures de fonctions qualifiées par leur schéma.
# `acldefault` rend explicite l'ACL des objets dont `*acl` est NULL (droits du propriétaire,
# EXECUTE pour PUBLIC). Les membres d'extension sont exclus : leurs droits sont ceux de l'extension.
SNAPSHOT_SQL = """
SET LOCAL search_path = pg_catalog;
SELECT jsonb_build_object(
  'schemas', (
    SELECT coalesce(jsonb_agg(jsonb_build_object(
      'name', n.nspname,
      'owner', pg_get_userbyid(n.nspowner),
      'acl', coalesce(n.nspacl, acldefault('n', n.nspowner))::text[])), '[]'::jsonb)
    FROM pg_namespace n
    WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'),
  'relations', (
    SELECT coalesce(jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'name', c.relname, 'kind', c.relkind,
      'owner', pg_get_userbyid(c.relowner),
      'acl', coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char",
                                           c.relowner))::text[])), '[]'::jsonb)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p', 'f', 'v', 'm', 'S')
      AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d
                      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                        AND d.deptype = 'e')),
  'routines', (
    SELECT coalesce(jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'signature', p.oid::regprocedure::text, 'kind', p.prokind,
      'owner', pg_get_userbyid(p.proowner),
      'acl', coalesce(p.proacl, acldefault('f', p.proowner))::text[])), '[]'::jsonb)
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d
                      WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                        AND d.deptype = 'e')),
  'default_acls', (
    SELECT coalesce(jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'role', pg_get_userbyid(d.defaclrole),
      'objtype', d.defaclobjtype, 'acl', d.defaclacl::text[])), '[]'::jsonb)
    FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace)
) AS snapshot;
"""

RawSnapshot = dict[str, list[dict[str, Any]]]
Privileges = dict[str, bool]  # lettre du privilège -> avec WITH GRANT OPTION
AclByRole = dict[str, Privileges]


class AlignmentError(Exception):
    """Erreur d'utilisation ou d'accès : l'outil s'arrête sans rien appliquer de plus."""


@dataclass(frozen=True)
class Securable:
    """Un objet portant des droits, avec les droits des rôles suivis."""

    kind: str  # schema, table, view, matview, sequence, function, procedure, default_acl_*
    schema: str
    reference: str  # texte SQL déjà quoté, utilisable tel quel dans GRANT et REVOKE
    owner: str
    acl: AclByRole = field(compare=False)


Snapshot = dict[tuple[str, str], Securable]


@dataclass(frozen=True)
class Divergence:
    securable: Securable
    role: str
    source: Privileges
    target: Privileges


@dataclass
class Report:
    to_fix: list[Divergence] = field(default_factory=list)
    observed_only: list[Divergence] = field(default_factory=list)  # PUBLIC, storage
    missing_in_target: list[Securable] = field(default_factory=list)

    @property
    def counts_by_kind(self) -> Counter[str]:
        # Un écart = un objet dont au moins un rôle diffère.
        return Counter(kind for kind, _ in {(d.securable.kind, d.securable.reference) for d in self.to_fix})


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def is_user_schema(name: str) -> bool:
    return name not in EXCLUDED_SCHEMAS and not name.startswith(EXCLUDED_SCHEMA_PREFIXES)


def split_aclitem(item: str) -> tuple[str, str]:
    """Sépare `grantee=privs/grantor` en (grantee, privs), en lisant un grantee quoté."""
    if item.startswith('"'):
        grantee_chars: list[str] = []
        index = 1
        while index < len(item):
            if item[index] == '"':
                if item[index + 1 : index + 2] == '"':
                    grantee_chars.append('"')
                    index += 2
                    continue
                index += 1
                break
            grantee_chars.append(item[index])
            index += 1
        grantee = "".join(grantee_chars)
        rest = item[index:]
    else:
        grantee, separator, rest = item.partition("=")
        rest = separator + rest
    if not rest.startswith("="):
        raise AlignmentError(f"aclitem illisible : {item!r}")
    privileges, _, _grantor = rest[1:].partition("/")
    return grantee or PUBLIC_ROLE, privileges


def parse_privileges(text: str) -> Privileges:
    privileges: Privileges = {}
    for character in text:
        if character == "*":
            if not privileges:
                raise AlignmentError(f"« * » sans privilège : {text!r}")
            privileges[list(privileges)[-1]] = True
        else:
            privileges[character] = False
    return privileges


def parse_acl(items: Iterable[str]) -> AclByRole:
    """Les droits des rôles suivis, tous grantors confondus ; les autres rôles sont ignorés."""
    acl: AclByRole = {}
    for item in items:
        grantee, privileges_text = split_aclitem(item)
        if grantee not in TRACKED_ROLES:
            continue
        for letter, with_grant_option in parse_privileges(privileges_text).items():
            merged = acl.setdefault(grantee, {})
            merged[letter] = merged.get(letter, False) or with_grant_option
    return acl


def build_snapshot(raw: RawSnapshot) -> Snapshot:
    snapshot: Snapshot = {}

    def add(kind: str, schema: str, reference: str, owner: str, acl_items: list[str]) -> None:
        snapshot[(kind, reference)] = Securable(kind, schema, reference, owner, parse_acl(acl_items))

    for row in raw["schemas"]:
        name = str(row["name"])
        add("schema", name, quote_identifier(name), str(row["owner"]), list(row["acl"]))
    for row in raw["relations"]:
        schema, name = str(row["schema"]), str(row["name"])
        reference = f"{quote_identifier(schema)}.{quote_identifier(name)}"
        add(RELATION_KINDS[str(row["kind"])], schema, reference, str(row["owner"]), list(row["acl"]))
    for row in raw["routines"]:
        add(
            ROUTINE_KINDS[str(row["kind"])],
            str(row["schema"]),
            str(row["signature"]),
            str(row["owner"]),
            list(row["acl"]),
        )
    for row in raw["default_acls"]:
        object_type = str(row["objtype"])
        if row["role"] != DEFAULT_ACL_OWNER or object_type not in DEFAULT_ACL_OBJECT_TYPES:
            continue
        schema = str(row["schema"])
        add(
            f"{DEFAULT_ACL_KIND_PREFIX}{DEFAULT_ACL_OBJECT_TYPES[object_type].lower()}",
            schema,
            quote_identifier(schema),
            DEFAULT_ACL_OWNER,
            list(row["acl"]),
        )
    return snapshot


def schemas_in_scope(source: Snapshot, target: Snapshot) -> set[str]:
    def schema_names(snapshot: Snapshot) -> set[str]:
        return {s.schema for (kind, _), s in snapshot.items() if kind == "schema"}

    return {name for name in schema_names(source) & schema_names(target) if is_user_schema(name)}


def compared_privileges(kind: str, privileges: Privileges) -> Privileges:
    allowed = COMPARED_PRIVILEGES.get(kind)
    return privileges if allowed is None else {k: v for k, v in privileges.items() if k in allowed}


def compute_report(source: Snapshot, target: Snapshot) -> Report:
    in_scope = schemas_in_scope(source, target)
    report = Report()
    storage_present = any(s.schema == REPORT_ONLY_SCHEMA for s in source.values()) and any(
        s.schema == REPORT_ONLY_SCHEMA for s in target.values()
    )
    for key in sorted(source):
        reference_object = source[key]
        schema = reference_object.schema
        is_storage = storage_present and schema == REPORT_ONLY_SCHEMA
        if schema not in in_scope and not is_storage:
            continue
        if is_storage and reference_object.owner != DEFAULT_ACL_OWNER:
            continue  # objets de Supabase, pas créés par nos migrations
        current_object = target.get(key)
        if current_object is None and reference_object.kind.startswith(DEFAULT_ACL_KIND_PREFIX):
            # Une ligne pg_default_acl absente veut dire « aucun droit par défaut », pas « objet absent ».
            current_object = Securable(reference_object.kind, schema, reference_object.reference, "", {})
        if current_object is None:
            report.missing_in_target.append(reference_object)
            continue
        for role in TRACKED_ROLES:
            wanted = compared_privileges(reference_object.kind, reference_object.acl.get(role, {}))
            actual = compared_privileges(current_object.kind, current_object.acl.get(role, {}))
            if wanted == actual:
                continue
            divergence = Divergence(reference_object, role, wanted, actual)
            if role == PUBLIC_ROLE or is_storage:
                report.observed_only.append(divergence)
            else:
                report.to_fix.append(divergence)
    return report


def privilege_names(privileges: Privileges, *, with_grant_option: bool) -> list[str]:
    letters = [
        letter
        for letter in sorted(privileges, key=PRIVILEGE_ORDER.index)
        if privileges[letter] == with_grant_option
    ]
    return [PRIVILEGE_NAMES[letter] for letter in letters]


def render_divergence(divergence: Divergence) -> list[str]:
    """REVOKE ciblé, puis GRANT exacts, pour un objet et un rôle."""
    securable, role = divergence.securable, divergence.role
    if role not in MANAGED_ROLES:
        raise AlignmentError(f"rôle non modifiable : {role}")
    if securable.kind.startswith(DEFAULT_ACL_KIND_PREFIX):
        prefix = f"ALTER DEFAULT PRIVILEGES FOR ROLE {DEFAULT_ACL_OWNER} IN SCHEMA {securable.reference}"
        target_clause = securable.kind.removeprefix(DEFAULT_ACL_KIND_PREFIX).upper()
        revoke_on = f"{prefix} REVOKE {{what}} ON {target_clause} FROM {role};"
        grant_on = f"{prefix} GRANT {{what}} ON {target_clause} TO {role}{{option}};"
    else:
        keyword = SQL_OBJECT_KEYWORD[securable.kind]
        revoke_on = f"REVOKE {{what}} ON {keyword} {securable.reference} FROM {role};"
        grant_on = f"GRANT {{what}} ON {keyword} {securable.reference} TO {role}{{option}};"
    revoked = "USAGE" if securable.kind == "schema" else "ALL"
    statements = [revoke_on.format(what=revoked)]
    for with_grant_option, option in ((False, ""), (True, " WITH GRANT OPTION")):
        names = privilege_names(divergence.source, with_grant_option=with_grant_option)
        if names:
            statements.append(grant_on.format(what=", ".join(names), option=option))
    return statements


def render_sql(divergences: Sequence[Divergence]) -> list[str]:
    return [
        statement
        for divergence in sorted(divergences, key=lambda d: (d.securable.kind, d.securable.reference, d.role))
        for statement in render_divergence(divergence)
    ]


def split_batches(statements: Sequence[str], size: int) -> list[list[str]]:
    if size < 1:
        raise AlignmentError("la taille d'un lot doit être positive")
    return [list(statements[start : start + size]) for start in range(0, len(statements), size)]


def wrap_in_transaction(statements: Sequence[str]) -> str:
    return "BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;"


def apply_batches(statements: Sequence[str], size: int, execute: Callable[[str], object]) -> int:
    """Envoie chaque lot dans sa transaction ; un lot en échec s'annule en entier et arrête tout."""
    batches = split_batches(statements, size)
    for number, batch in enumerate(batches, start=1):
        try:
            execute(wrap_in_transaction(batch))
        except AlignmentError as error:
            raise AlignmentError(f"lot {number}/{len(batches)} refusé, annulé : {error}") from error
    return len(batches)


def render_script(report: Report, statements: Sequence[str]) -> str:
    header = [
        "-- Généré par ops/aligne_droits.py : REVOKE ciblé puis GRANT exacts, jamais de GRANT en bloc.",
        f"-- Écarts à corriger : {sum(report.counts_by_kind.values())}",
        *(f"--   {kind}: {count}" for kind, count in sorted(report.counts_by_kind.items())),
        "",
    ]
    return "\n".join([*header, *statements, ""])


# --- Accès aux deux bases -----------------------------------------------------------------


def parse_snapshot_output(output: str) -> RawSnapshot:
    try:
        snapshot = json.loads(output)
    except json.JSONDecodeError as error:
        raise AlignmentError("la lecture des droits n'a pas rendu du JSON") from error
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "schemas",
        "relations",
        "routines",
        "default_acls",
    }:
        raise AlignmentError("la lecture des droits a une forme inattendue")
    return snapshot


def read_source(dsn: str) -> Snapshot:
    """Lecture seule de la base locale : la transaction est refusée si elle écrit."""
    if dsn.startswith("-"):
        raise AlignmentError("le DSN source ne peut pas commencer par un tiret")
    environment = {**os.environ, "PGOPTIONS": "-c default_transaction_read_only=on"}
    try:
        result = subprocess.run(  # noqa: S603 - arguments en liste, pas de shell
            ["psql", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", dsn, "-c", SNAPSHOT_SQL],  # noqa: S607 - psql du PATH
            capture_output=True,
            text=True,
            timeout=PSQL_TIMEOUT_SECONDS,
            check=False,
            env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AlignmentError(f"psql inutilisable : {type(error).__name__}") from error
    if result.returncode != 0:
        # La sortie d'erreur de psql peut citer la chaîne de connexion : on ne la relaie pas.
        raise AlignmentError("lecture de la base source impossible (psql a échoué)")
    return build_snapshot(parse_snapshot_output(result.stdout))


class ManagementApi:
    """POST /v1/projects/{ref}/database/query. Le jeton n'est ni affiché ni conservé dans repr."""

    def __init__(self, project_ref: str, token: str) -> None:
        if not PROJECT_REF_PATTERN.fullmatch(project_ref):
            raise AlignmentError("ESSAI_REF n'a pas la forme d'une référence de projet")
        if project_ref == FORBIDDEN_PROJECT_REF:
            raise AlignmentError("la prod n'est jamais une cible")
        self._url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
        self._token = token

    def __repr__(self) -> str:
        return "ManagementApi(<projet d'essai>)"

    def query(self, sql: str) -> object:
        request = urllib.request.Request(  # noqa: S310 - URL https fixe
            self._url,
            data=json.dumps({"query": sql}).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "popote-aligne-droits/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:  # noqa: S310 - URL https fixe
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read(500).decode("utf-8", errors="replace")
            raise AlignmentError(f"API de gestion : HTTP {error.code} {detail}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise AlignmentError(f"API de gestion injoignable : {type(error).__name__}") from error

    def read_snapshot(self) -> Snapshot:
        rows = self.query(SNAPSHOT_SQL)
        if not isinstance(rows, list) or len(rows) != 1 or "snapshot" not in rows[0]:
            raise AlignmentError("réponse inattendue à la lecture des droits")
        value = rows[0]["snapshot"]
        return build_snapshot(parse_snapshot_output(value if isinstance(value, str) else json.dumps(value)))


def read_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise AlignmentError(f"variable d'environnement absente : {name}")
    return value


def print_report(report: Report) -> None:
    counts = report.counts_by_kind
    print(f"écarts à corriger : {sum(counts.values())}")
    for kind, count in sorted(counts.items()):
        print(f"  {kind}: {count}")
    for title, divergences in (("hors périmètre (rapporté, non corrigé)", report.observed_only),):
        if divergences:
            print(f"{title} : {len(divergences)}")
            for divergence in divergences[:20]:
                print(f"  {divergence.securable.kind} {divergence.securable.reference} {divergence.role}")
    if report.missing_in_target:
        print(f"objets de la source absents de la cible (ignorés) : {len(report.missing_in_target)}")


def parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--appliquer", action="store_true", help="envoie le SQL à la cible")
    parser.add_argument("--source-dsn", default=os.environ.get("ALIGNE_SOURCE_DSN", DEFAULT_SOURCE_DSN))
    parser.add_argument("--sortie", type=Path, default=DEFAULT_OUTPUT_PATH, help="fichier SQL écrit")
    parser.add_argument("--taille-lot", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def run(arguments: argparse.Namespace) -> int:
    api = ManagementApi(read_environment("ESSAI_REF"), read_environment("SUPABASE_ESSAI_TOKEN"))
    source = read_source(arguments.source_dsn)
    report = compute_report(source, api.read_snapshot())
    statements = render_sql(report.to_fix)
    arguments.sortie.write_text(render_script(report, statements), encoding="utf-8")
    print_report(report)
    print(f"SQL écrit : {arguments.sortie} ({len(statements)} instructions)")
    if not arguments.appliquer:
        print("à blanc : rien n'est envoyé (--appliquer pour appliquer)")
        return 1 if report.to_fix else 0
    if statements:
        batch_count = apply_batches(statements, arguments.taille_lot, api.query)
        print(f"{batch_count} lot(s) appliqué(s)")
    remaining = compute_report(source, api.read_snapshot())
    print_report(remaining)
    return 1 if remaining.to_fix else 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_arguments(argv))
    except AlignmentError as error:
        print(f"erreur : {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
