-- Thauba arrive AVANT le déploiement : un second membre dans le foyer, sans compte à
-- elle. La migration doit tenir : les charges communes nées des enveloppes la
-- comptent, les personnelles restent au titulaire du seul compte personnel actif, et
-- les saisies d'amorce restent sans auteur.
with u as (
  insert into auth.users (id, aud, role, email)
  values (gen_random_uuid(), 'authenticated', 'authenticated', 'thauba@exemple.test')
  returning id
)
insert into public.user_profile (id, household_id, display_name, entre_le)
select u.id, (select h.id from public.household h), 'thauba', '2026-10-05' from u;

-- Son revenu, impair : sans lui, la clôture d'octobre attend (« thauba n'a pas encore
-- posé son revenu »).
insert into public.revenu (household_id, user_profile_id, net_mensuel_cents, valid_from)
select household_id, id, 210001, '2026-10-01' from public.user_profile where display_name = 'thauba';
