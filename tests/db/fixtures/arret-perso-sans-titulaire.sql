-- attendu : n'a pas de titulaire certain
-- Léa arrive avant le déploiement ET ouvre son compte personnel : deux comptes personnels
-- actifs, donc plus de titulaire certain pour les enveloppes personnelles. Sans arrêt, la
-- Pharmacie de Kamil serait aussi à Léa.
with u as (
  insert into auth.users (id, aud, role, email)
  values (gen_random_uuid(), 'authenticated', 'authenticated', 'lea@exemple.test')
  returning id
)
insert into public.user_profile (id, household_id, display_name, entre_le)
select u.id, (select h.id from public.household h), 'lea', '2026-10-05' from u;
insert into public.compte (household_id, nom, genre, titulaire_id)
select household_id, 'Léa CA', 'perso', id from public.user_profile where display_name = 'lea';
