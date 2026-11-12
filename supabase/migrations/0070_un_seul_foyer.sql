-- ═══════════════════════════════════════════════════════════════════════════
-- 0070 · Un foyer existe : on n'en crée plus un second par mégarde
--
-- Capturé : une personne authentifiée SANS foyer — Léa qui se connecte sans
-- ouvrir son lien d'invitation, ou après l'avoir laissé expirer — obtient
-- « Créer le foyer » en bouton PRINCIPAL, vert, pleine largeur. L'avertissement
-- « si quelqu'un t'a déjà invitée, ouvre plutôt le lien reçu par e-mail » est en
-- gris, EN DESSOUS. Un seul geste, et le couple se retrouve avec deux budgets
-- séparés, chacun croyant partager avec l'autre.
--
-- L'écran sait déjà dire « il te faut une invitation » — c'est la branche
-- fermée, et elle n'était atteignable par personne : le réglage est ouvert
-- depuis 0009 et rien ne le refermait jamais.
--
-- Cette instance est privée et sert un foyer. Dès qu'il existe, la création se
-- ferme : le seul chemin restant est le lien d'invitation, qui est le bon.
-- Rouvrir se fait à la main, d'une ligne, si un jour c'est voulu.
-- ═══════════════════════════════════════════════════════════════════════════

create or replace function public.tg_ferme_la_creation()
returns trigger language plpgsql security definer
set search_path = public, pg_temp as $$
begin
  /* ⚠️ Le rôle de SERVICE en est exempt : les bancs sèment des dizaines de
     foyers, et refermer la porte au premier rendrait tous les suivants
     impossibles. Ce qu'on ferme, c'est le chemin d'une PERSONNE. */
  if public.is_service_role() then return null; end if;
  update public.instance_setting
     set value = jsonb_build_object('enabled', false)
   where key = 'allow_household_creation';
  return null;
end $$;

drop trigger if exists tg_ferme_la_creation on public.household;
create trigger tg_ferme_la_creation
  after insert on public.household
  for each statement execute function public.tg_ferme_la_creation();

-- Et pour l'instance qui tourne déjà : un foyer existe, on referme.
update public.instance_setting
   set value = jsonb_build_object('enabled', false)
 where key = 'allow_household_creation'
   and exists (select 1 from public.household);
