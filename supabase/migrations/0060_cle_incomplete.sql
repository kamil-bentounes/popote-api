-- ═══════════════════════════════════════════════════════════════════════════
-- UN MOIS QU'ON N'A PAS ENCORE VÉCU N'EST PAS DE L'HISTOIRE
--
-- D60 dit que la clé se fige sur la dépense, et c'est juste : une augmentation
-- de juin ne doit pas réécrire les partages de mars. Mais le figeage se faisait
-- à la GÉNÉRATION, c'est-à-dire à la première ouverture de l'écran — ce qui
-- produisait un piège fragile :
--
--   Léa arrive en octobre, quelqu'un ouvre le budget avant qu'elle ait saisi
--   son revenu, `parts_du_foyer` partage à parts égales faute de mieux, et
--   octobre reste à 50/50 pour toujours. Il aurait fallu se souvenir de saisir
--   les revenus AVANT de regarder l'écran.
--
-- La règle devient donc : la clé se fige quand le mois est VÉCU — dès qu'une
-- de ses lignes est confirmée, réglée, ou rapprochée d'un paiement. Tant que
-- tout n'y est que provision, compléter les revenus recalcule ce qui n'a
-- encore rien coûté à personne. Ce n'est pas réécrire l'histoire : c'est finir
-- de l'écrire.
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function public.refige_le_mois(le_mois date)
returns integer
language plpgsql security definer set search_path = public as $$
declare
  foyer uuid := public.current_household();
  debut_mois date := date_trunc('month', le_mois)::date;
  refaites integer := 0;
begin
  if foyer is null then return 0; end if;

  /* Un mois DÉJÀ VÉCU ne se retouche pas. Une seule ligne confirmée suffit à
     le clore : à partir de là, quelqu'un a payé quelque chose selon un partage
     qu'on ne peut plus lui changer. */
  /* ⚠️ Ce qui CLÔT un mois n'est pas `nature = 'connue'` : une charge fixe naît
     déjà connue — son montant ne fait aucun doute — et le mois se serait donc
     fermé à sa propre création. Ce qui le clôt, c'est qu'on y ait VÉCU : une
     ligne réglée, un montant réel saisi (donc différent du prévu), ou une
     écriture qui ne vient pas du générateur. */
  if exists (
    select 1 from public.depense d
    where d.household_id = foyer and d.mois = debut_mois
      and (d.regle_le is not null
           or d.source <> 'modele'
           or d.montant_cents is distinct from d.montant_prevu_cents)
  ) then
    return 0;
  end if;

  create temp table a_refaire (id uuid, charge_id uuid, montant_cents integer)
    on commit drop;

  insert into a_refaire
  select d.id, d.charge_id, d.montant_cents
  from public.depense d
  where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele'
    and d.charge_id is not null;

  get diagnostics refaites = row_count;
  if refaites = 0 then return 0; end if;

  /* L'ordre est imposé par le contrôle de somme différé, qui n'admet que zéro
     part ou un total exact : on retire, puis on repose. */
  delete from public.depense_part p
  where p.depense_id in (select id from a_refaire);

  with pesee as (
    select n.id as depense_id, n.montant_cents, cp.user_profile_id as uid,
           case when sum(p.part_bps) over (partition by n.id) = 0
                then 1 else p.part_bps end as poids
    from a_refaire n
    join public.charge c on c.id = n.charge_id
    join public.charge_participant cp on cp.charge_id = c.id
    join lateral public.parts_du_foyer(debut_mois, foyer, c.cle) p
      on p.user_profile_id = cp.user_profile_id
  ),
  total as (
    select depense_id, montant_cents, uid, poids,
           sum(poids) over (partition by depense_id) as poids_total
    from pesee
  ),
  brut as (
    select depense_id, uid, montant_cents, poids, poids_total,
           (montant_cents::bigint * poids / poids_total)::integer as cents,
           (poids::bigint * 10000 / poids_total)::integer as bps,
           row_number() over (partition by depense_id order by poids desc, uid) as rang
    from total where poids_total > 0
  ),
  reste as (
    select depense_id, montant_cents - sum(cents) as r
    from brut group by depense_id, montant_cents
  )
  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  select b.depense_id, b.uid, foyer,
         b.cents + case when b.rang = 1 then coalesce(r.r, 0) else 0 end,
         b.bps
  from brut b left join reste r on r.depense_id = b.depense_id;

  return refaites;
end $$;

comment on function public.refige_le_mois(date) is
  'Repose les parts d''un mois dont AUCUNE ligne n''a encore été confirmée ni '
  'réglée. Sert quand un revenu arrive après l''ouverture du mois : la clé se '
  'fige quand le mois est vécu, pas quand il est engendré.';

revoke execute on function public.refige_le_mois(date) from public, anon;
grant   execute on function public.refige_le_mois(date) to authenticated, service_role;

-- ── Le mois courant se recalcule quand un revenu ou une règle arrive ──────
--
-- Sans ça, il aurait fallu se souvenir de saisir les revenus AVANT de regarder
-- l'écran du budget — une règle qu'on n'apprend qu'en la ratant.
create or replace function public.tg_refige_apres_cle()
returns trigger language plpgsql security definer set search_path = public as $$
declare foyer uuid := coalesce(new.household_id, old.household_id);
        depuis date := coalesce(new.valid_from, old.valid_from);
        m date;
begin
  /* TOUS les mois ouverts à partir de la date d'effet, pas seulement celui-là.
     Un revenu daté de janvier vaut pour février, mars, et le mois courant :
     ne rafraîchir que janvier laissait figés tous les mois entre les deux — ce
     que le test a montré, et que je n'avais pas vu en l'écrivant. */
  for m in
    select distinct d.mois from public.depense d
    where d.household_id = foyer and d.mois >= date_trunc('month', depuis)::date
    order by 1
  loop
    perform public.refige_pour(foyer, m);
  end loop;
  return null;
end $$;

/* Une variante qui prend le foyer en paramètre : le trigger tourne pour le rôle
   qui écrit, mais `refige_le_mois` lit `current_household()`, qui vaut null
   quand un script agit. On duplique le corps plutôt que de relâcher le garde de
   la fonction publique. */
create or replace function public.refige_pour(foyer uuid, le_mois date)
returns void
language plpgsql security definer set search_path = public as $$
declare debut_mois date := date_trunc('month', le_mois)::date;
begin
  if foyer is null then return; end if;
  /* ⚠️ Ce qui CLÔT un mois n'est pas `nature = 'connue'` : une charge fixe naît
     déjà connue — son montant ne fait aucun doute — et le mois se serait donc
     fermé à sa propre création. Ce qui le clôt, c'est qu'on y ait VÉCU : une
     ligne réglée, un montant réel saisi (donc différent du prévu), ou une
     écriture qui ne vient pas du générateur. */
  if exists (
    select 1 from public.depense d
    where d.household_id = foyer and d.mois = debut_mois
      and (d.regle_le is not null
           or d.source <> 'modele'
           or d.montant_cents is distinct from d.montant_prevu_cents)
  ) then return; end if;

  delete from public.depense_part p
  where p.depense_id in (
    select d.id from public.depense d
    where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele');

  with a_refaire as (
    select d.id, d.charge_id, d.montant_cents from public.depense d
    where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele'
      and d.charge_id is not null
  ),
  pesee as (
    select n.id as depense_id, n.montant_cents, cp.user_profile_id as uid,
           case when sum(p.part_bps) over (partition by n.id) = 0
                then 1 else p.part_bps end as poids
    from a_refaire n
    join public.charge c on c.id = n.charge_id
    join public.charge_participant cp on cp.charge_id = c.id
    join lateral public.parts_du_foyer(debut_mois, foyer, c.cle) p
      on p.user_profile_id = cp.user_profile_id
  ),
  total as (
    select depense_id, montant_cents, uid, poids,
           sum(poids) over (partition by depense_id) as poids_total
    from pesee
  ),
  brut as (
    select depense_id, uid, montant_cents, poids, poids_total,
           (montant_cents::bigint * poids / poids_total)::integer as cents,
           (poids::bigint * 10000 / poids_total)::integer as bps,
           row_number() over (partition by depense_id order by poids desc, uid) as rang
    from total where poids_total > 0
  ),
  reste as (
    select depense_id, montant_cents - sum(cents) as r
    from brut group by depense_id, montant_cents
  )
  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  select b.depense_id, b.uid, foyer,
         b.cents + case when b.rang = 1 then coalesce(r.r, 0) else 0 end,
         b.bps
  from brut b left join reste r on r.depense_id = b.depense_id;
end $$;
revoke execute on function public.refige_pour(uuid, date) from public, anon, authenticated;

create trigger tg_revenu_refige after insert or update or delete on public.revenu
  for each row execute function public.tg_refige_apres_cle();
create trigger tg_regle_refige after insert or update or delete on public.regle_partage
  for each row execute function public.tg_refige_apres_cle();
