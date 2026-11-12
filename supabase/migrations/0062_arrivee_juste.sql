-- ═══════════════════════════════════════════════════════════════════════════
-- L'ARRIVÉE DU SECOND MEMBRE, CORRIGÉE
--
-- Une revue a rejoué le scénario réel — Kamil configure seul en septembre,
-- Léa s'inscrit le 1er octobre — et a trouvé quatre défauts en base. Tous
-- portent sur le même moment : celui où quelqu'un entre.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1 · Le rattrapage de 0061 rendait communes les charges PERSO ──────────
--
-- Il disait : « commune si plus d'un participant, OU si le foyer ne compte
-- qu'une personne ». Or un foyer solo est précisément le cas de Kamil : ses
-- trois charges perso — mensualité de prêt, forfait mobile, salle de sport —
-- devenaient communes, et Léa y serait entrée à son inscription.
--
-- La production n'avait aucune charge au moment où c'est passé, donc rien à
-- réparer ; mais la règle, elle, doit être juste : ce qui dit « commune »,
-- c'est le CATALOGUE ou le nombre de participants, jamais la taille du foyer.
update public.charge c set commun = false
where commun
  and (select count(*) from public.charge_participant cp where cp.charge_id = c.id) <= 1
  and not exists (
    select 1 from public.catalogue_charge k
    where k.id = c.catalogue_id and k.portee = 'commun');

-- ── 2 · Le refige ne touchait QUE le mois courant ─────────────────────────
--
-- Kamil ouvre septembre ET octobre le 22 septembre ; Léa s'inscrit. Le
-- trigger refigeait septembre — et laissait octobre à 100 % Kamil, loyer
-- compris, définitivement. Rien ne le rattrapait, sauf si elle saisissait un
-- revenu par hasard.
create or replace function public.tg_membre_rejoint_les_communes()
returns trigger language plpgsql security definer set search_path = public as $$
declare m date;
begin
  insert into public.charge_participant (charge_id, user_profile_id, household_id)
  select c.id, new.id, c.household_id
  from public.charge c
  where c.household_id = new.household_id and c.commun and c.archive_le is null
  on conflict do nothing;

  /* TOUS les mois ouverts à partir de son entrée, pas seulement celui en cours.
     Un mois déjà vécu se défend tout seul : `refige_pour` refuse. */
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

-- ── 3 · Corriger sa date d'entrée ne changeait rien ───────────────────────
--
-- D71 promet qu'elle « se confirme, elle ne se devine pas ». Elle se devinait :
-- `entre_le` vaut `current_date` par défaut, si bien qu'une inscription le
-- 22 septembre faisait payer septembre à quelqu'un qui emménage le 1er octobre.
-- Et la corriger ensuite ne refigeait rien — il n'existait de trigger qu'à
-- l'insertion.
create or replace function public.tg_entre_le_refige()
returns trigger language plpgsql security definer set search_path = public as $$
declare m date;
        depuis date := least(new.entre_le, old.entre_le);
begin
  if new.entre_le is not distinct from old.entre_le then return null; end if;

  /* Depuis la PLUS ANCIENNE des deux dates : reculer son entrée doit la faire
     entrer dans des mois qu'elle ne portait pas, l'avancer doit l'en sortir.
     Les deux sens comptent. */
  for m in
    select distinct d.mois from public.depense d
    where d.household_id = new.household_id
      and d.mois >= date_trunc('month', depuis)::date
    order by 1
  loop
    perform public.refige_pour(new.household_id, m);
  end loop;
  return null;
end $$;

create trigger tg_profil_entre_le_refige
  after update of entre_le on public.user_profile
  for each row execute function public.tg_entre_le_refige();

-- ── 4 · Confirmer une dépense sans part la laissait sans part ─────────────
--
-- Le marqueur `confirme_le` était posé quand même, et `refige_pour` refusait
-- alors le mois entier pour toujours : une ligne que personne ne doit, gelée.
-- Le `greatest(n, 1)` censé couvrir le cas était du code mort — sans parts,
-- l'ensemble est vide et la division n'est jamais évaluée.
create or replace function public.confirme_la_depense(la_depense uuid, reel_cents integer)
returns void
language plpgsql security definer set search_path = public as $$
declare foyer uuid := public.current_household();
        ancien integer;
        combien integer;
begin
  select d.montant_cents into ancien from public.depense d
  where d.id = la_depense and d.household_id = foyer;
  if ancien is null then raise exception 'Dépense inconnue.'; end if;

  select count(*) into combien from public.depense_part where depense_id = la_depense;
  if combien = 0 then
    raise exception 'Cette dépense n''est partagée avec personne : il n''y a rien à confirmer.'
      using errcode = 'check_violation';
  end if;

  create temp table anciennes_parts on commit drop as
    select user_profile_id, part_cents, part_bps
    from public.depense_part where depense_id = la_depense;

  delete from public.depense_part where depense_id = la_depense;

  update public.depense
     set montant_cents = reel_cents, nature = 'connue', confirme_le = now()
   where id = la_depense;

  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  with total as (select coalesce(sum(part_cents), 0) as t, count(*) as n from anciennes_parts),
  brut as (
    select a.user_profile_id as uid, a.part_bps,
           case when (select t from total) = 0
                then reel_cents / (select n from total)
                else (reel_cents::bigint * a.part_cents / (select t from total))::integer
           end as cents,
           row_number() over (order by a.part_cents desc, a.user_profile_id) as rang
    from anciennes_parts a
  ),
  manque as (select reel_cents - coalesce(sum(cents), 0) as r from brut)
  select la_depense, b.uid, foyer,
         b.cents + case when b.rang = 1 then (select r from manque)::integer else 0 end,
         b.part_bps
  from brut b;

  drop table anciennes_parts;   -- deux confirmations dans une transaction
end $$;
revoke execute on function public.confirme_la_depense(uuid, integer) from public, anon;
grant   execute on function public.confirme_la_depense(uuid, integer) to authenticated, service_role;
