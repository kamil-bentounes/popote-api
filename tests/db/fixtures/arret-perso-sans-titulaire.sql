-- attendu : n'a pas de titulaire certain
-- Thauba arrive avant le déploiement ET ouvre son compte personnel : deux comptes personnels
-- actifs, donc plus de titulaire certain pour les enveloppes personnelles. Sans arrêt, la
-- Pharmacie de Kamil serait aussi à Thauba.
with u as (
  insert into auth.users (id, aud, role, email)
  values (gen_random_uuid(), 'authenticated', 'authenticated', 'thauba@exemple.test')
  returning id
)
insert into public.user_profile (id, household_id, display_name, entre_le)
select u.id, (select h.id from public.household h), 'thauba', '2026-10-05' from u;
insert into public.compte (household_id, nom, genre, titulaire_id)
select household_id, 'Thauba CA', 'perso', id from public.user_profile where display_name = 'thauba';
