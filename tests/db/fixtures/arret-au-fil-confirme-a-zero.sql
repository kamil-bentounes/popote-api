-- attendu : ligne(s) au fil du mois confirmée(s) à 0 € ou moins
-- Courses (au fil du mois : une enveloppe la sert) confirmée à 0 € en septembre,
-- ce que `confirme_la_ligne` permet. Une saisie d'amorce ne peut pas valoir 0 € :
-- sans elle, la clôture reconfirmerait la ligne à son prévu, et ce 0 € redeviendrait
-- 800 € à payer.
create temporary table la_ligne on commit drop as
  select d.id, d.household_id from public.depense d join public.charge c on c.id = d.charge_id
  where d.mois = '2026-09-01' and d.source = 'modele' and c.enveloppe_id is not null
    and d.confirme_le is not null
  order by c.libelle limit 1;
create temporary table ses_parts on commit drop as
  select p.* from public.depense_part p where p.depense_id in (select id from la_ligne);
delete from public.depense_part where depense_id in (select id from la_ligne);
update public.depense set montant_cents = 0
 where id in (select id from la_ligne);
insert into public.depense_part (depense_id, user_profile_id, household_id, part_cents, part_bps)
select depense_id, user_profile_id, household_id, 0, part_bps from ses_parts;
