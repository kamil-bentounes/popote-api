-- ═══════════════════════════════════════════════════════════════════════════
-- 0103 · Les arrivées : le premier revenu, la date d'entrée, le verrou
-- ═══════════════════════════════════════════════════════════════════════════

-- ── Le premier revenu d'un membre compte dès son arrivée ─────────────────
/* Choix de Kamil, le 01/10. Il remonte au mois d'`entre_le`, sans passer avant
   le mois qui suit la dernière clôture du foyer — on ne réécrit pas un mois
   clôturé. Léa arrive le 15/11 et pose son revenu le 02/12 : il vaut dès
   novembre, et `tg_revenu_refige` repartage novembre, encore ouvert. Sans cela,
   novembre n'aurait jamais de revenu pour elle, et la clôture l'attendrait pour
   toujours. Les revenus suivants prennent effet au mois de leur saisie. */
create or replace function public.tg_revenu_premier()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare arrivee date; apres_cloture date;
begin
  if exists (select 1 from public.revenu v where v.user_profile_id = new.user_profile_id) then
    return new;
  end if;
  select date_trunc('month', up.entre_le)::date into arrivee
  from public.user_profile up where up.id = new.user_profile_id;
  if arrivee is null then return new; end if;
  select (max(k.mois) + interval '1 month')::date into apres_cloture
  from public.cloture k where k.household_id = new.household_id;
  new.valid_from := least(new.valid_from, greatest(arrivee, coalesce(apres_cloture, arrivee)));
  return new;
end $$;
drop trigger if exists tg_revenu_premier on public.revenu;
create trigger tg_revenu_premier before insert on public.revenu
  for each row execute function public.tg_revenu_premier();

-- ── Un membre rejoint le foyer ─────────────────────────────────────────────
create or replace function public.tg_membre_rejoint_les_communes()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare m date; jusqua date;
begin
  /* Le verrou de SON foyer, AVANT la première écriture. L'insertion dans
     `charge_participant` tient KEY SHARE sur la charge : `retire_charge`, qui
     tenait le verrou, attendait de supprimer cette charge — interblocage
     reproduit le 01/10. La clé est `new.household_id` : sous la clé de service
     (l'invitation acceptée passe par elle), `current_household()` vaut NULL. */
  perform public.verrou_du_foyer(new.household_id);
  jusqua := public.mois_courant();

  insert into public.charge_participant (charge_id, user_profile_id, household_id)
  select c.id, new.id, c.household_id
  from public.charge c
  where c.household_id = new.household_id and c.commun and c.archive_le is null
  on conflict do nothing;

  /* Quelqu'un qui arrive avec une date passée rend éligibles des mois sans
     ligne : on les ouvre avant de refiger (0079). Les mois clôturés, eux, ne
     bougent pas : `ouvre_le_mois` et `refige_pour` s'arrêtent avant. */
  for m in
    select d.mois::date
    from generate_series(date_trunc('month', new.entre_le)::date, jusqua,
                         interval '1 month') as d(mois)
    order by 1
  loop
    perform public.ouvre_le_mois(m, new.household_id);
  end loop;

  for m in
    select distinct d.mois from public.depense d
    where d.household_id = new.household_id
      and d.mois >= date_trunc('month', new.entre_le)::date
    order by 1
  loop
    perform public.refige_pour(new.household_id, m);
  end loop;
  return null;
end $$;

-- ── La date d'entrée change ─────────────────────────────────────────────────
create or replace function public.tg_entre_le_refige()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare m date; depuis date; borne date; jusqua date; arrivee date; apres_cloture date;
begin
  if new.entre_le is not distinct from old.entre_le then return null; end if;
  perform public.verrou_du_foyer(new.household_id);

  /* Reculer son arrivée fait reculer son PREMIER revenu avec elle, comme à la pose
     (`tg_revenu_premier`) : Léa arrive le 01/10, pose son revenu en octobre, puis
     corrige son arrivée au 01/09. Sans revenu en septembre, le mois se partageait à
     parts égales et la clôture refusait (« Léa n'a pas encore posé son revenu »),
     sans qu'aucun écran permette de le poser : l'interface ne pose un revenu qu'à
     partir du mois courant. Un revenu ne se modifie pas (`tg_revenu_date_immuable`) :
     on en ajoute un, du même montant, à la nouvelle date — jamais avant le mois qui
     suit la dernière clôture.
     Seulement si ce revenu était ACCROCHÉ à l'ancienne arrivée, comme `tg_revenu_premier`
     l'accroche : un revenu posé bien après l'arrivée (celui de Kamil, depuis septembre,
     pour une arrivée de janvier) reste où il est, sans quoi corriger sa date d'un jour
     rendrait « suivis » des mois qu'il n'a jamais voulus.
     Seulement pour un GESTE de la personne (un jeton `authenticated`, donc un
     `auth.uid()`) : une amorce, une réparation en SQL ou la clé de service corrigent
     une date sans réécrire l'histoire des revenus. (`is_service_role()` ne suffit pas :
     sous `security definer`, `current_user` est le propriétaire.) */
  if new.entre_le < old.entre_le and auth.uid() is not null and not public.is_service_role() then
    arrivee := date_trunc('month', new.entre_le)::date;
    select (max(k.mois) + interval '1 month')::date into apres_cloture
    from public.cloture k where k.household_id = new.household_id;
    insert into public.revenu (household_id, user_profile_id, net_mensuel_cents, valid_from)
    select r.household_id, r.user_profile_id, r.net_mensuel_cents,
           greatest(arrivee, coalesce(apres_cloture, arrivee))
    from public.revenu r
    where r.user_profile_id = new.id
      and r.valid_from = (select min(v.valid_from) from public.revenu v
                          where v.user_profile_id = new.id)
      and r.valid_from <= greatest(date_trunc('month', old.entre_le)::date,
                                   coalesce(apres_cloture, date_trunc('month', old.entre_le)::date))
      and r.valid_from > greatest(arrivee, coalesce(apres_cloture, arrivee));
  end if;

  /* Seuls les mois ENTRE l'ancienne et la nouvelle date changent de partage. Il
     refigeait tous les mois depuis la plus ancienne : Léa partie le 03/11,
     corriger le 05/11 l'« entré le » de Kamil repartageait octobre — 1 678,53 €
     de communes sur lui seul — et effaçait les lignes perso de Léa. */
  depuis := date_trunc('month', least(new.entre_le, old.entre_le))::date;
  borne  := date_trunc('month', greatest(new.entre_le, old.entre_le))::date;
  jusqua := least(borne, public.mois_courant());

  /* D'ABORD ouvrir (0079) : reculer son entrée rend éligibles des mois qui n'ont
     jamais eu de ligne. */
  for m in
    select d.mois::date from generate_series(depuis, jusqua, interval '1 month') as d(mois)
    order by 1
  loop
    perform public.ouvre_le_mois(m, new.household_id);
  end loop;

  for m in
    select distinct d.mois from public.depense d
    where d.household_id = new.household_id and d.mois between depuis and borne
    order by 1
  loop
    perform public.refige_pour(new.household_id, m);
  end loop;
  return null;
end $$;
