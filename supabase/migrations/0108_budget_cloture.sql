-- ═══════════════════════════════════════════════════════════════════════════
-- 0108 · Clôturer un mois (D78, § 4.5)
--
-- On ne clôture jamais le mois en cours : ses derniers jours ont encore des
-- dépenses. Clôturer le 27 fermait octobre quatre jours trop tôt : les courses
-- du 30 auraient été refusées. Un mois passé non clôturé se clôture quand on
-- veut. La clôture ne bloque jamais sur une ligne : une ligne sans réponse
-- garde son prévu, un solde qui refuse laisse son année ouverte.
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function public.cloture_le_mois(
  le_mois date,
  factures jsonb default '[]'::jsonb,       -- [{ "depense": uuid, "montant_cents": int }] : les montants MODIFIÉS
  rien uuid[] default '{}'::uuid[],         -- les charges au fil du mois basculées sur « Rien dépensé »
  mis_de_cote_cents integer default null,   -- null : « tout ce qui reste »
  la_poche uuid default null)
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  foyer uuid := public.current_household();
  moi uuid := auth.uid();
  m date := date_trunc('month', le_mois)::date;
  fin date := (date_trunc('month', le_mois) + interval '1 month - 1 day')::date;
  courant date;
  mon_revenu integer;
  absent text;
  k record;
  l record;
  non_soldees jsonb := '[]'::jsonb;
  la_cloture uuid;
  reste bigint;
  mis bigint;
  le_versement uuid;
begin
  if foyer is null or moi is null then
    raise exception 'Tu n''es dans aucun foyer.' using errcode = 'insufficient_privilege';
  end if;
  /* Le verrou EN PREMIER : tout ce qui suit — l'heure comprise — se lit après
     lui. Une saisie, une facture ou un revenu qui arrive pendant la clôture
     attend sa fin, puis la voit. */
  perform public.verrou_du_foyer(foyer);
  courant := public.mois_courant();

  -- ── Les gardes ──────────────────────────────────────────────────────────
  if m >= courant then
    raise exception 'On clôture % une fois fini, à partir du 1er %.',
      public.nom_du_mois(m), public.nom_du_mois((m + interval '1 month')::date)
      using errcode = 'check_violation';
  end if;
  if exists (select 1 from public.cloture c where c.household_id = foyer and c.mois = m) then
    raise exception '% est déjà clôturé.', initcap(public.nom_du_mois(m))
      using errcode = 'unique_violation';
  end if;
  /* Sans revenu, `reste_cents` serait NULL et la clôture échouerait sur une
     erreur brute. Cela garde aussi les mois d'avant Popote hors de toute
     clôture. */
  select v.net_mensuel_cents into mon_revenu
  from public.revenu v
  where v.user_profile_id = moi and v.household_id = foyer and v.valid_from <= fin
  order by v.valid_from desc limit 1;
  if mon_revenu is null then
    raise exception 'Ajoute ton revenu % pour clôturer %.', public.de_mois(m),
      public.nom_du_mois(m) using errcode = 'check_violation';
  end if;
  /* Chaque autre membre présent ce mois-là y a un revenu. Sans lui, le partage
     bascule à moitié-moitié (0064), et la clôture le figerait : une commune de
     1 000 € à 500/500 au lieu de 633,70/366,30 (choix de Kamil, le 01/10). Un
     membre parti ne compte pas : son revenu est parti avec lui. */
  select public.prenom_de(up.display_name) into absent
  from public.user_profile up
  where up.household_id = foyer and up.id <> moi and up.entre_le <= fin
    and not exists (select 1 from public.revenu v
                    where v.user_profile_id = up.id and v.household_id = foyer
                      and v.valid_from <= fin)
  order by up.created_at limit 1;
  if absent is not null then
    raise exception '% n''a pas encore posé son revenu : % attend.', absent, public.nom_du_mois(m)
      using errcode = 'check_violation';
  end if;

  /* ── D'abord, le mois à jour. Les lignes qui manquent naissent, avec leurs
     parts. Sans cela, octobre clôturé juste après la migration, sans avoir
     ouvert /budget, gardait 22 lignes et 3 898,20 € au lieu de 25 et
     4 008,20 € : 110 € de reste en trop. On ne refait PAS les parts des lignes
     existantes : un mois passé ne se repartage pas. À deux, Léa partie le
     03/11, refiger octobre le 05/11 mettait 1 678,53 € de communes sur Kamil
     seul. ── */
  perform public.ouvre_le_mois(m);

  /* ── 1 · Les années à solder, chacune dans son propre bloc. Si une garde
     refuse un solde, l'année reste ouverte, la clôture continue, et la charge
     entre dans `non_soldees`. La clôture suivante réessaie. ── */
  for k in select * from public.annees_a_solder(foyer, m) loop
    begin
      perform public.solde_l_annee(k.charge_id, k.annee, m);
    exception when others then
      non_soldees := non_soldees || jsonb_build_array(jsonb_build_object(
        'charge', k.charge_id, 'libelle', k.libelle, 'annee', k.annee, 'raison', sqlerrm));
    end;
  end loop;

  /* ── 2 · Les factures du mois : le montant modifié s'il y en a un, que la
     ligne soit validée ou non ; sinon le montant actuel si elle ne l'est pas ;
     sinon on n'y touche pas — une ligne validée par sa feuille garde son
     montant. Une ligne sans part n'est jamais recalculée : `confirme_la_ligne`
     la refuserait (0064), et une ligne anormale ne doit pas bloquer la
     clôture. Elle ne reçoit que le gel. ── */
  for l in
    select d.id, d.montant_cents, d.confirme_le,
           (select (e ->> 'montant_cents')::integer
              from jsonb_array_elements(coalesce(factures, '[]'::jsonb)) e
             where (e ->> 'depense')::uuid = d.id
             limit 1) as dit
    from public.depense d
    where d.household_id = foyer and d.mois = m and d.source = 'modele' and d.facon = 'facture'
      and exists (select 1 from public.depense_part p where p.depense_id = d.id)
  loop
    if l.dit is not null then
      perform public.confirme_la_ligne(l.id, l.dit);
    elsif l.confirme_le is null then
      perform public.confirme_la_ligne(l.id, l.montant_cents);
    end if;
  end loop;

  /* ── 3 · Les lignes au fil du mois : Σ des saisies s'il y en a ; 0 si la
     charge est dans `rien` ; sinon le prévu. Le résultat ne dépend que de ce
     que montre l'écran, jamais d'une confirmation antérieure : une reclôture
     refait le même calcul. Les lignes de septembre, confirmées avant la
     refonte, gardent leur montant grâce à la saisie d'amorce de 0114. ── */
  for l in
    select d.id, d.charge_id,
           coalesce(d.montant_prevu_cents, d.montant_cents) as prevu,
           (select count(*) from public.saisie s where s.depense_id = d.id) as nb,
           (select coalesce(sum(s.montant_cents), 0) from public.saisie s
             where s.depense_id = d.id) as saisi
    from public.depense d
    where d.household_id = foyer and d.mois = m and d.source = 'modele' and d.facon = 'au_fil'
      and exists (select 1 from public.depense_part p where p.depense_id = d.id)
  loop
    if l.nb > 0 then
      perform public.confirme_la_ligne(l.id, l.saisi::integer);
    elsif l.charge_id = any(coalesce(rien, '{}'::uuid[])) then
      perform public.confirme_la_ligne(l.id, 0);
    else
      perform public.confirme_la_ligne(l.id, l.prevu);
    end if;
  end loop;

  /* ── 4 · Le gel : chaque ligne du mois encore sans `confirme_le` le reçoit,
     sans changer ni son montant ni sa nature — les fixes, les mises de côté,
     les ajustements (ceux que l'étape 1 vient de poser compris), les lignes
     sans part. Ni `corrige_la_charge`, ni « Retirer », ni le client ne peuvent
     ensuite y toucher. ── */
  update public.depense d set confirme_le = public.maintenant()
  where d.household_id = foyer and d.mois = m and d.confirme_le is null;

  -- ── L'enregistrement ─────────────────────────────────────────────────────
  insert into public.cloture (household_id, mois, cloture_le, cloture_par)
  values (foyer, m, public.maintenant(), moi)
  returning id into la_cloture;

  /* Le reste se calcule EN BASE : le revenu du mois moins mes parts du mois,
     ajustements compris. */
  select mon_revenu - coalesce(sum(p.part_cents), 0) into reste
  from public.depense d join public.depense_part p on p.depense_id = d.id
  where d.household_id = foyer and d.mois = m and p.user_profile_id = moi;

  if mis_de_cote_cents is not null and mis_de_cote_cents < 0 then
    raise exception 'On ne met pas de côté un montant négatif.' using errcode = 'check_violation';
  end if;
  /* null : « tout ce qui reste », au centime. Sinon ramené au reste s'il le
     dépasse : à deux, la projection de l'écran peut différer d'un centime. */
  mis := least(coalesce(mis_de_cote_cents::bigint, greatest(reste, 0)), greatest(reste, 0));

  if mis > 0 then
    if la_poche is null or not exists (select 1 from public.poche_epargne pe
                                        where pe.id = la_poche and pe.household_id = foyer) then
      raise exception 'Choisis une poche d''épargne de ton foyer.' using errcode = 'check_violation';
    end if;
    /* Ramené à 0, pas de versement : la contrainte `montant_cents <> 0` (0054)
       ferait échouer toute la clôture. */
    insert into public.versement_epargne
      (household_id, poche_id, user_profile_id, montant_cents, motif, fait_le)
    values (foyer, la_poche, moi, mis::integer, 'balayage', public.aujourdhui())
    returning id into le_versement;
  end if;

  insert into public.cloture_choix
    (cloture_id, household_id, user_profile_id, reste_cents, mis_de_cote_cents, poche_id,
     versement_id)
  values (la_cloture, foyer, moi, reste::integer, mis::integer,
          case when mis > 0 then la_poche end, le_versement);

  return jsonb_build_object('cloture', la_cloture, 'non_soldees', non_soldees);
end $$;
revoke execute on function public.cloture_le_mois(date, jsonb, uuid[], integer, uuid) from public, anon;
grant execute on function public.cloture_le_mois(date, jsonb, uuid[], integer, uuid) to authenticated;
