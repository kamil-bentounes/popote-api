-- ═══════════════════════════════════════════════════════════════════════════
-- LE FRIGO : MANGER, JETER, RETIRER — ET LES REPAS QUI RÉCLAMENT LA PART
--
-- Une revue du frigo américain (chantier 2) a trouvé trois défauts de la même famille : l'écran
-- changeait l'état d'une barquette en plusieurs écritures, sans verrou, et oubliait que des REPAS la
-- réclament (`meal_slot.portion_id`).
--
--  1. « Jeter » passait la part à `jetee` sans lâcher le repas qui la réclamait : la case restait
--     pointée sur une part jetée, et « Je l'ai mangé » la faisait passer de `jetee` à `mangee`
--     (`tg_meal_slot_consomme` ne regardait pas l'état d'où elle venait).
--  2. Une barquette qu'on voulait seulement RETIRER (mangée en douce, perdue, donnée) n'avait plus de
--     geste : le vieil écran « Ce que j'ai » la supprimait, le frigo ne savait que la jeter, ce qui la
--     compte comme gaspillée.
--  3. « En manger une maintenant » lisait, libérait un autre repas, puis écrivait le sien : trois
--     requêtes. Deux membres qui mangeaient la dernière part libre en même temps pouvaient la réserver
--     deux fois ; et rien ne regardait POUR QUI est la part (`for_user_id`) — celle de Léa pouvait
--     être mangée par Kamil, avec les calories de Léa.
--
-- Trois remèdes, dans une base qui est seule à pouvoir verrouiller : le trigger ne consomme que ce qui
-- est encore là, et deux fonctions font chacune leur geste en UNE transaction.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. Le trigger ne ressuscite pas une part jetée ──────────────────────────
-- Comme 0028 (le garde-fou du foyer reste), mais une part `jetee` ou déjà `mangee` n'est jamais
-- consommée à nouveau : cocher « mangé » une case qui la pointe ne la change plus de mains.
create or replace function public.tg_meal_slot_consomme()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.state = 'mange' and new.portion_id is not null
     and (tg_op = 'INSERT' or old.state is distinct from 'mange') then
    update public.portion set state = 'mangee'
    where id = new.portion_id
      and state in ('au_frais', 'decongelee')   -- ⚠️ pas `jetee` : jetée, elle le reste
      and household_id = new.household_id;      -- ⚠️ le garde-fou (0028)
  end if;
  return null;
end $$;

-- ── 2. « En manger une maintenant » : une transaction, et la part de qui la mange ──
-- Le plat est désigné comme l'écran le regroupe : recette, libellé, lieu, état. La fonction :
--   · verrouille TOUTES les parts du plat (dans l'ordre de leur identifiant : pas d'interblocage) —
--     le second membre qui mange attend le premier, puis relit : une part déjà mangée n'est plus candidate ;
--   · si MA case de ce repas porte déjà une part de ce plat, c'est celle-là ;
--   · sinon elle choisit : d'abord celle qui est pour MOI (`for_user_id`), puis celle qui est pour
--     n'importe qui (`null`), celle d'un autre en dernier recours ; à destinataire égal, une part libre
--     (qu'aucun repas à venir ne réclame) avant une réclamée, la libre la plus pressée d'abord, la
--     réclamée par le repas le plus tardif d'abord ;
--   · lâche le repas qui la réclamait (il reste « prévu », sans barquette) et dit lequel ;
--   · pose MA case mangée ; la part est consommée par `tg_meal_slot_consomme`.
-- `p_day` est le jour LOCAL de l'appelant (la base ne connaît pas son fuseau) : « à venir » veut dire
-- ce jour-là ou après ; une réclamation d'avant est un repas passé que personne n'a noté, pas une
-- vraie réservation.
-- Rend {portion_id, libere: [{day, meal, user_profile_id}]}.
create or replace function public.mange_une_part(
  p_recipe uuid, p_label text, p_location text, p_state text,
  p_day date, p_meal text, p_eaten_at timestamptz
)
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  foyer uuid := public.current_household();
  moi uuid := auth.uid();
  maint timestamptz := public.maintenant();
  ma_id uuid;
  ma_etat text;
  ma_part uuid;
  choisie uuid;
  libere jsonb := '[]'::jsonb;
begin
  if foyer is null or moi is null then
    raise exception 'Aucun foyer.' using errcode = 'no_data_found';
  end if;
  if p_label is null or p_location not in ('frigo', 'congelateur') or p_state not in ('au_frais', 'decongelee') then
    raise exception 'Ce plat n’est pas lisible.' using errcode = 'invalid_parameter_value';
  end if;
  if p_day is null or p_meal is null or p_meal not in ('petit_dejeuner', 'dejeuner', 'diner', 'collation') then
    raise exception 'Il faut dire quel repas on mange.' using errcode = 'invalid_parameter_value';
  end if;
  if p_eaten_at is null or p_eaten_at > maint + interval '5 minutes' or p_eaten_at < maint - interval '2 days' then
    raise exception 'L’heure du repas n’est pas plausible.' using errcode = 'invalid_parameter_value';
  end if;

  -- Toutes les parts du plat, verrouillées dans un ordre fixe.
  perform 1 from public.portion p
  where p.household_id = foyer and p.state = p_state and p.location = p_location
    and p.label = p_label and p.recipe_id is not distinct from p_recipe
  order by p.id for update;

  -- Ma case de ce repas, verrouillée aussi.
  select s.id, s.state, s.portion_id into ma_id, ma_etat, ma_part
  from public.meal_slot s
  where s.household_id = foyer and s.user_profile_id = moi and s.day = p_day and s.meal = p_meal
  for update;
  if ma_id is not null and ma_etat = 'mange' then
    raise exception 'Ton repas de maintenant est déjà noté mangé : change-le depuis la semaine.'
      using errcode = 'object_not_in_prerequisite_state';
  end if;

  -- Celle que ma case porte déjà, si elle est de ce plat et encore là.
  if ma_part is not null then
    select p.id into choisie from public.portion p
    where p.id = ma_part and p.household_id = foyer and p.state = p_state and p.location = p_location
      and p.label = p_label and p.recipe_id is not distinct from p_recipe;
  end if;

  if choisie is null then
    select p.id into choisie
    from public.portion p
    left join lateral (
      select max(to_char(s.day, 'YYYY-MM-DD')
                 || array_position(array['petit_dejeuner', 'dejeuner', 'collation', 'diner'], s.meal)::text) as dernier
      from public.meal_slot s
      where s.portion_id = p.id and s.state = 'prevu' and s.day >= p_day and s.id is distinct from ma_id
    ) r on true
    where p.household_id = foyer and p.state = p_state and p.location = p_location
      and p.label = p_label and p.recipe_id is not distinct from p_recipe
    order by
      case when p.for_user_id = moi then 0 when p.for_user_id is null then 1 else 2 end,
      case when r.dernier is null then 0 else 1 end,
      case when r.dernier is null then p.expires_at end,
      r.dernier desc nulls last,
      p.id
    limit 1;
  end if;

  if choisie is null then
    raise exception 'Il n’y a plus de part de ce plat.' using errcode = 'no_data_found';
  end if;

  -- Le repas qui la réclamait la lâche.
  with l as (
    update public.meal_slot s set portion_id = null
    where s.portion_id = choisie and s.id is distinct from ma_id and s.state = 'prevu'
    returning s.day, s.meal, s.user_profile_id
  )
  select coalesce(jsonb_agg(jsonb_build_object('day', l.day, 'meal', l.meal, 'user_profile_id', l.user_profile_id)
                            order by l.day), '[]'::jsonb)
  into libere from l where l.day >= p_day;

  if ma_id is not null then
    update public.meal_slot set state = 'mange', eaten_at = p_eaten_at, portion_id = choisie where id = ma_id;
  else
    begin
      insert into public.meal_slot (household_id, user_profile_id, day, meal, state, eaten_at, portion_id)
      values (foyer, moi, p_day, p_meal, 'mange', p_eaten_at, choisie);
    exception when unique_violation then
      raise exception 'Ton repas de maintenant est déjà noté mangé : change-le depuis la semaine.'
        using errcode = 'object_not_in_prerequisite_state';
    end;
  end if;

  return jsonb_build_object('portion_id', choisie, 'libere', libere);
end $$;
revoke execute on function public.mange_une_part(uuid, text, text, text, date, text, timestamptz) from public, anon;
grant   execute on function public.mange_une_part(uuid, text, text, text, date, text, timestamptz) to authenticated;

-- ── 3. Jeter, ou simplement retirer : des parts, et les repas qui les réclamaient ──
-- `p_geste` :
--   · 'jeter'   → la part passe à `jetee` (elle compte comme gaspillée) ;
--   · 'retirer' → la part est SUPPRIMÉE, ni mangée ni jetée : une barquette mangée en douce, perdue ou
--                 donnée ne doit pas rester à l'écran, ni peser dans le gaspillage (c'est ce que
--                 faisait « Supprimer » dans l'ancien « Ce que j'ai »).
-- Dans les deux cas, les repas encore « prévus » qui réclamaient ces parts les lâchent (portion_id = null) :
-- une case ne reste jamais pointée sur une part jetée ou disparue. Ne touche que des parts encore là, du
-- foyer. Rend {n, libere: [{day, meal, user_profile_id}]} (les repas d'aujourd'hui ou à venir).
create or replace function public.ecarte_des_parts(p_ids uuid[], p_geste text, p_day date)
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  foyer uuid := public.current_household();
  ids uuid[];
  n integer;
  libere jsonb := '[]'::jsonb;
begin
  if foyer is null then
    raise exception 'Aucun foyer.' using errcode = 'no_data_found';
  end if;
  if p_geste is null or p_geste not in ('jeter', 'retirer') or p_day is null then
    raise exception 'Jeter ou retirer : il faut choisir.' using errcode = 'invalid_parameter_value';
  end if;
  if p_ids is null or cardinality(p_ids) = 0 or cardinality(p_ids) > 300 then
    raise exception 'Il faut dire quelles parts.' using errcode = 'invalid_parameter_value';
  end if;

  select array_agg(x.id) into ids from (
    select p.id from public.portion p
    where p.id = any(p_ids) and p.household_id = foyer and p.state in ('au_frais', 'decongelee')
    order by p.id for update
  ) x;
  n := coalesce(cardinality(ids), 0);
  if n = 0 then
    raise exception 'Ces parts ne sont plus là.' using errcode = 'no_data_found';
  end if;

  with l as (
    update public.meal_slot s set portion_id = null
    where s.portion_id = any(ids) and s.state = 'prevu'
    returning s.day, s.meal, s.user_profile_id
  )
  select coalesce(jsonb_agg(jsonb_build_object('day', l.day, 'meal', l.meal, 'user_profile_id', l.user_profile_id)
                            order by l.day), '[]'::jsonb)
  into libere from l where l.day >= p_day;

  if p_geste = 'jeter' then
    update public.portion set state = 'jetee' where id = any(ids);
  else
    delete from public.portion where id = any(ids);
  end if;

  return jsonb_build_object('n', n, 'libere', libere);
end $$;
revoke execute on function public.ecarte_des_parts(uuid[], text, date) from public, anon;
grant   execute on function public.ecarte_des_parts(uuid[], text, date) to authenticated;
