-- Ce que la copie n'a pas : une charge ARCHIVÉE, une ligne RÉGLÉE, une saisie et une
-- facture DÉJÀ LÀ. Chargée après 0113 (`saisie` et `facture` n'existent pas avant).
--
-- · « Courses » archivée : son enveloppe ne ressuscite pas en charge active ; sa ligne
--   de septembre, confirmée, reçoit quand même son amorce.
-- · Une ligne de Netflix réglée en septembre : la migration n'y touche pas.
-- · Une saisie déjà posée sur la ligne de Restaurants : pas d'amorce par-dessus.
-- · La facture née du relevé de la taxe foncière existe déjà : pas de doublon.
update public.charge set archive_le = '2026-10-10T10:00:00+02:00'
where libelle = 'Courses' and archive_le is null;

update public.depense set regle_le = '2026-09-05'
where libelle = 'Netflix' and mois = '2026-09-01';

/* La garde des saisies (0099) ne les accepte que sur une ligne déjà au fil du mois ;
   avant 0114, aucune ne l'est encore : on lui donne la façon que 0114 lui donnerait. */
update public.depense set facon = 'au_fil'
where libelle = 'Restaurants' and mois = '2026-09-01';

insert into public.saisie (id, household_id, depense_id, fait_le, montant_cents, source, saisi_par)
select gen_random_uuid(), d.household_id, d.id, '2026-09-12', 5001, 'manuel',
       (select p.id from public.user_profile p where p.household_id = d.household_id limit 1)
from public.depense d
where d.libelle = 'Restaurants' and d.mois = '2026-09-01';

insert into public.facture (id, household_id, charge_id, annee, paye_le, montant_cents,
                            origine, saisi_par, created_at)
select gen_random_uuid(), r.household_id, r.charge_id, r.annee, r.saisi_le::date,
       r.reel_cents, 'releve', r.saisi_par, r.saisi_le
from public.releve_annuel r join public.charge c on c.id = r.charge_id
where c.libelle = 'Taxe foncière';
