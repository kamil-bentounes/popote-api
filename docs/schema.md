# Schéma

64 tables, trois classes d'isolation. Toute policy RLS découle de la classe.

| Classe | Règle | Tables |
|---|---|---|
| **A — référentiel** | Lecture : tout authentifié. Écriture : rôle de service. | `food`, `food_yield_factor`, `unit_weight`, `unit_conversion`, `density`, `default_temperature`, `default_duration`, `typical_quantity`, `appliance_catalog`, `ingestion_job`, `instance_setting`, `non_action_pattern`, `suggested_item`, `cycle_transition` |
| **B — catalogue partagé** | Lecture : tous. `UPDATE` tracé, refusé si `confidence >= 0.8`, et **seulement sur ce que personne ne possède** (`owner_household_id is null`) ou sur ce qui est à soi — 0036/0038. Ni `INSERT` ni `DELETE`. | `recipe`, `recipe_ingredient`, `recipe_step`, `recipe_step_dependency`, `recipe_nutrition` |

`portion` porte `source` (`session` · `manuel` · `achete`, migration 0046) : une
barquette peut naître sans session de cuisine — un plat tout prêt acheté dehors
est un REPAS, il se mange depuis la semaine et pèse dans les calories du jour.
Sa provenance est gelée par `tg_portion_source`, sans quoi le bilan mélangerait
ce qu'on a cuisiné et ce qu'on a acheté. `stock_item` porte désormais
`frozen_at` comme `portion`.

La péremption (D29) reste de quatre jours au frigo et trois mois au
congélateur, mais elle ne s'applique plus que faute de mieux : une date donnée à
l'insertion — celle imprimée sur un emballage — est respectée (0047). Elle était
écrasée en silence.

`recipe_nutrition` fait exception à la traçabilité : elle n'a ni
`edited_by_household_id` ni garde de classe B, donc une correction des macros du
catalogue mutualisé y reste anonyme (0039).

Une recette peut désormais APPARTENIR à un foyer (`owner_household_id`, 0034) :
collée, inventée ou importée. Elle n'est alors plus de la classe B mais de la C,
et sa colonne `visibility` (`privee` / `partagee` / `publique`, 0035) décide qui
la lit. C'est une colonne de DROITS : seul le foyer propriétaire y touche, et
`created_by` non plus ne se réécrit pas.

`recipe_step` porte `verb` et `quantity_g` (migration 0019) : la fusion des
gestes entre recettes (D35) compare des verbes, pas des phrases, et la mesure
des durées (D48) s'agrège par verbe — une étape n'est jamais refaite, un verbe
l'est toutes les semaines. Remplis par l'ingestion, voir [`ingestion.md`](ingestion.md).

`recipe_step.gesture_min` (0092, `numeric`, `>= 0`) : les minutes de gestes que l'étape
conjugue, quel que soit le verbe retenu ; `NULL` = non mesuré, l'étape compte comme avant.
`tg_recipe_agrege` compte, par étape, le plus grand de sa durée et de ses gestes (active ou
bloquante), ou ses gestes seuls (passive). `recipe.image_url` (0092, `https://`, 2 048
caractères au plus) : la photo du site, en lien, écrite par le rôle de service seul
(`tg_recipe_photo`). La source qui la pilote (`source_url`, `source_name`) est figée de
même sur les recettes du catalogue (`tg_recipe_source`) : le crawler de photos se fie à
`source_url`, la changer ferait écrire par le service la photo de la page de son choix.
Une recette de foyer garde sa source modifiable par son foyer.
| **C — foyer** | RLS stricte, trois formes de prédicat. | `household`, `user_profile`, `nutrition_target`, `invitation`, `llm_usage`, `foyer_ami`, `session_convive` + les 18 tables du lot 1 et les 6 des lots 0c et 5 (ci-dessous) |

Deux tables ouvrent une brèche *nommée* dans la classe C, et une seule à la fois :

- `foyer_ami` (0035) — l'amitié entre deux foyers, symétrique et explicite. Elle
  ouvre la LECTURE des recettes `partagee` de l'autre, et rien d'autre.
- `session_convive` (0037, resserrée par 0038) — un foyer ami convié à une
  session de cuisine. Il lit le plan et prend des gestes tant que trois choses
  tiennent ENSEMBLE : il a accepté, le cycle est vivant (`pret`, `en_cuisine`,
  `dressage`) et l'amitié tient encore. Un trigger gèle tout le reste : il
  cuisine, il ne réécrit pas.

`session_task` est publiée en temps réel (`supabase_realtime`, 0037). La RLS
s'applique au flux — sauf aux événements DELETE, que Supabase ne filtre pas ;
leur charge ne porte que l'identifiant.

## Les tables du lot 1

| Domaine | Tables | Ce qu'elles portent |
|---|---|---|
| Le cycle | `cycle`, `cycle_recipe` | L'état de la semaine, les recettes choisies. Voir [`cycle.md`](cycle.md) |
| Les courses | `store`, `aisle_order`, `shopping_item`, `shopping_trip`, `shopping_habit` | Une sortie par magasin, l'ordre des rayons appris du geste |
| La session | `session_task`, `session_task_recipe`, `session_task_dependency`, `session_appliance`, `duration_observation` | Le plan calculé et persisté, les durées mesurées |
| Les barquettes | `portion`, `portion_event` | L'unité de suivi, et son journal |
| La semaine | `meal_slot`, `meal_extra`, `frequent_food` | Ce qui est prévu, ce qui a été mangé en plus |
| L'inventaire | `stock_item` | Frigo, congélateur, placard |
| Nos aliments | `aliment` (0124) | Ce que le foyer mange, avec ses vraies valeurs pour 100 g, l'unité (« pot ») et son poids, le code-barres, la source (`main`, `etiquette`, `code_barres`). Un geste écrit une COPIE d'une unité dans `meal_extra` |

## Les tables des lots 0c, 4, 5 et 6

| Domaine | Tables | Ce qu'elles portent |
|---|---|---|
| Les filtres (lot 4, classe B) | `recipe_nutrition` | Macros **par part**, avec leur marge et leur couverture (D18). `recipe` gagne `active_time_min`, `appliances`, `step_count`, `freezable` — matérialisés par `tg_recipe_agrege` |
| Les prix (lot 5) | `receipt`, `receipt_line`, `household_price` | Le ticket lu, ses lignes, et le prix appris par produit **et par enseigne**. Voir [`prix.md`](prix.md) |
| La pesée (lot 0c) | `weighing`, `household_unit_weight`, `household_ingredient_resolution` | L'observation brute, la médiane retenue, et la correction de rattachement propre au foyer (§5.2.1) |
| Le budget (lot 6) | — | `household.food_budget_eur`, **nullable** : ne pas s'en fixer est un choix. Voir [`suivi.md`](suivi.md) |

`price_knowledge` est une **vue** (`security_invoker`) sur `household_price`
jointe à `store` : elle existe pour que « ignorer les relevés trop vieux » soit
un jour la correction d'une seule ligne.

Les quatre policies (`select`, `insert`, `update`, `delete`) sont écrites
**séparément** sur chacune. Jamais `for all` : la leçon a déjà été payée sur
`household`, où `for all` incluait `DELETE`.

## Les trois prédicats de la classe C

| Forme | Tables | Prédicat |
|---|---|---|
| La clé **est** le foyer | `household` | `id = current_household()` |
| Colonne directe | `user_profile`, `invitation`, `llm_usage` | `household_id = current_household()` |
| Dénormalisée | `nutrition_target` | `household_id`, rempli par trigger depuis `user_profile` |

**Portée personne, pas foyer** — sur `nutrition_target` et `user_profile` la *lecture* est au foyer
(le bilan nutritionnel en a besoin), toute *écriture* exige `= auth.uid()`. Sans cela un membre
effacerait les objectifs de l'autre.

**Aucune policy `DELETE` sur `household` ni `user_profile`** — `for all` inclut `DELETE` : un membre
pourrait supprimer son foyer (la cascade emporte profils et objectifs) ou son propre profil, ce qui
remettrait `current_household()` à `NULL` et lui permettrait de créer un second foyer. On sort par
`delete_my_account()`, pas autrement.

## Fonctions et triggers

| Objet | Rôle |
|---|---|
| `current_household()` | `SECURITY DEFINER` : contourne la RLS de `user_profile` par *ownership de table*, ce qui évite la récursion de policy. **Ne jamais poser `FORCE ROW LEVEL SECURITY` sur `user_profile`.** |
| `is_service_role()` | `session_user = 'popote_internal'`, ou `session_user = 'authenticator'` avec le claim JWT `role = service_role` (branche retirée à J+2). Voir `docs/securite.md` § 5.1. |
| `mon_email()` | `SECURITY DEFINER`, `search_path = ''`, exécutable par `authenticated` seul (0134). L'adresse de `auth.uid()`, ou `NULL` : `user_profile` n'a pas d'e-mail et `authenticated` ne lit pas `auth.users`. Aucun paramètre : on ne peut demander que la sienne. Sert `GET /api/v1/me`. |
| `session_personne(p_hash bytea)` | `SECURITY DEFINER`, `search_path = ''`, exécutable par `popote_api` **seul** (0133). La personne d'une session de connexion valide, ou `NULL` ; repousse l'échéance au plus une fois toutes les 5 minutes. Table `login_session` : hors des trois classes, RLS activée sans politique, aucun droit à personne. Voir `docs/securite.md` § 4. |
| `tg_class_b_guard` | `BEFORE UPDATE` sur les 4 tables de classe B. Pose la traçabilité, refuse les lignes sûres. Générique via `to_jsonb(old) ? 'confidence'`. |
| `tg_nutrition_target_household` | `BEFORE INSERT` : remplit `household_id`. S'exécute avant `NOT NULL` et avant le `WITH CHECK`. |
| `current_cycle()` | Le cycle vivant du foyer, ou `NULL`. |
| `cycle_a_reprendre()` | L'id de la dernière session `interrompue` du foyer dont la semaine est la courante, la dernière ou une à venir (horloge de la base, 0117), sinon `NULL`. L'écran ne calcule plus de date. |
| `open_cycle(week, servings)` | Rend le cycle vivant s'il y en a un, refuse de rouvrir une semaine close — ou interrompue et reprenable (« reprends-la », 0117). |
| `tg_shopping_item_protege` | `BEFORE DELETE` : une ligne cochée ou payée ne se supprime pas. Suppression directe : `restrict_violation` (23001) avec un message lisible ; en cascade (cycle, foyer, `delete_my_account`) la ligne part avec son parent (0117 — avant, elle survivait, orpheline). |
| `tg_cycle_recipe_position` | `BEFORE INSERT` sur `cycle_recipe` : `position = max + 1` du cycle, 0 pour la première (0117). |
| `tg_cycle_transition` | `BEFORE UPDATE OF state` : refuse toute transition absente de `cycle_transition`, horodate `started_at` et `closed_at`. |
| `tg_derive_household` | Générique. Dérive `household_id` du parent (`TG_ARGV`) : RLS empêche d'écrire au nom d'un autre foyer, pas de s'accrocher à SON cycle. |
| `tg_portion_peremption` | Pose `expires_at` selon le lieu : frigo 4 j, congélateur 90 j, décongelée **24 h**. Sortir du congélateur *est* une décongélation. |
| `tg_portion_journal` | `AFTER` : écrit `portion_event`. Le journal n'a ni `INSERT`, ni `UPDATE`, ni `DELETE` pour personne. |
| `tg_shopping_check` / `tg_shopping_check_apres` | Cocher = rang + ordre des rayons appris + entrée à l'inventaire + habitude retenue. **En base**, parce que deux téléphones cochent la même liste. Pas d’entrée à l’inventaire pour le non-alimentaire : rayons Entretien et Hygiène (0117) ; « Autre », rayon par défaut des libellés inconnus, se range. Pas de fusion avec une ligne de stock existante : décocher défait exactement ce que cocher a fait, par `shopping_item_id`. |
| `tg_session_task_duree` / `_mesure` | La durée réelle est mesurée entre « je prends » et « c'est fait », jamais demandée. Alimente `duration_observation`. |
| `tg_meal_slot_consomme` | Une case passée à « mangé » consomme sa barquette. |
| `tables_de_foyer()` | Introspection, rôle de service. Ne liste que des `BASE TABLE` — sinon la vue `price_knowledge` réclamerait un export en plus de la table qu'elle lit. Sert au test qui empêche `export_my_data` de prendre du retard sur le schéma. |
| `tg_recipe_agrege` | `AFTER INSERT/UPDATE/DELETE` sur `recipe_step` : recalcule temps actif (chaque étape compte au moins ses gestes, 0092), appareils et nombre d'étapes. **Un trigger ne rattrape pas le passé** — `scripts/recalcule.mjs` existe pour cela. |
| `tg_recipe_photo` | `BEFORE INSERT OR UPDATE OF image_url` sur `recipe` : hors rôle de service, poser ou changer la photo est refusé (`check_violation`). Une adresse posée par un compte ferait charger à tous une image de son choix, et lui dirait qui regarde et quand. Pas `security definer` : `is_service_role()` suffit, et la porte ne disparaît pas en silence le jour où elle le deviendrait. |
| `tg_recipe_source` | `BEFORE UPDATE OF source_url, source_name` sur `recipe` : hors rôle de service, changer la source d'une recette du catalogue (`owner_household_id is null`) est refusé (`check_violation`) ; le titre, les ingrédients et les étapes restent corrigeables. `scripts/relis-photos.mjs` (rôle de service) se fie à `source_url` : sans cette garde, un foyer la redirigerait et ferait poser sa photo dans le catalogue, au mépris de `tg_recipe_photo`. Les recettes de foyer gardent leur source modifiable. Même porte : `is_service_role()`. |
| `recettes_faisables()` | `STABLE`, `SECURITY INVOKER`, ids **triés** (`order by r.id`). Les recettes planifiables dont tous les ingrédients reconnus sont au placard du foyer, et qui en ont au moins un. La RLS de `recipe` et de `stock_item` s'applique telle quelle. `authenticated` seul (`revoke … from public, anon`). Voir [`api.md`](api.md) |
| `tg_receipt_line_apprend` | `AFTER INSERT` sur `receipt_line` : apprend le prix (ramené au kilo ou au litre, **médiane mobile**) et reporte `paid_price_eur`. ⚠️ `SECURITY DEFINER`, donc il **vérifie lui-même** le foyer de l'article et du magasin — la RLS ne le protège pas. |
| `tg_pesee_apprend` | `AFTER INSERT/UPDATE/DELETE` sur `weighing` : rejette les aberrantes hors `[0,4× ; 2,5×]` la référence, retient la **médiane**, active à 3 observations (5 sans référence). Repart des observations à chaque fois — une médiane incrémentale serait fausse dès la première suppression. |
| `poids_unitaire(food, unit)` | Le poids appris s'il est actif, sinon la référence, sinon `NULL`. Jamais un chiffre inventé (D18). |
| `llm_consomme(foyer, kind)` | Incrément **atomique** du quota. Le code lisait puis écrivait : un appel simultané sur deux ne comptait pas. Rôle de service seulement. |

### La règle du temps actif, et son contrôle (0092)

| Charge de l'étape | Ce qu'elle compte |
|---|---|
| `actif`, `bloquant` | `greatest(duration_min, gesture_min)`, chacun nul comptant 0 |
| autre (`passif`) | `gesture_min` seul : le four cuit seul, mais quelqu'un a versé la pâte dans le moule |

`recipe.active_time_min` est la somme de ces nombres sur les étapes. Une étape à `gesture_min`
nul compte comme avant la 0092. La même règle est écrite côté client dans
`src/lib/recettes/temps.ts` (`minutesDeMains`), et `tests/recettes.test.ts` vérifie que les
deux disent la même chose : si l'une change, l'autre doit suivre.

Après un recalcul, cette requête doit rendre **0** :

```sql
select count(*) from recipe r
where exists (select 1 from recipe_step s where s.recipe_id = r.id)
  and active_time_min is distinct from (
    select coalesce(sum(case when load_type in ('actif','bloquant')
           then greatest(coalesce(duration_min,0), coalesce(gesture_min,0))
           else coalesce(gesture_min,0) end), 0)
    from recipe_step s where s.recipe_id = r.id)
```

### Retour arrière de la 0092

Dans cet ordre, et pas un autre : tant que le corps de `tg_recipe_agrege` lit `gesture_min`,
chaque écriture d'étape échouerait si la colonne n'existait plus.

1. Remettre le corps de la 0023 de `tg_recipe_agrege` :

   ```sql
   create or replace function public.tg_recipe_agrege()
   returns trigger language plpgsql security definer set search_path = public as $$
   declare r uuid := coalesce(new.recipe_id, old.recipe_id);
   begin
     update public.recipe set
       active_time_min = (
         select coalesce(sum(duration_min), 0) from public.recipe_step
         where recipe_id = r and load_type in ('actif', 'bloquant')),
       appliances = (
         select coalesce(array_agg(distinct appliance_type), '{}')
         from public.recipe_step
         where recipe_id = r and appliance_type is not null),
       step_count = (select count(*) from public.recipe_step where recipe_id = r)
     where id = r;
     return null;
   end $$;
   ```

2. `drop trigger recipe_source on public.recipe;` puis `drop function public.tg_recipe_source();`
3. `drop trigger recipe_photo on public.recipe;`
4. `drop function public.tg_recipe_photo();`
5. `drop function public.recettes_faisables();`
6. Et seulement alors : `alter table public.recipe drop column image_url;` et
   `alter table public.recipe_step drop column gesture_min;`.

Les `active_time_min` déjà recalculés gardent les gestes jusqu'à la prochaine écriture de
leurs étapes : la sauvegarde prise avant le recalcul en prod (`recipe` : `id`, `title`,
`active_time_min`, `total_time_min` ; `recipe_nutrition` entier ; `recipe_step` : `id`,
`duration_min`) sert à les remettre. Les photos et les gestes, eux, sont perdus avec leurs
colonnes — ils se relisent par [`ingestion.md`](ingestion.md).

## Budget LLM

| | Plafond | Compteur |
|---|---|---|
| Ingestion, mutualisée entre foyers | `instance_setting.llm_global_monthly_cap_eur` | `llm_usage` où `household_id IS NULL` |
| Vision et propositions | `household.llm_monthly_cap_eur` | `llm_usage` du foyer |

`unique nulls not distinct (household_id, month, kind)` → **PostgreSQL 15+ requis**.

## Mode sur invitation

`create_household()` n'est ouverte que si `instance_setting.allow_household_creation` vaut `true`
(valeur d'amorçage). **La refermer une fois les comptes créés**, sinon toute personne qui s'inscrit
peut se créer un foyer.

## Référentiels chargés (lot 0a-2)

| Table | Lignes | Source |
|---|---|---|
| `food` | **3 185** | CIQUAL 2020 (ANSES) — 14 nutriments retenus sur ~60, groupes et sous-groupes, état cru/cuit déduit du nom |
| `unit_conversion` | 29 | Construite à la main. Cuillères, pincées, poignées → grammes, avec surcharges par sous-groupe (huile 13,5 g la c. à soupe contre 15 g par défaut) |
| `default_duration` | **55** | Construite à la main puis **étendue par mesure** : partie de 35 verbes couvrant 86 % des étapes réelles, portée à 55 pour **98 %**. (verbe, appareil) → durée, `load_type`, `scaling` |
| `default_temperature` | 12 | Construite à la main |
| `typical_quantity` | 9 | Construite à la main. Borne haute des lignes d'ingrédients sans quantité |
| `density` | 6 | Construite à la main, rattachée à un code CIQUAL |
| `non_action_pattern` | 16 | Phrases qui ne décrivent aucun geste (« bon appétit », « astuce : »). Sans elles, le plan gagne des minutes fantômes. |
| `appliance_catalog` | 8 | Four, plaques, air fryer, micro-ondes, robot cuiseur, autocuiseur, blender, batteur |

```bash
npm run seed            # base locale
node scripts/seed.mjs --prod   # production
```

Idempotent : rejouable sans effet de bord, tout passe par des `upsert`.

**Attribution obligatoire** : ANSES-CIQUAL, Licence Ouverte Etalab.
La conversion du `.xls` d'origine est un geste ponctuel — `scripts/ciqual-to-json.py`,
à rejouer seulement si l'ANSES publie une nouvelle table.

## Un piège à ne pas réintroduire

`unique (a, b)` **ne contraint pas** les lignes où `b` est `NULL` : Postgres traite chaque
`NULL` comme distinct, donc un `upsert` répété les duplique. Constaté en production —
`default_duration` est montée à 74 lignes au lieu de 55.

La forme correcte, partout où une colonne de la clé peut être nulle :

```sql
unique nulls not distinct (a, b)   -- PostgreSQL 15+
```

Concernées : `default_duration` (`appliance_type`), `unit_conversion` (`ciqual_subgroup`),
`llm_usage` (`household_id`). Un test de non-régression le vérifie
(`tests/referentiels.test.ts`).

## Ce qui existe sans être branché

Relevé honnêtement plutôt que laissé à découvrir. Ces objets sont créés, testés
et documentés, mais **aucun écran ne les lit** :

| Objet | Ce qui manque |
|---|---|
| `household_ingredient_resolution` | La correction d'un rattachement PAR LE FOYER (D3, D16). La table, la RLS et les tests existent ; l'écran qui permettrait de corriger « crème » quand il tombe sur la crème dessert n'est pas écrit. |
| `duration_observation` → `default_duration` | La boucle D48 est à moitié fermée : la durée réelle est bien MESURÉE et consignée à chaque session, mais rien ne la réagrège vers `default_duration`. Les durées par défaut restent donc celles du seed. |
| `poids_unitaire()` | La règle « poids appris s'il est actif, sinon la référence » est appliquée côté client dans `courses.ts`. La fonction SQL dit la même chose et n'a pas d'appelant. |

> Les deux premières lignes sont des fonctionnalités promises par la conception.
> La troisième est une duplication à résorber le jour où la règle bougera.

## Le budget (migrations 0049 à 0057)

| Table | Classe | Ce qu'elle porte |
|---|---|---|
| `compte` | C | Un par vrai compte bancaire. `matelas_cents` : ce qu'on laisse sur le commun, au-dessus de quoi se pose la question de fin de mois. Un compte `perso` a un titulaire, un compte `commun` n'en a pas — la contrainte le dit. |
| `revenu` | C en lecture, **PERSONNE en écriture** | Le net mensuel après impôt, en centimes, daté par `valid_from`. Visible par le foyer (D63), écrit par son seul titulaire — comme `nutrition_target`, et pour la même raison. |
| `regle_partage` | C | `prorata` ou `moitie`, datée. Il n'y a pas de troisième clé globale : « telle chose à 50/50 » se dit sur la charge, « 100 % pour quelqu'un » en ne mettant qu'une personne dans les participants. |
| `catalogue_charge` | A | 52 lignes en 7 sections, proposées à la saisie. `portee` n'est qu'une case pré-cochée, jamais une décision. |

`user_profile.entre_le` décide des mois qu'une personne partage. C'est une
colonne de DROITS, bornée par contrainte : la porter à 2099 faisait disparaître
quelqu'un de tous les mois, sans erreur et sans trace.

`parts_du_foyer(le_mois, le_foyer default null)` rend la part de chacun en
points de base pour un mois donné ; la somme fait exactement 10000, le reliquat
allant au plus gros contributeur. `le_foyer` n'est honoré que pour le rôle de
service — sans quoi un authentifié lirait la clé du voisin. Elle partage à parts
égales tant qu'un présent n'a pas saisi son revenu : ne pas avoir répondu n'est
pas gagner zéro.

### Les charges et les dépenses

| Table | Ce qu'elle porte |
|---|---|
| `charge` | Le modèle récurrent : un montant POUR SA PÉRIODE, une périodicité, une clé facultative qui surcharge celle du foyer, un compte débité, un début et une fin. `archive_le` : une charge qui a produit des dépenses ne se supprime pas (`on delete restrict`), elle s'archive. |
| `charge_participant` | Qui participe. Il n'y a qu'UNE liste de charges par foyer ; « perso » n'est que le cas où il n'y a qu'une personne ici. |
| `depense` | La ligne d'un mois. `unique (charge_id, mois) where source = 'modele'` — partielle, sans quoi la ligne d'ajustement de D62 serait impossible. |
| `depense_part` | La part de chacun, **figée en centimes**. Son `user_profile_id` n'a **pas** de clé étrangère, délibérément : une part figée est un fait comptable, pas un pointeur, et elle survit au départ de la personne. |

`charge.mode` dit comment on la paie (D75) : `fixe`, `facture`, `au_fil` ou
`mis_de_cote` — ce dernier si et seulement si la charge n'est pas mensuelle
(contrainte `charge_mode_periodicite`). `charge.categorie` la range à l'écran
(D74) : elle vient du catalogue par défaut et se change dans « Mes charges ».
`depense.facon` fige la façon de LA LIGNE à sa naissance : la clôture et la garde
des saisies la lisent, jamais celle de la charge, qui a pu changer depuis. Null
pour un ajustement ; toute ligne `modele` en a une (`depense_modele_a_une_facon`).

### Le budget refait (migrations 0093 à 0114, D74 à D80)

| Table | Ce qu'elle porte |
|---|---|
| `saisie` | Une dépense au fil du mois, rattachée à la LIGNE du mois (`depense_id`, en cascade). L'id vient de l'appareil : un renvoi est un succès sans effet. `saisi_par` à null : la saisie d'amorce posée par 0114 pour une ligne déjà confirmée, ou un membre parti. |
| `facture` | Une facture d'une charge mise de côté. Pour une charge et une année, le total payé est la somme de ses factures, aucune autre source. `origine = 'releve'` : un ancien relevé annuel, converti par 0114. |
| `cloture` | Un mois clôturé par foyer (`unique (household_id, mois)`), avec l'heure de la clôture. |
| `cloture_choix` | Le choix de chacun à la clôture : son reste, ce qu'il met de côté, sur quelle poche. `user_profile_id` sans clé étrangère : un fait comptable, qui survit au départ. |

`releve_annuel` ne porte plus que l'année soldée, et son prévu figé
(`prevu_cents`) ; le total payé, ce sont les factures.

**L'heure.** `maintenant()`, `aujourdhui()` et `mois_courant()` donnent l'heure de
Paris ; `popote.maintenant` (réglage de base, superutilisateur seul) la fait jouer
aux bancs. **Le verrou du foyer.** Toute fonction du budget prend
`verrou_du_foyer` avant sa première écriture, et un trigger d'instruction fait de
même pour les écritures du client : une saisie ou une facture qui arrive pendant
une clôture attend sa fin, puis la voit.

`ouvre_le_mois(le_mois, le_foyer default null)` engendre les dépenses des
charges actives et fige les parts. Idempotente — il n'y a pas de `pg_cron`,
donc l'ouverture est paresseuse et le premier qui ouvre l'app le 1er la
déclenche. Elle renormalise les parts sur les seuls participants : sans ça,
celui qui paie seul son crédit auto ne s'en verrait attribuer que sa part de
foyer.

Deux `constraint trigger` différés garantissent que la somme des parts
recompose le montant — au moment de valider, donc supprimer puis reposer des
parts dans une transaction reste possible, mais une somme fausse ne l'est
jamais.

### Les enveloppes, l'épargne et la régularisation

`enveloppe` est un plafond mensuel : aucun argent n'y bouge, et il repart à zéro
chaque mois. `poche_epargne` et `versement_epargne` tiennent l'argent qui
persiste et **le cumul par personne** — sans lui, un livret joint est présumé
moitié-moitié alors que les versements ne l'étaient pas (D64). Le
`user_profile_id` d'un versement n'a pas de clé étrangère, comme
`depense_part` : c'est un fait comptable, pas un pointeur.

`regularise_annuel(charge, annee, reel)` pose la ligne d'ajustement de D62. Elle
ne touche à aucun mois déjà partagé : l'écart se répartit selon ce que chacun a
**porté** sur l'année, donc selon la clé en vigueur chaque mois, sans avoir à la
relire. Quelqu'un arrivé en octobre ne porte que ses trois mois. (Depuis 0113, elle
ne fait plus que refuser : ce sont les factures qui régularisent, D77.)

**`depense.montant_cents` est signé.** Un relevé inférieur à la provision est un
remboursement, pas une anomalie. Le contrôle qui compte reste le même : la somme
des parts recompose le montant, signe compris.

**Ce qui protège le passé n'est pas l'historique des revenus** — il part en
cascade avec le profil, pour que la suppression de compte aboutisse — mais la
part figée en centimes sur chaque dépense (D60).
