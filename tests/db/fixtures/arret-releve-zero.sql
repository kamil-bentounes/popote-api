-- attendu : relevé(s) à 0 € sans auteur
-- Un relevé à 0 € sans auteur : la trace de 0078, qui ne dit pas ce qui a été payé.
insert into public.releve_annuel (household_id, charge_id, annee, reel_cents, ecart_cents)
select c.household_id, c.id, 2025, 0, 0 from public.charge c
where c.periodicite <> 'mensuel' order by c.libelle limit 1;
