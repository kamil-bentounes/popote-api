---
id: compte-profil
titre: Ton profil : prénom, revenu, arrivée
ecrans: [/profil]
questions:
  - Comment changer mon prénom ?
  - À quoi sert mon revenu net mensuel ?
  - Pourquoi l’appli me demande ma date d’arrivée dans le foyer ?
  - Comment corriger mon revenu ou ma date d’arrivée ?
  - C’est quoi « Complète ton profil » ?
sources:
  - src/pages/Profil.tsx
  - src/App.tsx
  - src/pages/Hub.tsx
  - src/lib/donnees/foyer.ts
  - src/lib/donnees/budget.ts
  - src/lib/budget/revenu.ts
  - src/lib/budget/mois.ts
  - supabase/migrations/0051_budget_socle_corrige.sql
  - supabase/migrations/0103_budget_arrivees.sql
  - supabase/migrations/0112_budget_depart.sql
verifie_sur: 5fc4aa2
---
## Ce que fait l’écran

Ton profil donne à l’appli ton prénom, ton revenu et ta date d’entrée dans le foyer. On l’ouvre avec le rond qui porte ton initiale, en haut à droite de l’accueil de Popote (ou de l’écran du budget). Un « ? » dans le rond : ton prénom est vide.

## Les trois champs

- **« Ton prénom »** : 40 caractères au plus. Les autres le lisent sur chaque ligne de charge. Vide, il s’affiche « Sans prénom ».
- **« Ton revenu net mensuel (€) »** : après impôt (2 500 ou 2 500,50). Il ne sert qu’à calculer votre partage du budget, et **le foyer le voit**. Sous 100 € par mois, l’appli demande « Tu déclares 0,50 € par mois. C’est bien ça ? » (avec ton montant) : « Oui, c’est ça » ou « Non, je corrige ». Zéro est refusé.
- **« Ton arrivée dans le foyer »** : le jour à partir duquel tu habites là. C’est elle qui décide des mois que tu partages. Au plus deux ans à l’avance (au-delà, la base refuse).

« Enregistrer » ne s’allume que quand les trois champs sont remplis.

## Ce que ça déclenche

- **Sans ton revenu** (ou si l’un de ceux qui sont là ce mois-là n’en a pas), le partage se fait à parts égales. Sur l’accueil, le bandeau « Complète ton profil. » s’affiche quand ton prénom ou ton revenu manque (il ne regarde que toi).
- Ton **premier revenu** compte dès le mois de ton arrivée, sauf pour un mois déjà clôturé. Les revenus suivants prennent effet le mois où tu les saisis.
- **Date dans le futur** : l’appli écrit « Tu arrives plus tard : tu ne participeras à aucune charge d’ici là. » L’accueil de Popote compte les jours jusqu’au 1er de ce mois (« Commence en … » quand aucune charge n’est posée).
- **Changer la date** repartage les mois situés entre l’ancienne et la nouvelle date. Un mois déjà clôturé ne bouge pas.
- À ton arrivée, tu es ajouté(e) aux charges communes déjà posées.

## Exemple

Une personne arrive le 15 novembre et pose son revenu le 2 décembre : il vaut dès novembre, si novembre n’est pas clôturé.

## Si tu es invité(e)

En rejoignant par un lien, ton prénom est vide et ta date d’arrivée est le 1er du mois suivant. L’appli t’amène sur ton profil à chaque ouverture, tant que ton prénom est vide. Tu peux appuyer sur « ‹ Popote » pour le remettre à plus tard : l’accueil te le rappellera.

## Ce que l’appli ne fait pas

Je n’ai pas trouvé d’écran pour supprimer un revenu.
