---
id: rappels-un-seul-mail
titre: Un seul mail par jour, et ce qui ne repart pas
ecrans: [/rappels]
questions:
  - Pourquoi je n’ai pas reçu de mail pour la barquette que j’ai ajoutée ?
  - Pourquoi un seul mail pour plusieurs barquettes qui périment ?
  - Que veut dire « Prévue samedi, mais elle périme mercredi » ?
  - Pourquoi le mail de clôture parle du revenu de quelqu’un d’autre ?
  - Pourquoi je n’ai pas reçu un deuxième mail ?
sources:
  - supabase/migrations/0126_rappels.sql
  - supabase/functions/_shared/rappels/mails.ts
  - supabase/functions/_shared/rappels/texte.ts
verifie_sur: 8748fad
---
## Un mail perdu vaut mieux qu’un doublon

Popote n’envoie jamais deux fois le même mail. Quand un rappel est parti pour un jour, une semaine ou un mois, il ne repart pas, même si la situation change après coup. Un rappel coupé juste avant son heure ne part pas : Popote revérifie l’interrupteur au moment d’envoyer.

## Après le mail de 19 h

« Sortir du congélateur » part une fois, à 19 h, pour le lendemain. Si tu prévois une barquette congelée pour demain APRÈS ce mail, aucun second mail ne part : sors-la toi-même, ou dans le doute décongèle-la au micro-ondes. Même chose pour une barquette posée au frigo après le mail de 8 h : elle attend le lendemain.

## Les barquettes qui périment

« Une barquette va périmer » est UN mail par jour, qui liste tous les plats concernés, du plus pressé au moins pressé. Il compte les barquettes du frigo qui périment avant demain soir et ne sont prévues dans aucun repas, et celles qui ont péri depuis moins de 24 heures : celles-ci sont annoncées « Périmée : à jeter ».

Une barquette prévue pour un repas APRÈS sa péremption compte comme non prévue, et le mail le dit : « Prévue samedi, mais elle périme mercredi ».

## Les factures annuelles

Plusieurs charges annuelles qui tombent le même jour : un seul mail, qui les liste.

## Clôturer le mois

Le mail du dernier jour du mois te prévient que tu pourras clôturer le lendemain. La clôture est refusée tant qu’une autre personne du foyer n’a pas posé son revenu de ce mois : le mail le dit alors (« Léa doit encore poser son revenu de novembre ») au lieu de promettre la clôture.

## Les exemples

« M’envoyer un exemple » est limité à un exemple par rappel et par heure : un second répond « Tu as déjà demandé cet exemple pendant cette heure ».
