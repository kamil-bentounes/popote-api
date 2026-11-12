-- Un relevé positif sans auteur : celui d'un membre parti (RGPD). Il passe, et
-- devient une facture sans auteur.
insert into public.releve_annuel (household_id, charge_id, annee, reel_cents, ecart_cents)
select c.household_id, c.id, 2025, 145000, 0 from public.charge c
where c.periodicite <> 'mensuel' order by c.libelle limit 1;
