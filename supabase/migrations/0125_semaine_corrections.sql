-- ═══════════════════════════════════════════════════════════════════════════
-- 0125 · LA SEMAINE QU'ON CHOISIT : ce que la revue adverse du chantier 3 a trouvé
--
-- Une revue du chantier 3 (0123, l'écran « La semaine ») a trouvé cinq défauts de base. 0123 n'est pas
-- touchée : `choisir_un_repas` est redéfinie ici — son corps change, jamais sa signature.
--
--  1. M3 · UN REPÈRE CHOISI COMPTAIT DANS LE BILAN DÈS QU'IL ÉTAIT CHOISI. « Autre chose » (un restaurant, un
--     sandwich) pose un extra sur une case qui reste « prévue » : le bilan comptait donc le restaurant de
--     jeudi dès mardi, et rien ne le confirmait jamais. `meal_extra.planifie` distingue ce que la feuille de
--     choix a posé (vrai) de ce qu'on note après coup (« en plus » : faux, par défaut). Le bilan ne compte un
--     extra planifié que si sa case est mangée ou si son jour est passé.
--  2. M1 · « RETIRER » LE DERNIER EXTRA LAISSAIT UNE CASE VIDE. Une case « prévue », sans barquette ni extra,
--     restait en base ; l'écran la masquait et ne proposait plus le petit déjeuner ni la collation.
--     `retire_un_extra` retire l'extra ET la case qu'il laisse vide, en une transaction (la case est
--     verrouillée : un ajout concurrent attend, puis est compté).
--  3. M2 · AUCUNE GARDE DE PÉREMPTION. `choisir_un_repas` posait la barquette la plus pressée sans regarder si
--     elle serait encore bonne à l'heure du repas. Elle préfère maintenant celles qui le sont (petit déjeuner
--     8 h, déjeuner 12 h, collation 16 h, dîner 19 h, à Paris : les heures de `frigo.ts`), AVANT l'ordre « la
--     sienne, celle de personne, celle d'un autre » ; faute de mieux elle pose quand même une barquette qui
--     périme avant (le choix reste le sien) et le DIT : `perime_avant`.
--  4. L1 · `p_today` VENAIT DU CLIENT et servait à lâcher des réclamations (« un jour passé ne retient pas la
--     barquette »). Un `p_today` forgé lâchait les repas de la semaine. Il est borné à ±1 jour de la date de
--     Paris de la base (`aujourdhui()`, 0093), sinon refusé ; et les réclamations lâchées sont rendues
--     (`lachees`).
--  5. L2 · « Léa et Kamil a déjà mangé » : « ont » au pluriel, les prénoms dans un ordre stable
--     (alphabétique, puis l'identifiant).
--
-- Rend { poses: { <personne>: <barquette> },
--        liberees: [{ portion_id, recipe_id, label, location, state }],
--        lachees: [{ day, meal, user_profile_id }],
--        perime_avant: [{ user_profile_id, portion_id, expires_at }] }.
-- ═══════════════════════════════════════════════════════════════════════════

alter table public.meal_extra add column planifie boolean not null default false;
comment on column public.meal_extra.planifie is
  'Posé par la feuille de choix (« autre chose ») : ne compte dans le bilan que quand le repas est mangé ou passé.';

-- ── « Retirer » un extra : et la case qu'il laisse vide ─────────────────────
create or replace function public.retire_un_extra(p_id uuid)
returns jsonb
language plpgsql security invoker set search_path = public, pg_temp
as $$
declare
  foyer uuid := public.current_household();
  v_slot uuid;
  v_etat text;
  v_part uuid;
  restantes integer;
  retiree boolean := false;
begin
  if foyer is null then
    raise exception 'Aucun foyer.' using errcode = 'no_data_found';
  end if;
  select e.meal_slot_id into v_slot from public.meal_extra e where e.id = p_id and e.household_id = foyer;
  -- Déjà retiré (un double toucher, un autre téléphone) : rien à faire, ce n'est pas une erreur.
  if v_slot is null then
    return jsonb_build_object('extra', false, 'case', false);
  end if;

  -- La case d'abord (verrouillée) : un extra ajouté en même temps attend ici, puis est compté plus bas.
  select s.state, s.portion_id into v_etat, v_part
  from public.meal_slot s where s.id = v_slot and s.household_id = foyer for update;

  delete from public.meal_extra where id = p_id and household_id = foyer;
  select count(*) into restantes from public.meal_extra where meal_slot_id = v_slot;

  -- Une case « prévue », sans barquette ni extra, n'est ni un plat ni une réponse : elle s'en va avec le dernier.
  if restantes = 0 and v_etat = 'prevu' and v_part is null then
    delete from public.meal_slot where id = v_slot and household_id = foyer;
    retiree := true;
  end if;
  return jsonb_build_object('extra', true, 'case', retiree);
end $$;

revoke execute on function public.retire_un_extra(uuid) from public, anon;
grant   execute on function public.retire_un_extra(uuid) to authenticated;

-- ── Choisir un repas, avec une garde de péremption ──────────────────────────
create or replace function public.choisir_un_repas(
  p_day date, p_meal text, p_users uuid[], p_today date, p_choix jsonb
)
returns jsonb
language plpgsql security invoker set search_path = public, pg_temp
as $$
declare
  foyer uuid := public.current_household();
  users uuid[];
  u uuid;
  genre text := p_choix ->> 'type';
  v_recipe uuid;
  v_label text;
  v_loc text;
  v_state text;
  v_moment timestamptz;
  bonne boolean;
  passe int;
  pris uuid[] := '{}';
  poses jsonb := '{}'::jsonb;
  choisie uuid;
  anciens uuid[];
  noms text[];
  mange_par text;
  slot_id uuid;
  v_cycle uuid;
  libere jsonb;
  lachees jsonb := '[]'::jsonb;
  perime jsonb := '[]'::jsonb;
begin
  if foyer is null then
    raise exception 'Aucun foyer.' using errcode = 'no_data_found';
  end if;
  if p_day is null or p_today is null or p_meal is null
     or p_meal not in ('petit_dejeuner', 'dejeuner', 'diner', 'collation') then
    raise exception 'Il faut dire quel repas on choisit.' using errcode = 'invalid_parameter_value';
  end if;
  -- `p_today` est le jour LOCAL de l'appelant (la base ne connaît pas son fuseau) : à un jour près de celui de
  -- Paris. Au-delà, il ne sert qu'à lâcher les réclamations de repas qui ne sont pas passés.
  if abs(p_today - public.aujourdhui()) > 1 then
    raise exception 'La date de l’appareil n’est pas la bonne : le repas n’est pas choisi.'
      using errcode = 'invalid_parameter_value';
  end if;
  if p_day < p_today then
    raise exception 'Un repas d’hier ne se choisit plus : il se note mangé ou sauté.'
      using errcode = 'invalid_parameter_value';
  end if;
  if p_day > p_today + 62 then
    raise exception 'C’est trop loin : choisis un repas des prochaines semaines.'
      using errcode = 'invalid_parameter_value';
  end if;
  if genre is null or genre not in ('plat', 'repere', 'saute') then
    raise exception 'Il faut dire ce qu’on mange.' using errcode = 'invalid_parameter_value';
  end if;

  select array_agg(distinct x order by x) into users from unnest(p_users) x;
  if users is null or cardinality(users) = 0 or cardinality(users) > 8 then
    raise exception 'Il faut dire pour qui.' using errcode = 'invalid_parameter_value';
  end if;
  if (select count(*) from public.user_profile up
      where up.household_id = foyer and up.id = any(users)) <> cardinality(users) then
    raise exception 'Cette personne n’est pas du foyer.' using errcode = 'foreign_key_violation';
  end if;

  if genre = 'repere' then
    v_label := btrim(coalesce(p_choix ->> 'label', ''));
    if v_label = '' or length(v_label) > 80 then
      raise exception 'Il faut dire ce que c’est, en quelques mots.' using errcode = 'invalid_parameter_value';
    end if;
  end if;

  v_cycle := public.current_cycle();
  -- L'heure du repas, à Paris : celle de `frigo.ts` (`HEURE_DU_REPAS`).
  v_moment := (p_day::timestamp + make_interval(hours => case p_meal
                when 'petit_dejeuner' then 8 when 'dejeuner' then 12 when 'collation' then 16 else 19 end))
              at time zone 'Europe/Paris';

  -- ── Les barquettes du plat, verrouillées d'abord (dans un ordre fixe), puis les cases ───────────────
  if genre = 'plat' then
    v_recipe := nullif(p_choix ->> 'recipe_id', '')::uuid;
    v_label := p_choix ->> 'label';
    v_loc := p_choix ->> 'location';
    v_state := p_choix ->> 'state';
    if v_label is null or btrim(v_label) = '' or v_loc is null or v_loc not in ('frigo', 'congelateur')
       or v_state is null or v_state not in ('au_frais', 'decongelee') then
      raise exception 'Ce plat n’est pas lisible.' using errcode = 'invalid_parameter_value';
    end if;
    perform 1 from public.portion p
    where p.household_id = foyer and p.state = v_state and p.location = v_loc
      and p.label = v_label and p.recipe_id is not distinct from v_recipe
    order by p.id for update;
  end if;

  perform 1 from public.meal_slot s
  where s.household_id = foyer and s.day = p_day and s.meal = p_meal and s.user_profile_id = any(users)
  order by s.id for update;

  -- Un repas déjà noté mangé ne se change pas : « Kamil a déjà mangé », « Kamil et Léa ont déjà mangé ».
  select array_agg(coalesce(nullif(btrim(up.display_name), ''), 'Quelqu’un')
                   order by coalesce(nullif(btrim(up.display_name), ''), 'Quelqu’un'), up.id)
  into noms
  from public.meal_slot s join public.user_profile up on up.id = s.user_profile_id
  where s.household_id = foyer and s.day = p_day and s.meal = p_meal
    and s.user_profile_id = any(users) and s.state = 'mange';
  if noms is not null then
    mange_par := case when cardinality(noms) > 1
                   then array_to_string(noms[1:cardinality(noms) - 1], ', ') || ' et ' || noms[cardinality(noms)] || ' ont'
                   else noms[1] || ' a' end;
    raise exception '% déjà mangé ce repas : on ne le change plus.', mange_par
      using errcode = 'object_not_in_prerequisite_state';
  end if;

  -- Les barquettes que ces cases portent AVANT : ce qu'on lâchera si elles changent.
  select coalesce(array_agg(s.portion_id), '{}') into anciens
  from public.meal_slot s join public.portion p on p.id = s.portion_id
  where s.household_id = foyer and s.day = p_day and s.meal = p_meal and s.user_profile_id = any(users)
    and s.state = 'prevu' and p.household_id = foyer and p.state in ('au_frais', 'decongelee');

  -- Les extras d'une case qu'on remplace : une case SANS barquette (« autre chose ») les perd, ils étaient le
  -- repas. Une case AVEC barquette, qu'on change pour un autre plat, les garde : ce sont des en-plus. Quand le
  -- nouveau choix est « autre chose » ou « on saute », le repas change tout entier : plus rien ne reste.
  delete from public.meal_extra e
  using public.meal_slot s
  where e.meal_slot_id = s.id and s.household_id = foyer and s.day = p_day and s.meal = p_meal
    and s.user_profile_id = any(users)
    and (genre <> 'plat' or s.portion_id is null);

  -- ── Un plat : une barquette libre par personne, toutes personnes confondues, passe par passe ───────
  -- D'abord celles qui seront encore bonnes à l'heure du repas, ensuite — faute de mieux — les autres :
  -- on ne refuse jamais une barquette qui périme avant, on la pose en dernier et on le dit.
  if genre = 'plat' then
    foreach bonne in array array[true, false] loop
      foreach passe in array array[1, 2, 3, 4] loop
        foreach u in array users loop
          if poses ? u::text then continue; end if;
          select p.id into choisie
          from public.portion p
          where p.household_id = foyer and p.state = v_state and p.location = v_loc
            and p.label = v_label and p.recipe_id is not distinct from v_recipe
            and p.id <> all(pris)
            and (not bonne or p.expires_at >= v_moment)
            -- Libre : aucun repas à venir ne la réclame (hors les cases qu'on remplit en ce moment).
            and not exists (
              select 1 from public.meal_slot s
              where s.portion_id = p.id and s.state = 'prevu' and s.day >= p_today
                and not (s.day = p_day and s.meal = p_meal and s.user_profile_id = any(users)))
            and case passe
                  -- 1 · celle que la case de cette personne porte déjà (changer pour le même plat ne perd rien)
                  when 1 then p.id = (select s2.portion_id from public.meal_slot s2
                                      where s2.household_id = foyer and s2.day = p_day and s2.meal = p_meal
                                        and s2.user_profile_id = u and s2.state = 'prevu')
                  when 2 then p.for_user_id = u            -- 2 · la sienne
                  when 3 then p.for_user_id is null        -- 3 · celle de personne
                  else true                                -- 4 · celle d'un autre, en dernier recours
                end
          order by p.expires_at, p.id
          limit 1;
          if choisie is not null then
            pris := pris || choisie;
            poses := poses || jsonb_build_object(u::text, choisie);
          end if;
        end loop;
      end loop;
    end loop;

    if cardinality(pris) < cardinality(users) then
      raise exception 'Il n’y a pas assez de parts libres de ce plat pour %.',
        case when cardinality(users) > 1 then 'tout le monde' else 'cette personne' end
        using errcode = 'no_data_found';
    end if;

    -- Une réclamation d'un jour passé ne retient pas la barquette : elle la lâche (et on le rend).
    with l as (
      update public.meal_slot s set portion_id = null
      where s.portion_id = any(pris) and s.state = 'prevu'
        and not (s.day = p_day and s.meal = p_meal and s.user_profile_id = any(users))
      returning s.day, s.meal, s.user_profile_id
    )
    select coalesce(jsonb_agg(jsonb_build_object('day', l.day, 'meal', l.meal, 'user_profile_id', l.user_profile_id)
                              order by l.day, l.meal, l.user_profile_id), '[]'::jsonb)
    into lachees from l;

    -- Celles qui périment avant le repas : dites, jamais refusées.
    select coalesce(jsonb_agg(jsonb_build_object(
             'user_profile_id', k.key, 'portion_id', p.id, 'expires_at', p.expires_at)
             order by p.expires_at, k.key), '[]'::jsonb)
    into perime
    from jsonb_each_text(poses) k join public.portion p on p.id = k.value::uuid
    where p.expires_at < v_moment;
  end if;

  -- ── Les cases ────────────────────────────────────────────────────────────────────────────────────
  foreach u in array users loop
    insert into public.meal_slot (household_id, cycle_id, user_profile_id, day, meal, state, portion_id)
    values (foyer, v_cycle, u, p_day, p_meal,
            case when genre = 'saute' then 'saute' else 'prevu' end,
            case when genre = 'plat' then (poses ->> u::text)::uuid else null end)
    on conflict (household_id, user_profile_id, day, meal) do update
      set state = excluded.state, eaten_at = null, portion_id = excluded.portion_id
      where public.meal_slot.state <> 'mange'
    returning id into slot_id;
    if slot_id is null then
      raise exception 'Ce repas vient d’être noté mangé : on ne le change plus.'
        using errcode = 'object_not_in_prerequisite_state';
    end if;

    if genre = 'repere' then
      -- `planifie` : posé par la feuille, il ne compte au bilan que le repas mangé ou passé.
      insert into public.meal_extra (household_id, meal_slot_id, label, food_id, grams,
                                     kcal, protein_g, fiber_g, carb_g, fat_g, planifie)
      values (foyer, slot_id, v_label,
              nullif(p_choix ->> 'food_id', '')::uuid,
              nullif(p_choix ->> 'grams', '')::numeric,
              coalesce((p_choix ->> 'kcal')::numeric, 0),
              coalesce((p_choix ->> 'protein_g')::numeric, 0),
              coalesce((p_choix ->> 'fiber_g')::numeric, 0),
              coalesce((p_choix ->> 'carb_g')::numeric, 0),
              coalesce((p_choix ->> 'fat_g')::numeric, 0),
              true);
    end if;
  end loop;

  -- ── Ce qu'on a lâché : les anciennes barquettes que plus aucune case de cet appel ne porte ────────
  select coalesce(jsonb_agg(jsonb_build_object(
           'portion_id', p.id, 'recipe_id', p.recipe_id, 'label', p.label,
           'location', p.location, 'state', p.state) order by p.expires_at, p.id), '[]'::jsonb)
  into libere
  from public.portion p
  where p.id = any(anciens) and p.id <> all(pris)
    and p.household_id = foyer and p.state in ('au_frais', 'decongelee');

  return jsonb_build_object('poses', poses, 'liberees', libere, 'lachees', lachees, 'perime_avant', perime);
end $$;

revoke execute on function public.choisir_un_repas(date, text, uuid[], date, jsonb) from public, anon;
grant   execute on function public.choisir_un_repas(date, text, uuid[], date, jsonb) to authenticated;
