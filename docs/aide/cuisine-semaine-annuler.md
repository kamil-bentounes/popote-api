---
id: cuisine-semaine-annuler
titre: La semaine : annuler « Je l’ai mangé »
ecrans: [/semaine]
questions:
  - Comment annuler « Je l’ai mangé » si je me suis trompé ?
  - Comment remettre un repas à prévu ?
  - Que devient la barquette quand j’annule ?
  - Le bandeau « Noté : mangé. » a disparu, comment annuler ?
  - Est-ce que ça change le repas de Léa ?
sources:
  - src/pages/Semaine.tsx
  - src/pages/Hub.tsx
  - src/pages/Accueil.tsx
  - src/ui/semaine/Carte.tsx
  - src/ui/semaine/AnnulerLeMange.tsx
  - src/ui/semaine/MangeAujourdhui.tsx
  - src/lib/annuler-mange.ts
  - src/lib/donnees/barquettes.ts
  - supabase/migrations/0129_annuler_mange.sql
verifie_sur: 5fc4aa2
---
## Ce que fait l’appli

Un faux appui se rattrape, sur « La semaine » (aujourd’hui comme les jours passés), sur l’accueil de Popote et sur l’accueil de la cuisine.

- **Tout de suite** : un bandeau sombre « Noté : mangé. » reste 6 secondes avec **« Annuler »**. Un seul toucher suffit, sans question. Le délai s’arrête tant que le pointeur ou le focus est sur le bandeau.
- **Ensuite**, tant que ta case est « mangé » : la carte dit **« Mangé à 12 h 40 »** (l’heure à laquelle tu l’as noté ; si tu l’as noté un autre jour que celui du repas, **« Noté mangé le mar. 27 oct. à 9 h 12 »**) et propose le lien **« Pas mangé ? Annuler »**. Il demande confirmation dans la carte : « Remettre ce repas à « prévu » ? Ta part redevient prévue et la barquette revient au frigo. Si elle venait du congélateur, elle y retourne. » Puis **« Oui, remettre »** ou **« Non, garder »**. Sur l’accueil de Popote et de la cuisine, ce lien vit sous la carte sombre, dans une carte « Midi : … » par repas déjà noté.

Ce que ça fait : **ta** case repasse à « prévu » et l’heure notée s’efface ; la part est rendue là où elle était (5 parts au frigo redeviennent 6 ; une part du congélateur y retourne ; une part décongelée revient décongelée, **avec sa date limite**) ; la case de l’autre personne ne bouge pas ; le repas ne compte plus dans les calories et protéines jusqu’à ce qu’il soit de nouveau noté. Si l’autre personne a noté **la même part**, elle reste mangée tant qu’elle ne l’annule pas aussi. Ce que tu as mangé « en plus » d’un plat n’est pas touché : il garde son « Retirer ». Pour « Autre chose » (sans barquette), le repas entier ne compte plus au bilan, sur un jour passé comme aujourd’hui, jusqu’à ce que tu le notes de nouveau. Une case que l’autre téléphone vient déjà de remettre à « prévu » ne rend rien une seconde fois : tu n’as pas d’erreur, l’écran se met à jour.

Le geste « En manger une maintenant » de la fiche d’un plat n’a pas ce bandeau : le repas du midi ou du soir qu’il note s’annule ensuite depuis « La semaine ».

## Les règles

- Seule **ta** case s’annule : la base refuse celle de l’autre personne, et celle d’un autre foyer.
- Une case qui n’est pas « mangé » ne s’annule pas : l’appli dit « Ce repas n’est pas noté mangé : rien à remettre. »
- Un jour passé s’annule comme aujourd’hui : « Mangé à 19 h 05 » et le lien restent tant que la case est « mangé ».
