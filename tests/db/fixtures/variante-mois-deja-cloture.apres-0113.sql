-- Septembre est DÉJÀ clôturé (la copie n'a aucune clôture) : ses lignes confirmées sont
-- gelées, rien à protéger, donc aucune saisie d'amorce — et rien de septembre ne bouge.
-- Chargée après 0113 (`cloture` n'existe pas avant).
-- On ne gèle que les lignes des charges mensuelles : une vraie clôture gèlerait aussi
-- celles des charges annuelles, et 0114 s'arrêterait (« ligne(s) réglée(s) ou confirmée(s)
-- d'une charge non mensuelle »), à raison : avant 0114 elles n'ont pas de façon.
update public.depense d set confirme_le = '2026-10-02T10:00:00+02:00'
from public.charge c
where c.id = d.charge_id and c.periodicite = 'mensuel'
  and d.mois = '2026-09-01' and d.confirme_le is null;

insert into public.cloture (household_id, mois, cloture_le, cloture_par)
select h.id, '2026-09-01', '2026-10-02T10:00:00+02:00',
       (select p.id from public.user_profile p where p.household_id = h.id limit 1)
from public.household h;
