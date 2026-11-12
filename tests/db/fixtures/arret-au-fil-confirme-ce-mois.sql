-- attendu : ligne(s) au fil du mois confirmée(s) pour le mois en cours ou à venir
-- Une ligne au fil du mois confirmée en OCTOBRE (le mois du banc, déjà ouvert dans la
-- copie) avant le déploiement, à un montant impair : l'amorce serait datée du 31/10,
-- dans le futur, et les tickets déclarés ensuite s'y ajouteraient (800,01 + 20 = 820,01 €
-- au lieu du total du mois).
create temporary table la_ligne on commit drop as
  select d.id, d.household_id from public.depense d join public.charge c on c.id = d.charge_id
  where d.mois = '2026-10-01' and d.source = 'modele' and c.enveloppe_id is not null
    and d.confirme_le is null
  order by c.libelle limit 1;
create temporary table ses_parts on commit drop as
  select p.* from public.depense_part p where p.depense_id in (select id from la_ligne);
delete from public.depense_part where depense_id in (select id from la_ligne);
update public.depense set montant_cents = 80001, nature = 'connue', confirme_le = '2026-10-15T10:00:00+02:00'
 where id in (select id from la_ligne);
insert into public.depense_part (depense_id, user_profile_id, household_id, part_cents, part_bps)
select depense_id, user_profile_id, household_id, 80001, part_bps from ses_parts;
