---
id: compte-objectifs
titre: Tes objectifs nutritionnels
ecrans: [/objectifs]
questions:
  - Comment régler mes objectifs de calories et de protéines ?
  - Pourquoi mes barquettes sont-elles dressées à parts égales ?
  - Qu’est-ce que « Fixe tes objectifs » ?
  - Est-ce que Léa voit mes objectifs ?
  - Comment changer mes objectifs ?
  - À quoi servent les objectifs dans l’appli ?
  - Quelles sont les valeurs par défaut des objectifs ?
  - Peut-on revoir mes anciens objectifs ?
sources:
  - src/pages/Targets.tsx
  - src/ui/reglages/coque.tsx
  - src/lib/donnees/foyer.ts
  - src/pages/Dressage.tsx
  - src/pages/Hub.tsx
  - src/pages/Inventer.tsx
  - src/lib/donnees/bilan.ts
  - src/lib/nutrition/portions.ts
  - src/pages/Accueil.tsx
  - supabase/migrations/0005_policies.sql
verifie_sur: 5fc4aa2
---
## Ce que fait l’écran

« Mes objectifs » fixe ce que tu vises **chaque jour** : calories, protéines, fibres, glucides, lipides. Chacun a les siens (« Ta moitié a les siens »). Tu y vas par « Objectifs » dans le sélecteur « Objectifs | Réglages » en haut de « Réglages » et de « Mes objectifs », par le bandeau « Fixe tes objectifs. » de l’accueil de Popote (si ton prénom et ton revenu sont posés ; sinon c’est « Complète ton profil. »), ou par le bouton « Fixe tes objectifs » du dressage (quand c’est toi qui n’en as pas).

## Comment faire

1. Fais glisser chaque curseur.
2. Appuie sur « Enregistrer » : « Objectif enregistré. »

Limites : calories de 1 200 à 4 000 kcal (pas de 50) ; protéines de 40 à 250 g (pas de 5) ; fibres de 10 à 60 g (pas de 1) ; glucides de 50 à 500 g (pas de 10) ; lipides de 20 à 150 g (pas de 5).

Tant que tu n’as rien enregistré, les curseurs partent de 2 000 kcal, 150 g de protéines, 30 g de fibres, 200 g de glucides et 60 g de lipides. Ce ne sont pas des objectifs tant que tu n’as pas appuyé sur « Enregistrer ».

## Les règles

- Chaque « Enregistrer » ajoute une ligne : les anciens restent sous « Ce que tu visais avant » (date, calories, protéines, le dernier compris).
- **Sans objectifs, tes barquettes sont dressées à parts égales** : chacune pèse la moyenne des parts des autres. L’étape de dressage le dit : « … n’a pas encore fixé ses objectifs : ses barquettes sont dressées à parts égales. » Le bandeau de l’accueil dit : « Sans tes objectifs, tes barquettes sont dressées à parts égales. »

## À quoi ils servent

- **Dressage** : le poids de ta part. Un dîner vaut **35 %** de ta journée, en calories et en protéines : avec 2 000 kcal et 150 g de protéines, 700 kcal et 52,5 g (voir « cuisine-portions »).
- **Accueil** : « kcal aujourd’hui, sur … », avec une barre, quand un repas est prévu aujourd’hui (sans repas, rien ne s’affiche). **Bilan** : la cible tracée sur les graphes de chacun (rien n’est tracé pour qui n’a pas d’objectifs).
- **Inventer** : les bornes de départ (calories et protéines d’un dîner, soit 35 % de ta journée), modifiables là-bas. Le modèle de langage ne voit jamais tes objectifs, seulement ces bornes. Sans objectifs enregistrés, elles partent de 30 g et 620 kcal.

## Qui voit quoi

L’autre personne du foyer peut lire tes objectifs ; seul(e) toi peux modifier les tiens. Les foyers amis ne les voient jamais.

## Ce que l’appli ne fait pas

Elle ne calcule pas d’objectif à partir de ton poids ou de ton âge : tu choisis les chiffres.
