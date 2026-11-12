# Le manuel de l'aide intégrée

Ces pages sont lues par le modèle de l'aide (« Demande à Popote »). **Le code prime toujours** : une page qui
contredit le code est fausse, pas le code.

## Format d'une page (`docs/aide/<id>.md`)

```
---
id: budget-charges            # identique au nom du fichier, sans .md ; minuscules, chiffres, tirets
titre: Les charges            # court, tel qu'on le dirait à voix haute
ecrans: [/charges]            # les routes de l'appli où cette page sert (voir src/App.tsx), peut être vide
questions:                    # 3 à 6 questions comme Kamil ou Léa les poseraient, avec leurs mots à eux
  - Comment ajouter la taxe foncière ?
sources:                      # TOUS les fichiers dont dépend une affirmation de la page (code, migrations)
  - src/pages/Charges.tsx
  - src/lib/budget/charges.ts
verifie_sur: 8b43c99          # le commit contre lequel la page a été vérifiée
---
Corps en français, « tu », mots simples, phrases courtes. 450 mots au plus (sinon on coupe en deux pages).
```

Le corps dit, dans cet ordre quand c'est utile : **ce que fait l'appli**, **comment faire** (les étapes, avec les
libellés EXACTS des boutons et champs tels qu'ils s'affichent), **les règles et les calculs** (avec un exemple chiffré
que le code confirme), **ce que l'appli ne fait pas**.

## Règles d'écriture

1. Chaque phrase se vérifie dans le code. Pas sûr : on ne l'écrit pas, on le note dans `_incertain-<domaine>.md`.
2. Aucun jargon de développeur dans le corps (pas de « trigger », « RLS », « edge function », « table »…) ni de
   chemin de fichier : le lecteur n'est pas développeur. Les fichiers vont dans `sources`, et nulle part ailleurs.
3. Les libellés d'écran sont recopiés tels quels, avec leur typographie (« Créer l’invitation »).
4. Un chiffre (30 jours, 20 dictées par mois…) vient du code, pas de la mémoire.
5. Une négation (« l'appli ne sait pas… ») ne s'écrit que si on a cherché et qu'on n'a rien trouvé : le dire dans la
   page, par exemple « Il n'existe pas aujourd'hui de… ».
6. Pas de secret, pas de clé, pas d'adresse d'API, pas de donnée réelle de Kamil ou de Léa.

## La péremption

`verifie_sur` + `sources` servent à `npm run manuel:verifie` : si un fichier de `sources` a changé depuis ce commit,
la page est **périmée** et le déploiement refuse de partir tant qu'elle n'a pas été relue contre le code et
re-datée. Garde donc `sources` précis (la logique et les écrans cités), sans y mettre tout le dépôt.
