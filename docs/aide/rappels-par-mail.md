---
id: rappels-par-mail
titre: Les rappels par mail
ecrans: [/rappels]
questions:
  - Comment activer un rappel par mail ?
  - Léa voit-elle mes rappels ?
  - Pourquoi je ne reçois pas de mail de rappel ?
  - Comment tester le mail avant de l’activer ?
  - Où sont les rappels par mail ?
sources:
  - src/pages/Rappels.tsx
  - src/lib/rappels.ts
  - src/lib/donnees/rappels.ts
  - src/pages/Settings.tsx
  - supabase/migrations/0126_rappels.sql
  - supabase/functions/rappels/index.ts
  - supabase/functions/_shared/rappels/mails.ts
  - supabase/functions/_shared/rappels/service.ts
verifie_sur: 84225ae
---
## Ce que fait l’appli

Elle t’envoie des mails de la part de « Popote », à l’adresse avec laquelle tu te connectes, seulement quand il y a quelque chose à faire. Il y a sept rappels. **Tous sont coupés tant que tu ne les actives pas** : rien ne part à qui n’a rien demandé.

## Où les régler

« Réglages », carte « Les rappels par mail », bouton « Régler mes rappels ». L’écran « Les rappels par mail » a une carte par rappel : son moment, une phrase qui dit quand il part, un interrupteur (« Activé » ou « Coupé ») et « M’envoyer un exemple ». L’interrupteur agit tout de suite ; il est grisé le temps que la demande parte, et si elle échoue il revient à l’état d’avant.

## Chacun les siens

Tes réglages sont à toi seul. L’autre personne du foyer ne voit pas les tiens, tu ne vois ni ne règles les siens. Léa ne reçoit donc rien tant qu’elle n’a rien activé elle-même.

## Tester

« M’envoyer un exemple » envoie UN mail d’exemple, avec « [Exemple] » devant le sujet, à ton adresse seulement. Il faut que ton adresse soit confirmée, sinon l’écran répond « Confirme d’abord ton adresse e-mail. ». Les données sont inventées ; il ne compte pour rien et n’empêche aucun vrai rappel de partir. Un seul exemple par rappel et par heure : un second, dans la même heure, répond « Tu as déjà demandé cet exemple pendant cette heure ».

## Si rien n’arrive

Vérifie que l’interrupteur dit « Activé » et regarde dans les indésirables. Un rappel ne part que s’il y a quelque chose à rappeler. Il n’existe pas aujourd’hui d’historique des envois à l’écran (j’ai cherché).

## Ce que l’appli ne fait pas

Pas de notification sur le téléphone : des mails seulement. Les jours et les heures sont fixes, on ne les change pas. Il n’existe pas de rappel pour les courses ni pour la session de cuisine.

Le détail des sept rappels, leurs heures et le lien « C’est fait, c’est au frigo » : voir « rappels-les-sept ».
