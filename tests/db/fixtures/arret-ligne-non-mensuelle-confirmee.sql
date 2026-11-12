-- attendu : ligne(s) réglée(s) ou confirmée(s) d'une charge non mensuelle
-- Une ligne de septembre confirmée, d'une charge qui n'est pas mensuelle : elle
-- recevrait `mis_de_cote`, façon que rien n'a gardée pour elle.
update public.depense set confirme_le = '2026-09-20T10:00:00+02:00', nature = 'connue'
where id = (
  select d.id from public.depense d join public.charge c on c.id = d.charge_id
  where d.mois = '2026-09-01' and d.source = 'modele' and c.periodicite <> 'mensuel'
  order by c.libelle limit 1);
