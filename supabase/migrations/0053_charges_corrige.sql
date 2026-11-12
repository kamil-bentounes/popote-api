-- ═══════════════════════════════════════════════════════════════════════════
-- CE QUE 0052 A LAISSÉ OUVERT
--
-- Sept défauts trouvés par une relecture à l'œil frais, tous reproduits en SQL.
-- Le premier est le pire : la fonctionnalité annoncée n'existait pas.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1 · `charge.cle` était une colonne MORTE ───────────────────────────────
--
-- 0052 annonçait « les courses au prorata mais Netflix à 50/50 », son
-- commentaire le promettait, le message de commit le répétait — et
-- `ouvre_le_mois` ne lisait jamais la colonne. Vérifié : deux charges
-- identiques, l'une `moitie` et l'autre non, donnaient exactement le même
-- partage. C'est la seule chose que l'utilisateur avait explicitement demandée.
--
-- `parts_du_foyer` accepte donc une clé forcée, et le générateur la lui passe
-- charge par charge.
drop function if exists public.parts_du_foyer(date, uuid);

create or replace function public.parts_du_foyer(
  le_mois date, le_foyer uuid default null, la_cle text default null)
returns table (user_profile_id uuid, part_bps integer)
language sql stable security definer set search_path = public as $$
  with bornes as (
    select (date_trunc('month', le_mois) + interval '1 month - 1 day')::date as fin,
           case when public.is_service_role() and le_foyer is not null
                then le_foyer else public.current_household() end as foyer
  ),
  regle as (
    /* La clé passée l'emporte sur celle du foyer : c'est ainsi qu'une charge
       impose la sienne sans qu'il faille une seconde table de règles. */
    select coalesce(la_cle, (
      select r.cle from public.regle_partage r, bornes b
      where r.household_id = b.foyer and r.valid_from <= b.fin
      order by r.valid_from desc limit 1
    ), 'prorata') as cle
  ),
  membres as (
    select p.id as uid,
           (select v.net_mensuel_cents
              from public.revenu v, bornes b2
             where v.user_profile_id = p.id
               and v.household_id = b2.foyer
               and v.valid_from <= b2.fin
             order by v.valid_from desc limit 1) as revenu_cents
    from public.user_profile p, bornes b
    where p.household_id = b.foyer and p.entre_le <= b.fin
  ),
  pesee as (
    select uid,
           case when (select cle from regle) = 'moitie'
                     or exists (select 1 from membres where revenu_cents is null)
                     or coalesce((select sum(revenu_cents) from membres), 0) = 0
                then 1::bigint else revenu_cents::bigint end as poids
    from membres
  ),
  somme as (select sum(poids) as total from pesee),
  brut as (
    select p.uid, p.poids, (p.poids * 10000 / s.total)::integer as bps
    from pesee p, somme s where s.total > 0
  ),
  reliquat as (select 10000 - coalesce(sum(bps), 0) as r from brut),
  ainee as (select uid from brut order by poids desc, uid limit 1)
  select b.uid,
         b.bps + case when b.uid = (select uid from ainee)
                      then (select r from reliquat) else 0 end
  from brut b
$$;
revoke execute on function public.parts_du_foyer(date, uuid, text) from public, anon;
grant   execute on function public.parts_du_foyer(date, uuid, text) to authenticated, service_role;

-- ── 2 · On ne supprime plus une charge qui a une histoire ──────────────────
--
-- Deux défauts d'un coup, et le même remède.
--
-- `on delete set null` émet un UPDATE sur `depense.charge_id`, que
-- `tg_depense_ancree` refusait : un membre ne pouvait PAS supprimer sa propre
-- charge. Le test ne le voyait pas, il supprimait en rôle de service, qui
-- court-circuite le trigger — le motif « test vide » du dépôt, encore.
--
-- Et l'unicité `(charge_id, mois)` étant `nulls distinct`, supprimer une charge
-- puis la recréer facturait le mois DEUX fois : les anciennes dépenses,
-- devenues orphelines, ne bloquaient plus rien.
--
-- Donc : `restrict`. On supprime une charge qui n'a rien produit ; celle qui a
-- une histoire s'ARCHIVE. C'est plus juste de toute façon — arrêter de payer
-- Netflix n'efface pas les douze mois où on l'a payé.
alter table public.charge add column archive_le timestamptz;
comment on column public.charge.archive_le is
  'Une charge qui a produit des dépenses ne se supprime pas : elle s''archive. '
  'Elle cesse alors d''engendrer, sans que son histoire disparaisse.';

alter table public.depense drop constraint depense_charge_id_fkey;
alter table public.depense add constraint depense_charge_id_fkey
  foreign key (charge_id) references public.charge(id) on delete restrict;

-- Dénouer le lien reste permis (une régularisation manuelle peut le faire),
-- le DÉPLACER non : c'est ça, l'ancrage.
create or replace function public.tg_depense_ancree()
returns trigger language plpgsql as $$
begin
  if public.is_service_role() then return new; end if;
  if new.mois is distinct from old.mois then
    raise exception 'Une dépense ne change pas de mois.' using errcode = 'check_violation';
  end if;
  if new.charge_id is distinct from old.charge_id and new.charge_id is not null then
    raise exception 'Une dépense ne change pas de charge.' using errcode = 'check_violation';
  end if;
  return new;
end $$;

-- ── 3 · La régularisation de D62 était impossible ──────────────────────────
--
-- `unique (charge_id, mois)` empêchait toute SECONDE ligne sur la même charge
-- et le même mois — c'est-à-dire exactement la ligne d'ajustement que D62
-- décrit. L'unicité ne doit porter que sur ce que le générateur produit.
alter table public.depense drop constraint depense_charge_id_mois_key;
create unique index depense_modele_unique
  on public.depense (charge_id, mois) where source = 'modele';

-- ── 4 · Le vocabulaire de D62 ──────────────────────────────────────────────
-- `provision`/`reelle` d'un côté, `estimee`/`connue` dans la décision : une
-- dérive de vocabulaire sur la colonne pivot de la régularisation se paie cher.
alter table public.depense drop constraint depense_nature_check;
update public.depense set nature = case nature when 'provision' then 'estimee'
                                               when 'reelle' then 'connue'
                                               else nature end;
alter table public.depense alter column nature set default 'estimee';
alter table public.depense add constraint depense_nature_check
  check (nature in ('estimee', 'connue'));

-- ── 5 · Les parts figées survivent au départ de leur personne ──────────────
--
-- `depense_part.user_profile_id` était en `on delete cascade` : le profil part,
-- les parts partent, et une dépense de 37 € n'en porte plus que 22. C'est mot
-- pour mot ce que 0051 déclarait impossible.
--
-- On retire donc la clé étrangère. Ce n'est pas un relâchement : une part figée
-- est un fait comptable, pas un pointeur. Elle désigne qui devait quoi à un
-- moment donné, et cela reste vrai quand la personne s'en va. Le rattachement
-- au foyer, lui, est conservé et reste contrôlé.
alter table public.depense_part drop constraint depense_part_user_profile_id_fkey;
comment on column public.depense_part.user_profile_id is
  'Sans clé étrangère, DÉLIBÉRÉMENT : une part figée est un fait comptable, pas '
  'un pointeur. Elle survit au départ de la personne — sinon supprimer un compte '
  'réécrirait tous les partages du passé (D60).';

-- Le trigger de rattachement ne peut plus s'appliquer à cette colonne.
drop trigger if exists z_user_profile_id_meme_foyer on public.depense_part;

-- ── 6 · La somme des parts ne pouvait PAS mentir ───────────────────────────
--
-- Trois chemins l'ouvraient : supprimer puis réinsérer les parts (le trigger
-- ne gardait que l'UPDATE, et son message invitait littéralement à ce
-- détour) ; créer une dépense manuelle avec une part d'un centime ; ou changer
-- `montant_cents` en laissant les parts d'avant.
--
-- Une vérification DIFFÉRÉE couvre les trois : elle se prononce au moment de
-- valider, donc une suppression suivie d'une réinsertion dans la même
-- transaction reste possible, et une somme fausse ne l'est jamais.
create or replace function public.tg_parts_somment()
returns trigger language plpgsql as $$
declare cible uuid := coalesce(new.depense_id, old.depense_id);
        montant integer;
        total   integer;
        combien integer;
begin
  select d.montant_cents into montant from public.depense d where d.id = cible;
  if montant is null then return null; end if;   -- la dépense a disparu

  select count(*), coalesce(sum(part_cents), 0) into combien, total
  from public.depense_part where depense_id = cible;

  /* Zéro part = pas encore répartie, ce qui est un état de passage légitime :
     PostgREST valide chaque requête dans sa propre transaction, et poser une
     dépense puis ses parts fait deux requêtes. Mais dès qu'il y a des parts,
     elles doivent recomposer le montant à l'euro près. */
  if combien > 0 and total <> montant then
    raise exception 'Les parts font % centimes pour une dépense de % : elles doivent recomposer le montant.',
      total, montant using errcode = 'check_violation';
  end if;
  return null;
end $$;

create constraint trigger tg_depense_part_somme
  after insert or update or delete on public.depense_part
  deferrable initially deferred
  for each row execute function public.tg_parts_somment();

-- Et du côté de la dépense : changer le montant sans reposer les parts.
create or replace function public.tg_depense_somme()
returns trigger language plpgsql as $$
declare total integer; combien integer;
begin
  select count(*), coalesce(sum(part_cents), 0) into combien, total
  from public.depense_part where depense_id = new.id;
  if combien > 0 and total <> new.montant_cents then
    raise exception 'Le montant passe à % centimes mais les parts en font % : repose-les.',
      new.montant_cents, total using errcode = 'check_violation';
  end if;
  return null;
end $$;

create constraint trigger tg_depense_montant_somme
  after update of montant_cents on public.depense
  deferrable initially deferred
  for each row execute function public.tg_depense_somme();

-- ── 7 · Les bornes, comme 0029 et 0051 les posent ailleurs ─────────────────
alter table public.depense add constraint depense_mois_borne
  check (mois between '2000-01-01'::date and (current_date + interval '5 years')::date);
alter table public.charge add constraint charge_fin_borne
  check (fin is null or fin <= (current_date + interval '30 years')::date);

-- ── 8 · Les index des clés étrangères à `set null` ─────────────────────────
-- Chacune provoquait un parcours complet de `depense` à la suppression d'un
-- compte ou d'un profil — ce que 0051 avait corrigé pour `compte.titulaire_id`.
create index depense_compte_idx   on public.depense (compte_id);
create index depense_paye_par_idx on public.depense (paye_par);
create index charge_catalogue_idx on public.charge (catalogue_id);

revoke execute on function public.provision_mensuelle(integer, text) from public, anon;
grant   execute on function public.provision_mensuelle(integer, text) to authenticated, service_role;

-- ═══ Le générateur, réécrit ════════════════════════════════════════════════
--
-- Quatre corrections dedans :
--
--  · il lit enfin `charge.cle`, par un `lateral` sur `parts_du_foyer` ;
--  · il ne laisse plus une dépense SANS AUCUNE PART. Un membre dont le revenu
--    saisi vaut zéro obtenait `part_bps = 0` ; sa charge perso engendrait la
--    dépense et aucune part, jamais rattrapée puisque la relance ne revoit pas
--    une dépense déjà créée. Quand les participants pèsent zéro à eux tous, on
--    partage entre eux à parts égales ;
--  · il fige le bps RENORMALISÉ, celui qui explique vraiment la part en
--    centimes. Il figeait celui du foyer : un payeur unique avait 100 % des
--    centimes et 5962 points de base, ce qui rendait la trace inutilisable ;
--  · il rend le nombre de DÉPENSES, pas de parts. `get diagnostics` suivait le
--    dernier `insert` : quatre dépenses annonçaient douze.
create or replace function public.ouvre_le_mois(le_mois date, le_foyer uuid default null)
returns integer
language plpgsql security definer set search_path = public as $$
declare
  foyer uuid := case when public.is_service_role() and le_foyer is not null
                     then le_foyer else public.current_household() end;
  debut_mois date := date_trunc('month', le_mois)::date;
  fin_mois   date := (date_trunc('month', le_mois) + interval '1 month - 1 day')::date;
  nees  integer := 0;
begin
  if foyer is null then return 0; end if;
  if debut_mois < '2000-01-01'::date
     or debut_mois > (current_date + interval '5 years')::date then
    raise exception 'Mois hors des bornes raisonnables : %', debut_mois
      using errcode = 'check_violation';
  end if;

  create temp table depenses_nees (id uuid, charge_id uuid, montant_cents integer)
    on commit drop;

  with actives as (
    select c.id, c.libelle, c.cle, c.compte_id, c.variable, c.periodicite,
           public.provision_mensuelle(c.montant_cents, c.periodicite) as du_mois
    from public.charge c
    where c.household_id = foyer
      and c.archive_le is null
      and c.debut <= fin_mois
      and (c.fin is null or c.fin >= debut_mois)
      and exists (select 1 from public.charge_participant cp where cp.charge_id = c.id)
  )
  insert into public.depense
    (household_id, charge_id, mois, libelle, montant_cents, nature, source, compte_id)
  select foyer, a.id, debut_mois, a.libelle, a.du_mois,
         /* Une charge variable ou non mensuelle n'est qu'une estimation tant
            que le relevé n'est pas arrivé (D62). Une charge mensuelle fixe est
            connue dès le premier jour. */
         case when a.variable or a.periodicite <> 'mensuel' then 'estimee' else 'connue' end,
         'modele', a.compte_id
  from actives a
  on conflict do nothing;

  get diagnostics nees = row_count;

  insert into depenses_nees (id, charge_id, montant_cents)
  select d.id, d.charge_id, d.montant_cents
  from public.depense d
  where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele'
    and not exists (select 1 from public.depense_part p where p.depense_id = d.id);

  with pesee as (
    select n.id as depense_id, n.montant_cents, cp.user_profile_id as uid,
           /* Les participants d'une charge ne sont pas tout le foyer : leurs
              parts ne font pas 10000 à elles seules, on renormalise sur leur
              propre total. Et s'ils pèsent zéro à eux tous, on partage entre
              eux à parts égales plutôt que de ne rien leur attribuer. */
           case when sum(p.part_bps) over (partition by n.id) = 0
                then 1 else p.part_bps end as poids
    from depenses_nees n
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
  from brut b left join reste r on r.depense_id = b.depense_id
  on conflict do nothing;

  return nees;
end $$;

comment on function public.ouvre_le_mois(date, uuid) is
  'Engendre les dépenses du mois à partir des charges actives et non archivées, '
  'et fige les parts en centimes. Idempotente. Rend le nombre de DÉPENSES créées. '
  '`le_foyer` n''est honoré que pour le rôle de service.';
