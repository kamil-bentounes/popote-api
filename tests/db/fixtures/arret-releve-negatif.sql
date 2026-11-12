-- attendu : relevé(s) négatif(s)
-- Un relevé négatif : une facture le refuse.
insert into public.releve_annuel (household_id, charge_id, annee, reel_cents, ecart_cents, saisi_par)
select c.household_id, c.id, 2025, -100, -100,
       (select p.id from public.user_profile p where p.household_id = c.household_id limit 1)
from public.charge c where c.periodicite <> 'mensuel' order by c.libelle limit 1;
