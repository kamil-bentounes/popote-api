-- attendu : ligne(s) « modele » sans charge
-- Une ligne modèle dont la charge n'existe plus (`charge_id` null) : la migration ne
-- peut pas lui donner de façon, et `depense_modele_a_une_facon` ferait échouer la
-- transaction entière, sans un mot sur la ligne coupable.
insert into public.depense (household_id, charge_id, mois, libelle, montant_cents, nature, source)
select id, null, '2026-10-01', 'Ligne sans charge', 12345, 'estimee', 'modele'
from public.household;
