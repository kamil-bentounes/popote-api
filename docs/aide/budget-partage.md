---
id: budget-partage
titre: Le partage au prorata ou moitié-moitié
ecrans: [/budget-reglages, /charges]
questions:
  - Comment est calculée ma part d’une charge commune ?
  - C’est quoi « Au prorata » et « Moitié-moitié » ?
  - Que se passe-t-il s’il manque un revenu ?
  - Comment changer la règle de partage ?
  - Puis-je partager une charge autrement que les autres ?
sources:
  - src/pages/BudgetReglages.tsx
  - src/pages/Charges.tsx
  - src/ui/budget/Gestes.tsx
  - src/lib/donnees/budget.ts
  - src/lib/budget/mois.ts
  - supabase/migrations/0065_gardes_manquantes.sql
  - supabase/migrations/0100_budget_mois_gele.sql
  - supabase/migrations/0102_budget_mois_suivis.sql
  - supabase/migrations/0105_budget_cible.sql
verifie_sur: fa94f4a
---
Chaque ligne d’une charge commune se répartit entre ses participants, au centime près. Les parts sont figées sur la ligne.

## La règle du foyer

Dans « Réglages du budget » (bouton « Revenus » de l’écran du mois), section « Comment vous partagez » :
- « Au prorata » : chacun paie selon son net mensuel.
- « Moitié-moitié » : parts égales.

Sans choix enregistré, c’est « Au prorata ». Le changement vaut à partir de ce mois : les mois déjà partagés ne bougent pas.

## Le calcul

Au prorata, ta part = ton net ÷ la somme des nets des personnes présentes ce mois-là. Pour un mois, on prend le revenu le plus récent daté d’avant la fin du mois.

Exemple : loyer de 800 €, nets de 3 000 € et 2 000 €. Total 5 000 €, donc 60 % et 40 % : 480 € et 320 €. En moitié-moitié : 400 € chacun.

Sur une charge, seuls les participants se partagent le montant, dans les proportions du foyer. Une seule personne : 100 % pour elle. Seul dans le foyer : tout est à toi, la règle ne change rien. Les parts sont arrondies au centime, leur somme fait toujours le montant exact.

## S’il manque un revenu

Dès qu’une personne présente ce mois-là n’a pas de revenu, tout le monde est compté à parts égales, même si la règle est « Au prorata ». C’est vrai aussi pour une charge qui impose « Au prorata ». L’écran le dit : « Tant qu’il en manque un, le partage se fait à parts égales — même si tu as choisi le prorata. » Quelqu’un qui n’est pas encore arrivé ce mois-là ne « manque » pas.

## Une charge à part

À l’ajout, quand au moins deux personnes participent, « Comment la partager » propose « Comme le foyer » (suit la règle), « Au prorata » ou « Moitié-moitié ». Le panneau « Corriger » ne la change pas ensuite.

## Quand une part bouge

Poser un revenu ou changer la règle refait le partage des mois ouverts à partir du mois d’effet. Restent intacts : les mois clôturés et les lignes déjà confirmées ou réglées.
