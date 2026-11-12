---
id: budget-charges-ajouter
titre: Ajouter une charge
ecrans: [/charges]
questions:
  - Comment ajouter une charge ?
  - Comment ajouter la taxe foncière ?
  - C’est quoi « Comment elle se paie » ?
  - Comment ajouter une charge trimestrielle ou annuelle ?
  - Je ne trouve pas ma charge dans la liste, que faire ?
sources:
  - src/pages/Charges.tsx
  - src/ui/charges/Catalogue.tsx
  - src/lib/budget/charges.ts
  - src/lib/budget/categories.ts
  - src/lib/budget/feuilles.ts
  - src/ui/budget/Gestes.tsx
  - src/lib/donnees/budget.ts
  - supabase/migrations/0050_catalogue_charges.sql
  - supabase/migrations/0085_ce_quon_reconnait.sql
  - supabase/migrations/0096_budget_facon.sql
  - supabase/migrations/0098_budget_lignes_nees.sql
verifie_sur: fa94f4a
---
Une charge est une dépense qui revient (loyer, assurance, taxe foncière). Le bouton « Mes charges » de l’écran du mois ouvre la page « Les charges » : tu y poses toutes tes charges.

## Comment faire

1. Dans « Ou une par une », cherche (champ « Chercher : « assurance », « mobile »… ») ou ouvre une rubrique (Logement, Auto, Abonnements…), puis touche la ligne. Rien ne correspond ? Touche « Autre chose », sous les rubriques.
2. Remplis « Quoi » (80 caractères au plus) et « Combien (€) », au-dessus de 0 € et au plus 1 000 000 €. C’est le montant de la période : 1 200 € pour une taxe foncière annuelle, pas 100 €.
3. Choisis « Catégorie » : Vie courante, Maison, Crédits, Auto, Abonnements, Santé, Impôts ou Autre. Le catalogue la propose selon la section.
4. Choisis « Comment elle se paie » :
   - « Fixe » : le même montant chaque mois (un loyer).
   - « Une facture chaque mois » : le montant est une estimation, tu donnes le vrai chiffre chaque mois (Électricité, Gaz).
   - « Plusieurs dépenses dans le mois » : le montant est un plafond, tu déclares tes dépenses au fil du mois (Courses).
   - « Mise de côté » : pour ce qui ne tombe pas chaque mois. Tu choisis « Tous les trois mois » ou « Une fois par an ».
5. Règle « Qui participe », « Comment la partager », « Elle court depuis » et « Payée depuis » (pages à part).
6. Touche « Ajouter cette charge ».

## La mise de côté

Le formulaire annonce « On en met de côté le douzième chaque mois » (le tiers pour le trimestriel) et la somme. Une charge de 1 200 € par an met 100 € de côté chaque mois ; 300 € par trimestre aussi.

Une charge trimestrielle ou annuelle est toujours « Mise de côté ». Les trois autres façons sont toujours mensuelles.

## Le catalogue

Le catalogue est rangé par rubrique : la première est ouverte, les autres se déplient d’un toucher, et une recherche ouvre celles qui répondent. Chaque ligne arrive préremplie : rythme, façon, catégorie, partage. « Taxe foncière » est annuelle et commune, « Électricité » est une facture chaque mois, « Courses » se dépense au fil du mois. Tu peux tout changer avant d’ajouter.

## À savoir

- Il n’y a que trois rythmes : par mois, par trimestre, par an. Rien pour « tous les deux ans ».
- Dès l’ajout, les mois écoulés depuis la date « Elle court depuis » reçoivent leur ligne, sauf les mois clôturés et ceux d’avant l’arrivée des participants.
- Le total en haut de la page ramène tout au mois et ne compte que les charges déjà en vigueur ce mois-là et dont au moins un participant est déjà dans le foyer. Les charges sont rangées par catégorie, avec le total de chacune ; touche l’en-tête d’une catégorie pour la replier ou la rouvrir (l’appareil s’en souvient).
- Avant ton arrivée dans le foyer, la page se cale sur ton mois d’arrivée : elle le dit en haut, et les montants sont ceux de ce mois-là.
