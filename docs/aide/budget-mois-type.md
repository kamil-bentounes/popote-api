---
id: budget-mois-type
titre: Le mois type
ecrans: [/mois-type, /budget]
questions:
  - C’est quoi le mois type ?
  - Combien chacun paie par mois ?
  - Pourquoi une charge annuelle est comptée au mois ?
  - Pourquoi une charge est grisée ?
sources:
  - src/pages/MoisType.tsx
  - src/ui/budget/MoisType.tsx
  - src/lib/budget/mois-type.ts
  - src/pages/Budget.tsx
  - src/pages/Hub.tsx
  - src/App.tsx
  - src/lib/donnees/budget.ts
  - src/lib/budget/charges.ts
  - src/lib/budget/categories.ts
  - src/lib/budget/mois.ts
  - supabase/migrations/0102_budget_mois_suivis.sql
verifie_sur: 5fc4aa2
---
## Ce que c’est

Tes charges **telles qu’elles sont posées**, ramenées au mois, et ce que chacun en paie. Ce n’est pas l’écran du mois : il se lit même avant le début du budget.

## Où le trouver

- Avant ton arrivée dans le foyer, l’écran du budget le montre pour le mois où tu entres (« Pas encore » tant que rien n’est posé). La tuile « Budget » de l’accueil le dit aussi : « Ton mois type, chaque mois », ton reste, tes charges et le compte à rebours.
- Ensuite : la carte **« Le mois type »** de l’écran du budget.

## Comment il est calculé

- Il se calcule pour le mois en cours ou, si tu n’es pas encore dans le foyer, pour le mois de ton arrivée.
- Un trimestre compte un tiers, une année un douzième : une taxe foncière de 1 200 € par an pèse 100 € par mois.
- Le partage est celui du budget : au prorata des revenus, ou moitié-moitié si la charge est réglée ainsi ou si un revenu manque. Qui n’est pas encore arrivé n’a aucune part.
- Une charge qui commence plus tard (« commence plus tard »), ou dont personne de ceux qui la paient n’est encore dans le foyer (« pas encore dans le foyer »), est grisée et n’entre dans aucun total. Une charge retirée ne compte pas.

## L’écran « Le mois type »

- **« Le foyer »** ou un prénom : le sélecteur recompte l’anneau et les catégories sur la part de cette personne.
- **L’anneau** : une couleur par catégorie, le total au centre. Touche un arc ou sa légende : le centre montre la catégorie et sa part du mois ; retouche-la, le total revient.
- **Une jauge par personne** (sur « Le foyer ») : la part du revenu que ses charges prennent, son total, « Commun » et « À soi », puis « Il reste 420 € sur 2 500 € » ou « Il manque… ». Sans revenu : un tiret dans la jauge et « Revenu pas encore posé ».
- **« Par catégorie »** : une carte par catégorie, avec son total et ce que paie chacun. Elle ouvre ses lignes ; « Toutes les lignes » ouvre tout.
- Si « Autre » pèse au moins 20 % du mois, un encart propose « Ranger mes charges ».

Le tableau de toutes les charges, avec recherche et filtres, a sa page (« budget-toutes-les-charges »).

## Ce que ça ne fait pas

Rien ne s’y règle ni ne s’y déclare, et il ne compte pas les dépenses réelles.
