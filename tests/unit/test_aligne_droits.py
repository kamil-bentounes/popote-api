"""Tests de ops/aligne_droits.py : parsing des ACL, calcul des écarts, génération du SQL."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))

import aligne_droits as tool


def snapshot_of(
    *,
    relations: list[dict] | None = None,
    routines: list[dict] | None = None,
    default_acls: list[dict] | None = None,
    schemas: list[dict] | None = None,
) -> tool.Snapshot:
    return tool.build_snapshot(
        {
            "schemas": schemas
            if schemas is not None
            else [{"name": "public", "owner": "postgres", "acl": ["postgres=UC/postgres"]}],
            "relations": relations or [],
            "routines": routines or [],
            "default_acls": default_acls or [],
        }
    )


def table(name: str, acl: list[str], schema: str = "public", kind: str = "r") -> dict:
    return {"schema": schema, "name": name, "kind": kind, "owner": "postgres", "acl": acl}


FULL = "arwdDxtm"


class TestParsing:
    def test_aclitem_with_grantor(self) -> None:
        assert tool.split_aclitem("anon=arwdDxtm/postgres") == ("anon", "arwdDxtm")

    def test_empty_grantee_is_public(self) -> None:
        assert tool.split_aclitem("=X/postgres") == (tool.PUBLIC_ROLE, "X")

    def test_quoted_grantee(self) -> None:
        assert tool.split_aclitem('"odd=role"=r/postgres') == ("odd=role", "r")

    def test_grant_option_is_attached_to_the_preceding_privilege(self) -> None:
        assert tool.parse_privileges("ar*w") == {"a": False, "r": True, "w": False}

    def test_star_without_privilege_is_rejected(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.parse_privileges("*r")

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.split_aclitem("pas-un-aclitem")

    def test_only_tracked_roles_are_kept(self) -> None:
        acl = tool.parse_acl(["postgres=arwdDxtm/postgres", "supabase_admin=r/postgres", "anon=r/postgres"])
        assert acl == {"anon": {"r": False}}

    def test_grantors_are_merged(self) -> None:
        acl = tool.parse_acl(["anon=r/postgres", "anon=r*a/supabase_admin"])
        assert acl == {"anon": {"r": True, "a": False}}


class TestScope:
    def test_system_and_managed_schemas_are_excluded(self) -> None:
        for name in ("auth", "storage", "extensions", "supabase_functions", "pg_toast", "net", "vault"):
            assert not tool.is_user_schema(name)
        assert tool.is_user_schema("public")

    def test_only_schemas_present_on_both_sides(self) -> None:
        both = [{"name": "public", "owner": "postgres", "acl": []}]
        extra = [*both, {"name": "autre", "owner": "postgres", "acl": []}]
        assert tool.schemas_in_scope(snapshot_of(schemas=extra), snapshot_of(schemas=both)) == {"public"}


class TestDivergences:
    def test_equal_acls_give_no_divergence(self) -> None:
        acl = [f"anon={FULL}/postgres"]
        report = tool.compute_report(
            snapshot_of(relations=[table("t", acl)]), snapshot_of(relations=[table("t", acl)])
        )
        assert report.to_fix == []

    def test_missing_privileges_are_found_per_role(self) -> None:
        source = snapshot_of(
            relations=[table("t", [f"anon={FULL}/postgres", f"service_role={FULL}/postgres"])]
        )
        target = snapshot_of(relations=[table("t", ["anon=Dxtm/postgres", f"service_role={FULL}/postgres"])])
        report = tool.compute_report(source, target)
        assert [(d.role, d.source, d.target) for d in report.to_fix] == [
            ("anon", tool.parse_privileges(FULL), tool.parse_privileges("Dxtm"))
        ]

    def test_extra_privilege_on_target_is_a_divergence(self) -> None:
        source = snapshot_of(relations=[table("t", ["anon=r/postgres"])])
        target = snapshot_of(relations=[table("t", ["anon=ar/postgres"])])
        assert len(tool.compute_report(source, target).to_fix) == 1

    def test_counts_are_per_object_and_kind(self) -> None:
        source = snapshot_of(
            relations=[
                table("t", [f"anon={FULL}/postgres", f"authenticated={FULL}/postgres"]),
                table("v", ["anon=r/postgres"], kind="v"),
            ]
        )
        target = snapshot_of(relations=[table("t", []), table("v", [], kind="v")])
        assert tool.compute_report(source, target).counts_by_kind == {"table": 1, "view": 1}

    def test_public_divergence_is_reported_not_fixed(self) -> None:
        source = snapshot_of(relations=[table("t", ["=r/postgres"])])
        target = snapshot_of(relations=[table("t", [])])
        report = tool.compute_report(source, target)
        assert report.to_fix == []
        assert [d.role for d in report.observed_only] == [tool.PUBLIC_ROLE]

    def test_schema_compares_usage_only(self) -> None:
        source = snapshot_of(schemas=[{"name": "public", "owner": "postgres", "acl": ["anon=U/postgres"]}])
        target = snapshot_of(schemas=[{"name": "public", "owner": "postgres", "acl": ["anon=UC/postgres"]}])
        assert tool.compute_report(source, target).to_fix == []

    def test_object_missing_in_target_is_listed_not_fixed(self) -> None:
        report = tool.compute_report(snapshot_of(relations=[table("t", ["anon=r/postgres"])]), snapshot_of())
        assert report.to_fix == [] and len(report.missing_in_target) == 1

    def test_function_signature_is_the_key(self) -> None:
        def routine(signature: str, acl: list[str]) -> dict:
            return {"schema": "public", "signature": signature, "kind": "f", "owner": "postgres", "acl": acl}

        source = snapshot_of(
            routines=[routine("public.f(uuid)", ["anon=X/postgres"]), routine("public.f(uuid,integer)", [])]
        )
        target = snapshot_of(routines=[routine("public.f(uuid)", []), routine("public.f(uuid,integer)", [])])
        (divergence,) = tool.compute_report(source, target).to_fix
        assert divergence.securable.reference == "public.f(uuid)"

    def test_storage_is_reported_only_and_only_for_objects_we_own(self) -> None:
        storage_schema = {"name": "storage", "owner": "supabase_admin", "acl": []}
        ours = table("objets", ["anon=r/postgres"], schema="storage")
        theirs = {
            **table("buckets", ["anon=r/supabase_storage_admin"], schema="storage"),
            "owner": "supabase_storage_admin",
        }
        source = snapshot_of(schemas=[storage_schema], relations=[ours, theirs])
        target = snapshot_of(
            schemas=[storage_schema], relations=[table("objets", [], schema="storage"), {**theirs, "acl": []}]
        )
        report = tool.compute_report(source, target)
        assert report.to_fix == []
        assert [d.securable.reference for d in report.observed_only] == ['"storage"."objets"']

    def test_default_acl_only_for_postgres_owner(self) -> None:
        defaults = [
            {"schema": "public", "role": "postgres", "objtype": "r", "acl": [f"anon={FULL}/postgres"]},
            {
                "schema": "public",
                "role": "supabase_admin",
                "objtype": "r",
                "acl": [f"anon={FULL}/supabase_admin"],
            },
        ]
        source = snapshot_of(default_acls=defaults)
        report = tool.compute_report(source, snapshot_of())
        assert [d.securable.kind for d in report.to_fix] == ["default_acl_tables"]


class TestSql:
    def divergence(
        self, kind: str, reference: str, role: str, source: str, target: str = ""
    ) -> tool.Divergence:
        securable = tool.Securable(kind, "public", reference, "postgres", {})
        return tool.Divergence(securable, role, tool.parse_privileges(source), tool.parse_privileges(target))

    def test_revoke_comes_before_grant(self) -> None:
        statements = tool.render_divergence(self.divergence("table", '"public"."t"', "anon", "rD"))
        assert statements == [
            'REVOKE ALL ON TABLE "public"."t" FROM anon;',
            'GRANT SELECT, TRUNCATE ON TABLE "public"."t" TO anon;',
        ]

    def test_nothing_wanted_means_revoke_only(self) -> None:
        statements = tool.render_divergence(self.divergence("table", '"public"."t"', "anon", "", "r"))
        assert statements == ['REVOKE ALL ON TABLE "public"."t" FROM anon;']

    def test_function_keeps_its_full_signature(self) -> None:
        statements = tool.render_divergence(
            self.divergence("function", "public.f(uuid,integer)", "service_role", "X")
        )
        assert statements[1] == "GRANT EXECUTE ON FUNCTION public.f(uuid,integer) TO service_role;"

    def test_procedure_and_sequence_keywords(self) -> None:
        assert tool.render_divergence(self.divergence("procedure", "public.p()", "anon", "X"))[1].startswith(
            "GRANT EXECUTE ON PROCEDURE"
        )
        assert tool.render_divergence(self.divergence("sequence", '"public"."s"', "anon", "rwU"))[1] == (
            'GRANT SELECT, UPDATE, USAGE ON SEQUENCE "public"."s" TO anon;'
        )

    def test_grant_option_gets_its_own_statement(self) -> None:
        statements = tool.render_divergence(self.divergence("table", '"public"."t"', "anon", "ar*"))
        assert statements[1:] == [
            'GRANT INSERT ON TABLE "public"."t" TO anon;',
            'GRANT SELECT ON TABLE "public"."t" TO anon WITH GRANT OPTION;',
        ]

    def test_schema_revokes_usage_only(self) -> None:
        statements = tool.render_divergence(self.divergence("schema", '"public"', "anon", "U"))
        assert statements == [
            'REVOKE USAGE ON SCHEMA "public" FROM anon;',
            'GRANT USAGE ON SCHEMA "public" TO anon;',
        ]

    def test_default_acl_is_scoped_to_postgres_and_schema(self) -> None:
        statements = tool.render_divergence(self.divergence("default_acl_functions", '"public"', "anon", "X"))
        prefixe = 'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA "public"'
        assert statements == [
            f"{prefixe} REVOKE ALL ON FUNCTIONS FROM anon;",
            f"{prefixe} GRANT EXECUTE ON FUNCTIONS TO anon;",
        ]

    @pytest.mark.parametrize("role", ["postgres", "supabase_admin", "PUBLIC"])
    def test_unmanaged_roles_are_never_touched(self, role: str) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.render_divergence(self.divergence("table", '"public"."t"', role, "r"))

    def test_output_is_deterministic(self) -> None:
        a = self.divergence("table", '"public"."a"', "anon", "r")
        b = self.divergence("table", '"public"."b"', "anon", "r")
        assert tool.render_sql([b, a]) == tool.render_sql([a, b])

    def test_quote_identifier_escapes_quotes(self) -> None:
        assert tool.quote_identifier('a"b') == '"a""b"'


class TestBatches:
    def test_split_keeps_order_and_size(self) -> None:
        assert tool.split_batches(list("abcde"), 2) == [["a", "b"], ["c", "d"], ["e"]]

    def test_invalid_size(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.split_batches(["a"], 0)

    def test_each_batch_is_one_transaction(self) -> None:
        sent: list[str] = []
        count = tool.apply_batches(["A;", "B;", "C;"], 2, sent.append)
        assert count == 2
        assert sent == ["BEGIN;\nA;\nB;\nCOMMIT;", "BEGIN;\nC;\nCOMMIT;"]

    def test_failure_stops_at_the_failed_batch(self) -> None:
        sent: list[str] = []

        def execute(sql: str) -> None:
            sent.append(sql)
            if len(sent) == 2:
                raise tool.AlignmentError("refusé")

        with pytest.raises(tool.AlignmentError, match="lot 2/3"):
            tool.apply_batches(list("ABCDEF"), 2, execute)
        assert len(sent) == 2


class TestApi:
    def test_prod_is_refused(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.ManagementApi(tool.FORBIDDEN_PROJECT_REF, "jeton")

    def test_malformed_reference_is_refused(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.ManagementApi("../x", "jeton")

    def test_token_is_not_in_repr(self) -> None:
        assert "jeton-secret" not in repr(tool.ManagementApi("abcdefghijklmnopqrst", "jeton-secret"))

    def test_snapshot_output_shape_is_checked(self) -> None:
        with pytest.raises(tool.AlignmentError):
            tool.parse_snapshot_output('{"schemas": []}')
        with pytest.raises(tool.AlignmentError):
            tool.parse_snapshot_output("pas du json")
