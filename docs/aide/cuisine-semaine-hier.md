---
id: cuisine-semaine-hier
titre: La semaine : noter hier et les jours passés
ecrans: [/semaine]
questions:
  - Comment noter ce que j’ai mangé hier ?
  - J’ai oublié de noter mon repas d’hier, que faire ?
  - Que veut dire « pas encore noté » ?
  - Jusqu’à quand puis-je noter un repas passé ?
  - Pourquoi la barquette sort du frigo quand je note hier ?
sources:
  - src/pages/Semaine.tsx
  - src/ui/semaine/Bandeau.tsx
  - src/ui/semaine/Carte.tsx
  - src/ui/semaine/FeuilleDeChoix.tsx
  - src/lib/choix.ts
  - src/lib/donnees/barquettes.ts
  - supabase/migrations/0125_semaine_corrections.sql
  - supabase/migrations/0128_semaine_hier.sql
verifie_sur: 9b03c3e
---
## Ce que fait l’appli

Le bandeau de « La semaine » remonte de **sept jours** : sept jours passés, aujourd’hui, puis les six suivants. Il s’ouvre sur aujourd’hui, avec hier visible à sa gauche ; un petit « ‹ » dit qu’il y a des jours plus anciens. Un jour passé est dessiné en **pointillé**, son numéro en gris, et **« hier »** remplace l’abréviation d’hier.

Les deux points sous chaque jour restent : **creux**, c’est un repas pas noté. Sous le titre (« Lundi 26 octobre », avec « hier » en ocre pour hier ; pour les autres jours passés, la date seule), une phrase : « Un jour passé : tu notes ce que tu as mangé. Les barquettes que tu coches sortent du frigo ou du congélateur. »

## Noter un repas passé

- Un repas vide dit **« + Noter ce que j’ai mangé ce midi »** (ou « ce soir »). Pour une seule personne : « + Noter ce que Léa a mangé ce soir ». Touche-le : la feuille de choix s’ouvre **sur toi** (« Pour » : Kamil), avec « Un jour passé : ce que tu choisis est noté mangé… ». Pour noter aussi l’autre personne, touche « Vous deux » ou son prénom : rien n’est noté à sa place sans ce choix. Choisis une barquette, un aliment à nous, un repère, ou **« On saute ce repas »**.
- Un repas déjà posé mais pas marqué mangé dit **« … · pas encore noté »**. **« Je l’ai mangé »** note ta part ; « Changer » ouvre la même feuille. Quand une seule personne l’a mangé : « Kamil l’a mangé, pas encore noté pour Léa ».
- **Ce que tu choisis est mangé**, puisque le repas a eu lieu : la barquette quitte le frigo ou le congélateur, comme avec « Je l’ai mangé ». La case est notée à l’heure habituelle du repas (8 h, 12 h, 16 h ou 19 h). « On saute ce repas » reste « sauté ».
- Un repas noté mangé par erreur se remet à « prévu » avec **« Pas mangé ? Annuler »** (voir « cuisine-semaine-annuler »).
- Sous un plat, **« + ce que j’ai mangé en plus »** note un dessert (voir « cuisine-semaine-en-plus »).

## Les règles

- On note **sept jours** en arrière : au-delà, la base refuse.
- **On peut toujours laisser un repas vide**, passé ou à venir : c’est un trou, hors des moyennes du bilan, pas un repas à zéro.
- Une barquette déjà réservée par un repas **à venir** n’est pas libre pour un repas passé : la ligne est grisée.
- Un repas déjà noté mangé ne se change plus pour cette personne.
- Un jour passé ne dit plus « périme avant ce repas » ni quand sortir du congélateur : sous la barquette, « sort du frigo » ou « sort du congélateur ».
