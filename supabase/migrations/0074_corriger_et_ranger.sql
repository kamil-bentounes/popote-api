-- ═══════════════════════════════════════════════════════════════════════════
-- 0074 · La date de départ se corrige, les comptes se rangent, et on sait qui
--
-- Trois manques que le parcours réel a mis au jour, et une décision.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1 · Qui a touché la charge, et quand ───────────────────────────────────
--
-- Le foyer partage tout : Léa peut corriger et archiver les charges perso de
-- Kamil, et c'est voulu — deux personnes, pas un conseil d'administration. Mais
-- une correction silencieuse sur la ligne de quelqu'un d'autre est une
-- surprise. On ne verrouille pas, on TRACE : l'écran dit qui a touché en
-- dernier, et ça suffit à ce que la question se pose à voix haute.
alter table public.charge
  add column if not exists modifie_par uuid references public.user_profile(id) on delete set null,
  add column if not exists modifie_le  timestamptz;

-- ── 2 · Corriger la DATE DE DÉPART ─────────────────────────────────────────
--
-- C'était le seul champ que l'écran signale comme dangereux — « remonte la
-- date, sinon le relevé annuel tombera d'un coup » — et le seul qu'on ne
-- pouvait plus toucher. Une taxe foncière posée avec le mauvais mois de départ
-- n'avait aucune issue : « Retirer » échoue sur la clé étrangère dès qu'un mois
-- est ouvert et retombe sur l'archivage.
--
-- Reculer la date fait NAÎTRE des mois : ils s'ouvriront à la visite, comme
-- n'importe quel mois passé. L'avancer en fait DISPARAÎTRE : les dépenses des
-- mois désormais hors de la période s'en vont — sauf celles qu'on a réglées ou
-- confirmées, qui sont un fait comptable.
create or replace function public.corrige_la_charge(
  la_charge            uuid,
  nouveau_libelle      text,
  nouveau_montant      integer,
  nouvelle_periodicite text,
  nouveau_debut        date default null)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  foyer   uuid := public.current_household();
  moi     uuid := auth.uid();
  m       date;
  debut_final date;
  refaits integer := 0;
begin
  if foyer is null then
    raise exception 'Tu n''es dans aucun foyer.' using errcode = 'insufficient_privilege';
  end if;

  /* ⚠️ `security definer` : le propriétaire contourne la RLS, donc la fonction
     revérifie elle-même que la charge est bien celle de l'appelant. */
  if not exists (select 1 from public.charge
                  where id = la_charge and household_id = foyer) then
    raise exception 'Cette charge n''est pas celle de ton foyer.'
      using errcode = 'insufficient_privilege';
  end if;

  if coalesce(btrim(nouveau_libelle), '') = '' then
    raise exception 'Une charge porte un nom.' using errcode = 'check_violation';
  end if;
  if length(btrim(nouveau_libelle)) > 80 then
    raise exception 'Ce nom est trop long.' using errcode = 'check_violation';
  end if;
  if nouveau_montant is null or nouveau_montant <= 0
     or nouveau_montant > 100000000 then
    raise exception 'Montant hors des bornes raisonnables.' using errcode = 'check_violation';
  end if;
  if nouvelle_periodicite not in ('mensuel', 'trimestriel', 'annuel') then
    raise exception 'Périodicité inconnue : %', nouvelle_periodicite
      using errcode = 'check_violation';
  end if;

  select coalesce(nouveau_debut, c.debut) into debut_final
  from public.charge c where c.id = la_charge;
  if debut_final < '2000-01-01'::date
     or debut_final > (current_date + interval '5 years')::date then
    raise exception 'Cette date de départ n''est pas raisonnable.'
      using errcode = 'check_violation';
  end if;

  update public.charge
     set libelle       = btrim(nouveau_libelle),
         montant_cents = nouveau_montant,
         periodicite   = nouvelle_periodicite,
         debut         = debut_final,
         modifie_par   = moi,
         modifie_le    = now()
   where id = la_charge;

  /* La charge ne court plus sur ces mois-là : leurs dépenses n'ont plus de
     raison d'être. Un mois réglé ou confirmé garde la sienne. */
  delete from public.depense d
   where d.charge_id = la_charge and d.household_id = foyer
     and d.source = 'modele'
     and d.regle_le is null and d.confirme_le is null
     and d.mois < date_trunc('month', debut_final)::date;

  create temp table if not exists mois_a_refaire (mois date) on commit drop;
  delete from mois_a_refaire where true;
  insert into mois_a_refaire (mois)
  select distinct d.mois
    from public.depense d
   where d.charge_id = la_charge and d.household_id = foyer
     and d.source = 'modele'
     and d.regle_le is null and d.confirme_le is null;

  delete from public.depense d
   where d.charge_id = la_charge and d.household_id = foyer
     and d.source = 'modele'
     and d.regle_le is null and d.confirme_le is null;

  for m in select mois from mois_a_refaire order by mois loop
    perform public.ouvre_le_mois(m, foyer);
    refaits := refaits + 1;
  end loop;

  return refaits;
end $$;

revoke execute on function public.corrige_la_charge(uuid, text, integer, text, date)
  from public, anon;
grant execute on function public.corrige_la_charge(uuid, text, integer, text, date)
  to authenticated, service_role;
drop function if exists public.corrige_la_charge(uuid, text, integer, text);

-- ── 3 · Ranger un compte ou une enveloppe ──────────────────────────────────
--
-- On pouvait en ajouter, jamais en retirer. « Compte commn » restait pour
-- toujours — dans la liste, et dans le menu « où débiter » de chaque charge.
-- Les deux colonnes `archive_le` existaient depuis le début ; aucun écran ne
-- les écrivait.
--
-- On ARCHIVE, on ne supprime pas : un compte a débité des mois qu'on relit. Et
-- on refuse d'archiver ce qui sert encore, en le disant — sinon la charge
-- pointerait vers un compte qui n'apparaît plus nulle part.
create or replace function public.range_le_compte(le_compte uuid, ranger boolean)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare foyer uuid := public.current_household(); combien integer; nom text;
begin
  if foyer is null then raise exception 'Aucun foyer.'; end if;
  select c.nom into nom from public.compte c
   where c.id = le_compte and c.household_id = foyer;
  if nom is null then
    raise exception 'Ce compte n''est pas celui de ton foyer.'
      using errcode = 'insufficient_privilege';
  end if;

  if ranger then
    select count(*) into combien from public.charge
     where compte_id = le_compte and archive_le is null;
    if combien > 0 then
      raise exception 'Ce compte porte encore % charge(s). Rattache-les ailleurs d''abord.', combien
        using errcode = 'check_violation';
    end if;
  end if;

  update public.compte set archive_le = case when ranger then now() else null end
   where id = le_compte;
end $$;

create or replace function public.range_l_enveloppe(l_enveloppe uuid, ranger boolean)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare foyer uuid := public.current_household(); combien integer; nom text;
begin
  if foyer is null then raise exception 'Aucun foyer.'; end if;
  select e.libelle into nom from public.enveloppe e
   where e.id = l_enveloppe and e.household_id = foyer;
  if nom is null then
    raise exception 'Cette enveloppe n''est pas celle de ton foyer.'
      using errcode = 'insufficient_privilege';
  end if;

  if ranger then
    select count(*) into combien from public.charge
     where enveloppe_id = l_enveloppe and archive_le is null;
    if combien > 0 then
      raise exception 'Cette enveloppe porte encore % charge(s). Détache-les d''abord.', combien
        using errcode = 'check_violation';
    end if;
  end if;

  update public.enveloppe set archive_le = case when ranger then now() else null end
   where id = l_enveloppe;
end $$;

revoke execute on function public.range_le_compte(uuid, boolean) from public, anon;
grant   execute on function public.range_le_compte(uuid, boolean) to authenticated, service_role;
revoke execute on function public.range_l_enveloppe(uuid, boolean) from public, anon;
grant   execute on function public.range_l_enveloppe(uuid, boolean) to authenticated, service_role;
