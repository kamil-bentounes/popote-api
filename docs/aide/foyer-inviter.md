---
id: foyer-inviter
titre: Inviter quelqu’un dans le foyer
ecrans: [/reglages]
questions:
  - Comment inviter Léa ?
  - L’invitation part par mail ?
  - Combien de temps le lien d’invitation marche ?
  - Le lien d’invitation a expiré, que faire ?
  - Je n’ai pas reçu l’invitation, que faire ?
sources:
  - src/pages/Settings.tsx
  - src/pages/Hub.tsx
  - src/pages/BudgetReglages.tsx
  - supabase/functions/invite/index.ts
  - supabase/functions/accept-invite/index.ts
  - supabase/migrations/0071_invitation_trente_jours.sql
  - supabase/migrations/0089_le_lien_suffit.sql
verifie_sur: 5fc4aa2
---
## Ce que fait l’appli

Inviter, c’est créer un lien. **Aucun e-mail n’est envoyé** : c’est toi qui transmets le lien, par SMS, WhatsApp ou mail. Les anciens mails d’invitation ont été supprimés, parce que leur lien mourait au bout d’une heure.

## Comment faire

Trois chemins mènent au même endroit, la carte « Inviter » des réglages :

- sur l’accueil de Popote, la carte « Inviter quelqu’un. » (elle n’apparaît que tant que tu es seul(e) dans le foyer) ;
- dans les réglages du budget, le bouton « Inviter quelqu’un » (même condition) ;
- sur l’accueil de la cuisine, le rond avec ton initiale en haut à droite ouvre « Réglages » ; « Inviter » est la première carte.

Puis :

1. Écris l’adresse dans « Son e-mail ».
2. Appuie sur « Créer l’invitation ».
3. L’appli répond « Invitation créée pour … Envoie-lui ce lien. » et affiche « Son lien, valable 30 jours : ».
4. Appuie sur « Partager » (si ton téléphone le permet) ou « Copier le lien », puis envoie-le.

## Les règles

- Le lien vaut **30 jours** et **ne sert qu’une fois**.
- Sur l’écran d’inscription du lien, l’adresse saisie est affichée et ne se change pas. Quelqu’un qui a déjà un compte sans foyer peut aussi s’en servir, même avec une autre adresse.
- Quiconque a le lien peut s’en servir une fois : ne le publie pas.
- Si tu réinvites la même adresse alors qu’une invitation attend, tu récupères le même lien.
- Si l’invitation a expiré, retape la même adresse : tu obtiens un nouveau lien, valable 30 jours (l’ancien ne marche plus).
- Si l’adresse est déjà dans ton foyer, l’appli répond « Cette personne est déjà dans ton foyer. » Si elle est dans un autre foyer, le lien est créé, mais à l’ouverture l’appli répond « Cette adresse a déjà un compte Popote. »
- Une adresse mal écrite donne « Adresse e-mail invalide ».

## Exemple

Tu écris l’adresse de Léa, tu appuies sur « Créer l’invitation », tu copies le lien et tu le lui envoies sur WhatsApp. Elle l’ouvre sur son téléphone : voir la page « foyer-rejoindre ».

## Ce que l’appli ne fait pas

Il n’existe pas d’envoi automatique de l’invitation. Je n’ai pas trouvé d’écran qui liste les invitations en attente, ni de bouton pour en annuler une : retaper l’adresse redonne seulement le lien.

À ne pas confondre avec « Inviter un foyer » (réglages, section « Vos amis »), qui sert à échanger des recettes : page « reglages ».
