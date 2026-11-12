-- ═══════════════════════════════════════════════════════════════════════════
-- 0128 · LA SEMAINE REMONTE : noter hier, et la quantité de nos aliments
--
-- « La semaine » remonte de sept jours. Hier, on note ce qu'on a mangé ; ce qu'on y choisit est MANGÉ, puisque le
-- repas a eu lieu. Les RPC et la RLS acceptaient déjà un jour passé (la RLS ne regarde que le foyer ; `mange_une_part`
-- n'a aucune borne de jour), sauf une : `choisir_un_repas` refusait « un repas d'hier ». Elle est redéfinie ici — son
-- corps change, jamais sa signature :
--
--  1. UN JOUR PASSÉ SE NOTE. Pour un jour avant `p_today` (et jusqu'à sept jours en arrière), la case passe à
--     « mangé » d'un coup, à l'heure du repas (8 h, 12 h, 16 h, 19 h à Paris, jamais dans le futur : la
--     contrainte `meal_slot_mange_date` veut une date), et la barquette posée sort du stock
--     (`tg_meal_slot_consomme`, comme pour « Je l'ai mangé »). « On saute ce repas » reste « sauté ». Au-delà de sept
--     jours : refusé. Un jour d'aujourd'hui ou à venir se comporte comme avant (0125). « Passé » se juge contre la date de la
--     base AUSSI (`least(p_today, aujourdhui())`) : `p_today` vient du client.
--  2. UN EXTRA D'UN JOUR PASSÉ N'EST PAS « PLANIFIÉ » : `planifie` vaut faux, c'est une note après coup.
--  3. `meal_extra.aliment_id` : l'aliment à nous (`aliment`, 0124) dont l'extra est une COPIE. Ce n'est pas une
--     référence de valeurs (corriger l'aliment demain ne réécrit pas le bilan d'hier) : elle ne sert qu'à retrouver
--     les quantités récentes de la personne pour cet aliment (« 30 g, 60 g »). Un aliment retiré laisse la ligne et
--     vide le lien (`on delete set null`). `tg_meme_foyer` refuse l'aliment d'un autre foyer. `food_id` ne
--     pouvait pas le porter : il désigne `food`, le catalogue partagé, pas nos aliments.
--  4. `choisir_un_repas` lit `aliment_id` dans le choix « repère » (le panneau de quantité de la feuille de choix).
--
-- Rend { poses, liberees, lachees, perime_avant }, comme en 0125.
-- ═══════════════════════════════════════════════════════════════════════════

alter table public.meal_extra
  add column if not exists aliment_id uuid references public.aliment(id) on delete set null;
comment on column public.meal_extra.aliment_id is
  'L''aliment à nous dont cet extra est une copie : sert aux quantités récentes, jamais aux valeurs.';
create index if not exists meal_extra_aliment_idx on public.meal_extra (aliment_id, created_at desc)
  where aliment_id is not null;

drop trigger if exists z_aliment_id_meme_foyer on public.meal_extra;
create trigger z_aliment_id_meme_foyer before insert or update on public.meal_extra
  for each row execute function public.tg_meme_foyer('aliment_id', 'aliment');

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
  v_mange_le timestamptz;
  v_passe boolean;
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
  -- Un jour PASSÉ se note (0128) : ce qu'on y choisit est mangé, puisque le repas a eu lieu. Sept jours en arrière :
  -- c'est ce que le bandeau de « La semaine » remonte.
  if p_day < p_today - 7 then
    raise exception 'C’est trop ancien : un repas se note sur les 7 derniers jours.'
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
  -- `p_today` vient du client (à un jour près de Paris) : un jour n'est « passé » que s'il l'est aussi pour la base. Un
  -- `p_today` en avance d'un jour ne fait pas noter mangé le repas d'aujourd'hui.
  v_passe := p_day < least(p_today, public.aujourdhui());
  -- L'heure du repas, à Paris : celle de `frigo.ts` (`HEURE_DU_REPAS`).
  v_moment := (p_day::timestamp + make_interval(hours => case p_meal
                when 'petit_dejeuner' then 8 when 'dejeuner' then 12 when 'collation' then 16 else 19 end))
              at time zone 'Europe/Paris';
  -- Un repas passé est mangé à l'heure où on le sert, jamais dans le futur (le jour local peut avoir un jour d'écart).
  v_mange_le := least(v_moment, public.maintenant());

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
    insert into public.meal_slot (household_id, cycle_id, user_profile_id, day, meal, state, eaten_at, portion_id)
    values (foyer, v_cycle, u, p_day, p_meal,
            case when genre = 'saute' then 'saute' when v_passe then 'mange' else 'prevu' end,
            case when v_passe and genre <> 'saute' then v_mange_le else null end,
            case when genre = 'plat' then (poses ->> u::text)::uuid else null end)
    on conflict (household_id, user_profile_id, day, meal) do update
      set state = excluded.state, eaten_at = excluded.eaten_at, portion_id = excluded.portion_id
      where public.meal_slot.state <> 'mange'
    returning id into slot_id;
    if slot_id is null then
      raise exception 'Ce repas vient d’être noté mangé : on ne le change plus.'
        using errcode = 'object_not_in_prerequisite_state';
    end if;

    if genre = 'repere' then
      -- `planifie` : posé par la feuille, il ne compte au bilan que le repas mangé ou passé. Un repas déjà passé est
      -- NOTÉ, pas planifié. `aliment_id` : l'aliment à nous dont c'est une copie (ses quantités récentes).
      insert into public.meal_extra (household_id, meal_slot_id, label, food_id, aliment_id, grams,
                                     kcal, protein_g, fiber_g, carb_g, fat_g, planifie)
      values (foyer, slot_id, v_label,
              nullif(p_choix ->> 'food_id', '')::uuid,
              nullif(p_choix ->> 'aliment_id', '')::uuid,
              nullif(p_choix ->> 'grams', '')::numeric,
              coalesce((p_choix ->> 'kcal')::numeric, 0),
              coalesce((p_choix ->> 'protein_g')::numeric, 0),
              coalesce((p_choix ->> 'fiber_g')::numeric, 0),
              coalesce((p_choix ->> 'carb_g')::numeric, 0),
              coalesce((p_choix ->> 'fat_g')::numeric, 0),
              not v_passe);
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
