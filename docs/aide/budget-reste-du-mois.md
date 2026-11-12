---
id: budget-reste-du-mois
titre: Le reste du mois et son calcul
ecrans: [/, /budget]
questions:
  - Comment est calculé « Il te reste » ?
  - Pourquoi mon reste ne baisse pas quand je déclare une dépense ?
  - Pourquoi « Il te manque » ?
  - C’est quoi « après X € de charges prévues » ?
  - Pourquoi il n’y a pas de reste sur un vieux mois ?
  - Que veut dire la barre en couleurs ?
sources:
  - src/lib/budget/mois.ts
  - src/ui/budget/Recap.tsx
  - src/ui/budget/Ligne.tsx
  - src/pages/Budget.tsx
  - src/pages/Hub.tsx
verifie_sur: 5fc4aa2
---
« Il te reste » est la carte sombre de l'écran du mois. L'accueil donne le même chiffre, arrondi à l'euro.

## Le calcul

**Il te reste = ton revenu du mois − ta part de chaque ligne du mois.**

- **Ton revenu du mois** : le plus récent dont la date d'effet ne dépasse pas le dernier jour du mois. Si ton revenu change en janvier, décembre reste calculé sur l'ancien.
- **Ta part** : ce que le partage te donne de la ligne. Une ligne où tu n'as aucune part ne compte pas pour toi, même si tu la vois.

Ce que pèse une ligne :

- **Plusieurs dépenses dans le mois** : le plus grand des deux, le prévu ou le déclaré (toutes les dépenses déclarées sur la ligne, par l'un ou par l'autre).
- **Une facture chaque mois** : le montant habituel tant que la facture n'est pas validée, puis le montant retenu.
- **Fixe**, **Mise de côté**, ajustement : le montant de la ligne.

## Exemple

Revenu : 2 500 €. Tes parts de charges prévues : 1 750 €. Il te reste **750 €**. Parmi elles, « Courses » : 500 € prévus, dont ta part est de 60 %, soit 300 €.

- Tu déclares 350 € de courses : rien ne bouge, 750 €. La ligne compte toujours ses 500 € prévus.
- Tu déclares 650 € : la ligne compte 650 €, ta part passe à 390 € (+ 90 €). Il te reste **660 €**.

Le chiffre ne baisse donc que si tu dépasses le prévu. Si tu dépenses moins, la différence ne te revient qu'à la clôture.

## Ce que montre la carte

- « sur 2 500 € de revenus » et « après 1 750 € de charges prévues » : c'est la somme de **tes** parts. Seul, c'est le total du foyer ; à deux, non.
- **« Il te manque »** quand le total dépasse ton revenu. Le chiffre est montré sans signe.
- **La barre** : tes parts par catégorie, et un morceau « Reste », en pourcentages entiers qui font 100. Quand il te manque de l'argent, il n'y a pas de morceau « Reste ».

## Sans chiffre

« Ajoute ton revenu pour voir ce qu’il te reste. » et le bouton « Revenus » : pas de revenu pour ce mois, y compris pour un mois d'avant ton premier revenu. Avant ton arrivée dans le foyer : voir la page sur l'arrivée.

Sur un mois clôturé, le chiffre est celui du jour de la clôture : « Il t’est resté ».
