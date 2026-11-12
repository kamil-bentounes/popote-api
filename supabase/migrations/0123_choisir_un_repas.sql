-- ═══════════════════════════════════════════════════════════════════════════
-- 0123 · LA SEMAINE QU'ON CHOISIT : un repas choisi, ou changé, en UNE transaction
--
-- Kamil choisit ce qu'il mange chaque jour. Le chantier 1 a retiré la distribution automatique de la fin
-- de la session ; c'est l'écran « La semaine » qui la remplace, repas par repas. Choisir un plat pour
-- « vous deux » touche plusieurs lignes : une case par personne, la barquette de chacune, l'ancienne
-- barquette qu'on lâche, des extras qui n'ont plus de sens. Écrit côté client, cela faisait quatre ou cinq
-- requêtes sans verrou : deux téléphones qui choisissaient les dernières lasagnes en même temps les
-- réservaient deux fois.
--
-- `choisir_un_repas(jour, repas, personnes, aujourd'hui, choix)` fait tout, ou rien :
--
--   · `choix.type = 'plat'`   : un plat du frigo ou du congélateur, désigné comme l'écran le regroupe
--                               (recette, libellé, lieu, état). Une barquette LIBRE du plat est posée dans la
--                               case de CHAQUE personne visée ;
--   · `choix.type = 'repere'` : autre chose, sans barquette (restaurant, sandwich, un yaourt…) : la case reste
--                               « prévue », sans barquette, et porte un extra qui dit quoi et combien ;
--   · `choix.type = 'saute'`  : on saute ce repas (« sauté » est une réponse, pas un trou : D33).
--
-- Ce que la fonction garantit :
--
--   · les barquettes du plat sont VERROUILLÉES (`for update`, dans l'ordre de leur identifiant : pas
--     d'interblocage, et le second appel attend le premier puis relit). Jamais la même barquette dans
--     deux cases ;
--   · une barquette n'est candidate que si elle est encore là (au frais ou décongelée), du foyer, et libre :
--     aucun repas à venir ne la réclame, sauf les cases qu'on est en train de remplir (la barquette d'une
--     case qu'on re-choisit reste candidate : changer pour le même plat ne perd rien) ;
--   · pour chaque personne, dans cet ordre : la barquette que sa case porte déjà, puis une barquette POUR
--     ELLE (`for_user_id`), puis une pour personne (`for_user_id` nul), puis celle d'un autre en dernier
--     recours ; à égalité, la plus pressée d'abord. Les passes se font toutes personnes confondues : la
--     barquette de Léa ne part pas chez Kamil tant qu'il en reste une pour Kamil ;
--   · pas assez de barquettes libres pour tout le monde : rien n'est écrit, on le dit ;
--   · l'ancienne barquette d'une case qu'on change est LÂCHÉE (la case ne la porte plus : elle est libre pour
--     un autre jour) et rendue à l'écran, qui dit où elle retourne (frigo : « libre pour un autre jour »,
--     congélateur : « reste au congélateur ») ;
--   · une case déjà mangée n'est jamais touchée : on refuse, on dit qui ;
--   · une réclamation d'un jour PASSÉ (un repas que personne n'a noté) ne retient pas la barquette : elle est
--     lâchée aussi — jamais la même barquette dans deux cases ;
--   · quand une case sans barquette (« autre chose ») est remplacée, ses extras s'en vont avec : ils étaient
--     le repas, pas un en-plus. Sur une case avec barquette, les extras restent (ce sont des en-plus).
--
-- `security invoker` : la RLS du foyer s'applique à chaque ligne lue ou écrite, et les gardes de rattachement
-- (`tg_meme_foyer`) aussi — une barquette ou une personne d'un autre foyer est invisible, donc refusée. La
-- fonction ne lit jamais `current_user` : rien ne dépend de l'identité du propriétaire (voir 0122, 0120).
-- `p_aujourdhui` est le jour LOCAL de l'appelant : la base ne connaît pas son fuseau. Rend
-- { poses: { <personne>: <barquette> }, liberees: [{ portion_id, recipe_id, label, location, state }] }.
-- ═══════════════════════════════════════════════════════════════════════════

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
  passe int;
  pris uuid[] := '{}';
  poses jsonb := '{}'::jsonb;
  choisie uuid;
  anciens uuid[];
  mange_par text;
  slot_id uuid;
  v_cycle uuid;
  libere jsonb;
begin
  if foyer is null then
    raise exception 'Aucun foyer.' using errcode = 'no_data_found';
  end if;
  if p_day is null or p_today is null or p_meal is null
     or p_meal not in ('petit_dejeuner', 'dejeuner', 'diner', 'collation') then
    raise exception 'Il faut dire quel repas on choisit.' using errcode = 'invalid_parameter_value';
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

  -- Un repas déjà noté mangé ne se change pas.
  select string_agg(coalesce(nullif(btrim(up.display_name), ''), 'Quelqu’un'), ' et ' order by up.id)
  into mange_par
  from public.meal_slot s join public.user_profile up on up.id = s.user_profile_id
  where s.household_id = foyer and s.day = p_day and s.meal = p_meal
    and s.user_profile_id = any(users) and s.state = 'mange';
  if mange_par is not null then
    raise exception '% a déjà mangé ce repas : on ne le change plus.', mange_par
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
  if genre = 'plat' then
    foreach passe in array array[1, 2, 3, 4] loop
      foreach u in array users loop
        if poses ? u::text then continue; end if;
        select p.id into choisie
        from public.portion p
        where p.household_id = foyer and p.state = v_state and p.location = v_loc
          and p.label = v_label and p.recipe_id is not distinct from v_recipe
          and p.id <> all(pris)
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

    if cardinality(pris) < cardinality(users) then
      raise exception 'Il n’y a pas assez de parts libres de ce plat pour %.',
        case when cardinality(users) > 1 then 'tout le monde' else 'cette personne' end
        using errcode = 'no_data_found';
    end if;

    -- Une réclamation d'un jour passé ne retient pas la barquette : elle la lâche.
    update public.meal_slot s set portion_id = null
    where s.portion_id = any(pris) and s.state = 'prevu'
      and not (s.day = p_day and s.meal = p_meal and s.user_profile_id = any(users));
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
      insert into public.meal_extra (household_id, meal_slot_id, label, food_id, grams,
                                     kcal, protein_g, fiber_g, carb_g, fat_g)
      values (foyer, slot_id, v_label,
              nullif(p_choix ->> 'food_id', '')::uuid,
              nullif(p_choix ->> 'grams', '')::numeric,
              coalesce((p_choix ->> 'kcal')::numeric, 0),
              coalesce((p_choix ->> 'protein_g')::numeric, 0),
              coalesce((p_choix ->> 'fiber_g')::numeric, 0),
              coalesce((p_choix ->> 'carb_g')::numeric, 0),
              coalesce((p_choix ->> 'fat_g')::numeric, 0));
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

  return jsonb_build_object('poses', poses, 'liberees', libere);
end $$;

revoke execute on function public.choisir_un_repas(date, text, uuid[], date, jsonb) from public, anon;
grant   execute on function public.choisir_un_repas(date, text, uuid[], date, jsonb) to authenticated;
