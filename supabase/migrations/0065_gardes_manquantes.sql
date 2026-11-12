-- ═══════════════════════════════════════════════════════════════════════════
-- DEUX GARDES RETIRÉES PAR INADVERTANCE, ET UN INVARIANT QUE LE CODE CONTREDIT
--
-- Un audit RLS a éprouvé les douze tables du budget avec de vrais jetons. La
-- frontière entre foyers est hermétique — vérifiée sur quatre verbes et douze
-- tables, plus chaque fonction appelée avec un identifiant d'en face. Ce qui a
-- lâché est ailleurs : deux gardes supprimées en croyant bien faire, et une
-- promesse écrite deux fois dans la documentation que le code ne tient pas.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1 · Les parts et les versements acceptaient n'importe quel identifiant ─
--
-- 0053 a retiré la clé étrangère de `depense_part.user_profile_id` — à raison :
-- une part figée est un fait comptable, elle doit survivre au départ de la
-- personne. Mais il a retiré dans la foulée `z_user_profile_id_meme_foyer`, au
-- motif que « le trigger ne peut plus s'appliquer à cette colonne ». C'est
-- faux : `tg_meme_foyer` lit `user_profile.household_id`, il n'a jamais eu
-- besoin de la clé étrangère.
--
-- Éprouvé : un membre pouvait attribuer une part — ou un versement d'épargne —
-- à l'identifiant du voisin, ou à un uuid inventé. Et `versement_epargne`
-- n'avait jamais eu de garde du tout.
--
-- Le trigger ne vérifie QUE ce qui existe : un identifiant qui ne désigne plus
-- personne passe, ce qui est exactement ce qu'on veut pour un fait comptable
-- dont le titulaire est parti.
create trigger z_user_profile_id_meme_foyer
  before insert or update on public.depense_part
  for each row execute function public.tg_meme_foyer('user_profile_id', 'user_profile');

create trigger z_user_profile_id_meme_foyer
  before insert or update on public.versement_epargne
  for each row execute function public.tg_meme_foyer('user_profile_id', 'user_profile');

-- ── 2 · Un versement d'épargne ne se pose qu'à son propre nom ─────────────
--
-- Éprouvé : Kamil posait un versement de −499,99 € au nom de Léa, et
-- supprimait les siens. `tg_versement_ancre` ne gardait que l'UPDATE, et rien
-- n'oblige à passer par un UPDATE. Comme le revenu, un versement se pose et se
-- retire par son titulaire ; le foyer le lit.
drop policy versement_epargne_insert on public.versement_epargne;
drop policy versement_epargne_update on public.versement_epargne;
drop policy versement_epargne_delete on public.versement_epargne;

create policy versement_epargne_insert on public.versement_epargne
  for insert to authenticated
  with check (household_id = public.current_household()
              and user_profile_id = auth.uid());
create policy versement_epargne_update on public.versement_epargne
  for update to authenticated
  using (user_profile_id = auth.uid())
  with check (household_id = public.current_household()
              and user_profile_id = auth.uid());
create policy versement_epargne_delete on public.versement_epargne
  for delete to authenticated
  using (user_profile_id = auth.uid());

-- ── 3 · Les parts d'une dépense ne se réécrivent pas à la main ────────────
--
-- Le contrôle différé ne regarde que la SOMME : supprimer les parts puis en
-- reposer d'autres permettait de passer de 600/400 à 1 centime contre
-- 999,99 €. La somme tombait juste, et le partage était réécrit.
--
-- Les parts appartiennent au calcul, pas à la saisie : elles se posent par
-- `ouvre_le_mois`, `refige_pour`, `confirme_la_depense` ou `regularise_annuel`,
-- toutes `security definer`. Personne n'a besoin de les écrire à la main.
drop policy depense_part_insert on public.depense_part;
drop policy depense_part_delete on public.depense_part;

comment on table public.depense_part is
  'La part de chacun, figée en centimes (D60). AUCUNE policy d''écriture : elles '
  'se posent par les fonctions de calcul, jamais à la main — le contrôle de somme '
  'ne regardant que le total, les reposer permettait de réécrire le partage.';

-- ── 4 · Une part figée survit VRAIMENT au départ de la personne ───────────
--
-- `docs/schema.md` le promet deux fois. Éprouvé : elle ne survivait pas. La
-- chaîne : supprimer son compte fait tomber ses revenus en cascade, ce qui
-- déclenche `tg_revenu_refige`, qui appelle `refige_pour`, qui supprime les
-- parts — puis `repartit_les_lignes` demande la clé à `parts_du_foyer`, dont
-- l'argument `foyer` n'est honoré que pour le rôle de service. L'appelant
-- n'étant plus rattaché à rien, elle rendait zéro ligne, et rien n'était
-- reposé. Le mois entier perdait ses parts, y compris celles de l'autre.
--
-- On ne refige donc PAS quand le déclencheur est une suppression : il n'y a
-- plus de clé à appliquer, et le passé n'a pas à être recalculé pour quelqu'un
-- qui s'en va.
create or replace function public.tg_refige_apres_cle()
returns trigger language plpgsql security definer set search_path = public as $$
declare foyer uuid;
        depuis date;
        m date;
begin
  /* Une SUPPRESSION ne refige rien. Elle survient quand un compte s'en va, et
     recalculer le passé à ce moment-là, c'est le perdre : les parts figées sont
     un fait comptable, elles doivent rester même sans personne en face. */
  if tg_op = 'DELETE' then return null; end if;

  foyer := new.household_id;
  depuis := new.valid_from;
  for m in
    select distinct d.mois from public.depense d
    where d.household_id = foyer and d.mois >= date_trunc('month', depuis)::date
    order by 1
  loop
    perform public.refige_pour(foyer, m);
  end loop;
  return null;
end $$;

-- ── 5 · On ne se retire pas seul d'une charge commune ─────────────────────
--
-- Éprouvé : un membre supprimait sa ligne de `charge_participant`, appelait le
-- refige, et le loyer passait entièrement sur l'autre — durablement, sans
-- trace. Se retirer d'une charge COMMUNE est une décision à deux ; sortir de sa
-- propre charge perso reste libre.
create or replace function public.tg_participant_commun()
returns trigger language plpgsql as $$
declare est_commune boolean;
begin
  if public.is_service_role() then return old; end if;
  select c.commun into est_commune from public.charge c where c.id = old.charge_id;
  if est_commune and old.user_profile_id = auth.uid() then
    raise exception 'On ne se retire pas seul d''une charge commune : change-la en charge personnelle, ou retire-la.'
      using errcode = 'check_violation';
  end if;
  return old;
end $$;

create trigger tg_participant_commun
  before delete on public.charge_participant
  for each row execute function public.tg_participant_commun();
