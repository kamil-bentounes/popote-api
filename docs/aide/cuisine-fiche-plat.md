---
id: cuisine-fiche-plat
titre: La fiche d’un plat : parts, dates, photo
ecrans: [/frigo]
questions:
  - Comment corriger la date d’une barquette ?
  - Que veut dire « Prévues pour vous deux » ?
  - Pourquoi la fiche donne deux poids de part différents ?
  - Comment ajouter la photo d’un plat ?
  - Combien de temps se garde une barquette au congélateur ?
sources:
  - src/ui/frigo/FichePlat.tsx
  - src/ui/frigo/Combien.tsx
  - src/ui/frigo/ChampDate.tsx
  - src/lib/frigo.ts
  - src/lib/donnees/frigo.ts
  - src/lib/reseau.ts
  - src/lib/peremption.ts
  - src/lib/ranger.ts
  - supabase/migrations/0017_triggers_lot1.sql
  - supabase/migrations/0047_peremption_donnee.sql
  - supabase/migrations/0092_la_photo_et_les_gestes.sql
  - supabase/migrations/0121_photo_des_plats.sql
  - supabase/migrations/0122_frigo_corrections.sql
verifie_sur: ff3539b
---
## Ce que fait l’appli

Dans le frigo, touche la carte d’un plat : sa fiche s’ouvre en bas de l’écran (« cuisine-stock » décrit le frigo). Ses gestes (manger, congeler, sortir, jeter, retirer) sont dans « cuisine-fiche-plat-gestes ». Tant que les repas prévus ne sont pas lus (chargement, erreur), la fiche le dit et ses gestes restent grisés.

## Ce que dit la fiche

Lieu, nom, nombre de parts, ce que pèse une part, les repas où il est posé (« Prévues pour vous deux », « Prévues pour Kamil », ou « Pas encore » ; un repas d’avant aujourd’hui n’y est plus), les dates.

- **Une part est pour quelqu’un** : si toutes sont pareilles, une phrase (« 784 g, 682 kcal et 56 g de protéines la part »). Sinon une ligne par personne (« Kamil : 784 g, 682 kcal, 56 g de protéines », « Léa : … »), jamais une moyenne qui ne serait la part de personne.
- **Dates** : « Au frigo depuis » ou « Congelés le » (pas dans le futur) recalcule « À manger avant » : **4 jours** (96 heures pleines) au frigo, **90 jours** au congélateur. Une part décongelée se mange dans les **24 heures** : pas de « depuis » pour elle. « À manger avant », saisie à la main, prime (jusqu’à 23 h 59 ce jour-là). Enregistrer sans changer la date n’écrit rien ; une date changée ne réécrit que les parts qu’elle change.

Mots d’urgence au frigo : « encore N jours », « demain dernier délai », « à manger aujourd'hui », « périmée ». Au congélateur : « N j au congélateur », puis « à sortir sous N j ». Sur la carte, une part périmée dit « périmée » (« 1 périmée » si une seule l’est), et un plat dont les repas tombent après sa péremption dit son mot d’urgence, ou « périme avant mar. soir ».

## La photo d’un plat

« Prendre le plat en photo » (ensuite « Changer la photo ») n’existe que pour une recette **à ton foyer** (collée, inventée ou saisie), pas pour le catalogue. Elle est réduite (1 400 px), envoyée dans un seau public à ton foyer (2 Mo, JPEG, PNG ou WebP au plus) et devient la photo de la recette. Une photo que le téléphone ne lit pas (HEIC) ou trop lourde est refusée avec une phrase claire.
