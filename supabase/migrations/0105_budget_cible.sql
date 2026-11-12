-- ═══════════════════════════════════════════════════════════════════════════
-- 0105 · Ce qu'une année doit, et une seule fonction pour le poser (§ 4.4)
--
--   B      = Σ facture.montant_cents                      (charge, année)
--   soldee = exists releve_annuel                         (charge, année)
--   L      = les lignes `modele` de la charge, de façon `mis_de_cote`, qui ont
--            au moins une part, dans les mois suivis de l'année
--   Pl     = soldee ? releve_annuel.prevu_cents
--                   : Σ L + les provisions à venir des mois suivis
--   cible  = soldee ? B − Pl : greatest(0, B − Pl)
--   pose   = Σ des lignes d'ajustement                    (charge, année)
--   delta  = cible − pose
--
-- Pl se lit sur `depense`, pas par `provisions_de`, qui ne filtre ni la façon ni
-- le mois. Une ligne sans part n'a été mise de côté par personne. Une ligne
-- fixe d'avant un passage en mise de côté est de l'argent déjà payé :
-- l'assurance à 100 € par mois, clôturée en septembre et en octobre puis passée
-- à 1 200 € par an, ferait sinon rendre 200 € déjà versés à l'assureur.
--
-- Les fonctions de ce fichier, sauf `etat_de_l_annee`, sont INTERNES. Elles ne
-- lisent pas `current_household()` : `delete_my_account` les appelle après la
-- suppression du profil, quand il n'y a plus de foyer courant.
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function public.cible_de(la_charge uuid, annee integer,
                                           comme_soldee boolean default false)
returns table (b bigint, pl bigint, cible bigint, pose bigint, soldee boolean)
language sql stable security definer set search_path = public, pg_temp
as $$
  with c as (
    select ch.household_id as foyer, ch.mode, ch.montant_cents, ch.periodicite,
           ch.debut, ch.fin, ch.archive_le
    from public.charge ch where ch.id = la_charge
  ),
  r as (
    select ra.prevu_cents from public.releve_annuel ra
    where ra.charge_id = la_charge and ra.annee = cible_de.annee
  ),
  -- B : les factures, et elles seules (§ 4.3, l'invariant).
  factures as (
    select coalesce(sum(f.montant_cents), 0)::bigint as total
    from public.facture f where f.charge_id = la_charge and f.annee = cible_de.annee
  ),
  -- Les provisions faites : L.
  faites as (
    select coalesce(sum(d.montant_cents), 0)::bigint as total
    from public.depense d, c
    where d.charge_id = la_charge and d.source = 'modele' and d.facon = 'mis_de_cote'
      and extract(year from d.mois)::integer = cible_de.annee
      and exists (select 1 from public.depense_part p where p.depense_id = d.id)
      and public.mois_suivi(c.foyer, d.mois)
  ),
  /* Les provisions à venir : les mois suivis, non clôturés, sans ligne, que la
     charge ferait naître (le prédicat d'`ouvre_la_charge`). Pour un solde
     (`comme_soldee`), tous les mois que le solde matérialiserait ; sinon,
     seulement à partir du mois en cours. */
  a_venir as (
    select coalesce(sum(public.provision_mensuelle(c.montant_cents, c.periodicite)), 0)::bigint
           as total
    from c, generate_series(make_date(cible_de.annee, 1, 1), make_date(cible_de.annee, 12, 1),
                            interval '1 month') as m(mois)
    where c.mode = 'mis_de_cote'
      and c.archive_le is null
      and c.debut <= (m.mois + interval '1 month - 1 day')::date
      and (c.fin is null or c.fin >= m.mois::date)
      and m.mois::date >= '2000-01-01'::date
      and m.mois::date <= (current_date + interval '5 years')::date
      and (comme_soldee or m.mois::date >= public.mois_courant())
      and public.mois_suivi(c.foyer, m.mois::date)
      and not exists (select 1 from public.cloture k
                      where k.household_id = c.foyer and k.mois = m.mois::date)
      and not exists (select 1 from public.depense d
                      where d.charge_id = la_charge and d.source = 'modele'
                        and d.mois = m.mois::date)
      and exists (select 1 from public.charge_participant cp
                  join public.user_profile up on up.id = cp.user_profile_id
                  where cp.charge_id = la_charge
                    and up.entre_le <= (m.mois + interval '1 month - 1 day')::date)
  ),
  posees as (
    select coalesce(sum(d.montant_cents), 0)::bigint as total
    from public.depense d
    where d.charge_id = la_charge and d.source = 'manuel'
      and d.regularise_annee = cible_de.annee
  ),
  calcul as (
    select fa.total as b, po.total as pose,
           exists (select 1 from r) as soldee,
           coalesce((select prevu_cents from r), fp.total + av.total) as pl
    from factures fa, faites fp, a_venir av, posees po
  )
  select b, pl,
         case when soldee or comme_soldee then b - pl else greatest(0, b - pl) end,
         pose, soldee
  from calcul
$$;
revoke execute on function public.cible_de(uuid, integer, boolean) from public, anon, authenticated;

/*
 * Pose les parts d'un ajustement, au plus fort reste, selon des poids que
 * l'appelant a mis dans `poids_a_poser` (table temporaire). L'algorithme et le
 * départage de `regularise_annuel` (0064) : reproductible sans favoriser
 * personne. Des poids tous nuls se partagent à parts égales, comme dans
 * `repartit_les_lignes`. Rend le nombre de parts posées.
 */
create or replace function public.pose_les_parts(la_ligne uuid, foyer uuid, montant bigint)
returns integer
language plpgsql security definer set search_path = public, pg_temp
as $$
declare n integer;
begin
  insert into public.depense_part (depense_id, user_profile_id, household_id, part_cents, part_bps)
  with p0 as (
    select uid, poids, sum(poids) over () as total from poids_a_poser where poids >= 0
  ),
  p as (select uid, (case when total = 0 then 1 else poids end)::bigint as poids from p0),
  s as (select sum(poids)::bigint as t from p),
  brut as (
    select p.uid,
           abs(montant) * p.poids / s.t as base,
           (p.poids * 10000) / s.t as bps_base,
           row_number() over (order by (abs(montant) * p.poids) % s.t desc,
                                       md5(p.uid::text || la_ligne::text)) as rang,
           row_number() over (order by (p.poids * 10000) % s.t desc,
                                       md5(p.uid::text || la_ligne::text)) as rang_bps
    from p, s where s.t > 0 and p.poids > 0
  ),
  manque as (
    select abs(montant) - coalesce(sum(base), 0) as cents,
           10000 - coalesce(sum(bps_base), 0) as bps
    from brut
  )
  select la_ligne, b.uid, foyer,
         ((b.base + case when b.rang <= (select cents from manque) then 1 else 0 end)
          * case when montant < 0 then -1 else 1 end)::integer,
         (b.bps_base + case when b.rang_bps <= (select bps from manque) then 1 else 0 end)::integer
  from brut b;
  get diagnostics n = row_count;
  return n;
end $$;
revoke execute on function public.pose_les_parts(uuid, uuid, bigint) from public, anon, authenticated;

/*
 * Recale une année : pose `delta`, s'il n'est pas nul. Interne, appelée sous le
 * verrou du foyer (qu'elle ne prend pas). Plusieurs ajustements par
 * charge-année : chacun ne pose que ce qui manque, sous verrou.
 */
create or replace function public.recale_l_annee(la_charge uuid, annee integer,
                                                 mois_cible date default null)
returns void
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  foyer uuid; nom text; le_compte uuid; la_cle text;
  x record;
  delta bigint;
  mois_ajuste date;
  la_ligne uuid;
  presents bigint; tous bigint; negatifs integer;
begin
  select c.household_id, c.libelle, c.compte_id, c.cle into foyer, nom, le_compte, la_cle
  from public.charge c where c.id = la_charge;
  if foyer is null then
    raise exception 'Charge inconnue.' using errcode = 'no_data_found';
  end if;

  select * into x from public.cible_de(la_charge, annee, false);
  delta := x.cible - x.pose;
  -- Sans rien à répartir, il n'y a rien à refuser : les gardes ne jouent que si delta ≠ 0.
  if delta = 0 then return; end if;
  if abs(delta) > 100000000 then
    raise exception 'Écart hors des bornes raisonnables.' using errcode = 'check_violation';
  end if;

  /* Le mois que la clôture est en train de clôturer, sinon le mois en cours, qui
     n'est jamais clôturé (D78). Une clôture de décembre faite en janvier solde
     donc l'année EN DÉCEMBRE, et le reste de décembre la compte. */
  mois_ajuste := coalesce(date_trunc('month', mois_cible)::date, public.mois_courant());
  if exists (select 1 from public.cloture k
             where k.household_id = foyer and k.mois = mois_ajuste) then
    raise exception '% est déjà clôturé : l''écart n''a nulle part où aller.',
      initcap(public.nom_du_mois(mois_ajuste)) using errcode = 'check_violation';
  end if;

  /* Ce que chacun a porté sur L (la même définition que dans `cible_de`). */
  create temp table if not exists porte_par (uid uuid, cents bigint) on commit drop;
  delete from porte_par where true;
  insert into porte_par (uid, cents)
  select p.user_profile_id, sum(p.part_cents)::bigint
  from public.depense d join public.depense_part p on p.depense_id = d.id
  where d.charge_id = la_charge and d.source = 'modele' and d.facon = 'mis_de_cote'
    and extract(year from d.mois)::integer = annee
    and public.mois_suivi(foyer, d.mois)
  group by p.user_profile_id;

  select coalesce(sum(pp.cents) filter (where up.id is not null), 0),
         coalesce(sum(pp.cents), 0),
         count(*) filter (where up.id is not null and pp.cents < 0)
    into presents, tous, negatifs
  from porte_par pp
  left join public.user_profile up on up.id = pp.uid and up.household_id = foyer;

  -- Un mélange de signes reste refusé (0069) : la proportion n'existe pas.
  if negatifs > 0 then
    raise exception 'Les provisions de % ne vont pas toutes dans le même sens : un membre a porté un montant négatif. Corrige les mois concernés.', annee
      using errcode = 'check_violation';
  end if;

  /* L n'a été porté que par des membres partis, et l'argent revient : ce qu'ils
     avaient mis de côté est parti avec eux. L'Entretien perso de Léa, partie
     le 03/11 : la clôture de décembre rendait sinon 166,68 € à Kamil, qui ne les
     avait jamais mis de côté. Au solde, l'année est déjà marquée soldée : elle
     l'est donc sans ligne.
     MAIS ce que des ajustements ont déjà posé (`x.pose`) est de l'argent que le
     foyer présent a porté : le rendre est toujours permis. Sans cette borne, la
     facture que Kamil retirait après le départ de Léa laissait ses 116,66 €
     sur novembre. On ne rend donc que la part de `delta` qui défait du posé. */
  if presents <= 0 and tous > 0 and delta < 0 then
    delta := greatest(delta, -x.pose);
    if delta = 0 then return; end if;
  end if;

  insert into public.depense
    (household_id, charge_id, mois, libelle, montant_cents, nature, source, compte_id,
     regularise_annee)
  values (foyer, la_charge, mois_ajuste,
          /* 55 caractères : le suffixe en fait au plus 13, et `depense_libelle_check`
             s'arrête à 80 (0084). */
          left(nom, 55) || case when x.soldee then ' — solde ' else ' — facture ' end || annee,
          delta::integer, 'connue', 'manuel', le_compte, annee)
  returning id into la_ligne;

  create temp table if not exists poids_a_poser (uid uuid, poids bigint) on commit drop;
  delete from poids_a_poser where true;
  if presents > 0 then
    -- Selon ce que chacun a porté sur l'année (D62).
    insert into poids_a_poser
    select pp.uid, pp.cents from porte_par pp
    join public.user_profile up on up.id = pp.uid and up.household_id = foyer
    where pp.cents > 0;
  else
    /* Sans provision à suivre — rien de porté, comme une charge retirée dont les
       provisions sont parties : la ligne se répartit comme une ligne de la
       charge, aux participants présents ce mois-là, au poids du mois
       (`parts_du_mois` : la pesée de `repartit_les_lignes`). Sans participant
       présent, à tous les membres présents. Refuser ferait échouer le solde
       d'une charge retirée à chaque clôture. */
    insert into poids_a_poser
    with du_mois as (select * from public.parts_du_mois(foyer, mois_ajuste, la_cle)),
    participants as (
      select m.user_profile_id, m.part_bps from du_mois m
      where exists (select 1 from public.charge_participant cp
                    where cp.charge_id = la_charge and cp.user_profile_id = m.user_profile_id)
    )
    select user_profile_id, part_bps::bigint from participants
    union all
    select user_profile_id, part_bps::bigint from du_mois
    where not exists (select 1 from participants);
  end if;

  -- Un ajustement n'est jamais posé sans part.
  if public.pose_les_parts(la_ligne, foyer, delta) = 0 then
    raise exception 'Personne au foyer pour porter cet écart en %.', public.nom_du_mois(mois_ajuste)
      using errcode = 'check_violation';
  end if;
end $$;
revoke execute on function public.recale_l_annee(uuid, integer, date) from public, anon, authenticated;

/* Ce que la feuille « Facture mise de côté », la liste « Retirées, encore à
   régler » et la borne d'« Autre jour » lisent. `useProvisionsDe` disparaît :
   elle comptait les douze mois et ignorait `prevu_cents`. */
create or replace function public.etat_de_l_annee(la_charge uuid, annee integer)
returns jsonb
language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare foyer uuid := public.current_household(); x record;
begin
  if foyer is null or not exists (select 1 from public.charge c
                                  where c.id = la_charge and c.household_id = foyer) then
    raise exception 'Cette charge n''est pas celle de ton foyer.'
      using errcode = 'insufficient_privilege';
  end if;
  select * into x from public.cible_de(la_charge, annee, false);
  return jsonb_build_object('b', x.b, 'pl', x.pl, 'pose', x.pose, 'soldee', x.soldee,
                            'premier_mois_suivi', public.premier_mois_suivi(foyer));
end $$;
revoke execute on function public.etat_de_l_annee(uuid, integer) from public, anon;
grant execute on function public.etat_de_l_annee(uuid, integer) to authenticated, service_role;
