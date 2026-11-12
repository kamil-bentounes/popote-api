# Inventaire de la surface appelée par le front (avant le socle)

Produit par `ops/inventaire.mjs` le 2026-11-12. Une ligne = une sorte d'appel dans un fichier.

| Sorte | Nom | Geste | Fichier |
|---|---|---|---|
| fonction | accept-invite | appel | pages/AcceptInvite.tsx |
| fonction | accept-invite | appel | pages/Rejoindre.tsx |
| fonction | aide | appel | lib/aide/aide.ts |
| fonction | charges | appel | pages/Dictee.tsx |
| fonction | etiquette | appel | lib/aliments/etiquette.ts |
| fonction | etiquette | appel | pages/AjoutManuel.tsx |
| fonction | etiquette | appel | ui/aliments/Formulaire.tsx |
| fonction | etiquette | appel | ui/semaine/EtiquetteEnPlus.tsx |
| fonction | frigo | appel | pages/Photo.tsx |
| fonction | importer | appel | pages/Importer.tsx |
| fonction | inventer | appel | pages/Inventer.tsx |
| fonction | invite | appel | pages/Settings.tsx |
| fonction | rappels | appel | lib/donnees/rappels.ts |
| fonction | revue-charges | appel | pages/RevueCharges.tsx |
| fonction | ticket | appel | pages/Ticket.tsx |
| rpc | accepter_amitie | appel | lib/donnees/amis.ts |
| rpc | annule_mange | appel | lib/donnees/barquettes.ts |
| rpc | apercu_des_soldes | appel | lib/donnees/budget.ts |
| rpc | ce_que_la_session_prend | appel | lib/donnees/barquettes.ts |
| rpc | choisir_un_repas | appel | lib/donnees/barquettes.ts |
| rpc | cloture_le_mois | appel | lib/donnees/budget.ts |
| rpc | confirme_la_depense | appel | lib/donnees/budget.ts |
| rpc | corrige_la_charge | appel | lib/donnees/budget.ts |
| rpc | corrige_le_releve | appel | lib/donnees/budget.ts |
| rpc | create_household | appel | pages/Onboarding.tsx |
| rpc | current_cycle | appel | lib/donnees/cycle.ts |
| rpc | current_household | appel | App.tsx |
| rpc | current_household | appel | lib/donnees/aliments.ts |
| rpc | current_household | appel | lib/donnees/amis.ts |
| rpc | current_household | appel | lib/donnees/barquettes.ts |
| rpc | current_household | appel | lib/donnees/catalogue.ts |
| rpc | current_household | appel | lib/donnees/convives.ts |
| rpc | current_household | appel | lib/donnees/courses.ts |
| rpc | current_household | appel | lib/donnees/cycle.ts |
| rpc | current_household | appel | lib/donnees/foyer.ts |
| rpc | current_household | appel | lib/donnees/importer.ts |
| rpc | current_household | appel | lib/donnees/pesee.ts |
| rpc | current_household | appel | lib/donnees/prix.ts |
| rpc | current_household | appel | lib/donnees/session.ts |
| rpc | current_household | appel | pages/Inventer.tsx |
| rpc | current_household | appel | pages/Settings.tsx |
| rpc | current_household | appel | pages/Targets.tsx |
| rpc | cycle_a_reprendre | appel | lib/donnees/cycle.ts |
| rpc | delete_my_account | appel | pages/Settings.tsx |
| rpc | ecarte_des_parts | appel | lib/donnees/frigo.ts |
| rpc | etat_de_l_annee | appel | lib/donnees/budget.ts |
| rpc | export_my_data | appel | pages/Settings.tsx |
| rpc | foyers_amis | appel | lib/donnees/convives.ts |
| rpc | invitation_par_jeton | appel | pages/Rejoindre.tsx |
| rpc | invitations_de_session | appel | lib/donnees/convives.ts |
| rpc | llm_budget_remaining | appel | pages/Settings.tsx |
| rpc | mange_une_part | appel | lib/donnees/barquettes.ts |
| rpc | mange_une_part | appel | lib/donnees/frigo.ts |
| rpc | open_cycle | appel | lib/donnees/cycle.ts |
| rpc | ouvre_le_mois | appel | lib/donnees/budget.ts |
| rpc | paie_une_facture | appel | lib/donnees/budget.ts |
| rpc | parts_du_foyer | appel | lib/donnees/budget.ts |
| rpc | prenoms_visibles | appel | lib/donnees/amis.ts |
| rpc | prenoms_visibles | appel | lib/donnees/catalogue.ts |
| rpc | prenoms_visibles | appel | lib/donnees/convives.ts |
| rpc | range_la_session | appel | lib/donnees/barquettes.ts |
| rpc | range_le_compte | appel | lib/donnees/budget.ts |
| rpc | rattrape_les_mois | appel | lib/donnees/budget.ts |
| rpc | recettes_faisables | appel | lib/donnees/catalogue.ts |
| rpc | refige_le_mois | appel | lib/donnees/budget.ts |
| rpc | retire_charge | appel | lib/donnees/budget.ts |
| rpc | retire_un_extra | appel | lib/donnees/barquettes.ts |
| rpc | retire_une_facture | appel | lib/donnees/budget.ts |
| rpc | rouvre_le_mois | appel | lib/donnees/budget.ts |
| rpc | solde_epargne | appel | lib/donnees/budget.ts |
| stockage | photos-des-plats | appel | lib/donnees/frigo.ts |
| table | aide_signalement | insert | lib/aide/aide.ts |
| table | aisle_order | select | lib/donnees/courses.ts |
| table | aliment | delete | lib/donnees/aliments.ts |
| table | aliment | insert | lib/donnees/aliments.ts |
| table | aliment | select | lib/donnees/aliments.ts |
| table | aliment | update | lib/donnees/aliments.ts |
| table | appliance_catalog | select | lib/donnees/foyer.ts |
| table | catalogue_charge | select | lib/donnees/budget.ts |
| table | charge_participant | delete | lib/donnees/budget.ts |
| table | charge_participant | insert | lib/donnees/budget.ts |
| table | charge_participant | select | lib/donnees/budget.ts |
| table | charge | insert | lib/donnees/budget.ts |
| table | charge | select | lib/donnees/budget.ts |
| table | charge | update | lib/donnees/budget.ts |
| table | cloture | select | lib/donnees/budget.ts |
| table | compte | insert | lib/donnees/budget.ts |
| table | compte | select | lib/donnees/budget.ts |
| table | cycle_recipe | delete | lib/donnees/cycle.ts |
| table | cycle_recipe | select | lib/donnees/catalogue.ts |
| table | cycle_recipe | select | lib/donnees/courses.ts |
| table | cycle_recipe | select | lib/donnees/cycle.ts |
| table | cycle_recipe | select | lib/donnees/pesee.ts |
| table | cycle_recipe | select | lib/donnees/recettes.ts |
| table | cycle_recipe | select | lib/donnees/session.ts |
| table | cycle_recipe | upsert | lib/donnees/cycle.ts |
| table | cycle | select | lib/donnees/cycle.ts |
| table | cycle | select | lib/donnees/session.ts |
| table | cycle | update | lib/donnees/cycle.ts |
| table | depense | select | lib/donnees/budget.ts |
| table | facture | select | lib/donnees/budget.ts |
| table | food | select | lib/donnees/importer.ts |
| table | foyer_ami | delete | lib/donnees/amis.ts |
| table | foyer_ami | insert | lib/donnees/amis.ts |
| table | foyer_ami | select | lib/donnees/amis.ts |
| table | frequent_food | select | lib/donnees/barquettes.ts |
| table | frequent_food | upsert | lib/donnees/barquettes.ts |
| table | household_unit_weight | select | lib/donnees/courses.ts |
| table | household_unit_weight | select | lib/donnees/pesee.ts |
| table | household | select | lib/donnees/bilan.ts |
| table | household | select | lib/donnees/foyer.ts |
| table | household | select | pages/Settings.tsx |
| table | household | update | pages/Settings.tsx |
| table | instance_setting | select | pages/Onboarding.tsx |
| table | meal_extra | insert | lib/donnees/barquettes.ts |
| table | meal_extra | select | lib/donnees/barquettes.ts |
| table | meal_extra | select | lib/donnees/bilan.ts |
| table | meal_slot | delete | lib/donnees/barquettes.ts |
| table | meal_slot | select | lib/donnees/barquettes.ts |
| table | meal_slot | select | lib/donnees/bilan.ts |
| table | meal_slot | select | lib/donnees/frigo.ts |
| table | meal_slot | update | lib/donnees/barquettes.ts |
| table | meal_slot | upsert | lib/donnees/barquettes.ts |
| table | nutrition_target_courante | select | lib/donnees/bilan.ts |
| table | nutrition_target_courante | select | lib/donnees/foyer.ts |
| table | nutrition_target | insert | pages/Targets.tsx |
| table | nutrition_target | select | pages/Targets.tsx |
| table | poche_epargne | insert | lib/donnees/budget.ts |
| table | poche_epargne | select | lib/donnees/budget.ts |
| table | poche_epargne | update | lib/donnees/budget.ts |
| table | poche_poste | delete | lib/donnees/budget.ts |
| table | poche_poste | insert | lib/donnees/budget.ts |
| table | poche_poste | select | lib/donnees/budget.ts |
| table | portion | insert | lib/donnees/barquettes.ts |
| table | portion | select | lib/donnees/barquettes.ts |
| table | portion | select | lib/donnees/bilan.ts |
| table | portion | update | lib/donnees/frigo.ts |
| table | price_knowledge | select | lib/donnees/courses.ts |
| table | price_knowledge | select | lib/donnees/prix.ts |
| table | rappel_reglage | select | lib/donnees/rappels.ts |
| table | rappel_reglage | upsert | lib/donnees/rappels.ts |
| table | receipt_line | insert | lib/donnees/prix.ts |
| table | receipt_line | select | lib/donnees/bilan.ts |
| table | receipt | delete | lib/donnees/prix.ts |
| table | receipt | insert | lib/donnees/prix.ts |
| table | receipt | select | lib/donnees/bilan.ts |
| table | recipe_ingredient | insert | lib/donnees/importer.ts |
| table | recipe_ingredient | insert | pages/Inventer.tsx |
| table | recipe_ingredient | select | lib/donnees/catalogue.ts |
| table | recipe_ingredient | select | lib/donnees/courses.ts |
| table | recipe_ingredient | select | lib/donnees/pesee.ts |
| table | recipe_ingredient | select | lib/donnees/recettes.ts |
| table | recipe_nutrition | insert | lib/donnees/importer.ts |
| table | recipe_step_dependency | insert | lib/donnees/importer.ts |
| table | recipe_step_dependency | select | lib/donnees/session.ts |
| table | recipe_step | insert | lib/donnees/importer.ts |
| table | recipe_step | insert | pages/Inventer.tsx |
| table | recipe_step | select | lib/donnees/session.ts |
| table | recipe | insert | lib/donnees/importer.ts |
| table | recipe | insert | pages/Inventer.tsx |
| table | recipe | select | lib/donnees/catalogue.ts |
| table | recipe | select | lib/donnees/fiche.ts |
| table | recipe | select | lib/donnees/frigo.ts |
| table | recipe | update | lib/donnees/frigo.ts |
| table | regle_partage | select | lib/donnees/budget.ts |
| table | regle_partage | upsert | lib/donnees/budget.ts |
| table | revenu | select | lib/donnees/budget.ts |
| table | revenu | upsert | lib/donnees/budget.ts |
| table | saisie | delete | lib/donnees/budget.ts |
| table | saisie | insert | lib/donnees/budget.ts |
| table | saisie | select | lib/donnees/budget.ts |
| table | session_appliance | delete | lib/donnees/session.ts |
| table | session_appliance | insert | lib/donnees/session.ts |
| table | session_appliance | select | lib/donnees/session.ts |
| table | session_convive | delete | lib/donnees/convives.ts |
| table | session_convive | select | lib/donnees/convives.ts |
| table | session_convive | update | lib/donnees/convives.ts |
| table | session_convive | upsert | lib/donnees/convives.ts |
| table | session_task_dependency | insert | lib/donnees/session.ts |
| table | session_task_dependency | select | lib/donnees/session.ts |
| table | session_task_recipe | insert | lib/donnees/session.ts |
| table | session_task_recipe | select | lib/donnees/session.ts |
| table | session_task | delete | lib/donnees/session.ts |
| table | session_task | insert | lib/donnees/session.ts |
| table | session_task | select | lib/donnees/session.ts |
| table | session_task | update | lib/donnees/session.ts |
| table | shopping_habit | select | lib/donnees/courses.ts |
| table | shopping_item | delete | lib/donnees/courses.ts |
| table | shopping_item | insert | lib/donnees/courses.ts |
| table | shopping_item | select | lib/donnees/bilan.ts |
| table | shopping_item | select | lib/donnees/courses.ts |
| table | shopping_item | select | lib/donnees/prix.ts |
| table | shopping_item | update | lib/donnees/courses.ts |
| table | shopping_item | update | lib/donnees/prix.ts |
| table | shopping_trip | select | lib/donnees/prix.ts |
| table | shopping_trip | update | lib/donnees/prix.ts |
| table | shopping_trip | upsert | lib/donnees/courses.ts |
| table | stock_item | delete | lib/donnees/barquettes.ts |
| table | stock_item | insert | lib/donnees/barquettes.ts |
| table | stock_item | select | lib/donnees/barquettes.ts |
| table | stock_item | select | lib/donnees/frigo.ts |
| table | stock_item | update | lib/donnees/frigo.ts |
| table | store | delete | lib/donnees/foyer.ts |
| table | store | insert | lib/donnees/foyer.ts |
| table | store | select | lib/donnees/courses.ts |
| table | store | select | lib/donnees/foyer.ts |
| table | store | update | lib/donnees/foyer.ts |
| table | suggested_item | select | lib/donnees/courses.ts |
| table | typical_quantity | select | lib/donnees/importer.ts |
| table | typical_quantity | select | lib/donnees/recettes.ts |
| table | unit_weight | select | lib/donnees/pesee.ts |
| table | user_profile | select | App.tsx |
| table | user_profile | select | lib/donnees/bilan.ts |
| table | user_profile | select | lib/donnees/foyer.ts |
| table | user_profile | select | lib/donnees/session.ts |
| table | user_profile | update | App.tsx |
| table | user_profile | update | pages/Password.tsx |
| table | user_profile | update | pages/Profil.tsx |
| table | versement_epargne | insert | lib/donnees/budget.ts |
| table | weighing | delete | lib/donnees/pesee.ts |
| table | weighing | insert | lib/donnees/pesee.ts |
| table | weighing | select | lib/donnees/pesee.ts |
| temps réel | - | abonnement | lib/temps-reel.ts |

**Totaux** : 54 tables, 37 fonctions SQL, 11 fonctions Edge, 1 seaux, temps réel dans 1 fichier(s).

## Routes de 0.5

Regroupement à la main des lignes ci-dessus, par domaine : ce que l'API de l'étape 0.5 devra exposer. Chaque
ligne du tableau appartient à un domaine, selon le fichier qui l'appelle. Les noms sont ceux d'aujourd'hui.

- **Foyer et réglages** (`lib/donnees/foyer.ts`, `amis.ts`, `convives.ts`, `pages/Settings.tsx`, `Onboarding`,
  `Rejoindre`, `AcceptInvite`, `Password`, `Profil`, `Targets`) : tables `household`, `user_profile`, `foyer_ami`,
  `compte`, `nutrition_target`, `nutrition_target_courante`, `session_convive`, `instance_setting` ; RPC
  `create_household`, `current_household`, `accepter_amitie`, `foyers_amis`, `prenoms_visibles`,
  `invitation_par_jeton`, `export_my_data`, `delete_my_account` ; fonctions `invite`, `accept-invite`.
- **Recettes** (`recettes.ts`, `fiche.ts`, `importer.ts`, `catalogue.ts`, `aliments.ts`, `prix.ts`, `pages/Importer`,
  `Inventer`, `Ticket`, `Dictee`, `AjoutManuel`) : tables `recipe`, `recipe_ingredient`, `recipe_step`,
  `recipe_step_dependency`, `recipe_nutrition`, `aliment`, `food`, `catalogue_charge`, `price_knowledge`, `store`,
  `receipt`, `receipt_line`, `unit_weight`, `household_unit_weight`, `typical_quantity` ; RPC `recettes_faisables`,
  `llm_budget_remaining` ; fonctions `importer`, `inventer`, `ticket`, `etiquette`, `aide`.
- **Cycle** (`cycle.ts`, `bilan.ts`) : tables `cycle`, `cycle_recipe`, `meal_slot`, `meal_extra`, `appliance_catalog` ;
  RPC `current_cycle`, `open_cycle`, `cycle_a_reprendre`, `choisir_un_repas`, `mange_une_part`, `annule_mange`,
  `retire_un_extra`.
- **Semaine et frigo** (`session.ts`, `courses.ts`, `frigo.ts`, `barquettes.ts`, `pesee.ts`, `pages/Photo`,
  `lib/temps-reel.ts`) : tables `session_task`, `session_task_dependency`, `session_task_recipe`,
  `session_appliance`, `stock_item`, `weighing`, `shopping_item`, `shopping_trip`, `shopping_habit`,
  `suggested_item`, `frequent_food`, `aisle_order` ; RPC `range_la_session`, `range_le_compte`,
  `ce_que_la_session_prend`, `invitations_de_session`, `ecarte_des_parts`, `parts_du_foyer` ; fonction `frigo` ;
  seau `photos-des-plats` ; temps réel (1 abonnement).
- **Budget** (`lib/donnees/budget.ts`, `pages/RevueCharges`) : tables `charge`, `charge_participant`, `depense`,
  `facture`, `saisie`, `revenu`, `cloture`, `poche_epargne`, `poche_poste`, `versement_epargne`,
  `regle_partage` ; RPC `ouvre_le_mois`, `rouvre_le_mois`, `refige_le_mois`, `cloture_le_mois`,
  `rattrape_les_mois`, `etat_de_l_annee`, `apercu_des_soldes`, `confirme_la_depense`, `corrige_la_charge`,
  `corrige_le_releve`, `retire_charge`, `retire_une_facture`, `paie_une_facture`, `solde_epargne` ; fonctions
  `charges`, `revue-charges`.
- **Rappels** (`rappels.ts`) : table `rappel_reglage`, `aide_signalement` ; fonction `rappels` (appelée aussi par
  `pg_cron`, route `/internal/*` de la spec § 3.10).
