/**
 * GÉNÉRÉ par `npm run manuel:genere` depuis docs/aide/*.md — ne pas modifier à la main.
 * `npm run manuel:verifie` (et le déploiement) échouent si ce fichier n'est pas à jour.
 */
import type { PageDatee } from '../_shared/manuel.ts'

export const PAGES: PageDatee[] = [
  {
    "id": "accueil-ta-journee",
    "titre": "« Ta journée » sur l’accueil",
    "ecrans": [
      "/"
    ],
    "questions": [
      "Où je vois combien de calories j’ai mangé aujourd’hui ?",
      "Où sont mes protéines du jour ?",
      "Pourquoi « Ta journée » dit 0 kcal alors que j’ai mangé ?",
      "Que veut dire « 1 repas pas encore noté aujourd’hui » ?"
    ],
    "sources": [
      "src/pages/Hub.tsx",
      "src/ui/hub/TuileJournee.tsx",
      "src/lib/semaine.ts",
      "src/lib/donnees/foyer.ts"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "La carte **« Ta journée »** est sur l’accueil de Popote, sous la carte sombre du jour. Elle dit où tu en es aujourd’hui :\n\n- **les calories** : « 600 kcal, sur 2 200 », avec une barre verte ;\n- **les protéines** : « 50 g de protéines, sur 150 », avec une barre jaune.\n\nLe second chiffre, ce sont tes objectifs du jour (« compte-objectifs »). La barre s’arrête pleine quand tu les dépasses, mais le chiffre continue.\n\n## Ce qui compte\n\nLe même calcul que le bilan (« cuisine-bilan ») et l’accueil de la cuisine, pour toi seul :\n\n- une barquette compte quand tu as touché **« Je l’ai mangé »** ;\n- ce que tu as noté **« en plus »** (un yaourt, des céréales) compte tout de suite ;\n- un **« autre chose »** choisi pour un repas (un resto, un sandwich) compte une fois noté mangé.\n\nAnnuler un repas (« cuisine-semaine-annuler ») le retire aussitôt du chiffre.\n\n## « Pas encore noté »\n\n**« 1 repas pas encore noté aujourd’hui. »** : un repas d’aujourd’hui est prévu, et rien n’est noté dessus. Ce n’est pas un repas à zéro : le chiffre ne le compte pas encore. Note-le avec « Je l’ai mangé », ou dans « La semaine ».\n\n## Sans objectifs\n\nLes deux chiffres s’affichent sans « sur … » ni barre, avec **« Fixe tes objectifs pour voir où tu en es »**, qui ouvre « Objectifs ».\n\n## Aller plus loin\n\nToucher la carte (ou « Le bilan », au bureau) ouvre **« Bilan »** (« cuisine-bilan »).\n\nPendant le chargement, la carte affiche « … ». Si la semaine ne se lit pas, la carte n’apparaît pas : c’est la carte du jour qui dit la panne.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "aide-integree",
    "titre": "L'aide « Demande à Popote »",
    "ecrans": [],
    "questions": [
      "Comment fonctionne l'aide ?",
      "Où poser une question à l'appli ?",
      "L'aide voit-elle mes chiffres ?",
      "Que faire si l'aide se trompe ?"
    ],
    "sources": [
      "src/ui/Aide.tsx",
      "src/lib/aide/aide.ts",
      "src/lib/aide/suggestions.ts",
      "supabase/functions/aide/index.ts",
      "supabase/functions/aide/prompt.ts",
      "supabase/migrations/0118_aide_signalement.sql"
    ],
    "verifie_sur": "cc8b190",
    "corps": "**Ce que c'est.** Un petit assistant qui répond à tes questions sur l'appli : où cliquer, comment c'est calculé, ce qu'elle ne fait pas. Il répond d'après un manuel écrit à partir du code de l'appli, pas de mémoire. Si plusieurs pages parlent du sujet, il retient celle qui traite le cas décrit, et la cite.\n\n**Où le trouver.** Le bouton rond avec un « ? » est dans l'en-tête de l'accueil, du budget, de l'accueil de la cuisine, du dressage, des charges et de « Toutes nos charges », à côté de ton initiale. Sur tous les autres écrans, il flotte en haut à droite. Il ouvre la feuille « Demande à Popote », sur l'écran où tu es : tu n'as pas à le quitter. Tu la fermes avec la croix, en touchant à côté, ou avec la touche Échap.\n\n**Poser une question.** Touche une des questions proposées (celles de l'écran, puis « Souvent demandé »), ou écris la tienne dans « Pose ta question sur l’appli… » : 500 caractères au plus. Il garde en tête ta dernière question, donc tu peux enchaîner par « et si… ? ».\n\n**Ce qu'il te rend.**\n- La réponse, en quelques lignes.\n- Une ligne « Source » qui nomme la page du manuel et la date où elle a été relue contre le code.\n- Parfois un bouton « Ouvrir … » qui t'amène à l'écran dont il parle.\n- Une mise en garde en cas de doute : « Je n’ai pas pu confirmer dans le manuel : … » quand la réponse contient un chiffre ou un libellé que les pages du manuel ne contiennent pas, ou une note quand la réponse n'est que partielle.\n\n**Ce qu'il ne fait pas.** Il ne voit ni tes revenus, ni tes charges, ni tes montants, ni ton écran : si tu lui demandes « combien », il t'explique où le lire et comment c'est calculé. Il ne donne pas de conseil de cuisine, de finances ou de droit. Quand le manuel ne répond pas, il le dit au lieu d'inventer.\n\n**S'il se trompe.** Touche « Cette réponse est fausse » sous sa réponse : la question, sa réponse et les pages utilisées sont enregistrées dans ton foyer, puis « Merci, c’est noté. » s'affiche. Cela sert à corriger le manuel ; rien ne change tout de suite pour toi.\n\n**Limite.** Chaque foyer a 300 questions par mois, le compteur repart au début du mois. Au-delà, l'aide répond « Quota atteint ». Si elle est très sollicitée, elle te demande de réessayer dans une minute.\n\n**Avant la connexion.** L'aide n'existe que dans l'appli connectée : ni sur l'écran de connexion, ni sur un lien d'invitation.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-arrivee-dans-le-foyer",
    "titre": "L’arrivée dans le foyer et les mois qui comptent",
    "ecrans": [
      "/",
      "/budget",
      "/profil"
    ],
    "questions": [
      "Pourquoi mon budget dit « Dans 5 jours » ?",
      "Pourquoi je n’ai aucune part sur octobre ?",
      "Où je change ma date d’arrivée ?",
      "Pourquoi mon revenu compte à partir d’un autre mois ?",
      "Pourquoi septembre dit « clôturé avant que ton revenu soit posé » ?",
      "Pourquoi le partage est à parts égales ?"
    ],
    "sources": [
      "src/pages/Hub.tsx",
      "src/pages/Budget.tsx",
      "src/pages/Cloture.tsx",
      "src/pages/Profil.tsx",
      "src/pages/BudgetReglages.tsx",
      "src/lib/budget/mois.ts",
      "src/lib/budget/cloture.ts",
      "src/lib/donnees/budget.ts",
      "src/ui/budget/MoisType.tsx",
      "supabase/migrations/0065_gardes_manquantes.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/functions/accept-invite/index.ts",
      "supabase/migrations/0098_budget_lignes_nees.sql",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0103_budget_arrivees.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## La date d'arrivée\n\nTa date d'arrivée est le champ **« Ton arrivée dans le foyer »** de ton profil (touche l'avatar, « Mon profil ») : elle décide des mois que tu partages.\n\nQuand quelqu'un accepte une invitation, son arrivée est posée d'office au **1er du mois suivant** ; il la corrige dans son profil.\n\n## Les mois qui comptent pour toi\n\nUn mois compte pour toi si ton arrivée n'est pas après son dernier jour : arriver le 15 novembre fait compter novembre en entier.\n\nAvant ton arrivée :\n\n- tu ne portes aucune part et on ne te demande aucun revenu ;\n- la tuile « Budget » de l'accueil dit ton **mois type** (« 420 € pour toi ») et compte les jours : « 5 jours avant ton premier mois, le 1er novembre ». Sans charges posées : **« Commence en novembre »** ;\n- l'écran du mois dit « Tu n’es pas encore dans le foyer : tu y entres en novembre. Ce mois-là ne te compte aucune part. » (« Tu n’étais pas encore… » sur un mois passé). Sur un mois vide, il montre le **mois type** de ton arrivée (« budget-mois-type ») ; tant qu’aucune charge n’est posée, il dit « Pas encore » ;\n- aucun bandeau « … est fini : on le clôture ? » ne paraît pour ces mois.\n\n## Ton revenu et ton arrivée\n\n- Un revenu posé aujourd'hui est daté de **ce mois-ci**, ou du **mois de ton arrivée** si elle est à venir : pas de reste avant ton arrivée.\n- Ton **premier** revenu remonte au mois de ton arrivée, mais jamais avant le mois qui suit la dernière clôture du foyer. Exemple : arrivée le 15 novembre, revenu posé le 2 décembre : il vaut dès novembre.\n- Les revenus suivants prennent effet le mois où tu les poses ; celui d'un mois antérieur est gardé.\n- Corriger ton arrivée refait le partage des mois entre l'ancienne et la nouvelle date (pas les mois clôturés ni les lignes déjà validées ou réglées). Reculée, elle ajoute aussi ton revenu à la nouvelle date, s'il datait de l'ancienne arrivée.\n\n## Parts égales\n\nTant que quelqu'un qui est là ce mois-là n'a pas de revenu, tout se partage à parts égales.\n\n## Un mois clôturé sans toi\n\nUn mois clôturé avant ton premier revenu ne se recalcule pas : « Le mois de septembre a été clôturé avant que ton revenu soit posé. »\n\n## Les mois suivis\n\nPopote suit le budget depuis le premier mois où un revenu est posé (ou un mois clôturé).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-charges-ajouter",
    "titre": "Ajouter une charge",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "Comment ajouter une charge ?",
      "Comment ajouter la taxe foncière ?",
      "C’est quoi « Comment elle se paie » ?",
      "Comment ajouter une charge trimestrielle ou annuelle ?",
      "Je ne trouve pas ma charge dans la liste, que faire ?"
    ],
    "sources": [
      "src/pages/Charges.tsx",
      "src/ui/charges/Catalogue.tsx",
      "src/lib/budget/charges.ts",
      "src/lib/budget/categories.ts",
      "src/lib/budget/feuilles.ts",
      "src/ui/budget/Gestes.tsx",
      "src/lib/donnees/budget.ts",
      "supabase/migrations/0050_catalogue_charges.sql",
      "supabase/migrations/0085_ce_quon_reconnait.sql",
      "supabase/migrations/0096_budget_facon.sql",
      "supabase/migrations/0098_budget_lignes_nees.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "Une charge est une dépense qui revient (loyer, assurance, taxe foncière). Le bouton « Mes charges » de l’écran du mois ouvre la page « Les charges » : tu y poses toutes tes charges.\n\n## Comment faire\n\n1. Dans « Ou une par une », cherche (champ « Chercher : « assurance », « mobile »… ») ou ouvre une rubrique (Logement, Auto, Abonnements…), puis touche la ligne. Rien ne correspond ? Touche « Autre chose », sous les rubriques.\n2. Remplis « Quoi » (80 caractères au plus) et « Combien (€) », au-dessus de 0 € et au plus 1 000 000 €. C’est le montant de la période : 1 200 € pour une taxe foncière annuelle, pas 100 €.\n3. Choisis « Catégorie » : Vie courante, Maison, Crédits, Auto, Abonnements, Santé, Impôts ou Autre. Le catalogue la propose selon la section.\n4. Choisis « Comment elle se paie » :\n   - « Fixe » : le même montant chaque mois (un loyer).\n   - « Une facture chaque mois » : le montant est une estimation, tu donnes le vrai chiffre chaque mois (Électricité, Gaz).\n   - « Plusieurs dépenses dans le mois » : le montant est un plafond, tu déclares tes dépenses au fil du mois (Courses).\n   - « Mise de côté » : pour ce qui ne tombe pas chaque mois. Tu choisis « Tous les trois mois » ou « Une fois par an ».\n5. Règle « Qui participe », « Comment la partager », « Elle court depuis » et « Payée depuis » (pages à part).\n6. Touche « Ajouter cette charge ».\n\n## La mise de côté\n\nLe formulaire annonce « On en met de côté le douzième chaque mois » (le tiers pour le trimestriel) et la somme. Une charge de 1 200 € par an met 100 € de côté chaque mois ; 300 € par trimestre aussi.\n\nUne charge trimestrielle ou annuelle est toujours « Mise de côté ». Les trois autres façons sont toujours mensuelles.\n\n## Le catalogue\n\nLe catalogue est rangé par rubrique : la première est ouverte, les autres se déplient d’un toucher, et une recherche ouvre celles qui répondent. Chaque ligne arrive préremplie : rythme, façon, catégorie, partage. « Taxe foncière » est annuelle et commune, « Électricité » est une facture chaque mois, « Courses » se dépense au fil du mois. Tu peux tout changer avant d’ajouter.\n\n## À savoir\n\n- Il n’y a que trois rythmes : par mois, par trimestre, par an. Rien pour « tous les deux ans ».\n- Dès l’ajout, les mois écoulés depuis la date « Elle court depuis » reçoivent leur ligne, sauf les mois clôturés et ceux d’avant l’arrivée des participants.\n- Le total en haut de la page ramène tout au mois et ne compte que les charges déjà en vigueur ce mois-là et dont au moins un participant est déjà dans le foyer. Les charges sont rangées par catégorie, avec le total de chacune ; touche l’en-tête d’une catégorie pour la replier ou la rouvrir (l’appareil s’en souvient).\n- Avant ton arrivée dans le foyer, la page se cale sur ton mois d’arrivée : elle le dit en haut, et les montants sont ceux de ce mois-là.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-charges-commune-ou-perso",
    "titre": "Charge commune ou à moi, et l’arrivée de l’autre",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "Quelle différence entre une charge commune et une charge à moi ?",
      "Je suis seul, que se passe-t-il si je pose une charge commune ?",
      "Que devient une charge quand l’autre arrive dans le foyer ?",
      "Comment changer qui participe à une charge ?",
      "Pourquoi ma charge dit « partagée dès que quelqu’un arrive » ?"
    ],
    "sources": [
      "src/pages/Charges.tsx",
      "src/ui/charges/LigneDeCharge.tsx",
      "src/lib/budget/charges-liste.ts",
      "src/lib/budget/charges.ts",
      "src/lib/donnees/budget.ts",
      "supabase/functions/accept-invite/index.ts",
      "supabase/migrations/0061_charge_commune_et_debut.sql",
      "supabase/migrations/0062_arrivee_juste.sql",
      "supabase/migrations/0066_se_retirer_dune_commune.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0103_budget_arrivees.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "Il n’y a qu’une liste de charges. Chaque ligne dit qui y participe. « À moi » veut simplement dire : une seule personne participe.\n\n## Poser une charge\n\nDans « Qui participe », touche les prénoms.\n- Deux personnes : la charge est commune et se partage (voir la page sur le partage).\n- Une seule : « Payée par une seule personne : elle n’entrera dans aucun partage. »\n\nChaque ligne du catalogue propose l’un ou l’autre (le loyer est commun, un forfait mobile est à toi). Ce n’est qu’une suggestion. La ligne « Autre chose » démarre à toi seul : elle ne présume rien.\n\n## Quand tu es seul dans le foyer\n\nUne case apparaît : « Elle se partagera avec le foyer ». Le texte dit : « Tu es seul pour l’instant. Coche si la personne que tu invites devra la partager : elle y entrera toute seule en arrivant. » Le catalogue la coche pour les charges communes comme la taxe foncière.\n\nTant que tu es seul, la ligne indique ton prénom suivi de « seul » et « partagée dès que quelqu’un arrive ». Tout est à ta charge. Cette ligne se retrouve sous le filtre « À moi », pas sous « En commun ».\n\nÀ deux, la case n’existe plus : une charge payée par une seule personne est à elle.\n\n## Quand l’autre arrive\n\n- Elle entre dans toutes les charges communes, y compris celles posées quand tu étais seul. Les charges à toi ne bougent pas.\n- Sa date d’entrée est par défaut le 1er du mois suivant l’acceptation de l’invitation.\n- À partir de ce mois, les lignes encore ouvertes se partagent ; une ligne déjà confirmée ne bouge pas. Les mois d’avant restent entièrement à celui qui était là, et un mois clôturé ne bouge jamais.\n\n## Changer qui participe\n\nTouche la ligne : « Changer qui participe » apparaît dès que le foyer a deux membres. Tu coches ou décoches un prénom, puis « Fermer ».\n- Le mois en cours est refait, sauf ce qui est déjà confirmé ou réglé.\n- Les mois passés ne changent pas. Les mois à venir naîtront avec les nouveaux participants.\n- Se retirer d’une charge commune est permis, sans l’accord de l’autre.\n\n## À savoir\n\nLe foyer partage tout : chacun peut corriger la ligne de l’autre. Quand quelqu’un d’autre l’a modifiée en dernier, la ligne affiche « ✎ » et son prénom. Le filtre « Tout » montre toutes les charges, y compris celles de l’autre.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-charges-corriger-retirer",
    "titre": "Corriger, retirer, rattacher une charge",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "Comment corriger le montant d’une charge ?",
      "Comment retirer une charge ?",
      "Que se passe-t-il pour les mois passés quand je corrige ou je retire ?",
      "C’est quoi « Retirées, encore à régler » ?",
      "C’est quoi « Rattacher » ?"
    ],
    "sources": [
      "src/pages/Charges.tsx",
      "src/ui/charges/LigneDeCharge.tsx",
      "src/ui/charges/gestes.ts",
      "src/lib/budget/charges.ts",
      "src/lib/donnees/budget.ts",
      "supabase/migrations/0096_budget_facon.sql",
      "supabase/migrations/0110_budget_corrige.sql",
      "supabase/migrations/0111_budget_retire.sql"
    ],
    "verifie_sur": "7ccc089",
    "corps": "Sur la page « Les charges », touche une ligne : ses gestes s’ouvrent dessous. Ce sont « Corriger », « Retirer », et selon le cas « Rattacher » ou « Changer qui participe ». Un seul panneau est ouvert à la fois ; retouche la ligne pour le fermer. Si un geste échoue, le message s’affiche sur cette ligne, même si tu as refermé son panneau.\n\n## Corriger\n\n« Corriger » déplie un panneau dans la ligne : « Son nom », « Son montant », « Catégorie », « Comment elle se paie », et « Elle court depuis » pour une « Mise de côté ». Puis « Enregistrer ».\n\n- « Les mois déjà confirmés gardent leur montant. Les autres se refont. » Un mois clôturé ne change pas, ni une année déjà soldée.\n- L’appli dit combien de mois elle a refaits : « « X » corrigée, 2 mois refaits. »\n- Changer seulement la catégorie ne touche aucun montant. La ligne passe dans sa nouvelle catégorie, qui se rouvre si elle était repliée.\n- Une charge « Mise de côté » qui a déjà une facture, un mois confirmé ou clôturé, ne devient plus mensuelle. Les trois autres façons sont grisées. Pour la payer chaque mois, retire-la et ajoute-en une nouvelle.\n- Si tu quittes « Plusieurs dépenses dans le mois » alors que des dépenses sont déclarées, l’appli refuse : « Des dépenses sont déclarées en octobre sur cette charge. Retire-les d'abord. »\n- La façon de partager (« Comme le foyer », « Au prorata », « Moitié-moitié ») se choisit à l’ajout : le panneau « Corriger » ne la propose pas.\n\n## Retirer\n\n« Retirer » demande : « Retirer « X » ? Elle disparaîtra de tous les mois. » \n- Les lignes des mois ouverts, non confirmées, disparaissent.\n- Une « Mise de côté » retirée avec des factures : l’écart de l’année se recalcule aussitôt, sur le mois en cours.\n- Si des dépenses sont déjà déclarées, l’appli demande : « Retirer X et ses N € déclarés ? ». Tu peux refuser, rien ne part.\n- Une charge sans histoire est supprimée : « « X » retirée. »\n- Une charge qui a de l’argent sorti (mois confirmé ou clôturé, facture, année soldée) est seulement rangée : « Les mois que tu as confirmés ou réglés la gardent : c’est de l’argent sorti. »\n\n## « Retirées, encore à régler »\n\nUne charge « Mise de côté » retirée reste visible dans cette liste, avec « Ajouter une facture ». Elle y reste jusqu’au 31 décembre de l’année qui suit son retrait (la facture arrive souvent après). Le texte dit « Retirée en 2026 » ou « 2026 reste à régler ».\n\n## « Rattacher »\n\nUne charge « sans compte » propose « Rattacher » (s’il existe un compte). Il la relie au compte commun, sinon au premier compte de la liste.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-charges-debut",
    "titre": "La date de début d’une charge",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "C’est quoi « Elle court depuis » ?",
      "Pourquoi remonter la date de début d’une charge annuelle ?",
      "J’ai posé ma taxe foncière en septembre, la facture me tombe d’un coup, pourquoi ?",
      "Puis-je changer la date de début après coup ?",
      "Pourquoi ma charge dit « commence en … » ?"
    ],
    "sources": [
      "src/pages/Charges.tsx",
      "src/lib/budget/charges-liste.ts",
      "src/lib/budget/charges.ts",
      "src/lib/budget/feuilles.ts",
      "src/lib/budget/mois.ts",
      "src/lib/donnees/budget.ts",
      "src/ui/budget/FeuilleMiseDeCote.tsx",
      "supabase/migrations/0096_budget_facon.sql",
      "supabase/migrations/0098_budget_lignes_nees.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0105_budget_cible.sql",
      "supabase/migrations/0110_budget_corrige.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "« Elle court depuis » est le mois où la charge commence à compter : rien n’est mis de côté avant.\n\n## Les règles\n\n- Par défaut : le mois en cours. Si ton arrivée dans le foyer est à venir, c’est ton mois d’arrivée, et une date plus ancienne y est ramenée.\n- Tu peux remonter dans le passé, mais pas avant janvier de l’année précédente. Plus tôt, l’appli répond « Pas avant janvier » suivi de l’année.\n- Dès l’ajout, chaque mois écoulé depuis cette date reçoit sa ligne, dès qu’un participant est arrivé. Un mois clôturé n’en reçoit pas.\n- Une charge qui commence plus tard apparaît dans la liste avec « commence en » et son mois. Elle n’est comptée ni dans le total « par mois » ni dans l’écran du mois. Une charge dont aucun participant n’est encore dans le foyer ce mois-là est grisée aussi (« pas encore dans le foyer »). Avant ton arrivée, la liste se cale sur ton mois d’arrivée : une charge qui court depuis lors y montre son montant, sans « commence en ».\n\n## Pourquoi remonter la date d’une charge annuelle\n\nUne charge « Mise de côté » met de côté un douzième par mois, seulement à partir de sa date de début. Ce qui a été prévu avant la facture réduit ce qu’il reste à payer d’un coup.\n\nExemple : taxe foncière de 1 200 € par an, donc 100 € par mois.\n- Posée en septembre avec le début en septembre : 4 mois × 100 € = 400 € prévus. Une facture de 1 200 € ajoute 800 € d’un coup au mois en cours.\n- Posée avec le début en janvier : 12 mois × 100 € = 1 200 € prévus. Une facture de 1 200 € n’ajoute rien.\n\nC’est pour ça que le formulaire t’avertit : « On ne mettra de côté qu’à partir de ce mois-là. Si tu la paies depuis janvier, remonte la date — sinon la facture annuelle tombera d’un coup. » Il apparaît pour une charge non mensuelle, quand le début est dans l’année en cours après janvier.\n\n## Une limite\n\nLe prévu de l’année ne compte que les mois « suivis » : ceux à partir du premier mois où un revenu du foyer est en vigueur (ou d’un mois clôturé). Les lignes d’avant existent mais ne comptent pas dans le prévu. La feuille de facture l’écrit : « Prévu pour 2026, depuis septembre ». Remonter la date plus loin que ce premier mois ne réduit donc pas l’écart.\n\n## Changer la date après coup\n\nTouche la ligne de la charge, puis « Corriger ». Le champ « Elle court depuis » n’apparaît que pour une « Mise de côté » : « C’est elle qui décide sur combien de mois le montant se répartit. » Les mois déjà confirmés gardent leur montant, les autres se refont. Reculer la date fait naître les mois manquants, mais pas avant ton arrivée dans le foyer : « Pas avant ton arrivée, en novembre 2026. »",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-cloture-quand",
    "titre": "Quand clôturer, et les rappels",
    "ecrans": [
      "/",
      "/budget",
      "/cloture"
    ],
    "questions": [
      "Quand est-ce que je peux clôturer le mois ?",
      "Que veut dire « Septembre est fini : on le clôture ? »",
      "Pourquoi le bandeau change à partir du 27 ?",
      "Pourquoi je ne peux pas clôturer octobre aujourd’hui ?",
      "Pourquoi « Ajoute ton revenu de septembre pour clôturer septembre » ?",
      "Pourquoi aucun bandeau ne me propose de clôturer ?"
    ],
    "sources": [
      "src/lib/budget/mois.ts",
      "src/ui/budget/Bandeau.tsx",
      "src/pages/Budget.tsx",
      "src/pages/Hub.tsx",
      "src/pages/Cloture.tsx",
      "src/lib/budget/cloture.ts",
      "supabase/migrations/0108_budget_cloture.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "Clôturer un mois, c'est le fermer une fois fini. Cette page dit quand c'est possible et quand Popote te le rappelle.\n\n## Quand on peut clôturer\n\n- **Pas avant le 1er du mois suivant.** Octobre se clôture à partir du 1er novembre. Avant, la page dit « On clôture octobre une fois fini, à partir du 1er novembre. » avec « Revenir au mois » : les derniers jours d'un mois ont encore des dépenses.\n- **Avec un revenu pour ce mois-là.** Sinon : « Ajoute ton revenu de septembre pour clôturer septembre. » et le bouton « Revenus ». Sans revenu, un mois ne se clôture pas, et rien ne le propose.\n- **Si tu étais dans le foyer ce mois-là.** Sinon : « Tu n’étais pas encore dans le foyer en septembre : ce mois-là ne te concerne pas. Les autres peuvent le clôturer. »\n- **Si l'autre personne présente ce mois-là a posé son revenu.** Sinon la clôture refuse, avec un message du type « [prénom] n'a pas encore posé son revenu : septembre attend. »\n- Un mois déjà clôturé ne se clôture pas deux fois.\n\nAucun ordre n'est imposé entre les mois : septembre peut être clôturé avant août.\n\n## Le bandeau de l'écran du mois\n\nEntre le filtre et les catégories, un seul bandeau à la fois. Il n'y en a jamais sur un mois clôturé, ni sur un mois sans aucune ligne.\n\n- **Du 1er au 26 du mois en cours** : « Le mois fini, on le clôture : tu confirmes les factures, et tu choisis quoi faire de ce qui reste. »\n- **À partir du 27** (jusqu'à la fin du mois) : « Octobre se termine. Le 1er novembre, on le clôture. »\n- **Le mois précédent n'est pas clôturé** : « Septembre est fini : on le clôture ? » avec le bouton « Clôturer septembre ». Ce bandeau passe devant les deux autres.\n- **Sur un mois passé non clôturé** : le même bandeau « … est fini : on le clôture ? ».\n\nLes bandeaux « … est fini » n'apparaissent que si tu avais un revenu ce mois-là et que tu étais déjà dans le foyer. Le bouton mène à la page de clôture.\n\n## Sur la tuile Budget de l'accueil\n\nLa ligne « Septembre est à clôturer » apparaît dans les mêmes conditions : le mois précédent n'est pas clôturé, tu y avais un revenu, tu étais là. Seul le mois précédent compte sur l'accueil ; les mois plus anciens non clôturés se retrouvent en les ouvrant un par un dans l'écran du mois.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-cloture",
    "titre": "Les trois étapes de la clôture",
    "ecrans": [
      "/cloture"
    ],
    "questions": [
      "Comment je clôture septembre ?",
      "Que veut dire « Rien dépensé » ?",
      "Qu’est-ce que je dois choisir à l’étape « Ce qui reste » ?",
      "Que devient l’argent que je mets de côté ?",
      "Pourquoi « Le mettre de côté » est grisé ?",
      "Que fait le bouton « Clôturer septembre » ?"
    ],
    "sources": [
      "src/pages/Cloture.tsx",
      "src/lib/budget/cloture.ts",
      "src/lib/budget/etapes.ts",
      "src/lib/budget/mois.ts",
      "src/ui/budget/EtapeFactures.tsx",
      "src/ui/budget/EtapeDepenses.tsx",
      "src/ui/budget/EtapeReste.tsx",
      "src/ui/budget/VueReste.tsx",
      "supabase/migrations/0108_budget_cloture.sql"
    ],
    "verifie_sur": "9504cf2",
    "corps": "Aucune étape n'est obligatoire. Les conditions sont dans la page « Quand clôturer ».\n\n## Les étapes\n\n1. **« Les factures du mois »** : chaque facture non validée montre son montant habituel, avec « C’est ça » ou « Modifier » (ils valident tout de suite). Rien de non validé : « Tout est validé. »\n2. **« Tes dépenses du mois »** : chaque ligne « Plusieurs dépenses dans le mois » montre ce qui est déclaré (« 350 € sur 500 € ») ou « Rien de déclaré ». Le bouton « + » ouvre la feuille pour ajouter. L'interrupteur **« Rien dépensé »**, proposé aux lignes sans aucune dépense, compte la ligne pour 0 €. Une phrase résume l'écart : « Tu as dépensé 90 € de moins que prévu. »\n3. **« Ce qui reste »** : « Tu décides où va l’argent qui n’a pas servi. » La carte donne « Il te reste ce mois-ci » et son détail : « 650 € prévus, plus 90 € dépensés en moins » font 740 €. Quand la clôture solde l'année d'une charge « Mise de côté » (décembre, ou une année passée), une phrase le dit au-dessus (« [charge] : 120 € non dépensés en 2025 reviennent. »).\n\n## Ce que tu en fais\n\n- **« Le mettre de côté »**, choisi d'office : tu verses dans une poche d'épargne (d'urgence si elle existe, sinon la première ; tu choisis la poche s'il y en a plusieurs). Le champ **« Combien mettre de côté »** propose tout le reste. Tu peux taper moins, ou 0 pour ne rien verser. Plus que le reste est ramené au reste. Le bouton « Tout ce qui reste » remet tout. À deux, si une année est soldée, la carte dit « Il te reste, avant les soldes d’année » : tape un montant, ou touche « Tout ce qui reste ».\n- **« Le garder sur le compte »** : « Il reste disponible pour octobre. »\n\n« Le mettre de côté » est grisé s'il n'y a aucune poche (« Il n’y a pas encore de poche d’épargne. ») ou s'il ne reste rien (« Il ne reste rien à mettre de côté ce mois-ci. »). La clôture reste possible.\n\n## Ce que fait « Clôturer septembre »\n\nLes factures non validées prennent leur montant habituel. Chaque ligne au fil du mois prend la somme des dépenses déclarées, ou 0 € si « Rien dépensé », sinon son prévu. Le mois est figé, ton reste est enregistré, le versement part, et tu reviens sur le mois clôturé. Tu pourras revenir dessus depuis le mois.",
    "verifie_le": "2026-10-26"
  },
  {
    "id": "budget-declarer",
    "titre": "Déclarer ce que j’ai dépensé",
    "ecrans": [
      "/budget"
    ],
    "questions": [
      "Comment je note mes courses ?",
      "J’ai fait une erreur de montant, comment corriger ?",
      "Comment je valide ma facture d’électricité ?",
      "Je peux déclarer une dépense d’hier ?",
      "Pourquoi je ne peux plus déclarer sur septembre ?",
      "Qu’est-ce que « C’est ça » ?"
    ],
    "sources": [
      "src/ui/budget/ChoixDeLaLigne.tsx",
      "src/ui/budget/FeuilleDeclarer.tsx",
      "src/ui/budget/FeuilleFactureMois.tsx",
      "src/ui/budget/FeuillesDuMois.tsx",
      "src/ui/budget/Ligne.tsx",
      "src/lib/budget/feuilles.ts",
      "src/lib/budget/mois.ts",
      "src/lib/donnees/budget.ts",
      "supabase/migrations/0097_budget_tables.sql",
      "supabase/migrations/0099_budget_garde_des_saisies.sql",
      "supabase/migrations/0104_budget_confirmer.sql"
    ],
    "verifie_sur": "9504cf2",
    "corps": "## Déclarer une dépense\n\nSeules les lignes « Plusieurs dépenses dans le mois » (les courses, par exemple) se déclarent. S'il n'y en a aucune, la feuille te dit d'aller dans « Mes charges » choisir « Plusieurs dépenses dans le mois ».\n\n1. Touche **« Déclarer »** en haut de l'écran du mois, puis choisis la ligne dans « Pour quelle ligne ? ». Ou touche le bouton « Déclarer » sur la ligne.\n2. Écris le montant dans **« Nouvelle dépense »** : « 47 » ou « 47,90 ».\n3. Choisis le jour : **« Aujourd’hui »**, **« Hier »** (pas proposé le 1er du mois : ouvre alors le mois précédent, s'il n'est pas clôturé) ou **« Autre jour »** (un jour du mois affiché, jusqu'à aujourd'hui).\n4. Touche **« Ajouter 47,90 € »**.\n\nLa feuille montre « 120 € sur 400 € », la barre, puis « Il reste 280 € pour octobre. » ou « 50 € au-delà du prévu. ». Plus bas, **« Déjà ce mois-ci »** liste chaque dépense : sa date, qui l'a saisie (à deux) et son montant. Les dépenses d'une ligne s'additionnent, qu'elles viennent de toi ou de l'autre.\n\nRègles : un montant au-dessus de 0 €, et une ligne ne dépasse pas 1 000 000 € en tout. Sur un mois passé non clôturé, tu peux aussi déclarer : le jour proposé est le dernier jour du mois, plus « Autre jour ».\n\n## Corriger\n\nUne dépense déclarée ne se modifie pas : retire-la avec la corbeille, à droite de sa ligne dans « Déjà ce mois-ci », puis déclare le bon montant. Aucune confirmation n'est demandée. Chacun peut retirer une dépense, même celle de l'autre.\n\n## Valider une facture\n\nPour une ligne « Une facture chaque mois » (l'électricité, par exemple), touche la ligne. La feuille dit « Le montant habituel : … ».\n\n- **« C’est ça »** : tu valides le montant habituel.\n- **« Modifier »** : tu tapes le vrai montant dans « Le montant de la facture », puis **« Valider 82,40 € »**. 0 € est accepté : c'est ainsi qu'on note un avoir.\n\nUne fois validée, la feuille dit « Le montant retenu : … » et tu peux encore « Modifier ». Une facture non validée est confirmée à son montant habituel par la clôture.\n\n## Sur un mois clôturé\n\nPlus rien ne se déclare ni ne se valide : « Déclarer » disparaît, les feuilles s'ouvrent en lecture seule avec « Revenir dessus » (voir la page sur le mois clôturé). Seule la feuille d'une charge « Mise de côté » reste utilisable.",
    "verifie_le": "2026-10-26"
  },
  {
    "id": "budget-dictee-charges",
    "titre": "Dicte tout, je range",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "Comment marche « Dicte tout, je range » ?",
      "Qu’est-ce que le modèle voit de mes données quand je dicte ?",
      "Combien de dictées puis-je faire par mois ?",
      "Pourquoi une ligne n’est-elle pas ajoutée ?",
      "À quoi sert « Vérifier mes charges » ?"
    ],
    "sources": [
      "src/pages/Dictee.tsx",
      "src/pages/Charges.tsx",
      "src/pages/RevueCharges.tsx",
      "supabase/functions/charges/index.ts",
      "supabase/functions/charges/prompt.ts",
      "supabase/functions/revue-charges/index.ts",
      "supabase/functions/revue-charges/prompt.ts",
      "supabase/migrations/0027_ecriture_croisee.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "« Dicte tout, je range » (page « Les charges », bouton « Dicter mes charges ») pose plusieurs charges à partir de ce que tu racontes. Le modèle propose, tu valides. Rien n’est enregistré tant que tu n’as pas touché « Ajouter N charges ».\n\n## Comment faire\n\n1. Choisis une section : « Le logement », « La voiture », « Les abonnements », « Les crédits » ou « Tout le reste, d’un coup ».\n2. Écris, ou touche le micro de ton clavier : l’appli n’enregistre pas ta voix. Il faut au moins 10 caractères et au plus 8 000.\n3. Touche « Range tout ça ».\n4. Sur « Ce que j’ai compris », décoche ce qui est faux. Pour chaque ligne tu peux changer le rythme (mois, trimestre, an), « en commun » ou « à toi », et le montant. Une charge non mensuelle a un champ « Elle court depuis » : janvier de l’année en cours par défaut.\n5. Touche « Ajouter N charges ».\n\nSont cochées d’office les lignes sûres (confiance d’au moins 0,7) avec un montant. Une ligne sans montant ne part pas.\n\n« Il me manque ça » liste des questions du modèle. « Tu n’en as pas parlé — tu en as ? » propose des postes du catalogue : touche-les, il reste à mettre le montant.\n\n## Ce que le modèle voit\n\n- Voit : ton texte, et le catalogue (section, libellé, rythme, partage habituel) de la section choisie, tout le catalogue pour « Tout le reste, d’un coup ».\n- Ne voit pas : tes revenus, tes charges déjà posées, les prénoms, les comptes. Il ne choisit ni la clé de partage ni le compte. Rien n’empêche de poser deux fois la même charge.\n- Les charges « en commun » sont posées avec tout le foyer ; celles « à toi » avec toi seul. Le compte commun est utilisé d’office (sinon le premier compte).\n\n## Le quota\n\n20 dictées par mois pour tout le foyer. Chaque envoi compte, même si le rangement échoue. Au-delà : « Quota atteint : 20 dictées par mois. Il repart le 1er. »\n\n## « Vérifier mes charges »\n\nCe bouton, à côté de « Dicte tout, je range » (dès qu’il y a une charge), fait relire tes charges : doublons (« Deux fois la même chose »), montants qui détonnent (« À vérifier »), postes courants oubliés (« Tu n’en as pas parlé »). Il ne corrige rien. Il envoie au modèle, pour chaque charge, libellé, montant, rythme, commun ou perso, fixe ou variable, compte et date de début ; jamais les revenus ni les prénoms. Quota séparé : 30 relectures par mois.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-ecran-du-mois",
    "titre": "L’écran du mois",
    "ecrans": [
      "/budget"
    ],
    "questions": [
      "Comment je change de mois ?",
      "Pourquoi je ne peux pas aller au mois prochain ?",
      "À quoi servent les quatre boutons en haut ?",
      "Pourquoi mon mois est vide ?",
      "Pourquoi l’écran dit qu’il n’a pas pu lire le budget ?"
    ],
    "sources": [
      "src/pages/Budget.tsx",
      "src/App.tsx",
      "src/ui/budget/Gestes.tsx",
      "src/ui/budget/CarteEpargne.tsx",
      "src/lib/budget/mois.ts",
      "src/lib/budget/ecran.ts",
      "src/lib/horloge.ts",
      "src/ui/budget/MoisType.tsx"
    ],
    "verifie_sur": "5f54c2b",
    "corps": "L'écran du mois s'ouvre depuis la tuile « Le budget » de l'accueil. Il montre un mois à la fois : le mois en cours au départ.\n\n## De haut en bas\n\n- **Changer de mois.** Sur septembre : « ‹ Août » (le mois précédent, toujours là) et « Octobre › » (le mois suivant, seulement sur un mois passé : on ne va jamais au-delà du mois en cours). L'année s'ajoute dès qu'elle n'est pas l'année en cours.\n- **Les jours**, sur le mois en cours seulement : « Il reste 8 jours. », « Il reste un jour. » ou « Dernier jour. ».\n- **Quatre gestes** : « Mes charges », « Déclarer », « Revenus » (les réglages du budget), « Épargne ». « Déclarer » disparaît sur un mois clôturé.\n- **Le reste du mois** : une carte sombre avec « Il te reste » (voir la page sur le calcul).\n- **Une phrase en ocre**, à deux sur un mois ouvert, si quelqu'un n'a pas dit son revenu : « [prénom] n’a pas encore dit son revenu : tant qu’il manque, le partage se fait à parts égales. » (ou « Aucun revenu n’est posé : le partage se fait à parts égales. »).\n- **Une carte par poche d'épargne**, si tu en as.\n- **« Le mois type »** : une carte sous l'épargne, quand le mois a des lignes. Elle ouvre le tableau de bord du mois type (« budget-mois-type »).\n- **« Par catégorie »** : les lignes du mois, avec le filtre « Tout / Commun / Moi ».\n- **Le bandeau de clôture**, entre le filtre et les catégories, quand il y a lieu (voir la page « Quand clôturer »).\n\n## Quand l'écran est vide ou prudent\n\n- **« Rien de posé »** : sur le mois en cours, « Aucune charge ce mois-ci. On commence par là. » avec un bouton : « Commencer par les revenus et les comptes » si aucun compte n'existe, sinon « Poser les charges ». Sur un mois passé : « Aucune charge n’était posée ce mois-là. »\n- **Avant ton arrivée** dans le foyer, sur un mois vide : l'écran montre le mois type du mois où tu entres (« budget-mois-type ») ; sans aucune charge posée, il dit « Pas encore ».\n- **Une panne de lecture** : « Je n’ai pas pu lire le budget… » et le bouton « Réessayer ». Aucun chiffre avant d'avoir tout lu.\n\n## À savoir\n\nUne adresse de mois à venir te ramène sur le mois en cours. Un mois passé s'ouvre toujours : Popote crée alors les lignes qui manquaient, sauf s'il est clôturé.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-epargne",
    "titre": "L’épargne, les poches et les versements",
    "ecrans": [
      "/epargne"
    ],
    "questions": [
      "Comment ouvrir une poche d’épargne ?",
      "Comment verser ou retirer de l’argent d’une poche ?",
      "À qui appartient l’argent d’une poche ?",
      "C’est quoi un projet, et « par mois pour tenir la date » ?",
      "Pourquoi je ne peux pas retirer plus que ce que j’ai versé ?"
    ],
    "sources": [
      "src/pages/Epargne.tsx",
      "src/ui/epargne/CartePoche.tsx",
      "src/ui/epargne/Projet.tsx",
      "src/ui/epargne/OuvrirUnePoche.tsx",
      "src/lib/budget/epargne-lecture.ts",
      "src/lib/donnees/budget.ts",
      "src/lib/budget/feuilles.ts",
      "src/ui/budget/CarteEpargne.tsx",
      "src/ui/budget/Gestes.tsx",
      "src/lib/budget/mois.ts",
      "supabase/migrations/0054_enveloppes_et_epargne.sql",
      "supabase/migrations/0116_budget_plancher_epargne.sql"
    ],
    "verifie_sur": "f84a76d",
    "corps": "L’épargne se range dans des poches. Le bouton « Épargne » de l’écran du mois, ou la carte d’une poche, ouvre cette page.\n\n## Ce que dit l’appli\n\n« Ce qui est versé appartient à qui l’a versé. » Chaque poche est une carte avec sa photo, son nom et son genre (« Fonds d’urgence » ou « Un projet »). Dessous : « 1 240 € sur 4 000 € », le pourcentage, une barre de progression et la date (« pour août 2027 » ou « pas de date »).\n\nLe registre vient ensuite : une pastille par personne, avec le montant versé et le prénom, pas une moitié-moitié présumée. Une personne à 0 € n’a pas de pastille. Une poche vide le dit : « Rien n’y est encore versé. », ou « Tout a été retiré » si tout est ressorti.\n\n## Ouvrir une poche\n\nSous « Ouvrir une poche » :\n1. Choisis « Fonds d’urgence » ou « Un projet ».\n2. Remplis « Son nom » et « Objectif (€) » (un objectif qui n’est pas un montant est refusé).\n3. Pour un projet : « Pour quand (facultatif) » et « Comment le financer » (« Comme le foyer », « Au prorata », « Moitié-moitié »). Ce choix n’est qu’enregistré, aucun calcul ne s’en sert.\n4. Touche « Ouvrir ».\n\nPour le fonds d’urgence, l’appli rappelle la règle : quatre mois de ce qui est nécessaire, le toit et les courses.\n\n## Verser et retirer\n\nDans la poche, tape le montant dans « Verser (€) » puis « Je verse », ou « Je retire ». Le retrait demande confirmation : « Retirer X de « nom de la poche » ? »\n\n- Tu ne peux retirer que ce que toi tu as versé. Sinon : « Tu n’as versé que X ici : tu ne peux pas en retirer plus. » (ou « Tu n’as rien versé ici : il n’y a rien à retirer. »)\n- Un versement posé ne change plus.\n- « Je verse » écrit dans le registre de la poche. Cela ne change pas « Il te reste » sur l’écran du mois.\n- La clôture du mois peut aussi verser ton reste dans une poche.\n\n## Un projet\n\nUn projet a une date et des postes : sa carte les range sous « Le projet ».\n- « Pour quand » donne le rythme : « X par mois pendant N mois pour tenir la date ». L’appli ajoute : « Il y a X dessus pour l’instant. » C’est ce qu’il reste à atteindre (objectif moins le total déjà versé par tous) divisé par le nombre de mois jusqu’à l’échéance, arrondi au centime supérieur. Exemple : objectif 1 200 €, déjà 200 €, 5 mois : 200 € par mois.\n- Les postes détaillent ce qu’on va payer : tape le nom dans « Un poste », le montant, puis touche « + ». Si leur somme diffère de l’objectif, l’appli le dit et propose « Aligner l’objectif ».\n- Rien d’annoncé si l’objectif ou la date manque. Date ce mois-ci ou passée : « C’est pour ce mois-ci. » Objectif atteint : « C’est déjà atteint. »",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-factures-regularisation",
    "titre": "Les factures et la régularisation annuelle",
    "ecrans": [
      "/budget",
      "/charges"
    ],
    "questions": [
      "Comment entrer la facture de ma taxe foncière ?",
      "Comment se calcule la régularisation d’une charge annuelle ?",
      "Pourquoi la facture ajoute de l’argent à ce mois-ci ?",
      "Que veut dire « Prévu pour 2026, depuis septembre » ?",
      "J’ai entré une mauvaise facture, comment la retirer ?"
    ],
    "sources": [
      "src/ui/budget/FeuilleMiseDeCote.tsx",
      "src/lib/budget/feuilles.ts",
      "src/ui/budget/Ligne.tsx",
      "src/lib/donnees/budget.ts",
      "src/pages/Charges.tsx",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0105_budget_cible.sql",
      "supabase/migrations/0106_budget_factures.sql",
      "supabase/migrations/0107_budget_solde.sql",
      "supabase/migrations/0108_budget_cloture.sql",
      "supabase/migrations/0114_budget_donnees.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "Une charge « Mise de côté » met de côté un douzième (ou un tiers) par mois ; à la vraie facture, l’appli ne pose que l’écart avec le prévu : c’est la régularisation.\n\n## Entrer une facture\n\n1. Sur l’écran du mois, touche la ligne « mis de côté chaque mois » de la charge.\n2. La feuille montre « Prévu pour 2026 » et « Factures payées en 2026 ».\n3. Tape « Montant de la facture » (0,01 € à 1 000 000 €), « Payée » : « Aujourd’hui » ou « Autre jour » (du 1er janvier de l’an dernier à aujourd’hui).\n4. Un encadré annonce ce qui sera posé ; « Ajouter la facture ».\n\nL’année d’une facture est celle de son paiement. Un jour avant le premier mois suivi est refusé (« Popote ne suivait pas encore septembre 2026 : cette facture n'y compte pas. »), le mois en cours aussi tant que personne n’a posé de revenu (« Ajoute ton revenu d'abord. »).\n\n## Le calcul\n\n- Prévu = déjà mis de côté sur l’année + reste à mettre de côté jusqu’en décembre. Seuls les mois suivis comptent (« depuis septembre » : le suivi a commencé en septembre).\n- Écart = factures de l’année − prévu. Positif, il s’ajoute au mois où tu saisis, ligne « Taxe foncière — facture 2026 » ; sinon rien n’est posé (« Il restera X de côté pour 2026. »).\n- Chaque facture recalcule : seule la différence s’ajoute, ou revient si l’écart baisse.\n- L’écart se répartit selon ce que chacun a porté des mises de côté de l’année.\n\nExemple : 1 200 € par an depuis janvier, vu en octobre (10 lignes faites, 2 à venir) : prévu 1 200 €.\n- Facture de 1 320 € : « 120 € de plus que les 1 200 € prévus pour 2026 : ils s’ajoutent à octobre. »\n- Facture de 1 100 € : « Il restera 100 € de côté pour 2026. »\n\n## Retirer, corriger, solder\n\n- La corbeille « Retirer la facture de X € » recalcule l’écart sur le mois en cours.\n- Un « Relevé 2026 — total de l’année » se corrige (« Corriger le montant », « Corriger le relevé »), il ne se retire pas.\n- La clôture de décembre (dès le 1er janvier) solde l’année (« 2026 est soldée. ») : le prévu est figé, l’écart exact est posé en décembre, dans un sens ou dans l’autre. Facture plus basse que le prévu, ou aucune : le trop mis de côté revient. Une facture ajoutée ensuite s’ajoute en entier au mois en cours.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-hub",
    "titre": "La tuile Budget de l’accueil",
    "ecrans": [
      "/"
    ],
    "questions": [
      "Pourquoi mon budget dit « Dans 5 jours » ?",
      "Pourquoi la carte dit « Rien de posé » ?",
      "Que veut dire « 2 montants à dire » ?",
      "Pourquoi « Ajoute ton revenu » alors que je l’ai déjà mis ?",
      "Qu’est-ce que « Tout est à jour » ?",
      "Pourquoi « Septembre est à clôturer » ?"
    ],
    "sources": [
      "src/pages/Hub.tsx",
      "src/lib/budget/mois.ts",
      "src/lib/budget/ecran.ts",
      "src/lib/donnees/foyer.ts",
      "src/lib/donnees/budget.ts",
      "src/ui/budget/MoisType.tsx",
      "src/lib/budget/mois-type.ts",
      "src/lib/donnees/cycle.ts"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "La tuile « Budget » de l'accueil (« Le budget », à côté du frigo) donne l'état du mois en cours. Un toucher dessus ouvre l'écran du mois. Ouvrir l'accueil ouvre aussi le mois en cours : Popote crée ses lignes.\n\n## Ce que la tuile peut dire\n\nDans cet ordre :\n\n1. **« … »** : Popote lit encore ses données.\n2. **« Je n’ai pas pu lire le budget : tu n’as plus de connexion. »** (ou la raison de la panne) : aucun chiffre tant que tout n'est pas lu.\n3. **Avant ton arrivée** : ton mois type (« budget-mois-type ») — **« 420 € pour toi »** ou « Il te manque 90 € », tes charges, une barre — et le compte à rebours **« 5 jours avant ton premier mois, le 1er novembre »** (« Dans 5 jours » sur téléphone). Sans charge posée : **« Commence en novembre »** et « Tu entres dans le foyer à cette date : rien n’est à poser avant. »\n4. **« Rien de posé »**, avec « Les charges du foyer, et ce que chacun verse. » : aucune ligne ce mois-ci.\n5. **« Ajoute ton revenu »** : le mois a des lignes, pas ton revenu.\n6. **« Il te reste 560 € en octobre »** ou **« Il te manque 40 € en octobre »** : même calcul que sur l'écran du mois.\n\n## La ligne sous le chiffre\n\nSous le chiffre (cas 5 et 6), une seule phrase, la première qui s'applique (une pastille la résume sur téléphone) :\n\n- **« Septembre est à clôturer »** : le mois précédent n'est pas clôturé, tu y avais un revenu et tu étais déjà dans le foyer.\n- **« 2 montants à dire : Courses et Essence »** : des lignes « Plusieurs dépenses dans le mois » n'ont encore aucune dépense déclarée. Trois lignes nommées au plus, puis « et 2 autres ».\n- **« Tout est à jour »** : rien à clôturer, rien à dire.\n\n\n## Le reste de l'accueil\n\n- **La carte sombre du jour** dit « Session interrompue » et « Reprends-la depuis la cuisine. » quand une session est à reprendre (« cuisine-session-fin »). Son bouton « Cuisine » ouvre l'accueil de la cuisine.\n- **« Inviter quelqu’un. »** (« Tu obtiens un lien à lui envoyer. ») : tant que tu es seul dans le foyer.\n- **« Complète ton profil. »** : il manque ton prénom ou ton revenu ; un toucher mène au profil.\n- **« Fixe tes objectifs. »** : prénom et revenu sont posés, pas tes objectifs.\n- L'avatar (« Mon profil ») ouvre ton profil : prénom, revenu, date d'arrivée.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-lignes-et-categories",
    "titre": "Les lignes, les catégories et le filtre",
    "ecrans": [
      "/budget"
    ],
    "questions": [
      "Pourquoi une ligne est « mis de côté chaque mois » ?",
      "Je touche une ligne et il ne se passe rien, pourquoi ?",
      "C’est quoi un montant à dire ?",
      "À quoi sert le filtre Tout, Commun, Moi ?",
      "Pourquoi les catégories ne sont pas toujours dans le même ordre ?",
      "Pourquoi je vois les lignes de l’autre ?"
    ],
    "sources": [
      "src/ui/budget/Ligne.tsx",
      "src/ui/budget/Categorie.tsx",
      "src/ui/budget/Filtre.tsx",
      "src/ui/budget/Jauge.tsx",
      "src/lib/budget/mois.ts",
      "src/lib/budget/categories.ts",
      "src/lib/budget/ouvertes.ts",
      "src/lib/budget/feuilles.ts",
      "supabase/migrations/0096_budget_facon.sql",
      "supabase/migrations/0114_budget_donnees.sql"
    ],
    "verifie_sur": "bd10d8c",
    "corps": "Sous « Par catégorie », chaque charge du mois est une ligne. Ce qui se passe quand tu la touches dépend de sa façon : celle de la ligne, figée le jour où elle est née.\n\n## Les lignes\n\n- **Plusieurs dépenses dans le mois** : « 120 € sur 400 € », une barre, et un bouton « Déclarer » (absent sur un mois clôturé). La barre change de couleur (ocre, jamais rouge) au-delà du prévu.\n- **Une facture chaque mois** : le montant à droite ; un toucher ouvre sa feuille, où tu valides ou corriges la facture.\n- **Mise de côté**, la façon de toute charge non mensuelle : « 1 200 € par an, mis de côté chaque mois » (« par trimestre » pour une trimestrielle) et le montant du mois. Un toucher ouvre la feuille de la charge, où tu ajoutes une facture payée avec « Ajouter la facture ». Avant d'envoyer, la feuille dit en une phrase ce que ça change pour le mois.\n- **Fixe** : rien ne se passe. Pour corriger une ligne fixe, passe par « Mes charges ».\n- **Ajustement** : un montant qui peut être négatif. Rien à faire dessus.\n\nUn « montant à dire », c'est une ligne « Plusieurs dépenses dans le mois » d'un mois ouvert sans aucune dépense déclarée. Dès qu'une dépense est déclarée, la ligne n'est plus à dire. Les factures ne sont jamais à dire : on les valide à la clôture.\n\n## Les catégories\n\nHuit catégories : Vie courante, Maison, Crédits, Auto, Abonnements, Santé, Impôts, Autre. Une ligne sans catégorie connue va dans « Autre ».\n\n- Elles se rangent par total décroissant ; à total égal, dans l'ordre de la liste ci-dessus.\n- Une catégorie sans ligne ne s'affiche pas.\n- Chaque catégorie montre « N montants à dire » (en ocre) ou « N lignes », et son total.\n- Elle est ouverte d'office si elle a des montants à dire, repliée sinon. Ton choix de l'ouvrir ou la replier est retenu sur cet appareil seulement.\n- Dans une catégorie, les lignes les plus lourdes viennent d'abord.\n\n## Le filtre « Tout », « Commun », « Moi »\n\nChaque choix montre son total.\n\n- **Tout** : toutes les lignes du foyer, y compris celles que seule l'autre personne porte : chacun voit tout.\n- **Commun** : les lignes dont la charge est commune.\n- **Moi** : tes lignes personnelles (non communes) où tu as une part.\n\nAttention : les totaux des catégories et du filtre comptent chaque ligne en entier. « Il te reste » et sa barre ne comptent que ta part.",
    "verifie_le": "2026-10-23"
  },
  {
    "id": "budget-mois-clos",
    "titre": "Un mois clôturé, et « Revenir dessus »",
    "ecrans": [
      "/budget",
      "/cloture"
    ],
    "questions": [
      "Que veut dire « Septembre est clôturé » ?",
      "Comment je rouvre un mois clôturé ?",
      "Que devient l’argent mis de côté si je reviens dessus ?",
      "Si l’autre clôture le mois, est-ce que je dois le faire aussi ?",
      "Pourquoi je ne peux plus déclarer de dépense sur septembre ?",
      "Pourquoi « n’a pas pu être soldée » ?"
    ],
    "sources": [
      "src/pages/Budget.tsx",
      "src/pages/Cloture.tsx",
      "src/ui/budget/Recap.tsx",
      "src/ui/budget/MoisClos.tsx",
      "src/ui/budget/RevenirDessus.tsx",
      "src/ui/budget/FeuillesDuMois.tsx",
      "src/lib/budget/cloture.ts",
      "supabase/migrations/0065_gardes_manquantes.sql",
      "supabase/migrations/0098_budget_lignes_nees.sql",
      "supabase/migrations/0099_budget_garde_des_saisies.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0108_budget_cloture.sql",
      "supabase/migrations/0109_budget_rouvre.sql"
    ],
    "verifie_sur": "9504cf2",
    "corps": "## Ce que dit un mois clôturé\n\nSur l'écran du mois, la carte sombre dit **« Septembre est clôturé. »** (ou **« … clôturé par [prénom]. »** si c'est l'autre), puis **« Il t’est resté »** (ou **« Il te manque »**) avec le chiffre du jour de la clôture, et **« dont 316,80 € mis de côté »** si tu as mis de l'argent de côté. Dessous : **« Revenir dessus »**.\n\nUn mois clôturé est figé :\n\n- « Déclarer » disparaît ; aucune dépense ne se déclare ni ne se retire ;\n- les montants sont ceux que la clôture a laissés ;\n- aucune ligne n'y naît : une charge ajoutée après coup n'y ajoute rien ;\n- exception : la feuille d'une charge « Mise de côté ».\n\nSi une année n'a pas pu être soldée, une phrase le dit sous le chiffre : « [charge] : 2025 n’a pas pu être soldée. Elle le sera à la prochaine clôture. » Elle ne s'affiche que sur l'appareil qui vient de clôturer, jusqu'au rechargement.\n\n## Clôture à deux\n\nIl n'existe pas aujourd'hui de clôture séparée pour chacun : un mois se clôture **une seule fois pour tout le foyer**. La première personne qui clôture le ferme pour les deux.\n\n- **Celui qui clôture** : son reste et son versement sont enregistrés à son nom.\n- **L'autre** n'a rien à faire. Elle lit « … clôturé par [prénom]. », un « Il t’est resté » calculé sur ses parts, et « Calculé sur tes parts du mois : tu n’as pas fait cette clôture. » Aucun versement n'est fait en son nom.\n\n## « Revenir dessus »\n\nLe bouton est sur la carte du mois clôturé et sur la page de clôture (« Septembre est clôturé le 02/10. »). Chacun du foyer peut s'en servir.\n\n1. Popote demande : « Revenir sur septembre ? Les 316,80 € mis de côté seront retirés de l’épargne. » (sans la 2e phrase si rien n'a été mis de côté). Tu peux refuser.\n2. Si tu acceptes, le mois est de nouveau ouvert **pour tout le foyer**.\n\nCe que ça fait :\n\n- Les versements de la clôture sont retirés de l'épargne : celui de chaque personne encore dans le foyer. Le montant annoncé est ce total, pas ta part seule. Celui de quelqu'un parti du foyer reste dans la poche.\n- Les lignes déjà là restent confirmées et le partage du mois ne se refait pas : un revenu posé après la clôture ne change pas ce mois.\n- Le bandeau « … est fini : on le clôture ? » revient. Tu peux clôturer de nouveau.",
    "verifie_le": "2026-10-26"
  },
  {
    "id": "budget-mois-type",
    "titre": "Le mois type",
    "ecrans": [
      "/mois-type",
      "/budget"
    ],
    "questions": [
      "C’est quoi le mois type ?",
      "Combien chacun paie par mois ?",
      "Pourquoi une charge annuelle est comptée au mois ?",
      "Pourquoi une charge est grisée ?"
    ],
    "sources": [
      "src/pages/MoisType.tsx",
      "src/ui/budget/MoisType.tsx",
      "src/lib/budget/mois-type.ts",
      "src/pages/Budget.tsx",
      "src/pages/Hub.tsx",
      "src/App.tsx",
      "src/lib/donnees/budget.ts",
      "src/lib/budget/charges.ts",
      "src/lib/budget/categories.ts",
      "src/lib/budget/mois.ts",
      "supabase/migrations/0102_budget_mois_suivis.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que c’est\n\nTes charges **telles qu’elles sont posées**, ramenées au mois, et ce que chacun en paie. Ce n’est pas l’écran du mois : il se lit même avant le début du budget.\n\n## Où le trouver\n\n- Avant ton arrivée dans le foyer, l’écran du budget le montre pour le mois où tu entres (« Pas encore » tant que rien n’est posé). La tuile « Budget » de l’accueil le dit aussi : « Ton mois type, chaque mois », ton reste, tes charges et le compte à rebours.\n- Ensuite : la carte **« Le mois type »** de l’écran du budget.\n\n## Comment il est calculé\n\n- Il se calcule pour le mois en cours ou, si tu n’es pas encore dans le foyer, pour le mois de ton arrivée.\n- Un trimestre compte un tiers, une année un douzième : une taxe foncière de 1 200 € par an pèse 100 € par mois.\n- Le partage est celui du budget : au prorata des revenus, ou moitié-moitié si la charge est réglée ainsi ou si un revenu manque. Qui n’est pas encore arrivé n’a aucune part.\n- Une charge qui commence plus tard (« commence plus tard »), ou dont personne de ceux qui la paient n’est encore dans le foyer (« pas encore dans le foyer »), est grisée et n’entre dans aucun total. Une charge retirée ne compte pas.\n\n## L’écran « Le mois type »\n\n- **« Le foyer »** ou un prénom : le sélecteur recompte l’anneau et les catégories sur la part de cette personne.\n- **L’anneau** : une couleur par catégorie, le total au centre. Touche un arc ou sa légende : le centre montre la catégorie et sa part du mois ; retouche-la, le total revient.\n- **Une jauge par personne** (sur « Le foyer ») : la part du revenu que ses charges prennent, son total, « Commun » et « À soi », puis « Il reste 420 € sur 2 500 € » ou « Il manque… ». Sans revenu : un tiret dans la jauge et « Revenu pas encore posé ».\n- **« Par catégorie »** : une carte par catégorie, avec son total et ce que paie chacun. Elle ouvre ses lignes ; « Toutes les lignes » ouvre tout.\n- Si « Autre » pèse au moins 20 % du mois, un encart propose « Ranger mes charges ».\n\nLe tableau de toutes les charges, avec recherche et filtres, a sa page (« budget-toutes-les-charges »).\n\n## Ce que ça ne fait pas\n\nRien ne s’y règle ni ne s’y déclare, et il ne compte pas les dépenses réelles.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-partage",
    "titre": "Le partage au prorata ou moitié-moitié",
    "ecrans": [
      "/budget-reglages",
      "/charges"
    ],
    "questions": [
      "Comment est calculée ma part d’une charge commune ?",
      "C’est quoi « Au prorata » et « Moitié-moitié » ?",
      "Que se passe-t-il s’il manque un revenu ?",
      "Comment changer la règle de partage ?",
      "Puis-je partager une charge autrement que les autres ?"
    ],
    "sources": [
      "src/pages/BudgetReglages.tsx",
      "src/pages/Charges.tsx",
      "src/ui/budget/Gestes.tsx",
      "src/lib/donnees/budget.ts",
      "src/lib/budget/mois.ts",
      "supabase/migrations/0065_gardes_manquantes.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0105_budget_cible.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "Chaque ligne d’une charge commune se répartit entre ses participants, au centime près. Les parts sont figées sur la ligne.\n\n## La règle du foyer\n\nDans « Réglages du budget » (bouton « Revenus » de l’écran du mois), section « Comment vous partagez » :\n- « Au prorata » : chacun paie selon son net mensuel.\n- « Moitié-moitié » : parts égales.\n\nSans choix enregistré, c’est « Au prorata ». Le changement vaut à partir de ce mois : les mois déjà partagés ne bougent pas.\n\n## Le calcul\n\nAu prorata, ta part = ton net ÷ la somme des nets des personnes présentes ce mois-là. Pour un mois, on prend le revenu le plus récent daté d’avant la fin du mois.\n\nExemple : loyer de 800 €, nets de 3 000 € et 2 000 €. Total 5 000 €, donc 60 % et 40 % : 480 € et 320 €. En moitié-moitié : 400 € chacun.\n\nSur une charge, seuls les participants se partagent le montant, dans les proportions du foyer. Une seule personne : 100 % pour elle. Seul dans le foyer : tout est à toi, la règle ne change rien. Les parts sont arrondies au centime, leur somme fait toujours le montant exact.\n\n## S’il manque un revenu\n\nDès qu’une personne présente ce mois-là n’a pas de revenu, tout le monde est compté à parts égales, même si la règle est « Au prorata ». C’est vrai aussi pour une charge qui impose « Au prorata ». L’écran le dit : « Tant qu’il en manque un, le partage se fait à parts égales — même si tu as choisi le prorata. » Quelqu’un qui n’est pas encore arrivé ce mois-là ne « manque » pas.\n\n## Une charge à part\n\nÀ l’ajout, quand au moins deux personnes participent, « Comment la partager » propose « Comme le foyer » (suit la règle), « Au prorata » ou « Moitié-moitié ». Le panneau « Corriger » ne la change pas ensuite.\n\n## Quand une part bouge\n\nPoser un revenu ou changer la règle refait le partage des mois ouverts à partir du mois d’effet. Restent intacts : les mois clôturés et les lignes déjà confirmées ou réglées.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-reste-du-mois",
    "titre": "Le reste du mois et son calcul",
    "ecrans": [
      "/",
      "/budget"
    ],
    "questions": [
      "Comment est calculé « Il te reste » ?",
      "Pourquoi mon reste ne baisse pas quand je déclare une dépense ?",
      "Pourquoi « Il te manque » ?",
      "C’est quoi « après X € de charges prévues » ?",
      "Pourquoi il n’y a pas de reste sur un vieux mois ?",
      "Que veut dire la barre en couleurs ?"
    ],
    "sources": [
      "src/lib/budget/mois.ts",
      "src/ui/budget/Recap.tsx",
      "src/ui/budget/Ligne.tsx",
      "src/pages/Budget.tsx",
      "src/pages/Hub.tsx"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "« Il te reste » est la carte sombre de l'écran du mois. L'accueil donne le même chiffre, arrondi à l'euro.\n\n## Le calcul\n\n**Il te reste = ton revenu du mois − ta part de chaque ligne du mois.**\n\n- **Ton revenu du mois** : le plus récent dont la date d'effet ne dépasse pas le dernier jour du mois. Si ton revenu change en janvier, décembre reste calculé sur l'ancien.\n- **Ta part** : ce que le partage te donne de la ligne. Une ligne où tu n'as aucune part ne compte pas pour toi, même si tu la vois.\n\nCe que pèse une ligne :\n\n- **Plusieurs dépenses dans le mois** : le plus grand des deux, le prévu ou le déclaré (toutes les dépenses déclarées sur la ligne, par l'un ou par l'autre).\n- **Une facture chaque mois** : le montant habituel tant que la facture n'est pas validée, puis le montant retenu.\n- **Fixe**, **Mise de côté**, ajustement : le montant de la ligne.\n\n## Exemple\n\nRevenu : 2 500 €. Tes parts de charges prévues : 1 750 €. Il te reste **750 €**. Parmi elles, « Courses » : 500 € prévus, dont ta part est de 60 %, soit 300 €.\n\n- Tu déclares 350 € de courses : rien ne bouge, 750 €. La ligne compte toujours ses 500 € prévus.\n- Tu déclares 650 € : la ligne compte 650 €, ta part passe à 390 € (+ 90 €). Il te reste **660 €**.\n\nLe chiffre ne baisse donc que si tu dépasses le prévu. Si tu dépenses moins, la différence ne te revient qu'à la clôture.\n\n## Ce que montre la carte\n\n- « sur 2 500 € de revenus » et « après 1 750 € de charges prévues » : c'est la somme de **tes** parts. Seul, c'est le total du foyer ; à deux, non.\n- **« Il te manque »** quand le total dépasse ton revenu. Le chiffre est montré sans signe.\n- **La barre** : tes parts par catégorie, et un morceau « Reste », en pourcentages entiers qui font 100. Quand il te manque de l'argent, il n'y a pas de morceau « Reste ».\n\n## Sans chiffre\n\n« Ajoute ton revenu pour voir ce qu’il te reste. » et le bouton « Revenus » : pas de revenu pour ce mois, y compris pour un mois d'avant ton premier revenu. Avant ton arrivée dans le foyer : voir la page sur l'arrivée.\n\nSur un mois clôturé, le chiffre est celui du jour de la clôture : « Il t’est resté ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-revenus-comptes",
    "titre": "Les revenus et les comptes",
    "ecrans": [
      "/budget-reglages"
    ],
    "questions": [
      "Où poser mon revenu ?",
      "À partir de quand mon revenu compte-t-il ?",
      "Mon revenu est-il visible par l’autre ?",
      "À quoi servent les comptes ? Comment en ajouter ?",
      "Où sont passées les enveloppes ?"
    ],
    "sources": [
      "src/pages/BudgetReglages.tsx",
      "src/pages/Charges.tsx",
      "src/ui/budget/Gestes.tsx",
      "src/lib/budget/revenu.ts",
      "src/lib/budget/mois.ts",
      "src/lib/donnees/budget.ts",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0103_budget_arrivees.sql",
      "supabase/migrations/0076_apres_la_regularisation.sql",
      "supabase/migrations/0106_budget_factures.sql",
      "supabase/migrations/0114_budget_donnees.sql"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "Tout se pose dans « Réglages du budget » : le bouton « Revenus » de l’écran du mois.\n\n## Ton revenu\n\nSection « Les revenus » : tape ton net mensuel après impôt dans « Mon net mensuel (€) », puis « Enregistrer mon revenu » (« Mettre à jour mon revenu » si tu en as déjà un). Chacun pose le sien : il n’y a pas de champ pour celui de l’autre.\n\n- Il sert au partage au prorata. Le foyer le voit (la liste affiche le revenu de chacun, ou « pas encore renseigné »).\n- Sous 100 € par mois, l’appli demande « Tu déclares X par mois. C’est bien ça ? » (« Oui, c’est ça » / « Non, je corrige »).\n\n## À partir de quand\n\n- Il prend effet au mois en cours. Si ton arrivée est à venir, au mois d’arrivée.\n- Ton tout premier revenu remonte à ton mois d’arrivée, sans passer avant le mois qui suit la dernière clôture. Arrivée en septembre, premier revenu posé en octobre : il vaut dès septembre.\n- Les lignes ouvertes depuis ce mois sont repartagées, pas les mois clôturés ni les lignes confirmées.\n- L’ancien revenu est gardé. Posé deux fois le même mois, le second remplace le premier (sauf si le premier est daté de ton arrivée, plus tôt : il reste).\n- Un mois ne compte pour le suivi qu’à partir du premier revenu du foyer (ou d’une clôture) : avant, une facture mise de côté est refusée (« Ajoute ton revenu d'abord. »).\n\n## Les comptes\n\nSection « Les comptes » (« Un par vrai compte bancaire : chaque charge note de quel compte elle est payée. »). Suggestions : « Compte joint », « Mon compte courant », « Livret A », « LDDS ». Choisis le genre (« Commun », « Le mien » ou « Épargne »), puis « Ajouter ce compte ».\n\n- « Ranger » retire un compte des listes sans effacer ce qu’il a payé ; refusé tant que des charges ou poches l’utilisent (« Ce compte porte encore 1 charge(s). Rattache-les ailleurs d'abord. »).\n- À l’ajout d’une charge, « Payée depuis » propose les comptes ; le compte commun est choisi d’office (sinon le premier). Une charge sans compte affiche « sans compte » ; en touchant sa ligne, « Rattacher » apparaît.\n- Aucun écran n’affiche aujourd’hui de virement entre vous : le compte est un renseignement sur la charge.\n\n## Les enveloppes\n\nIl n’y a plus d’enveloppes à poser. Une charge « Plusieurs dépenses dans le mois » porte elle-même son plafond : c’est son montant prévu.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-taxe-fonciere-payee-seul",
    "titre": "La taxe foncière payée tout seul",
    "ecrans": [
      "/charges"
    ],
    "questions": [
      "J’ai payé la taxe foncière tout seul, si je la pose en charge commune, que se passe-t-il ?",
      "Est-ce que l’autre va me rembourser ce que j’ai avancé ?",
      "Existe-t-il une notion de « payé par l’un pour le foyer, à rembourser » ?",
      "Comment entrer une taxe foncière déjà payée avant d’utiliser Popote ?",
      "Les mois d’avant son arrivée sont-ils partagés ?"
    ],
    "sources": [
      "src/pages/Charges.tsx",
      "src/lib/budget/charges.ts",
      "src/lib/budget/feuilles.ts",
      "src/ui/budget/FeuilleMiseDeCote.tsx",
      "src/lib/donnees/budget.ts",
      "supabase/migrations/0050_catalogue_charges.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0103_budget_arrivees.sql",
      "supabase/migrations/0105_budget_cible.sql",
      "supabase/migrations/0106_budget_factures.sql",
      "supabase/migrations/0107_budget_solde.sql",
      "supabase/migrations/0108_budget_cloture.sql",
      "supabase/functions/accept-invite/index.ts"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "## Ce que fait l’appli\n\nLa taxe foncière du catalogue est annuelle et commune. Posée quand tu es seul, avec « Elle se partagera avec le foyer » cochée, c’est une « Mise de côté » : un douzième par mois (1 200 € : 100 €), une ligne par mois depuis « Elle court depuis » (jamais avant ton arrivée), à 100 % sur toi.\n\n« Payée depuis » n’est qu’un renseignement : l’appli ignore que tu l’as déjà payée et ne débite aucun compte.\n\n## L’année en cours, déjà payée\n\n- **Payée un mois que Popote suivait** (depuis le premier mois avec un revenu) : touche la ligne « mis de côté chaque mois », « Autre jour », « Ajouter la facture ». L’appli ne pose que l’écart avec le prévu de l’année, sur le mois où tu saisis : ligne « Taxe foncière — facture 2026 ». Facture de 1 320 € pour 1 200 € prévus : 120 €. Facture plus basse : rien.\n- **Payée avant le premier mois suivi** : facture refusée (« Popote ne suivait pas encore septembre 2026 : cette facture n'y compte pas. »). Les mises de côté courent jusqu’en décembre ; sans facture, la clôture de décembre (dès le 1er janvier) solde l’année et te les rend, en ligne négative « Taxe foncière — solde 2026 ». Pour 2026 tu récupères tout ; dès janvier 2027, tu mets de côté pour la facture de 2027.\n\n## Quand l’autre arrive\n\nElle entre dans la charge (par défaut le 1er du mois suivant son acceptation). Dès son mois d’arrivée, les lignes ouvertes se partagent selon la règle du foyer. Les mois d’avant restent à toi.\n\nExemple : 1 200 € par an, suivi depuis janvier, arrivée le 1er novembre, « Moitié-moitié ». Janvier à octobre : 1 000 € à toi ; novembre et décembre : 50 € chacun. Facture de 1 320 € saisie en décembre : l’écart de 120 € se répartit selon ce que chacun a porté (1 100 € et 100 €), soit 110 € et 10 €. Saisie avant son arrivée, la facture est à toi seul.\n\n## Payé par l’un, à rembourser\n\nIl n’existe pas aujourd’hui de notion « payé par l’un, à rembourser par l’autre » : la feuille de facture ne demande que le montant et la date, et aucun écran n’affiche de somme que l’autre te doit, ni de virement. L’autre paie sa part des lignes de ses mois dans le foyer et sa part de l’écart, pas ce que tu as avancé avant son arrivée.\n\nDécoche « Elle se partagera avec le foyer » pour la garder à toi.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-toutes-les-charges",
    "titre": "Toutes nos charges : le tableau, la recherche et les filtres",
    "ecrans": [
      "/toutes-les-charges"
    ],
    "questions": [
      "Où voir toutes nos charges ?",
      "Comment filtrer les charges par personne ?",
      "Comment chercher une charge ?",
      "Comment voir seulement les charges communes ?",
      "Comment trier les charges par montant ?"
    ],
    "sources": [
      "src/pages/ToutesLesCharges.tsx",
      "src/lib/budget/mois-type.ts",
      "src/ui/budget/MoisType.tsx",
      "src/App.tsx",
      "src/lib/budget/categories.ts"
    ],
    "verifie_sur": "fa94f4a",
    "corps": "## Ce que fait l’écran\n\n« Toutes nos charges » liste chaque charge posée, ramenée au mois (un trimestre compte un tiers, une année un douzième), et ce que chacun en paie : une colonne par personne, puis « Total ». Les chiffres sont ceux du mois type (« budget-mois-type »), à partir du mois où tu entres dans le foyer, ou du mois en cours.\n\n## Y aller\n\n- Sur l’écran « Le mois type » : **« Toutes les lignes »**.\n- Ou touche la carte d’une catégorie : le tableau s’ouvre déjà filtré sur elle, et sur la personne choisie en haut si tu en avais choisi une.\n\n## Chercher, filtrer, trier\n\n- **« Chercher »** : par le nom (« Netflix, prêt, assurance… »).\n- **« Qui paie »** : « Tout le monde », « Commun » (s’il y a plusieurs personnes), ou un prénom : les charges dont il paie une part.\n- **« Catégorie »**, **« Rythme »** (« Chaque mois », « Chaque trimestre », « Chaque année ») et **« Façon de payer »** (« Fixe », « Une facture chaque mois », « Plusieurs dépenses dans le mois », « Mise de côté »).\n- **« Tout effacer »** retire les filtres.\n- **« Trier : montant »** ou **« Trier : nom »** : un toucher passe de l’un à l’autre.\n\n## Les lignes et les totaux\n\n- Sous chaque nom : qui paie (« Commun » ou les prénoms), le montant d’origine d’une charge trimestrielle ou annuelle (« / trim. », « / an »), la façon de payer, et « commence plus tard » ou « pas encore dans le foyer » pour une charge grisée, qui n’entre dans aucun total.\n- Un tiret remplace « 0 € » quand quelqu’un ne paie rien.\n- Les totaux suivent les filtres : la dernière ligne dit « Total filtré ». Sans filtre elle dit « Total par mois », suivie du revenu et de « Il reste » de chacun.\n- Si rien ne correspond : « Aucune charge ne correspond à ces filtres. »\n\n## Ce que l’écran ne fait pas\n\nOn n’y modifie rien : pour corriger une charge, passe par « Mes charges ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "budget-vue-ensemble",
    "titre": "Le budget, en gros",
    "ecrans": [
      "/",
      "/budget"
    ],
    "questions": [
      "C’est quoi le budget dans Popote ?",
      "Comment Popote calcule ce qu’il me reste ?",
      "Pourquoi je ne peux pas voir le mois prochain ?",
      "Quand est-ce qu’un mois est fini ?",
      "Comment on se partage les charges ?",
      "Est-ce que Popote est branchée à la banque ?"
    ],
    "sources": [
      "src/pages/Hub.tsx",
      "src/pages/Budget.tsx",
      "src/pages/BudgetReglages.tsx",
      "src/lib/budget/mois.ts",
      "src/lib/budget/categories.ts",
      "src/lib/donnees/budget.ts",
      "src/lib/budget/mois-type.ts",
      "supabase/migrations/0096_budget_facon.sql",
      "supabase/migrations/0098_budget_lignes_nees.sql",
      "supabase/migrations/0100_budget_mois_gele.sql",
      "supabase/migrations/0102_budget_mois_suivis.sql",
      "supabase/migrations/0108_budget_cloture.sql",
      "supabase/migrations/0114_budget_donnees.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "Popote tient aussi le budget du foyer. L'accueil est la page de ta journée : le repas du jour, ce qui vient, le frigo, et la tuile « Budget » : ce qu'il te reste ce mois-ci.\n\n## Ce que fait le budget\n\nTu poses les charges du foyer (loyer, électricité, courses…) dans « Mes charges ». Chaque mois, chaque charge en cours devient une ligne du mois. Popote partage chaque ligne entre les personnes du foyer, puis calcule ton « Il te reste » : ton revenu du mois, moins ta part de chaque ligne.\n\nUne ligne se règle selon sa façon, choisie dans « Mes charges » :\n\n- « Fixe » : rien à faire, le montant est posé.\n- « Une facture chaque mois » : tu valides le montant habituel, ou tu le corriges.\n- « Plusieurs dépenses dans le mois » : tu déclares tes dépenses au fil du mois (les courses, par exemple).\n- « Mise de côté » : la façon de toute charge qui n'est pas mensuelle (annuelle, trimestrielle) ; une charge mensuelle n'y est jamais. Une part en est mise de côté chaque mois.\n\n## Le partage\n\nLes parts se calculent au prorata des revenus, ou en « Moitié-moitié » : tu choisis dans « Réglages du budget », rubrique « Comment vous partagez ». Exemple au prorata : revenus de 3 000 € et de 2 000 € donnent des parts de 60 % et 40 %. Une charge commune de 1 000 € fait alors 600 € et 400 €.\n\nTant que le revenu de quelqu'un qui est dans le foyer ce mois-là manque, tout se partage à parts égales.\n\n## Le mois type\n\nCarte « Le mois type » de l'écran du mois, ou avant ton arrivée : tes charges ramenées au mois, et ce que chacun en paie (« budget-mois-type »).\n\n## La logique du mois\n\n- Le mois s'ouvre tout seul. La première fois que quelqu'un ouvre le hub ou le budget, Popote crée les lignes du mois. Un mois passé non ouvert est rattrapé à l'ouverture (jusqu'à deux ans en arrière).\n- Un mois à venir ne s'ouvre jamais : on ne peut pas le consulter.\n- Un mois reste ouvert jusqu'à sa clôture. Le mois en cours ne se clôture jamais : on le clôture à partir du 1er du mois suivant.\n- Une fois clôturé, un mois est figé : plus aucune dépense à y déclarer. Seul « Revenir dessus » le rouvre.\n\n## Ce que le budget ne fait pas\n\nIl n'existe pas aujourd'hui de lien avec une banque : les dépenses se déclarent à la main.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "compte-connexion",
    "titre": "Se connecter, mot de passe, déconnexion",
    "ecrans": [
      "/motdepasse"
    ],
    "questions": [
      "J’ai oublié mon mot de passe, comment faire ?",
      "Comment changer mon mot de passe ?",
      "Comment me déconnecter ?",
      "L’appli dit « Ta session a expiré », pourquoi ?",
      "À quoi sert « Première connexion » ?"
    ],
    "sources": [
      "src/pages/SignIn.tsx",
      "src/ui/porte/EcranDeConnexion.tsx",
      "src/ui/porte/modes.ts",
      "src/pages/Password.tsx",
      "src/pages/Settings.tsx",
      "src/pages/Profil.tsx",
      "src/App.tsx",
      "src/lib/supabase.ts",
      "src/lib/session-perdue.ts",
      "src/lib/lien.ts",
      "src/pages/Onboarding.tsx",
      "supabase/config.toml"
    ],
    "verifie_sur": "e648dd8",
    "corps": "## Se connecter\n\nL’écran de connexion montre un frigo (ses aimants sont des exemples, rien de toi) et, sur une feuille, « Popote » et le formulaire. Sur grand écran, le frigo est à gauche. Deux liens en bas choisissent ce que tu fais ; celui du mode en cours devient « J’ai déjà un mot de passe ».\n\n- **Mot de passe** (le mode d’arrivée) : « Ton e-mail », « Mot de passe » (« Afficher » le montre en clair, « Cacher » le remasque), puis « Entrer ». Les portes du frigo s’ouvrent pendant l’envoi. Si ça échoue, elles se referment : « E-mail ou mot de passe incorrect. »\n- **« Première connexion »** : à utiliser quand ton compte n’a pas encore de mot de passe. « Recevoir le lien » envoie un lien par mail. Il sert une fois ; ouvre-le depuis le même appareil, puis choisis ton mot de passe.\n- **« Mot de passe oublié »** : « Réinitialiser mon mot de passe » envoie un lien de réinitialisation, valable une heure. L’appli répond « Si un compte existe pour … » : même message avec ou sans compte. Le lien mène droit à l’écran du nouveau mot de passe, qu’on ne peut pas passer.\n\nUn lien de mail ouvert sans être connecté (le « C’est fait » d’un rappel, par exemple) te ramène sur la même page après la connexion, dans l’heure. Un lien trop vieux ou déjà utilisé affiche « Ce lien a expiré ou a déjà servi » : redemande-en un. Si tu redemandes trop vite : « Doucement : attends une minute avant de redemander un lien. »\n\n## Choisir ou changer son mot de passe\n\nIl faut **8 caractères au moins**. Pour le changer (« Réglages », en haut à gauche, ramène en arrière) : accueil de la cuisine, rond avec ton initiale (« Réglages »), la ligne « Changer mon mot de passe » (dans la carte du bas). Écris-le dans « Mot de passe », puis « Enregistrer ». Refus possibles : « C’est déjà ton mot de passe : choisis-en un autre. » ou « Ce mot de passe est trop facile à deviner : allonge-le, ou mélange lettres et chiffres. »\n\n## Se déconnecter\n\n« Me déconnecter » dans les réglages (ligne « Me déconnecter », dans la carte du bas), « Me déconnecter » en bas de ton profil (le rond de l’accueil de Popote ; une fois ton revenu posé), et « Ce n’est pas moi » sur un lien d’invitation. Ces déconnexions valent pour **cet appareil seulement**, les autres restent connectés. Seul « Se déconnecter » de l’écran « Il te faut une invitation » ferme tous les appareils. Sans réseau, elle peut échouer (« La déconnexion n’a pas abouti… »).\n\n## Quand la session expire\n\nSi l’appli ne te reconnaît plus, elle te ramène à l’écran de connexion avec « Ta session a expiré : reconnecte-toi. » Une coupure de réseau n’est pas une session expirée (« installation-hors-ligne »).\n\n## Ce que l’appli ne fait pas\n\nJe n’ai pas trouvé de connexion par Google ou Apple, ni de moyen de changer l’adresse e-mail d’un compte.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "compte-objectifs",
    "titre": "Tes objectifs nutritionnels",
    "ecrans": [
      "/objectifs"
    ],
    "questions": [
      "Comment régler mes objectifs de calories et de protéines ?",
      "Pourquoi mes barquettes sont-elles dressées à parts égales ?",
      "Qu’est-ce que « Fixe tes objectifs » ?",
      "Est-ce que Léa voit mes objectifs ?",
      "Comment changer mes objectifs ?",
      "À quoi servent les objectifs dans l’appli ?",
      "Quelles sont les valeurs par défaut des objectifs ?",
      "Peut-on revoir mes anciens objectifs ?"
    ],
    "sources": [
      "src/pages/Targets.tsx",
      "src/ui/reglages/coque.tsx",
      "src/lib/donnees/foyer.ts",
      "src/pages/Dressage.tsx",
      "src/pages/Hub.tsx",
      "src/pages/Inventer.tsx",
      "src/lib/donnees/bilan.ts",
      "src/lib/nutrition/portions.ts",
      "src/pages/Accueil.tsx",
      "supabase/migrations/0005_policies.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que fait l’écran\n\n« Mes objectifs » fixe ce que tu vises **chaque jour** : calories, protéines, fibres, glucides, lipides. Chacun a les siens (« Ta moitié a les siens »). Tu y vas par « Objectifs » dans le sélecteur « Objectifs | Réglages » en haut de « Réglages » et de « Mes objectifs », par le bandeau « Fixe tes objectifs. » de l’accueil de Popote (si ton prénom et ton revenu sont posés ; sinon c’est « Complète ton profil. »), ou par le bouton « Fixe tes objectifs » du dressage (quand c’est toi qui n’en as pas).\n\n## Comment faire\n\n1. Fais glisser chaque curseur.\n2. Appuie sur « Enregistrer » : « Objectif enregistré. »\n\nLimites : calories de 1 200 à 4 000 kcal (pas de 50) ; protéines de 40 à 250 g (pas de 5) ; fibres de 10 à 60 g (pas de 1) ; glucides de 50 à 500 g (pas de 10) ; lipides de 20 à 150 g (pas de 5).\n\nTant que tu n’as rien enregistré, les curseurs partent de 2 000 kcal, 150 g de protéines, 30 g de fibres, 200 g de glucides et 60 g de lipides. Ce ne sont pas des objectifs tant que tu n’as pas appuyé sur « Enregistrer ».\n\n## Les règles\n\n- Chaque « Enregistrer » ajoute une ligne : les anciens restent sous « Ce que tu visais avant » (date, calories, protéines, le dernier compris).\n- **Sans objectifs, tes barquettes sont dressées à parts égales** : chacune pèse la moyenne des parts des autres. L’étape de dressage le dit : « … n’a pas encore fixé ses objectifs : ses barquettes sont dressées à parts égales. » Le bandeau de l’accueil dit : « Sans tes objectifs, tes barquettes sont dressées à parts égales. »\n\n## À quoi ils servent\n\n- **Dressage** : le poids de ta part. Un dîner vaut **35 %** de ta journée, en calories et en protéines : avec 2 000 kcal et 150 g de protéines, 700 kcal et 52,5 g (voir « cuisine-portions »).\n- **Accueil** : « kcal aujourd’hui, sur … », avec une barre, quand un repas est prévu aujourd’hui (sans repas, rien ne s’affiche). **Bilan** : la cible tracée sur les graphes de chacun (rien n’est tracé pour qui n’a pas d’objectifs).\n- **Inventer** : les bornes de départ (calories et protéines d’un dîner, soit 35 % de ta journée), modifiables là-bas. Le modèle de langage ne voit jamais tes objectifs, seulement ces bornes. Sans objectifs enregistrés, elles partent de 30 g et 620 kcal.\n\n## Qui voit quoi\n\nL’autre personne du foyer peut lire tes objectifs ; seul(e) toi peux modifier les tiens. Les foyers amis ne les voient jamais.\n\n## Ce que l’appli ne fait pas\n\nElle ne calcule pas d’objectif à partir de ton poids ou de ton âge : tu choisis les chiffres.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "compte-profil",
    "titre": "Ton profil : prénom, revenu, arrivée",
    "ecrans": [
      "/profil"
    ],
    "questions": [
      "Comment changer mon prénom ?",
      "À quoi sert mon revenu net mensuel ?",
      "Pourquoi l’appli me demande ma date d’arrivée dans le foyer ?",
      "Comment corriger mon revenu ou ma date d’arrivée ?",
      "C’est quoi « Complète ton profil » ?"
    ],
    "sources": [
      "src/pages/Profil.tsx",
      "src/App.tsx",
      "src/pages/Hub.tsx",
      "src/lib/donnees/foyer.ts",
      "src/lib/donnees/budget.ts",
      "src/lib/budget/revenu.ts",
      "src/lib/budget/mois.ts",
      "supabase/migrations/0051_budget_socle_corrige.sql",
      "supabase/migrations/0103_budget_arrivees.sql",
      "supabase/migrations/0112_budget_depart.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que fait l’écran\n\nTon profil donne à l’appli ton prénom, ton revenu et ta date d’entrée dans le foyer. On l’ouvre avec le rond qui porte ton initiale, en haut à droite de l’accueil de Popote (ou de l’écran du budget). Un « ? » dans le rond : ton prénom est vide.\n\n## Les trois champs\n\n- **« Ton prénom »** : 40 caractères au plus. Les autres le lisent sur chaque ligne de charge. Vide, il s’affiche « Sans prénom ».\n- **« Ton revenu net mensuel (€) »** : après impôt (2 500 ou 2 500,50). Il ne sert qu’à calculer votre partage du budget, et **le foyer le voit**. Sous 100 € par mois, l’appli demande « Tu déclares 0,50 € par mois. C’est bien ça ? » (avec ton montant) : « Oui, c’est ça » ou « Non, je corrige ». Zéro est refusé.\n- **« Ton arrivée dans le foyer »** : le jour à partir duquel tu habites là. C’est elle qui décide des mois que tu partages. Au plus deux ans à l’avance (au-delà, la base refuse).\n\n« Enregistrer » ne s’allume que quand les trois champs sont remplis.\n\n## Ce que ça déclenche\n\n- **Sans ton revenu** (ou si l’un de ceux qui sont là ce mois-là n’en a pas), le partage se fait à parts égales. Sur l’accueil, le bandeau « Complète ton profil. » s’affiche quand ton prénom ou ton revenu manque (il ne regarde que toi).\n- Ton **premier revenu** compte dès le mois de ton arrivée, sauf pour un mois déjà clôturé. Les revenus suivants prennent effet le mois où tu les saisis.\n- **Date dans le futur** : l’appli écrit « Tu arrives plus tard : tu ne participeras à aucune charge d’ici là. » L’accueil de Popote compte les jours jusqu’au 1er de ce mois (« Commence en … » quand aucune charge n’est posée).\n- **Changer la date** repartage les mois situés entre l’ancienne et la nouvelle date. Un mois déjà clôturé ne bouge pas.\n- À ton arrivée, tu es ajouté(e) aux charges communes déjà posées.\n\n## Exemple\n\nUne personne arrive le 15 novembre et pose son revenu le 2 décembre : il vaut dès novembre, si novembre n’est pas clôturé.\n\n## Si tu es invité(e)\n\nEn rejoignant par un lien, ton prénom est vide et ta date d’arrivée est le 1er du mois suivant. L’appli t’amène sur ton profil à chaque ouverture, tant que ton prénom est vide. Tu peux appuyer sur « ‹ Popote » pour le remettre à plus tard : l’accueil te le rappellera.\n\n## Ce que l’appli ne fait pas\n\nJe n’ai pas trouvé d’écran pour supprimer un revenu.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-ajout-stock",
    "titre": "Ajouter à la main un produit ou un plat acheté",
    "ecrans": [
      "/frigo"
    ],
    "questions": [
      "Comment ajouter un produit au congélateur ?",
      "Comment ajouter un plat acheté tout prêt ?",
      "Comment lire l’étiquette d’un plat avec une photo ?",
      "Pourquoi je ne peux pas ajouter un plat sans calories ?",
      "Quelle différence entre « Un produit » et « Un plat » ?",
      "Combien d’étiquettes puis-je lire par mois ?"
    ],
    "sources": [
      "src/pages/AjoutManuel.tsx",
      "src/pages/Frigo.tsx",
      "src/lib/donnees/barquettes.ts",
      "src/lib/donnees/bilan.ts",
      "src/lib/quantite.ts",
      "supabase/functions/etiquette/index.ts",
      "supabase/migrations/0047_peremption_donnee.sql",
      "supabase/migrations/0048_stock_congele.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nDans le frigo, porte ouverte, **« + Ajouter au frigo »** (ou **« + Ajouter au congélateur »**) ajoute ce que tu n’as pas cuisiné ; au placard, « Le placard » puis « + Ajouter au placard ». Au frigo et au congélateur, choisis d’abord « Un produit » (un ingrédient, il compte dans tes courses) ou « Un plat » (un repas, il compte dans ta semaine). Le placard ne prend que des produits.\n\n## Un produit\n\nLe nom (champ « Ce qu’il y a »), une quantité facultative (plus grande que zéro) et l’unité (g, ml ou u), puis « Ajouter ». Au congélateur, deux dates : « Congelé le » (aujourd’hui par défaut) et « À manger avant » (3 mois plus tard, jamais avant la mise au froid) ; changer la première recale la seconde. Elle se relit dans la fiche de l’ingrédient (« À manger avant »).\n\n## Un plat\n\nIl devient une ou plusieurs **barquettes**, mangées depuis « La semaine » et comptées dans les calories du jour. Remplis « Le plat », « Parts », « g / part », « kcal / part », puis « Protéines », « Glucides », « Lipides », « Fibres » (par part).\n\n« Ajouter la barquette » (ou « Ajouter N parts ») ne s’active que si le nom, le poids d’une part, ses calories et ses protéines sont remplis : sans eux, ce repas compterait pour zéro. Péremption au frigo : 4 jours. Une barquette ajoutée à la main ne compte pas dans les barquettes du bilan ni dans son coût par part.\n\n## Lire l’étiquette d’un plat acheté\n\n1. « Photographier » (jusqu’à **trois** photos : face, tableau nutritionnel, date ; « Une de plus »).\n2. « Lire l’étiquette ». Le modèle de langage **recopie** ce qui est imprimé, il n’estime rien. Les champs se remplissent sans rien valider : corrige.\n\n- Le tableau, pour 100 g, est ramené au poids d’une part (poids de la boîte ÷ parts) ; ignoré au-delà de 900 kcal pour 100 g.\n- Les calories « par portion » du fabricant ne sont préférées que si l’emballage annonce autant de portions que ton nombre de parts, à 25 % près du calcul.\n- La date imprimée remplit « À manger avant », mais ne sert qu’au congélateur : au frigo, 4 jours.\n- Rien de lisible : « Je n’ai rien pu lire sur ces photos. » Tableau flou : « Lu — à vérifier, le tableau n’est pas net. »\n\n**Quota : 40 lectures par mois** pour le foyer, remis à zéro le 1er. Au-delà : « Quota atteint : 40 étiquettes par mois. Il repart le 1er. »\n\n## Ce que l’appli ne fait pas\n\nElle n’estime pas les calories d’un plat d’après sa photo.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-amis",
    "titre": "Les foyers amis et les recettes partagées",
    "ecrans": [
      "/reglages"
    ],
    "questions": [
      "Comment ajouter un foyer ami pour échanger des recettes ?",
      "Que voit mon ami de mon foyer ?",
      "Combien de temps marche le lien d’ami ?",
      "Comment rompre une amitié ?",
      "Comment partager une recette avec mes amis ?"
    ],
    "sources": [
      "src/pages/Settings.tsx",
      "src/pages/AccepteAmi.tsx",
      "src/lib/donnees/amis.ts",
      "src/pages/Importer.tsx",
      "src/pages/Choisir.tsx",
      "src/ui/recettes/Vignette.tsx",
      "supabase/migrations/0035_amis.sql",
      "supabase/migrations/0037_cuisiner_ensemble.sql",
      "supabase/migrations/0038_convive_frontiere.sql"
    ],
    "verifie_sur": "84225ae",
    "corps": "## Ce que fait l’appli\n\nDeux foyers peuvent devenir **amis** : ils échangent des recettes, et l’un peut convier l’autre à cuisiner (voir « cuisine-session-partagee »). À ne pas confondre avec inviter quelqu’un dans ton propre foyer (« foyer-inviter »).\n\n## Devenir amis\n\n1. « Réglages », carte « Vos amis » : « Inviter un foyer ». Un lien apparaît (« Invitation en attente, valable jusqu’au … »).\n2. « Copier le lien » et envoie-le ; « Annuler » le retire.\n3. L’autre foyer l’ouvre (il lui faut déjà un foyer et un mot de passe) : « Devenir amis ? », puis « Accepter » ou « Non merci ».\n\nLe lien vaut **7 jours** et ne sert qu’une fois (« Ce lien a déjà servi. », « Ce lien a expiré. Demande-lui d’en refaire un. », « C’est ton propre lien. »). Passé 7 jours, il disparaît de la liste.\n\n## Les règles\n\n- L’amitié est dans les deux sens : « Rompre » (avec confirmation : « Ne plus partager avec … ? ») la coupe pour les deux, et les recettes partagées cessent d’être visibles des deux côtés. Les invitations à cuisiner entre ces deux foyers cessent aussi.\n- Un foyer ami est nommé par les prénoms de ses membres.\n- Un foyer ami voit les recettes marquées **« partagée »**, avec ton prénom : « Partagée par … » dans « Choisir ». Les recettes « publiques » sont vues par tous les foyers, amis ou non.\n- Tu choisis la visibilité en collant une recette (« Qui peut la voir » : « Nous deux », « Nos amis » ou « Tout le monde »). Une recette inventée reste privée.\n- Courses, barquettes, prix et objectifs ne sortent pas du foyer. Seule exception : quand tu convies un ami à ta session de cuisine, il voit les gestes et le nom de tes recettes pendant la session.\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui de choix de visibilité pour une recette déjà enregistrée.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-bilan",
    "titre": "Le bilan de la cuisine",
    "ecrans": [
      "/bilan"
    ],
    "questions": [
      "Que montre le bilan ?",
      "Comment est calculé le coût d’une part ?",
      "Pourquoi mon bilan dit « Aucun repas renseigné » ?",
      "Comment clore la semaine ?",
      "Pourquoi certains jours sont des traits et pas des barres ?",
      "À quoi sert le budget des courses dans le bilan ?"
    ],
    "sources": [
      "src/pages/Bilan.tsx",
      "src/ui/bilan/Barquettes.tsx",
      "src/ui/bilan/CartePersonne.tsx",
      "src/ui/bilan/CeQuiEstPasse.tsx",
      "src/ui/bilan/Courses.tsx",
      "src/ui/bilan/Graphe.tsx",
      "src/ui/bilan/echelle.ts",
      "src/lib/donnees/bilan.ts",
      "src/lib/suivi.ts",
      "src/pages/Settings.tsx",
      "src/lib/donnees/cycle.ts",
      "supabase/migrations/0013_cycle.sql",
      "src/pages/Choisir.tsx",
      "src/lib/donnees/catalogue.ts"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\n« Bilan » (barre du bas) se remplit tout seul : payé, mangé, jeté, calories et protéines. Période : « 7 jours » (six jours d’avant et aujourd’hui), « Ce mois » (depuis le 1er) ou « 3 mois » (depuis le 1er d’il y a deux mois).\n\n## Le budget\n\n- « 0,00 € » en très gros, « payés » dessous : le total imprimé des tickets de la période, à leur date d’achat.\n- « X € » à droite, « de budget sur la période » dessous : ton « Budget des courses » mensuel (réglages), ramené à la période. La jauge passe à l’ocre au-delà.\n- « N € la part » : payé ÷ barquettes dressées en session sur la période. Les plats achetés ne comptent pas.\n- « N € encore estimés » : les articles sans prix payé, **jamais additionnés** au payé.\n- Exemple : 320 € par mois, 7 jours : plafond 73,59 € (320 × 7 ÷ 30,44). Payé 87,40 € : « 13,81 € au-dessus du budget. » Sur 14 barquettes : 6,24 € la part.\n\n## Les barquettes\n\nCelles préparées dans la période, en trois cartes : « N mangées », « N au frais » et, s’il y en a, « N jetées ». « Ce qui est passé » : une ligne par recette, avec photo, barre et « mangées / dressées » (« 6 / 6 » : tout est mangé), puis « N jetées ».\n\n## Les courbes\n\nChaque personne a sa carte, avec deux graphiques jamais sur le même dessin : calories (« N kcal en moyenne », en vert) et protéines (« N g de protéines en moyenne », en safran). Les deux personnes se lisent à la **même échelle**. Avec des objectifs, la cible est tracée en pointillés (« cible 2 200 kcal ») ; sans, rien. Dessous : les jours de la semaine (« 7 jours »), ou les dates des bouts.\n\n- Calories = **plafond** : « N jours sous la cible sur les M renseignés ».\n- Protéines = **plancher** : « N jours au-dessus de la cible sur les M renseignés ».\n- Un jour hors cible a une barre plus claire ; la phrase dessous dit combien.\n- Un **jour non renseigné est un trait gris, pas un zéro**, hors de la moyenne.\n- Un jour est renseigné dès qu’un repas est « mangé » ou « sauté », ou qu’un extra est noté.\n- Sans jour renseigné : « Aucun repas renseigné sur la période. »\n\n## Clore la semaine\n\nLa carte « Clore la semaine » n’apparaît que sous « La semaine tourne ». « Clore et préparer la semaine prochaine » demande confirmation : la semaine se termine et l’accueil repasse à « Rien de prévu ».\n\n## Ce que l’appli ne fait pas\n\n« Rien à mesurer encore » tant qu’il n’y a ni barquette, ni ticket, ni article estimé, ni repas renseigné. Seuls les calories et les protéines sont suivis (ni glucides, ni lipides).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-choisir",
    "titre": "Choisir les recettes de la semaine",
    "ecrans": [
      "/choisir"
    ],
    "questions": [
      "Comment choisir les recettes de dimanche ?",
      "Que veut dire « 6 / 10 parts » ?",
      "Comment changer le nombre de parts d’une recette ?",
      "Comment filtrer les recettes rapides ou riches en protéines ?",
      "À quoi sert « Avec ce que j’ai » ?",
      "Pourquoi une recette est-elle affichée avec une fourchette de protéines ?"
    ],
    "sources": [
      "src/pages/Choisir.tsx",
      "src/lib/donnees/catalogue.ts",
      "src/lib/recettes/parts.ts",
      "src/lib/recettes/pages.ts",
      "src/ui/recettes/Filtres.tsx",
      "src/ui/recettes/Vignette.tsx",
      "src/ui/recettes/Retenues.tsx",
      "src/ui/recettes/FicheRecette.tsx",
      "src/lib/recettes/temps.ts",
      "src/lib/nutrition/macros.ts",
      "supabase/migrations/0092_la_photo_et_les_gestes.sql",
      "src/lib/donnees/cycle.ts",
      "src/pages/Inventer.tsx",
      "supabase/migrations/0003_class_b.sql"
    ],
    "verifie_sur": "02a9f37",
    "corps": "## Ce que fait l’appli\n\nTu retiens les recettes de dimanche. L’écran compte les parts : « 6 / 10 parts » en bas : 6 parts retenues sur 10 visées.\n\n## Comment faire\n\n1. Cherche ou filtre, puis touche le **+** rond d’une recette (sur sa photo). Le **i**, en haut à droite de la photo, ouvre sa fiche ; une coche verte (« Retenue ») et un cadre vert marquent une recette retenue.\n2. En haut, la carte sombre montre une bande de photos qui défile de côté : une petite carte par recette retenue, toutes ensemble. Le **−** et le **+** changent ses parts d’une en une (de 1 à 20 ; tu peux aussi taper le nombre ; deux appuis rapides font deux pas, et si l’écriture échoue le chiffre revient à celui de la base avec l’erreur), et la croix (« Retirer ») la retire.\n3. « N repas à couvrir » règle les « Parts visées cette semaine » (jusqu’à 40 ; 10 par défaut).\n4. « Faire la liste » (dès une recette) mène aux courses.\n\n## Les parts\n\nLa carte dit « Il manque N parts », « C’est couvert » ou « Au-delà du prévu ». Le + propose ce qui manque pour atteindre l’objectif, sans dépasser ce que la recette donne. Exemple : objectif 10, 4 parts déjà retenues, recette pour 8 : il propose 6 parts. Objectif atteint : 2 parts ; dépassé : 1.\n\n## Ce qu’affiche une recette\n\nSur la photo, le temps actif en pastille (« Gestes non comptés » si inconnu). Dessous : le nom, les parts et « se congèle », puis les protéines **en gros** et les calories, **en fourchette** (« 28–34 g de protéines par part »), et « il manque … » d’après ton stock. « Macros inconnues » : trop d’ingrédients non reconnus ; sous 90 % d’ingrédients connus, le pourcentage est indiqué.\n\nLe **temps actif** est celui de tes gestes : le four ne compte pas, enfourner oui. Tri : le plus rapide d’abord, temps inconnus à la fin.\n\n## Les filtres\n\nLes puces passent à la ligne : « ≤ 20 min actives », « ≥ 30 g de protéines », « Se congèle », « Avec ce que j’ai ». Le bouton à droite de la recherche (« Appareils et filtres ») ouvre : « Temps les mains prises », « Protéines au moins », « Calories au plus », « Avec seulement » (appareils), « Jamais essayée ».\n\n- Protéines et calories jouent la **borne défavorable** : « au moins 30 g » écarte une recette annoncée entre 28 et 34.\n- La recherche ne lit que le titre ; chaque mot doit s’y trouver, dans n’importe quel ordre.\n- « Avec ce que j’ai » : tous les ingrédients reconnus de la recette sont dans ton stock.\n- « Jamais essayée » écarte les recettes déjà retenues une autre semaine.\n\nLa liste se lit dix par dix : « Les 10 suivantes », ou les numéros de page. Elle ne montre que les recettes planifiables (chaque étape a une durée) : pas les inventées gardées avant le dernier changement.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-courses",
    "titre": "La liste de courses et le magasin",
    "ecrans": [
      "/magasin"
    ],
    "questions": [
      "Comment la liste de courses est-elle calculée ?",
      "Pourquoi la liste ne retire pas ce que j’ai déjà au frigo ?",
      "Comment ajouter un article à la liste ?",
      "Que se passe-t-il quand je coche un article ?",
      "Comment changer le magasin d’un article ?",
      "Que devient la liste si je la refais ?"
    ],
    "sources": [
      "src/pages/Magasin.tsx",
      "src/lib/donnees/courses.ts",
      "src/lib/liste.ts",
      "src/lib/rayons.ts",
      "src/ui/rayons.tsx",
      "supabase/migrations/0021_cocher_remplit.sql",
      "supabase/migrations/0117_cuisine_corrections.sql",
      "seed/conversions.json"
    ],
    "verifie_sur": "02a9f37",
    "corps": "## Ce que fait l’appli\n\n« Faire la liste » (dans « Choisir ») calcule la liste d’après les recettes retenues ; « La liste » sert au magasin.\n\n## Comment la liste est calculée\n\n- Chaque quantité est multipliée par **parts retenues ÷ parts de la recette**. Exemple : 200 g de crème pour 4, retenue pour 6 parts : 300 g.\n- Un même aliment dans plusieurs recettes fait **une ligne**, additionnée.\n- Ce qui se compte à l’unité (« 2 oignons ») passe en grammes si l’appli connaît le poids : celui que tu as pesé (voir « Peser »), sinon un poids de référence.\n- Ce qu’elle ne sait pas additionner devient une note (« + 1 à l’unité à compter »).\n- **Ce que tu as déjà n’est pas retiré** : la liste donne tout ce que les recettes demandent.\n\n## Au magasin\n\nEn haut, le total en gros (« 9,40 € estimés pour 3 articles à prendre », ou « payés ») et « 0 sur 3 dans le panier », avec une barre de segments.\n\n- Articles groupés par magasin, puis par rayon (Fruits et légumes, Boucherie, Frais, Surgelés, Épicerie salée, etc.), chacun dans sa carte. L’ordre s’apprend ensuite de tes cochages, magasin par magasin.\n- Touche une ligne pour changer son magasin, noter le « Prix payé », ou « Supprimer ». Une ligne cochée ou payée ne se supprime pas : l’écran le dit.\n- Sous la liste : « Ajouter un article » (« Ce qu’il faut prendre », rayon, prix estimé, « Ajouter à la liste »), « Compléter ma liste », « Estimer les prix d’après mes tickets » et « J’ai payé — photographier le ticket ».\n- « Compléter ma liste » : des catégories (Boissons, Entretien, Épicerie, Frais du quotidien, Hygiène, Maison) et « Ce que vous reprenez souvent ». Une suggestion va au rayon de sa catégorie (« Épicerie » : Épicerie salée ; « Maison » : Entretien) ; une habitude, au rayon deviné d’après son nom, sinon « Autre ».\n\n## Quand tu coches\n\nL’article entre dans le frigo, le congélateur ou le placard, selon son rayon (« cuisine-stock »), sauf Entretien et Hygiène, non rangés. Décocher le retire ; l’ordre des rayons appris reste.\n\n## Terminer\n\nLe bouton du bas, toujours visible, dit « J’ai tout, rentrons » : un appui, il passe à « Tout est là » et ouvre le plan. S’il reste des articles à cocher, il dit « Rentrer sans les N articles » (« Rentrer sans cet article » s’il n’en reste qu’un) : un premier appui le change en « Oui, rentrer sans les N » pendant cinq secondes ; seul le second ouvre le plan. « Continuer plus tard » revient en arrière.\n\n## Refaire la liste\n\nDepuis « Choisir », avant la session, les lignes venues des recettes sont recalculées. Ce que tu as ajouté, et ce qui est coché ou payé, reste. Si le besoin dépasse ce qui est pris, la nouvelle ligne est le manque : 200 g de beurre cochés, besoin de 400 g : une ligne de 200 g revient.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-dressage",
    "titre": "Le dressage, « On range » et les barquettes",
    "ecrans": [
      "/dressage"
    ],
    "questions": [
      "Comment dresser les barquettes après la cuisine ?",
      "Que fait le bouton « C’est dressé » ?",
      "Pourquoi celle qui n’a pas d’objectifs a-t-elle des parts égales ?",
      "Que se passe-t-il quand j’appuie sur « C’est dressé » ?"
    ],
    "sources": [
      "src/pages/Dressage.tsx",
      "src/ui/dressage/Habillage.tsx",
      "src/lib/dressage.ts",
      "src/lib/nutrition/portions.ts",
      "src/lib/donnees/barquettes.ts"
    ],
    "verifie_sur": "7ccc089",
    "corps": "## Ce que fait l’appli\n\nUne session produit des **barquettes**, pas des recettes : nommées, datées, avec leurs calories et leurs protéines. Le dressage a **deux étapes sur le même écran**, rappelées en haut par « 1 Dresser · 2 Ranger » (l’étape en cours est en safran) : on dresse, puis « On range » (« cuisine-on-range »). Tu y arrives par « Passer au dressage » ou « Dresser les barquettes ». Le calcul des poids est expliqué dans « cuisine-portions ».\n\n## Étape 1 : dresser\n\nLe titre donne le total en grand : « Dresse 30 barquettes », avec « Remplis chacune au poids indiqué : c’est ce qui rend les parts justes. » Dessous, une rangée de compteurs : le nombre de barquettes de chaque recette (« 6 Lasagnes », « 2 Pizza »).\n\nPuis une carte par recette, avec sa photo quand elle en a une, son titre et « N barquettes à remplir ». Pour chaque personne, une ligne : son initiale, « N × G g », « pour <prénom> », les kcal et les g de protéines d’une part. S’il faut un complément, il s’affiche sous la personne : « + N g de skyr pour <prénom> ». Une phrase explique le calcul. Il n’y a rien à saisir : remplis tes barquettes à ces poids.\n\n- Celui ou celle qui n’a pas fixé ses objectifs a quand même ses parts, au poids moyen des autres (« … parts égales »). Un encart le dit en haut ; il porte « Fixe tes objectifs » quand c’est toi.\n- Une recette dont trop peu d’ingrédients sont chiffrés dit : « Recette mal quantifiée : les parts sont égales, faute de mieux. »\n\n**« C’est dressé »** ouvre la seconde étape ; rien n’est encore créé.\n\n## Étape 2 : « On range »\n\nFrigo ou congélateur, l’heure du rangement, « La session a pris » et « Ranger les N barquettes » : tout est dans « cuisine-on-range ». Rien n’est posé tout seul sur les jours de la semaine : tu choisis ce que tu manges quand.\n\n## Si ça échoue\n\nAppuie de nouveau sur « Ranger » : les barquettes déjà créées ne sont pas refaites et les ingrédients ne sont pas retirés deux fois (« cuisine-on-range »). Sans recette retenue : « Rien à dresser » ; sans session : « Aucune session ». Si la lecture échoue, l’écran dit « Je n’ai pas pu lire la session » et propose « Réessayer ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-fiche-plat-gestes",
    "titre": "Les gestes d’une fiche : manger, congeler, sortir, jeter, retirer",
    "ecrans": [
      "/frigo"
    ],
    "questions": [
      "Comment manger une barquette maintenant ?",
      "Quelle part est prise quand j’en mange une ?",
      "Quelle différence entre jeter et retirer une barquette ?",
      "Comment congeler ou sortir une barquette du congélateur ?",
      "Pourquoi je ne peux pas sortir les parts de demain ce matin ?",
      "Pourquoi un repas n’a plus de barquette ?"
    ],
    "sources": [
      "src/ui/frigo/FichePlat.tsx",
      "src/ui/frigo/Combien.tsx",
      "src/lib/frigo.ts",
      "src/lib/donnees/frigo.ts",
      "src/lib/peremption.ts",
      "supabase/migrations/0047_peremption_donnee.sql",
      "supabase/migrations/0122_frigo_corrections.sql"
    ],
    "verifie_sur": "ff3539b",
    "corps": "## Ce que fait l’appli\n\nLes gestes de la fiche d’un plat (« cuisine-fiche-plat » dit ce qu’elle affiche) : manger une part, congeler, sortir du congélateur, jeter, retirer. Quand il y a plusieurs parts, la fiche demande « Combien tu en … ? » (un compteur − et +) ; les parts non posées sur un repas partent d’abord.\n\n## Au frigo\n\n- **« En manger une maintenant »** : ton repas du moment (matin avant 10 h, midi avant 16 h, sinon soir) devient mangé ; refusé s’il l’est déjà. L’appli prend **ta** part d’abord, puis une part pour tout le monde, celle d’un autre en dernier recours ; une part non posée avant une posée, la plus pressée d’abord. Si une part posée est prise, son repas la perd et la fiche le dit (« Le dîner de dimanche n’a plus de barquette. »). Deux personnes qui en mangent en même temps ne prennent jamais la même.\n- **« Congeler »** : la part tient trois mois à partir de maintenant. Pendant qu’un geste s’écrit, les autres boutons de la fiche sont grisés.\n- **« Jeter »** compte la part comme jetée. **« Retirer du frigo »** la supprime : ni mangée ni jetée, pour une barquette mangée en douce, donnée ou perdue. Dans les deux cas, le repas qui l’attendait la perd.\n\n## Au congélateur\n\n- **« Je les sors du congélateur »** sort les parts posées aujourd’hui ; celles de demain seulement à partir de l’heure du repas moins 24 heures (petit déjeuner 8 h, déjeuner 12 h, collation 16 h, dîner 19 h), car une part décongelée ne tient que 24 heures. Sinon, la fiche demande combien.\n- Une note le dit : « C’est pour ce soir : sors-les maintenant… » ou « C’est pour demain soir : sors-les à partir de 19 h… » (« sors-la », « passe-la » quand une seule barquette est posée sur ce repas).\n- « Changer le repas » mène à « La semaine ». « Jeter » et « Retirer du congélateur » font comme au frigo.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-fiche-plat",
    "titre": "La fiche d’un plat : parts, dates, photo",
    "ecrans": [
      "/frigo"
    ],
    "questions": [
      "Comment corriger la date d’une barquette ?",
      "Que veut dire « Prévues pour vous deux » ?",
      "Pourquoi la fiche donne deux poids de part différents ?",
      "Comment ajouter la photo d’un plat ?",
      "Combien de temps se garde une barquette au congélateur ?"
    ],
    "sources": [
      "src/ui/frigo/FichePlat.tsx",
      "src/ui/frigo/Combien.tsx",
      "src/ui/frigo/ChampDate.tsx",
      "src/lib/frigo.ts",
      "src/lib/donnees/frigo.ts",
      "src/lib/reseau.ts",
      "src/lib/peremption.ts",
      "src/lib/ranger.ts",
      "supabase/migrations/0017_triggers_lot1.sql",
      "supabase/migrations/0047_peremption_donnee.sql",
      "supabase/migrations/0092_la_photo_et_les_gestes.sql",
      "supabase/migrations/0121_photo_des_plats.sql",
      "supabase/migrations/0122_frigo_corrections.sql"
    ],
    "verifie_sur": "ff3539b",
    "corps": "## Ce que fait l’appli\n\nDans le frigo, touche la carte d’un plat : sa fiche s’ouvre en bas de l’écran (« cuisine-stock » décrit le frigo). Ses gestes (manger, congeler, sortir, jeter, retirer) sont dans « cuisine-fiche-plat-gestes ». Tant que les repas prévus ne sont pas lus (chargement, erreur), la fiche le dit et ses gestes restent grisés.\n\n## Ce que dit la fiche\n\nLieu, nom, nombre de parts, ce que pèse une part, les repas où il est posé (« Prévues pour vous deux », « Prévues pour Kamil », ou « Pas encore » ; un repas d’avant aujourd’hui n’y est plus), les dates.\n\n- **Une part est pour quelqu’un** : si toutes sont pareilles, une phrase (« 784 g, 682 kcal et 56 g de protéines la part »). Sinon une ligne par personne (« Kamil : 784 g, 682 kcal, 56 g de protéines », « Léa : … »), jamais une moyenne qui ne serait la part de personne.\n- **Dates** : « Au frigo depuis » ou « Congelés le » (pas dans le futur) recalcule « À manger avant » : **4 jours** (96 heures pleines) au frigo, **90 jours** au congélateur. Une part décongelée se mange dans les **24 heures** : pas de « depuis » pour elle. « À manger avant », saisie à la main, prime (jusqu’à 23 h 59 ce jour-là). Enregistrer sans changer la date n’écrit rien ; une date changée ne réécrit que les parts qu’elle change.\n\nMots d’urgence au frigo : « encore N jours », « demain dernier délai », « à manger aujourd'hui », « périmée ». Au congélateur : « N j au congélateur », puis « à sortir sous N j ». Sur la carte, une part périmée dit « périmée » (« 1 périmée » si une seule l’est), et un plat dont les repas tombent après sa péremption dit son mot d’urgence, ou « périme avant mar. soir ».\n\n## La photo d’un plat\n\n« Prendre le plat en photo » (ensuite « Changer la photo ») n’existe que pour une recette **à ton foyer** (collée, inventée ou saisie), pas pour le catalogue. Elle est réduite (1 400 px), envoyée dans un seau public à ton foyer (2 Mo, JPEG, PNG ou WebP au plus) et devient la photo de la recette. Une photo que le téléphone ne lit pas (HEIC) ou trop lourde est refusée avec une phrase claire.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-fiche-recette",
    "titre": "La fiche d’une recette",
    "ecrans": [
      "/choisir"
    ],
    "questions": [
      "Que veut dire « à 40 kcal près » sur la fiche ?",
      "Que signifie « Tout est pesé » ?",
      "Quelle différence entre « actives » et « en tout » ?",
      "Que veut dire « sans toi » sur une étape ?",
      "Pourquoi « Macros inconnues » sur une recette ?",
      "Comment voir la recette d’origine sur le site ?"
    ],
    "sources": [
      "src/ui/recettes/FicheRecette.tsx",
      "src/lib/recettes/fiche.ts",
      "src/lib/recettes/temps.ts",
      "src/lib/nutrition/macros.ts",
      "src/lib/donnees/fiche.ts",
      "scripts/recalcule.mjs",
      "src/lib/donnees/importer.ts",
      "src/pages/Inventer.tsx"
    ],
    "verifie_sur": "9504cf2",
    "corps": "## Ce que fait l’appli\n\nDans « Choisir », le **i** d’une recette ouvre sa fiche, par-dessus la liste. La croix « Fermer » la referme. En bas : le bouton « Ajouter à dimanche · N parts », ou, si la recette est déjà retenue, le simple message « Retenue pour dimanche · N parts ».\n\n## Ce que montre la fiche\n\n- En haut : la provenance (le site, ou « Ajoutée par … » pour une recette de foyer, même d’un ami), le titre et trois tuiles : « actives », « en tout », « parts ».\n- La carte « Par part » : protéines, calories, fibres.\n- Les appareils nécessaires.\n- « Ingrédients » (« pour N parts ») : la quantité, puis le nom.\n- « Étapes », avec à droite « N de gestes », suivi de « , le reste cuit seul » quand une étape cuit sans toi ; « Gestes non comptés » si aucun geste n’est connu.\n- « Voir la recette sur … » ouvre le site d’origine, quand il y a un lien web.\n\n## Les règles\n\n- **« actives »** est le temps de tes gestes. **« en tout »** est la durée annoncée par le site ; si le site annonce moins que tes gestes, ou rien, l’appli montre la somme de ses étapes (« — » sinon).\n- Chaque étape porte une pastille : « tes gestes » (tu travailles), « à surveiller » (étape bloquante : tu restes là), « sans toi » (cuisson qui n’occupe personne). Une étape qui cuit seule peut avoir les deux : ses gestes, puis son attente.\n- Les protéines et les calories sont **en fourchette** (« 28–34 g »). À côté de « Par part » :\n  - « Tout est pesé » : la marge d’erreur de la recette, arrondie, est de 0 kcal ;\n  - « à N kcal près » : cette marge d’erreur ;\n  - « N % des ingrédients connus » : sous 90 %, c’est ce pourcentage qui est affiché à la place.\n- « Macros inconnues : trop d’ingrédients non reconnus. » : aucun chiffre n’est donné quand moins de 75 % des lignes ont à la fois un aliment reconnu et un poids connu ou habituel. Même message pour une part impossible (plus de 1,5 kg, ou hors de 20 à 2 000 kcal).\n- Une recette devenue inaccessible (un ami ne la partage plus) : « Cette recette n’est plus accessible. »\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui de bouton pour corriger une recette du catalogue.",
    "verifie_le": "2026-10-26"
  },
  {
    "id": "cuisine-importer",
    "titre": "Coller sa propre recette",
    "ecrans": [
      "/importer"
    ],
    "questions": [
      "Comment ajouter ma propre recette ?",
      "Pourquoi ma recette ne part pas au plan du dimanche ?",
      "Que veut dire « pas reconnu — il ne comptera pas dans les macros » ?",
      "Qui peut voir la recette que j’ai collée ?",
      "Combien de recettes puis-je coller par mois ?",
      "Le modèle calcule-t-il les calories de ma recette ?"
    ],
    "sources": [
      "src/pages/Importer.tsx",
      "src/pages/Choisir.tsx",
      "src/lib/donnees/importer.ts",
      "src/lib/donnees/catalogue.ts",
      "supabase/functions/importer/index.ts",
      "supabase/migrations/0033_import.sql",
      "src/lib/nutrition/macros.ts"
    ],
    "verifie_sur": "ff3539b",
    "corps": "## Ce que fait l’appli\n\nTu colles une recette d’un carnet, d’un message ou d’un site, et elle rejoint le catalogue. **Le modèle de langage ne fait que découper le texte** (titre, parts, ingrédients, gestes) ; il ne reçoit que ce texte et ta précision. Le reste est du calcul ordinaire, comme pour les autres recettes : quantités, verbe, appareil, aliment reconnu, macros avec fourchette. Accès : « J’ai ma propre recette à coller » dans « Choisir ».\n\n## Comment faire\n\n1. Colle le texte dans « La recette, telle quelle » (40 caractères au moins, 24 000 au plus). Option : « Une précision à ajouter ? (facultatif) », attachée à la recette.\n2. « Ranger la recette ».\n3. Vérifie « Ce que j’ai compris » : titre, « Pour combien de parts ? » (1 à 20), ingrédients (« retirer »), étapes avec leur durée en minutes.\n4. Choisis « Qui peut la voir » : « Nous deux » (par défaut, au foyer seul), « Nos amis » (les foyers amis, avec ton prénom) ou « Tout le monde » (catalogue commun).\n5. « Garder cette recette » (avec un titre et une étape au moins) t’envoie sur « Choisir ».\n\n## Ce qui est signalé\n\n- « À compléter » : ingrédients non reconnus, étapes sans durée.\n- « reconnu : » suivi du nom de l’aliment retenu, ou « pas reconnu — il ne comptera pas dans les macros ».\n- « durée manquante » : tape les minutes.\n\n## Les règles\n\n- 60 ingrédients et 40 étapes au plus sont gardés ; une étape qui n’est pas une action est écartée.\n- Une recette n’est **planifiable** que si **toutes** ses étapes ont une durée. **Seules les recettes planifiables apparaissent dans « Choisir »** : sinon elle est enregistrée sans y figurer (l’écran le dit). Complète les durées avant de la garder.\n- Les macros se **calculent** : elles n’existent que si 75 % des lignes au moins sont reconnues et chiffrées, et sont écartées pour une part impossible (plus de 900 kcal/100 g).\n- **Quota : 40 imports par mois** pour le foyer, remis à zéro le 1er. Au-delà : « Quota atteint : 40 imports par mois. Il repart le 1er. »\n- Trop court : « Colle la recette : au moins quelques lignes. » Trop long : « Texte trop long. Colle la recette seule, sans la page. »\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui d’écran pour changer la visibilité d’une recette après coup. Elle n’est pas ajoutée toute seule à la semaine, et « Choisir » ne la met pas en avant (j’ai cherché : rien n’exploite l’adresse d’arrivée) : cherche-la par son titre.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-inventer",
    "titre": "Inventer une recette (Envie spéciale)",
    "ecrans": [
      "/inventer"
    ],
    "questions": [
      "Comment inventer une recette avec ce que j’ai ?",
      "Que signifie « Inventée · jamais testée » ?",
      "Combien de recettes puis-je inventer par mois ?",
      "Le modèle connaît-il mes objectifs ?",
      "Que veut dire « + 3 courses » ?",
      "Que devient la recette si je ne la garde pas ?"
    ],
    "sources": [
      "src/pages/Inventer.tsx",
      "supabase/functions/inventer/index.ts",
      "src/lib/nutrition/portions.ts",
      "src/lib/donnees/foyer.ts",
      "src/lib/donnees/catalogue.ts",
      "src/pages/Accueil.tsx",
      "src/pages/Choisir.tsx"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nQuand rien de prévu ne fait envie ce soir, « Envie spéciale ? » fait **inventer une recette par un modèle de langage**, d’après ton envie, ton stock et des bornes chiffrées. Accès : l’accueil de la cuisine (« Envie spéciale ? ») ou « Choisir » (« Rien ne va ? Invente-moi une recette »).\n\n## Comment faire\n\n1. Écris « Ce soir j’ai envie de… » ou touche une des six idées (« Réconfortant », « Asiatique », « Sans cuisson »…).\n2. « Avec quoi » : « Ce qu’on a » (on demande au modèle de s’en tenir à ton stock), « + 3 courses » (ton stock plus trois ingrédients à acheter au plus) ou « Libre ».\n3. « Sans négocier » : « Au moins » N g de protéines, « Au plus » N kcal la part, « En moins de » N min actives (25 au départ). Tu peux cocher des appareils.\n4. « Invente-moi ça », puis « Garder cette recette » ou « Autre idée ».\n\n## Ce que tu reçois\n\nLe badge **« Inventée · jamais testée »**, des fourchettes de protéines et de kcal par part (**proposées par le modèle**, pas mesurées), les minutes actives, « Il te manque N chose(s) » ou « Tu as tout. », les ingrédients, les étapes.\n\n## Les règles\n\n- Bornes de départ : tes objectifs ramenés à un repas, **35 %** de ta journée. Exemple : 2 000 kcal et 150 g de protéines donnent « Au plus 700 kcal » et « Au moins 53 g ». Sans objectifs enregistrés : 30 g et 620 kcal.\n- Le modèle ne voit **jamais tes objectifs ni ton prénom** : seulement ces bornes, ton envie, et les noms et quantités des ingrédients du frigo et du placard (60 lignes au plus ; rien en « Libre »).\n- Recette demandée pour **2 parts**.\n- **Quota : 10 générations par mois** pour le foyer ; il repart le 1er. « N générations restantes ce mois-ci » s’affiche sous le résultat, pas avant. Un échec ne consomme rien.\n\n## Garder ou non\n\n« Garder cette recette » l’enregistre (privée, pour ton foyer), puis t’envoie sur « Choisir ». « Choisir » ne montre que les recettes planifiables ; une recette inventée l’est quand chaque étape a une durée (le modèle en donne une à chacune) : cherche son titre, tu peux la retenir. Gardée avant le dernier changement, elle n’y est pas. Sans « Garder », elle **disparaît**.\n\n## Ce que l’appli ne fait pas\n\nElle ne calcule pas les macros de la recette inventée.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-nos-aliments-creer",
    "titre": "Créer un aliment à nous : étiquette, à la main, code-barres",
    "ecrans": [
      "/aliments"
    ],
    "questions": [
      "Comment ajouter mon propre yaourt avec ses vraies calories ?",
      "Comment enregistrer un aliment en photographiant l’étiquette ?",
      "Comment ajouter un aliment avec son code-barres ?",
      "Pourquoi l’appli me demande si mes calories sont des kJ ?",
      "Combien d’étiquettes puis-je photographier par mois ?"
    ],
    "sources": [
      "src/pages/Aliments.tsx",
      "src/ui/aliments/Formulaire.tsx",
      "src/ui/aliments/LecteurDeCodes.tsx",
      "src/lib/aliments/brouillon.ts",
      "src/lib/aliments/calcul.ts",
      "src/lib/aliments/etiquette.ts",
      "src/lib/aliments/openfoodfacts.ts",
      "src/lib/aliments/absents.ts",
      "src/lib/aliments/ordre.ts",
      "src/lib/aliments/retour.ts",
      "src/lib/donnees/aliments.ts",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/lib/aliments/consigne.ts",
      "src/pages/Settings.tsx",
      "supabase/functions/etiquette/index.ts",
      "supabase/migrations/0124_nos_aliments.sql"
    ],
    "verifie_sur": "99e3953",
    "corps": "## Créer un aliment\n\nDans « Nos aliments » (voir « cuisine-nos-aliments »), « Ajouter un aliment », un nom, puis trois façons de remplir, qui ne remplissent que les champs du dessous :\n- **« Étiquette »** : photographie le tableau nutritionnel. L’appli recopie les valeurs pour 100 g et le poids net, elle n’estime rien. « Reprendre la photo », « Ajouter l’autre face » (jusqu’à trois photos), « Réessayer » si la lecture échoue ou dépasse 30 secondes. Le champ facultatif **« Dis-moi ce que c’est (facultatif) »** et **« Relire avec cette consigne »** donnent un indice (le nom, l’unité, le poids), jamais des chiffres. Chaque lecture compte dans les 40 étiquettes par mois du foyer.\n- **« À la main »** : tape les valeurs pour 100 g.\n- **« Code-barres »** : les chiffres puis « Chercher », ou « Lire avec l’appareil photo » si ton navigateur sait le faire. Les valeurs viennent d’Open Food Facts, une base collaborative : vérifie-les.\n\nCe qu’une lecture ne donne pas **reste vide**, avec une phrase pour le dire : l’appli n’écrit jamais un 0 à la place. Une nouvelle photo ou un nouveau code remplace ce qui avait été lu avant, mais **jamais ce que tu as tapé**. Si tu tapes pendant la lecture, rien n’est écrasé : « Remplacer par les valeurs lues » le fait si tu veux.\n\n## Les valeurs et le calcul d’une unité\n\nLes calories et les protéines sont **obligatoires** ; glucides, lipides et fibres vides valent zéro. Plafonds : 900 kcal et 100 g pour 100 g. L’unité (« pot » au départ) et son poids (« Un pot pèse 125 g ») donnent **le calcul d’une unité**, en grand : valeurs × poids ÷ 100. Exemple : 76 kcal et 10 g de protéines pour 100 g, un pot de 125 g → **95 kcal et 12,5 g de protéines**. Si le poids vient d’un paquet divisé par ses portions, le calcul s’affiche (« 500 g en 4 portions = 125 g ») et le champ reste modifiable.\n\n## Des kJ pris pour des kcal\n\nL’appli compare les calories aux macros (4 kcal par g de protéines et de glucides, 9 de lipides, 2 de fibres). Hors de 0,6 à 1,5 fois cette valeur, elle te demande : « 318 kcal pour 100 g, c’est beaucoup pour ces macros : ce serait des kJ ? 318 kJ = 76 kcal. » Touche « Corriger en 76 kcal », ou coche « Les valeurs sont justes » pour enregistrer quand même.\n\n## Enregistrer\n\n« Enregistrer dans mes aliments ». Deux aliments ne peuvent pas avoir le même nom (accents, majuscules et espaces en trop ne comptent pas) ni le même code-barres dans le foyer.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-nos-aliments",
    "titre": "Nos aliments : le yaourt du foyer, avec ses vraies valeurs",
    "ecrans": [
      "/aliments"
    ],
    "questions": [
      "Comment choisir le repère qu’un aliment remplace ?",
      "Comment modifier ou retirer un de nos aliments ?",
      "À quoi sert « Nos aliments » ?",
      "Où trouver nos aliments ?"
    ],
    "sources": [
      "src/pages/Aliments.tsx",
      "src/ui/aliments/Formulaire.tsx",
      "src/ui/aliments/LecteurDeCodes.tsx",
      "src/lib/aliments/brouillon.ts",
      "src/lib/aliments/calcul.ts",
      "src/lib/aliments/etiquette.ts",
      "src/lib/aliments/openfoodfacts.ts",
      "src/lib/aliments/absents.ts",
      "src/lib/aliments/ordre.ts",
      "src/lib/aliments/retour.ts",
      "src/lib/donnees/aliments.ts",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/ui/aliments/Quantite.tsx",
      "src/pages/Settings.tsx",
      "supabase/functions/etiquette/index.ts",
      "supabase/migrations/0124_nos_aliments.sql"
    ],
    "verifie_sur": "99e3953",
    "corps": "## Ce que fait l’appli\n\nUn repère comme « Yaourt » (60 kcal, 4 g de protéines) est un ordre de grandeur. **« Nos aliments »** range ce que vous mangez vraiment, avec les valeurs de l’étiquette : le foyer en a une liste commune. La semaine et « en plus » les proposent **avant** les repères : un appui demande **combien** (deux pots, 30 g : voir « cuisine-semaine-en-plus-quantite »).\n\n## Où\n\n« Réglages », carte **« Nos aliments »**, bouton « Ouvrir nos aliments ». Ou, dans la feuille de choix d’un repas de la semaine, section « Autre chose » : « Ajouter un aliment à nous… » ou « Ajouter ou modifier nos aliments ». Le retour rouvre la feuille là où tu l’avais laissée.\n\nPour en créer un (étiquette, à la main, code-barres), voir « cuisine-nos-aliments-creer ».\n\n## Le repère remplacé\n\nLe champ **« Remplace le repère »** (facultatif) est proposé d’après le premier mot du nom : « Yaourt dessert protéiné » propose « Yaourt ». Tu peux le changer ou le retirer. **Un repère n’est caché que s’il est nommé là, ou s’il porte exactement le même nom qu’un aliment.** « Yaourt grec » ne cache donc rien tant que tu ne le lui dis pas. Même règle pour « Ce que vous reprenez souvent ».\n\n## Les utiliser\n\nUn appui ouvre « combien ? », puis la quantité s’écrit avec ces valeurs, pour chaque personne visée. Dans la semaine : « Autre chose ». Dans « en plus » : « Nos aliments ». Un aliment dont l’unité est le gramme (« g ») se pèse ; les autres se comptent (« 2 pots »). Ils comptent dans le bilan du jour comme un repère.\n\n## Modifier, retirer\n\nTouche l’aliment dans la liste. « Enregistrer les changements », ou « Retirer cet aliment » (une question avant). Les repas déjà notés **gardent leurs chiffres** : le repas écrit est une copie. Si l’aliment a été retiré entre-temps depuis l’autre téléphone, l’appli te le dit.\n\n## Ce que l’appli ne fait pas\n\nAucune photo de l’aliment n’est gardée. Je n’ai pas trouvé de modification de plusieurs aliments à la fois. Si deux personnes modifient le même aliment en même temps, la dernière écriture gagne.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-on-range-stock",
    "titre": "« La session a pris » : ce que le rangement retire du stock",
    "ecrans": [
      "/dressage"
    ],
    "questions": [
      "Que veut dire « La session a pris » ?",
      "Pourquoi mes ingrédients ont disparu du frigo ?",
      "Comment corriger ce que la session a retiré ?",
      "Pourquoi l’appli n’a pas retiré mon pot de yaourt ou mon ail ?",
      "Pourquoi n’a-t-elle retiré qu’une partie de ma farine ?"
    ],
    "sources": [
      "src/pages/Ranger.tsx",
      "src/lib/ranger.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/migrations/0120_la_session_prend_dans_le_stock.sql"
    ],
    "verifie_sur": "2ff18ce",
    "corps": "## Ce que fait l’écran\n\nLes ingrédients des recettes sortent du frigo, du congélateur et du placard : une puce par ingrédient (« Poireaux 1,5 kg »). Touche-la, écris « il en reste … » puis « Corriger » (ou « Comme prévu ») ; un texte qui n’est pas un nombre est refusé avec un message. Un stock tombé à zéro disparaît.\n\nLe calcul suit la liste de courses : la quantité de la recette, mise à l’échelle des parts cuisinées ; une recette dont on ne connaît pas le nombre de parts d’origine compte telle qu’elle est écrite. À la pièce, on arrondit vers le bas : trois quarts d’oignon, rien ne sort. L’appli ne touche **ni** à ce qui n’a pas de quantité, **ni** à ce qu’elle ne sait pas calculer : un pot, un ingrédient dont une ligne de recette n’a ni poids ni unité compatible, ou un ingrédient que tu as à la fois en grammes et à la pièce. « Reste au frigo : … » liste le reste. Le retrait n’a lieu qu’**une fois** par session.\n\nLe reste de l’écran (frigo, congélateur, heure du rangement) est dans « cuisine-on-range ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-on-range",
    "titre": "« On range » : frigo, congélateur et ingrédients de la session",
    "ecrans": [
      "/dressage"
    ],
    "questions": [
      "Comment choisir ce qui va au frigo et ce qui va au congélateur ?",
      "Combien de temps se garde une barquette ?",
      "Comment changer l’heure de rangement ?",
      "Que fait « Ranger les barquettes » ?",
      "Pourquoi « Ranger » est grisé ?",
      "Deux personnes ont rangé en même temps : que se passe-t-il ?"
    ],
    "sources": [
      "src/pages/Ranger.tsx",
      "src/pages/Dressage.tsx",
      "src/ui/dressage/Habillage.tsx",
      "src/lib/ranger.ts",
      "src/lib/donnees/barquettes.ts",
      "src/lib/peremption.ts",
      "src/App.tsx",
      "supabase/migrations/0047_peremption_donnee.sql",
      "supabase/migrations/0120_la_session_prend_dans_le_stock.sql"
    ],
    "verifie_sur": "7ccc089",
    "corps": "## Ce que fait l’écran\n\nAprès « C’est dressé » (« cuisine-dressage »), « On range » te fait choisir, pour le foyer entier, combien de barquettes de chaque recette restent au frigo : le reste part au congélateur. En haut, deux compteurs en grand, « 8 au frigo » et « 22 au congélateur », suivent tes réglages.\n\n## Comment faire\n\nUne carte par recette : sa photo quand elle en a une, le total, une barre frigo / congélateur, « Frigo · N » avec **−** et **+**, « Congélateur · N », et la date : « à manger avant le … » au frigo, « se garde jusqu’au … » au congélateur.\n\n- **La proposition de départ** remplit le frigo jusqu’à **4 jours de dîners pour le foyer** (4 × le nombre de personnes), recette par recette dans l’ordre retenu ; le reste va au congélateur.\n- **« Rangé le »** : maintenant par défaut. « Modifier » ouvre un champ date et heure : pas dans le futur, et au plus **4 jours** en arrière (sinon un message le dit et « Ranger » reste grisé). Cette heure devient celle de préparation de chaque barquette (et de congélation pour celles du congélateur).\n- **Le bilan** : « N barquettes au frigo », de quoi tenir tant de jours de dîners. Au-delà de 4 jours, l’encart passe sur fond sable : « congèle-en quelques-unes … ».\n- Une barquette se garde **4 jours** au frigo, **90 jours** au congélateur, **24 heures** décongelée.\n\n## « La session a pris »\n\nLes ingrédients des recettes sortent du stock : une puce par ingrédient (« Poireaux 1,5 kg »), à corriger si besoin. Le détail est dans « cuisine-on-range-stock ».\n\n## Ranger\n\n**« Ranger les N barquettes »** fait tout d’un coup : il crée les barquettes avec leur lieu, retire les ingrédients, passe la semaine à « La semaine tourne » et ouvre « La semaine », où tu choisis ce que tu manges chaque jour (« cuisine-semaine »). Rien n’est posé tout seul. Il reste grisé le temps que l’appli lise ce que la session prend.\n\nSi deux personnes appuient en même temps, une seule range : l’autre arrive devant le travail déjà fait.\n\n## Si ça échoue\n\n- Si la lecture de « La session a pris » échoue, l’écran dit « il ne sera pas retiré » : on range quand même, sans toucher au stock.\n- Si les barquettes existent déjà (un autre téléphone, une réponse perdue), l’écran dit « N barquettes déjà rangées pour vous deux : voilà ce qui est écrit. Il ne reste qu’à finir. » et les montre telles qu’elles sont écrites, sans réglage : le nombre au frigo et au congélateur de chaque recette, et la date. « Terminer le rangement » finit le travail et ouvre « La semaine » ; une fois la semaine commencée, le bouton devient « Choisir les repas de la semaine », avec « Voir le frigo » dessous.\n- Rien n’est créé ni retiré deux fois. Sans aucune barquette à ranger, l’écran le dit au lieu du bouton. Si la lecture des barquettes déjà rangées échoue, l’écran dit « Je n’ai pas pu lire la session » et propose « Réessayer ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-peser",
    "titre": "Peser ce qu’on compte à l’unité",
    "ecrans": [
      "/peser"
    ],
    "questions": [
      "À quoi sert l’écran « Peser » ?",
      "Combien de fois dois-je peser un oignon ?",
      "Pourquoi ma pesée n’est pas retenue ?",
      "Comment corriger une pesée fausse ?",
      "Pourquoi « 2 oignons » ne donne pas de grammes ?",
      "Que veut dire « 2 sur 3 » ?"
    ],
    "sources": [
      "src/pages/Peser.tsx",
      "src/pages/Choisir.tsx",
      "src/lib/pesee.ts",
      "src/lib/donnees/pesee.ts",
      "src/lib/donnees/courses.ts",
      "supabase/migrations/0025_pesee.sql"
    ],
    "verifie_sur": "bf28243",
    "corps": "## Ce que fait l’appli\n\n« 2 oignons » ne fait pas des grammes tout seul : un oignon de chez toi n’est pas un oignon moyen. « Peser » te fait peser ces aliments **jusqu’à ce que l’appli connaisse leur poids chez toi**, puis ne le redemande plus. Ce poids sert à la liste de courses, au prochain « Faire la liste » de « Choisir ».\n\n## Comment faire\n\n1. Sous le frigo, « Peser ce qu’on compte à l’unité ». La liste vient des recettes retenues de la semaine ; les aliments les plus utilisés passent d’abord.\n2. La carte sombre compte les aliments « à connaître ». Touche un aliment de « À peser » : chaque ligne montre un exemple de recette (« 2 oignons »), un poids de référence (« on compte 110 g en attendant », ou « aucun poids de référence ») et trois points qui se remplissent.\n3. Remplis « Combien » et « Pèsent, en grammes ». Pèse ce que tu mets dedans (oignon épluché, poivron épépiné).\n4. « Enregistrer · encore N après » (« Enregistrer · la dernière » pour la dernière).\n\n## Les règles\n\n- Il faut **3 pesées retenues** pour qu’un poids prime sur la référence, ou **5 si l’aliment n’a pas de référence**. Les points disent l’avancement : « 0 sur 3 » avant la première (« 0 sur 5 » sans référence), « 2 sur 3 » après deux. Avant la première pesée, la ligne dit aussi « 2 recettes » : c’est ce qui classe les aliments. L’en-tête de « À peser » dit « trois pesées par aliment », et « cinq sans poids de référence » quand les deux cas se mêlent.\n- Le poids retenu est la **médiane** des pesées retenues.\n- Une pesée est **écartée** si le poids d’une unité est sous 0,4 fois ou au-dessus de 2,5 fois la référence. Le champ passe au rouge et l’écran te prévient avant d’enregistrer : « … cette pesée ne sera pas retenue. » Exemple : référence 110 g, accepté de 44 à 275 g ; 1 200 g pour un oignon, non. Une pesée écartée reste listée, mais ne compte pas.\n- Sans référence, rien n’est écarté.\n- Une fois connu, l’aliment quitte la liste.\n\n## Corriger\n\nSous un aliment ouvert, chaque pesée est listée (« 2 pour 236 g (118 g l’unité) ») avec « effacer ». Efface la fausse plutôt que d’en refaire trois autres.\n\n## Effet sur les courses\n\n« 2 oignons » devient 2 × le poids appris. Exemple : 118 g l’unité donne 236 g pour une recette prise avec ses parts d’origine (sinon la quantité suit les parts retenues) ; deux recettes à « 2 oignons » donnent 472 g.\n\n## Ce que l’appli ne fait pas\n\n« Rien à peser » : toutes les recettes de la semaine se convertissent déjà en grammes, ou aucune n’est retenue. Sans semaine ouverte : « Choisis des recettes : ce sont elles qui disent quoi peser. » Il n’existe pas aujourd’hui d’effet de ces pesées sur les calories des recettes (seule la liste de courses lit les poids appris).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-photo-frigo",
    "titre": "La photo du frigo",
    "ecrans": [
      "/photo"
    ],
    "questions": [
      "Comment remplir mon stock avec une photo du frigo ?",
      "Pourquoi l’appli ne coche pas tous les articles ?",
      "Combien de photos puis-je prendre par mois ?",
      "Que veut dire « deviné, à vérifier » ?",
      "La photo ajoute-t-elle les aliments toute seule ?",
      "Que faire si l’appli n’a rien su lire ?"
    ],
    "sources": [
      "src/pages/Photo.tsx",
      "src/pages/Frigo.tsx",
      "src/lib/photo.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/functions/frigo/index.ts"
    ],
    "verifie_sur": "7a2a964",
    "corps": "## Ce que fait l’appli\n\nUn modèle de langage qui sait lire les images regarde ta photo et **propose** une liste d’aliments : **rien n’entre dans le frigo sans que tu l’aies coché**.\n\n## Comment faire\n\n1. Dans le frigo, porte ouverte, « Photo du frigo ».\n2. Choisis le lieu : « Frigo », « Congélateur » ou « Placard ». Il est sur « Frigo » au départ ; c’est seulement une indication pour le modèle.\n3. « Prendre la photo » : cadre une étagère à la fois, de face. L’appli attend environ quinze secondes (« Je regarde… »). La photo est réduite avant l’envoi (1 400 pixels au plus).\n4. Lis « Ce que j’ai vu » : ta photo, un résumé (« 9 articles vus · 7 retenus · 14 s », le temps seulement quand il est mesuré), puis les lignes, regroupées par lieu : nom, variété (« yaourt aux fruits » et « yaourt nature » n’ont pas les mêmes macros), quantité, endroit vu sur la photo (« étagère du haut, à gauche »), remarques. Touche la photo pour l’agrandir ; Échap la referme.\n5. Décoche ce qui n’y est pas, puis « Ajouter N articles » : tu arrives au frigo. Pas satisfait : « Reprendre une photo ».\n\n## Les règles\n\n- Sont cochés d’avance **seulement** les articles dont le modèle est sûr (confiance d’au moins 0,8). Les autres portent « deviné, à vérifier » et ne sont pas cochés.\n- Chaque article est rangé dans le lieu que **le modèle** lui attribue (givre = congélateur, bacs = frigo, boîtes = placard), pas dans celui que tu as choisi, sauf s’il n’en donne aucun ou un lieu inconnu : l’article prend alors le lieu choisi.\n- Ces lignes ne sont pas rattachées à un aliment : « Avec ce que j’ai » et « il manque … » les ignorent.\n- L’écran écrit « Tu pourras toujours retirer une ligne depuis le frigo » : la fiche d’un ingrédient permet de corriger sa quantité et « Fini » le retire.\n- **Quota : 30 photos par mois** pour le foyer ; il repart le 1er. « N photos restantes ce mois-ci » s’affiche sous « Reprendre une photo », après la lecture. Au-delà : « Quota atteint : 30 photos par mois. Il repart le 1er. »\n- Une panne du modèle ne consomme pas de photo ; une photo où rien n’est reconnu, si.\n- Le modèle ne reçoit que la photo et le lieu : pas tes objectifs, pas ton prénom.\n- « Je n’ai rien su lire » : photo floue, trop sombre ou sans nourriture ; « Reprendre une photo ».\n\n## Ce que l’appli ne fait pas\n\nElle n’ajoute rien automatiquement, ne fixe aucune date de péremption et ne calcule aucune macro d’après la photo : seulement des noms et des quantités.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-plan",
    "titre": "Le plan de dimanche",
    "ecrans": [
      "/plan"
    ],
    "questions": [
      "Comment est calculée la durée de la session de cuisine ?",
      "Que veut dire « les mains prises » ?",
      "Comment changer l’équipement du jour ?",
      "Qu’est-ce que le goulot dans le plan ?",
      "Pourquoi deux recettes partagent une même action ?",
      "Peut-on recalculer le plan quand la session a commencé ?"
    ],
    "sources": [
      "src/pages/Plan.tsx",
      "src/lib/donnees/session.ts",
      "src/lib/plan/fusion.ts",
      "src/lib/plan/equipement.ts",
      "src/lib/plan/types.ts",
      "seed/conversions.json",
      "src/lib/plan/ordonnance.ts",
      "src/lib/plan/duree.ts",
      "supabase/migrations/0005_policies.sql"
    ],
    "verifie_sur": "ff3539b",
    "corps": "## Ce que fait l’appli\n\nÀ partir des étapes des recettes retenues, l’appli calcule un plan : quoi faire, dans quel ordre, avec quels appareils. Il est **enregistré** au « Commencer la session », puis ne change plus pendant que tu cuisines.\n\n## Ce que dit l’écran\n\n- Sous « Le plan » : « Pour la cuisine du dimanche 25 octobre, à deux » (rien si tu es seul).\n- En très grand : le temps **en cuisine**, puis trois chiffres : « X les mains prises » (le temps où quelqu’un a les mains occupées ; un four n’occupe personne), « X d’attente » et « N actions pour une personne » (ou « N personnes » : les membres du foyer).\n- « Puis X de repos, sans toi » : repos compté à part.\n- « Au menu » : les photos des recettes retenues.\n- « Dans l’ordre » : un geste par ligne, avec son heure de début, sa durée, le plat qu’il sert (« pour Chili con carne ») et sa barre. Un point (•) marque ceux qui fixent la durée.\n- « Les appareils » : quand chacun travaille.\n\n## L’équipement du jour\n\nAu premier plan, quand aucun appareil n’est enregistré, « Ce dont tu disposes aujourd’hui » passe avant « Dans l’ordre ». Ensuite « Ce dont tu disposes » tient sur une ligne, en dernier (« 8 appareils », puis « Four ×2, plaques de cuisson ×4… »), et le crayon (« Changer l’équipement du jour ») rouvre la carte, avec « Recalculer le plan ». Le nombre dit combien de plats l’appareil prend à la fois. Il part de la dernière session du foyer (sinon four 2, plaques 4, les autres 1). **Tant que tu n’as pas touché « Recalculer le plan », le plan compte un seul plat par appareil.** Un appareil décoché reste utilisé, à un plat à la fois.\n\nSi un appareil retarde tout : « X est le goulot » et « S’il prenait deux plats à la fois, la session durerait X de moins. » (au-delà de 2 minutes), avec « Modifier l’équipement », qui ouvre la carte juste dessous. Le gain suppose 2 plats pour tous les appareils à 1 plat.\n\n## Les règles de calcul\n\n- Les durées sont celles des étapes des recettes : elles ne changent ni avec les parts retenues ni avec les quantités.\n- Deux recettes ne partagent une action (« pour Chili con carne et Lasagnes ») que si le geste est le même (même verbe, même appareil, même charge) **et** que les deux quantités sont connues. Durée : la somme, moins la mise en place payée une fois (2,5 minutes au plus). Exemple : 8 min + 6 min = 11,5 min. Sans quantités, seul « préchauffer » se partage.\n- Une étape sans durée : 1 minute.\n\n## Commencer\n\n« Commencer la session », le bouton du bas, enregistre le plan, note l’heure de début et ouvre l’écran de cuisine. Dès qu’une action est prise : « La session a commencé : le plan ne se recalcule plus. »\n\n## Pas de plan\n\n« Rien à ordonnancer » : les recettes choisies n’ont pas d’étapes utilisables.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-portions",
    "titre": "Le calcul des portions et le complément de skyr",
    "ecrans": [
      "/dressage"
    ],
    "questions": [
      "Comment sont calculées les portions de chacun ?",
      "Pourquoi l’appli propose du skyr en complément ?",
      "Pourquoi mes parts sont-elles égales à celles de l’autre ?",
      "Que veut dire « la part est en dessous de l’objectif » ?",
      "Pourquoi ma part est plus grosse que celle de l’autre ?",
      "Que veut dire « Recette mal quantifiée » ?"
    ],
    "sources": [
      "src/pages/Dressage.tsx",
      "src/lib/nutrition/portions.ts",
      "src/lib/nutrition/macros.ts",
      "src/lib/donnees/recettes.ts",
      "src/lib/donnees/foyer.ts"
    ],
    "verifie_sur": "7bb3825",
    "corps": "## Ce que fait l’appli\n\nTout le monde mange la même chose ; seule la **portion** diffère. Une part plus grosse donne plus de tout : quand le plat manque de protéines, l’appli ajoute du skyr plutôt que de grossir la part.\n\n## Les règles de calcul\n\n- Les parts d’une recette se répartissent **à parts égales entre les membres du foyer** (6 parts, 2 personnes : 3 et 3). Si c’est impair, la première personne du foyer en a une de plus.\n- Le **poids du plat** est la somme de ses ingrédients reconnus dont le poids est connu ou habituel. Il se découpe au prorata de l’objectif de chacun pour un dîner, soit **35 %** de sa journée en calories, pondéré par son nombre de parts.\n- Exemple : plat de 1 200 g, 6 parts, deux personnes à 2 500 et 1 800 kcal par jour. Cibles du repas : 875 et 630 kcal ; 3 × 875 + 3 × 630 = 4 515. Parts : 1 200 × 875 ÷ 4 515 ≈ **233 g**, 1 200 × 630 ÷ 4 515 ≈ **167 g**.\n\n## Les trois cas\n\n- Part **sous 90 %** de l’objectif en calories : « la part est N % en dessous de l’objectif ». Le plat est trop petit pour ce nombre de barquettes : cuisine plus, ou prévois moins de parts. Le skyr n’y change rien.\n- Part **au-dessus de 115 %** : fais une barquette de plus plutôt que des parts trop grosses.\n- Calories bonnes mais protéines **sous 90 %** de l’objectif du repas : « + N g de skyr pour <prénom> ». Le skyr compte 10 g de protéines pour 100 g ; la quantité est arrondie à 25 g. Exemple : 30 g de protéines pour un objectif de 40 g : « + 100 g de skyr ».\n\n## Sans objectifs\n\nQuelqu’un qui n’a pas fixé ses objectifs a quand même ses barquettes : « … n’a pas encore fixé ses objectifs : ses barquettes sont dressées à parts égales. » Chacune pèse la **moyenne** des parts des autres, et aucun complément de skyr ne lui est proposé. Si personne n’a d’objectifs, toutes les parts sont égales. « Fixe tes objectifs » mène à l’écran des objectifs.\n\n## Recette mal quantifiée\n\nSi moins de 75 % des lignes ont à la fois un aliment connu et un poids, l’écran affiche « Recette mal quantifiée : les parts sont égales, faute de mieux. » Elles ne le sont pas : le calcul est le même, sur un plat qui ne pèse que les ingrédients reconnus, donc trop léger.\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui de réglage du complément (c’est toujours du skyr) ni de la part du dîner (35 %).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-annuler",
    "titre": "La semaine : annuler « Je l’ai mangé »",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment annuler « Je l’ai mangé » si je me suis trompé ?",
      "Comment remettre un repas à prévu ?",
      "Que devient la barquette quand j’annule ?",
      "Le bandeau « Noté : mangé. » a disparu, comment annuler ?",
      "Est-ce que ça change le repas de Léa ?"
    ],
    "sources": [
      "src/pages/Semaine.tsx",
      "src/pages/Hub.tsx",
      "src/pages/Accueil.tsx",
      "src/ui/semaine/Carte.tsx",
      "src/ui/semaine/AnnulerLeMange.tsx",
      "src/ui/semaine/MangeAujourdhui.tsx",
      "src/lib/annuler-mange.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/migrations/0129_annuler_mange.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que fait l’appli\n\nUn faux appui se rattrape, sur « La semaine » (aujourd’hui comme les jours passés), sur l’accueil de Popote et sur l’accueil de la cuisine.\n\n- **Tout de suite** : un bandeau sombre « Noté : mangé. » reste 6 secondes avec **« Annuler »**. Un seul toucher suffit, sans question. Le délai s’arrête tant que le pointeur ou le focus est sur le bandeau.\n- **Ensuite**, tant que ta case est « mangé » : la carte dit **« Mangé à 12 h 40 »** (l’heure à laquelle tu l’as noté ; si tu l’as noté un autre jour que celui du repas, **« Noté mangé le mar. 27 oct. à 9 h 12 »**) et propose le lien **« Pas mangé ? Annuler »**. Il demande confirmation dans la carte : « Remettre ce repas à « prévu » ? Ta part redevient prévue et la barquette revient au frigo. Si elle venait du congélateur, elle y retourne. » Puis **« Oui, remettre »** ou **« Non, garder »**. Sur l’accueil de Popote et de la cuisine, ce lien vit sous la carte sombre, dans une carte « Midi : … » par repas déjà noté.\n\nCe que ça fait : **ta** case repasse à « prévu » et l’heure notée s’efface ; la part est rendue là où elle était (5 parts au frigo redeviennent 6 ; une part du congélateur y retourne ; une part décongelée revient décongelée, **avec sa date limite**) ; la case de l’autre personne ne bouge pas ; le repas ne compte plus dans les calories et protéines jusqu’à ce qu’il soit de nouveau noté. Si l’autre personne a noté **la même part**, elle reste mangée tant qu’elle ne l’annule pas aussi. Ce que tu as mangé « en plus » d’un plat n’est pas touché : il garde son « Retirer ». Pour « Autre chose » (sans barquette), le repas entier ne compte plus au bilan, sur un jour passé comme aujourd’hui, jusqu’à ce que tu le notes de nouveau. Une case que l’autre téléphone vient déjà de remettre à « prévu » ne rend rien une seconde fois : tu n’as pas d’erreur, l’écran se met à jour.\n\nLe geste « En manger une maintenant » de la fiche d’un plat n’a pas ce bandeau : le repas du midi ou du soir qu’il note s’annule ensuite depuis « La semaine ».\n\n## Les règles\n\n- Seule **ta** case s’annule : la base refuse celle de l’autre personne, et celle d’un autre foyer.\n- Une case qui n’est pas « mangé » ne s’annule pas : l’appli dit « Ce repas n’est pas noté mangé : rien à remettre. »\n- Un jour passé s’annule comme aujourd’hui : « Mangé à 19 h 05 » et le lien restent tant que la case est « mangé ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-changer",
    "titre": "La semaine : changer un repas, le manger, sortir un plat congelé",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment changer un repas le jour même ?",
      "Comment indiquer que j’ai mangé ma barquette ?",
      "Que devient la barquette quand je change de repas ?",
      "Que se passe-t-il quand je choisis un plat congelé ?",
      "Quand faut-il sortir un plat du congélateur ?",
      "Que veut dire « Je l’ai mangé » ?"
    ],
    "sources": [
      "src/pages/Semaine.tsx",
      "src/pages/Accueil.tsx",
      "src/ui/semaine/Bandeau.tsx",
      "src/ui/semaine/Carte.tsx",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/lib/choix.ts",
      "src/lib/semaine.ts",
      "src/lib/reperes.ts",
      "src/lib/aliments/ordre.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/migrations/0123_choisir_un_repas.sql",
      "supabase/migrations/0125_semaine_corrections.sql",
      "supabase/migrations/0128_semaine_hier.sql",
      "src/lib/peremption.ts"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Changer\n\nLa carte pleine d’un repas (voir « cuisine-semaine ») dit le plat, « Du frigo, pour vous deux » ou « Du congélateur, pour Kamil », et propose **« Changer »**, y compris le jour même. Sur l’accueil, « Changer » ouvre « La semaine » sur aujourd’hui avec la feuille du bon repas déjà ouverte.\n\nQuand tu changes, l’ancienne barquette est lâchée, et l’appli le dit : « Les 2 wraps restent au congélateur. » ; pour un plat à plusieurs mots, « Les 2 barquettes de lasagnes au saumon-poireaux retournent au frigo, libres pour un autre jour. » (« La barquette de … retourne au frigo » s’il n’y en a qu’une).\n\n## Manger\n\n**« Je l’ai mangé »** apparaît aujourd’hui, et sur un jour passé (voir « cuisine-semaine-hier »), sur ta carte, pour un plat comme pour « Autre chose » : la barquette est marquée mangée et quitte le frigo. Un repas que quelqu’un a mangé ne se change plus pour cette personne.\n\n## Annuler « Je l’ai mangé »\n\nUn faux appui se rattrape : bandeau « Noté : mangé. » pendant 6 secondes, puis le lien « Pas mangé ? Annuler » (voir « cuisine-semaine-annuler »).\n\n## Un plat congelé\n\nUn plat **congelé** a un bandeau bleu :\n- aujourd’hui : « C’est pour aujourd’hui : décongèle les 2 wraps au micro-ondes. » ;\n- un autre jour : « Pense à sortir les 2 wraps la veille au soir. » (« la barquette de … » pour un plat à plusieurs mots) ;\n- si ton rappel « Sortir du congélateur » est activé : « Mail mardi à 19 h : sortir 2 wraps du congélateur pour la nuit au frigo. » (voir « rappels-par-mail »).\n\nDemain, une fois l’heure venue (vingt-quatre heures avant le repas), la même phrase que la fiche du plat dans « Frigo ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-en-plus-quantite",
    "titre": "La semaine : combien d’un de nos aliments, et l’étiquette photographiée",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment ajouter deux yaourts en dessert ?",
      "Comment noter 30 g de céréales ?",
      "Comment ajouter un produit en photographiant son étiquette ?",
      "À quoi sert « Dis-moi ce que c’est (facultatif) » ?",
      "Puis-je garder le produit photographié dans nos aliments ?"
    ],
    "sources": [
      "src/ui/aliments/Quantite.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/ui/semaine/EtiquetteEnPlus.tsx",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/lib/aliments/en-plus.ts",
      "src/lib/aliments/consigne.ts",
      "src/lib/aliments/etiquette.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/functions/etiquette/index.ts",
      "supabase/functions/_shared/consigne.ts",
      "supabase/migrations/0128_semaine_hier.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Combien ?\n\nDans « en plus » (voir « cuisine-semaine-en-plus »), appuyer sur un de nos aliments ouvre sous les pastilles le panneau **« Yaourt nature : combien ? »**. La pastille dit son unité (« pot », « 100 g »).\n\n- **Un aliment à l’unité** : un compteur **« − 2 pots + »**, avec les grammes dessous (« 250 g »). Il commence à un pot, ou au même nombre que la dernière fois si c’était un nombre entier de pots (jusqu’à 20). **« ou en grammes »** passe aux grammes ; **« ou en pots »** revient.\n- **Un aliment au gramme** (son unité est le gramme) ou **« en grammes »** : tes **quantités récentes** pour cet aliment, les trois dernières différentes (« 30 g », « 60 g »), et **« Autre »** pour taper. Sans historique, le champ est là d’emblée. La dernière quantité est déjà choisie : deux gestes, l’aliment puis « Ajouter ».\n- Refus : « Dis combien, en grammes. », « Je ne lis pas ce nombre. », « Pas de valeur négative. », « Il faut au moins 0,1 g. », « Pas plus de 5 000 g. »\n\nLe calcul s’affiche (« 114 kcal · 3 g de protéines »), puis **« Ajouter au soir »**. La ligne dit la quantité : « Yaourt nature × 2 pots », « Céréales, 30 g ». Les valeurs écrites sont **une copie** : corriger l’aliment demain ne change pas le bilan d’hier. Dans la feuille de choix d’un repas, le même panneau a pour bouton « Choisir pour le soir » (« Noter pour le soir » sur un jour passé).\n\n## Photographier l’étiquette\n\nSous la saisie à la main, après « ou », **« Photographier l’étiquette »** ouvre une feuille « L’étiquette, en plus du soir » et lance la lecture :\n- la photo, jusqu’à trois (« Reprendre la photo », « Ajouter l’autre face ») ;\n- **« Dis-moi ce que c’est (facultatif) »**, 300 caractères au plus (« Skyr vanille, pot de 150 g. J’ai mangé le pot entier. »), puis **« Relire avec cette consigne »**. C’est un indice pour le nom, l’unité et le poids : les valeurs nutritionnelles se recopient toujours de l’étiquette. Ce que tu as corrigé à la main reste ;\n- « Lu sur l’étiquette, pour 100 g », avec **« Corriger »** pour retaper un chiffre ;\n- **« J’en ai mangé, en grammes »**, déjà rempli du poids lu, et le calcul (« 96 kcal · 14,3 g prot. ») ;\n- la case **« Le garder dans nos aliments, sous « Skyr vanille » »**, cochée d’office. Il garde ses valeurs pour 100 g et, si l’étiquette ou la consigne la donne, son unité (« pot ») et son poids ; sinon c’est un aliment au gramme. Si ce nom existe déjà dans nos aliments, c’est lui qui sert. Décochée, rien n’est gardé ;\n- **« Ajouter au soir »**.\n\nCalories et protéines sont exigées (« Il manque les calories. »). Le délai, les pannes et le quota (40 étiquettes par mois et par foyer, chaque lecture compte) sont ceux de la lecture dans « cuisine-nos-aliments-creer ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-en-plus",
    "titre": "La semaine : le petit déjeuner, la collation, un en-plus",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment noter mon petit déjeuner ?",
      "Comment noter une collation ?",
      "Comment ajouter un yaourt en plus de mon plat ?",
      "Comment noter un dessert à la main, avec ses calories et ses protéines ?",
      "Pourquoi mon yaourt n’a pas les mêmes calories que le repère « Yaourt » ?",
      "Comment effacer ce que j’ai noté en plus ?",
      "Les calories d’un jour sans rien coché comptent-elles pour zéro ?"
    ],
    "sources": [
      "src/pages/Semaine.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/lib/reperes.ts",
      "src/ui/semaine/EtiquetteEnPlus.tsx",
      "src/lib/aliments/ordre.ts",
      "src/lib/aliments/en-plus.ts",
      "src/lib/choix.ts",
      "src/lib/donnees/barquettes.ts",
      "src/lib/semaine.ts",
      "supabase/migrations/0125_semaine_corrections.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\n« La semaine » te fait choisir le midi et le soir (voir « cuisine-semaine »). Le reste de la journée — le petit déjeuner, la collation, ce que tu manges en plus d’un plat — se note après coup, en un geste, et seulement pour toi.\n\n## Comment faire\n\n- Sous **« Autres moments »**, « Mangé sans barquette ? » propose **« Petit déjeuner »** et **« Collation »** (ceux que tu n’as pas déjà notés ce jour-là). Touche-en un, puis choisis un repère ou écris la tienne.\n- Sur la carte d’un plat, **« + ce que j’ai mangé en plus »** ouvre « En plus du soir » (ou du midi, du petit déjeuner, de la collation), avec « fermer » :\n  - « Nos aliments » : ceux du foyer, avec leurs vraies valeurs. Un appui ne pose rien : il demande **combien** (voir « cuisine-semaine-en-plus-quantite ») ;\n  - « Ce que vous reprenez souvent » : les habitudes du foyer ;\n  - « Un repère, pas une pesée » : des repères en un geste — « Restaurant » 900 kcal, « Sandwich » 550, « Pizza » 850, « Yaourt » 60. Un repère n’apparaît plus quand un de nos aliments le remplace : il le nomme (champ « Remplace le repère ») ou porte exactement son nom ;\n  - **à la main** : « Autre chose, à la main : les calories et les protéines sont obligatoires ». Remplis **« Quoi »**, **« Calories »** et **« Protéines, en g »**, puis **« Ajouter au soir »** (« au midi », « au petit déjeuner », « à la collation »). Il manque une case : « Il manque les calories. », « Il manque les protéines. » sous elle, et rien n’est écrit. Un nombre illisible (« Je ne lis pas ce nombre. ») ou négatif est refusé ;\n  - **« ou »** puis **« Photographier l’étiquette »** (voir « cuisine-semaine-en-plus-quantite »).\n- **« retirer »** efface un en-plus ; s’il échoue, l’erreur s’affiche. Retirer le dernier d’un petit déjeuner ou d’une collation efface aussi ce moment : tu peux le noter de nouveau.\n- **« Je saute le petit déjeuner »** (ou **« Je saute la collation »**) dit que tu ne manges rien à ce moment ; **« annuler »** le remet.\n\n## Les règles\n\n- Une barquette ne compte dans les calories du jour que si le repas est **mangé**. Un en-plus noté après coup compte **toujours** ; un repère choisi dans la feuille d’un repas (« Autre chose ») ne compte qu’une fois « Je l’ai mangé » touché (ou noté sur un jour passé), et plus du tout si tu l’annules.\n- **Un jour sans rien coché ni noté n’est pas un jour à zéro** : c’est un trou, hors des moyennes du bilan. Sur l’accueil : « N repas pas encore renseignés ».\n- « On saute ce repas » (dans la feuille d’un repas) est une réponse : le jour est renseigné, avec zéro pour ce repas.\n\n## Ce que l’appli ne fait pas\n\nElle ne demande pas de saisir des calories chaque jour, et il n’existe pas aujourd’hui de rappel pour noter ses repas.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-hier",
    "titre": "La semaine : noter hier et les jours passés",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment noter ce que j’ai mangé hier ?",
      "J’ai oublié de noter mon repas d’hier, que faire ?",
      "Que veut dire « pas encore noté » ?",
      "Jusqu’à quand puis-je noter un repas passé ?",
      "Pourquoi la barquette sort du frigo quand je note hier ?"
    ],
    "sources": [
      "src/pages/Semaine.tsx",
      "src/ui/semaine/Bandeau.tsx",
      "src/ui/semaine/Carte.tsx",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/lib/choix.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/migrations/0125_semaine_corrections.sql",
      "supabase/migrations/0128_semaine_hier.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nLe bandeau de « La semaine » remonte de **sept jours** : sept jours passés, aujourd’hui, puis les six suivants. Il s’ouvre sur aujourd’hui, avec hier visible à sa gauche ; un petit « ‹ » dit qu’il y a des jours plus anciens. Un jour passé est dessiné en **pointillé**, son numéro en gris, et **« hier »** remplace l’abréviation d’hier.\n\nLes deux points sous chaque jour restent : **creux**, c’est un repas pas noté. Sous le titre (« Lundi 26 octobre », avec « hier » en ocre pour hier ; pour les autres jours passés, la date seule), une phrase : « Un jour passé : tu notes ce que tu as mangé. Les barquettes que tu coches sortent du frigo ou du congélateur. »\n\n## Noter un repas passé\n\n- Un repas vide dit **« + Noter ce que j’ai mangé ce midi »** (ou « ce soir »). Pour une seule personne : « + Noter ce que Léa a mangé ce soir ». Touche-le : la feuille de choix s’ouvre **sur toi** (« Pour » : Kamil), avec « Un jour passé : ce que tu choisis est noté mangé… ». Pour noter aussi l’autre personne, touche « Vous deux » ou son prénom : rien n’est noté à sa place sans ce choix. Choisis une barquette, un aliment à nous, un repère, ou **« On saute ce repas »**.\n- Un repas déjà posé mais pas marqué mangé dit **« … · pas encore noté »**. **« Je l’ai mangé »** note ta part ; « Changer » ouvre la même feuille. Quand une seule personne l’a mangé : « Kamil l’a mangé, pas encore noté pour Léa ».\n- **Ce que tu choisis est mangé**, puisque le repas a eu lieu : la barquette quitte le frigo ou le congélateur, comme avec « Je l’ai mangé ». La case est notée à l’heure habituelle du repas (8 h, 12 h, 16 h ou 19 h). « On saute ce repas » reste « sauté ».\n- Un repas noté mangé par erreur se remet à « prévu » avec **« Pas mangé ? Annuler »** (voir « cuisine-semaine-annuler »).\n- Sous un plat, **« + ce que j’ai mangé en plus »** note un dessert (voir « cuisine-semaine-en-plus »).\n\n## Les règles\n\n- On note **sept jours** en arrière : au-delà, la base refuse.\n- **On peut toujours laisser un repas vide**, passé ou à venir : c’est un trou, hors des moyennes du bilan, pas un repas à zéro.\n- Une barquette déjà réservée par un repas **à venir** n’est pas libre pour un repas passé : la ligne est grisée.\n- Un repas déjà noté mangé ne se change plus pour cette personne.\n- Un jour passé ne dit plus « périme avant ce repas » ni quand sortir du congélateur : sous la barquette, « sort du frigo » ou « sort du congélateur ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine-peremption",
    "titre": "La semaine : la péremption, la part de chacun, le jour qui avance",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Pourquoi la feuille dit « périme avant ce repas » ?",
      "Quelle barquette l’appli pose quand je choisis un plat ?",
      "Que dit la carte d’un repas sur le poids et les calories ?",
      "La page change-t-elle de jour à minuit ?"
    ],
    "sources": [
      "src/ui/semaine/Carte.tsx",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/lib/choix.ts",
      "src/lib/jour-local.ts",
      "src/pages/Semaine.tsx",
      "supabase/migrations/0125_semaine_corrections.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nQuand tu choisis un plat, l’appli prend de préférence une barquette **encore bonne à l’heure du repas** : petit déjeuner 8 h, midi 12 h, goûter 16 h, soir 19 h. Ce n’est qu’ensuite qu’elle compte « la tienne, puis celle de personne, puis celle d’un autre », la plus pressée d’abord.\n\nSi toutes les barquettes libres périment avant le repas, elle en pose quand même une : le choix reste le tien.\n\n## Ce que tu lis\n\n- **Dans la feuille**, la ligne d’un plat annonce la barquette qui sera vraiment posée : « à manger avant jeudi », ou « périme avant ce repas » en ocre quand il n’y en a pas de meilleure.\n- **Sur la carte d’un repas**, sous « Du frigo, pour vous deux » : le poids, les calories et les protéines de ta part (« 784 g · 682 kcal · 56 g de protéines »), ou de la première personne de la carte, nommée, si tu n’en fais pas partie. Puis, quand il y a lieu, « périmée », « périme avant ce repas » (en ocre) ou, au frigo, « à manger aujourd’hui ».\n- Un repas mangé n’affiche plus ni part ni péremption ; un jour passé non plus (voir « cuisine-semaine-hier »).\n\n## Le jour qui avance\n\nLa page relit « aujourd’hui » quand l’écran se rallume et à minuit : le bandeau repart d’un jour plus loin, le jour que tu regardais reste le même s’il y est encore.\n\n## Les règles\n\n- La date de ton appareil ne peut différer que d’un jour de celle de Paris : au-delà, le choix est refusé (« La date de l’appareil n’est pas la bonne »).\n- Pas assez de barquettes libres pour tout le monde : rien n’est écrit, la ligne est grisée.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-semaine",
    "titre": "La semaine : choisir ce que je mange",
    "ecrans": [
      "/semaine"
    ],
    "questions": [
      "Comment choisir ce que je mange à midi et le soir ?",
      "Que veulent dire les points sous chaque jour ?",
      "Comment choisir le repas d’un seul de nous deux ?",
      "Comment noter un repas au restaurant ?",
      "Que veut dire « On saute ce repas » ?"
    ],
    "sources": [
      "src/pages/Semaine.tsx",
      "src/pages/Accueil.tsx",
      "src/ui/semaine/Bandeau.tsx",
      "src/ui/semaine/Carte.tsx",
      "src/ui/semaine/FeuilleDeChoix.tsx",
      "src/ui/semaine/EnPlus.tsx",
      "src/lib/choix.ts",
      "src/lib/semaine.ts",
      "src/lib/reperes.ts",
      "src/lib/aliments/ordre.ts",
      "src/lib/donnees/barquettes.ts",
      "supabase/migrations/0123_choisir_un_repas.sql",
      "supabase/migrations/0125_semaine_corrections.sql",
      "supabase/migrations/0128_semaine_hier.sql",
      "src/lib/peremption.ts"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\n« La semaine » est l’écran où **tu choisis ce que tu manges** à midi et le soir. Après « On range », rien n’est posé tout seul : c’est ici que la semaine se remplit.\n\nLe bandeau du haut montre quatorze jours : les **sept jours passés** (en pointillé, qu’on note : voir « cuisine-semaine-hier »), aujourd’hui, puis les six suivants. Il s’ouvre sur aujourd’hui. Sous chaque jour, deux points, midi puis soir : **vert**, du frigo ; **bleu**, du congélateur ; **safran**, autre chose (ou un repas sauté) ; **creux**, rien de choisi.\n\n## Choisir un repas\n\n1. Sur un jour, la carte vide dit **« + Choisir le midi »** (ou « le soir »). Touche-la : une feuille s’ouvre (« Lundi midi »).\n2. **« Pour »** : « Vous deux » (tout le foyer) ou une seule personne, par son prénom.\n3. Choisis : **« Au frigo »** (ce qui presse d’abord, avec le nombre de barquettes libres), **« Au congélateur »** (à sortir la veille), ou **« Autre chose »** : **nos aliments** d’abord (un appui demande « combien ? » : voir « cuisine-semaine-en-plus-quantite ») ; puis ce que vous reprenez souvent, les repères du repas (« Restaurant » 900 kcal, « Sandwich » 550…) et **« On saute ce repas »**. Un repère qu’un de nos aliments remplace n’apparaît plus. Le lien **« Ajouter ou modifier nos aliments »** ouvre leur écran, et le retour rouvre la feuille. Si la liste ne se lit pas : « Je n’ai pas pu lire nos aliments : les repères sont proposés à leur place. »\n\nChoisir un plat pose une barquette libre dans la case de **chaque** personne visée, la plus pressée d’abord. Pour chacune, l’appli prend d’abord une barquette faite pour elle, puis une sans destinataire, puis celle d’un autre en dernier recours. Pas assez pour tout le monde : la ligne est grisée (« il en faut 2, 1 libre »).\n\nPour changer un repas ou le manger, voir « cuisine-semaine-changer ».\n\n## Les règles\n\n- « On saute ce repas » est une réponse : le jour est renseigné, sans rien compter. **Un repas jamais choisi n’est pas un repas à zéro** : c’est un trou, hors des moyennes du bilan.\n- Choisir autre chose pour un repas remplace le plat : ses en-plus s’en vont avec lui.\n- Un repas « Autre chose » (restaurant, sandwich) ne compte dans tes calories qu’une fois « Je l’ai mangé » touché (ou noté sur un jour passé), et plus du tout si tu l’annules.\n- Le petit déjeuner, la collation et ce qu’on mange en plus d’un plat se notent à part : voir « cuisine-semaine-en-plus ».\n- La péremption et la part de chacun sont dites sur la carte : voir « cuisine-semaine-peremption ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-session-fin",
    "titre": "Finir, interrompre ou reprendre la cuisine",
    "ecrans": [
      "/cuisine"
    ],
    "questions": [
      "Que faire quand tout est cuit ?",
      "Comment passer au dressage sans cocher toutes les actions ?",
      "Comment interrompre la session de cuisine ?",
      "Comment reprendre une session interrompue ?",
      "Pourquoi l’accueil de Popote dit « Session interrompue » ?",
      "Que veut dire « J’ai fini · passer au dressage » ?"
    ],
    "sources": [
      "src/pages/Cuisine.tsx",
      "src/pages/Accueil.tsx",
      "src/pages/Hub.tsx",
      "src/lib/donnees/cycle.ts",
      "supabase/migrations/0013_cycle.sql",
      "supabase/migrations/0117_cuisine_corrections.sql",
      "supabase/migrations/0119_reprendre_une_session_recente.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Quand tout est coché\n\nL’écran dit « C’est cuit. », avec « N actions en … ». **« Passer au dressage »** ouvre l’écran suivant.\n\n## Quand tout n’est pas coché : « J’ai fini »\n\nTant que toutes les actions ne sont pas cochées, le bouton **« J’ai fini · passer au dressage »** se tient au-dessus de « Interrompre la session ». Il n’existe que chez toi : un convié ne le voit pas.\n\nIl demande « Tout est cuit ? » et nomme les actions non cochées (quatre au plus, puis « … »). Si aucune action d’une recette n’est cochée, il le dit : « Aucune action de « … » n’est cochée : elle sera dressée quand même. » Le dressage prend toutes les recettes de la semaine, cuisinées avec l’appli ou sans.\n\n- **« Oui, au dressage »** passe au dressage. Ces actions restent non cochées.\n- **« Non, je continue »** (ou Échap) referme la question. Pendant l’envoi, elle reste ouverte.\n- Si l’autre téléphone coche la dernière action entre-temps, la question disparaît et « C’est cuit. » prend le relais.\n\n## Interrompre\n\n« Interrompre la session » demande « Interrompre la session ? » : « Non, je continue » ou « Oui, interrompre ». Pour dire que la cuisine est finie, prends plutôt « J’ai fini ». Un convié n’interrompt pas : il a « Quitter la session ».\n\n## Reprendre\n\n- L’accueil de la cuisine titre **« Session interrompue »** quand aucune semaine n’est ouverte, avec **« Reprendre la session interrompue »** en gros bouton et « Choisir de nouvelles recettes » en second.\n- La carte sombre de l’accueil de Popote dit « Session interrompue » et « Reprends-la depuis la cuisine. », avec le même bouton « Reprendre la session interrompue ».\n- Une session se reprend si sa semaine est la précédente, la courante ou une à venir, **ou** si elle a commencé il y a moins de 7 jours. Au-delà, elle ne se propose plus.\n- La semaine n’aura pas d’autre session : « Cette semaine a une session interrompue : reprends-la. »",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-session-partagee",
    "titre": "Cuisiner avec un ami : la session partagée",
    "ecrans": [
      "/plan",
      "/cuisine"
    ],
    "questions": [
      "Comment inviter un ami à cuisiner avec moi ?",
      "Mon ami peut-il modifier mon plan de cuisine ?",
      "Comment rejoindre la session d’un ami ?",
      "Comment retirer un invité de ma session ?",
      "Mon ami est-il prévenu quand je l’invite ?"
    ],
    "sources": [
      "src/pages/Plan.tsx",
      "src/pages/Cuisine.tsx",
      "src/pages/Accueil.tsx",
      "src/lib/donnees/convives.ts",
      "supabase/migrations/0037_cuisiner_ensemble.sql",
      "supabase/migrations/0038_convive_frontiere.sql",
      "supabase/migrations/0043_amitie_pas_transitive.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nTu peux convier un foyer **ami** (voir « cuisine-amis ») à ta session de cuisine. Il suit l’avancement et prend des gestes ; il ne touche pas au plan.\n\n## Inviter\n\n1. Sur le plan, « Qui cuisine avec toi ? » liste tes foyers amis (la question n’apparaît que s’il y en a). Coche-les.\n2. « Commencer la session » enregistre le plan et l’heure de début, envoie l’invitation, puis passe la session « en cuisine » et ouvre l’écran de cuisine. Si l’invitation échoue, une erreur s’affiche et tu restes sur le plan (qui, lui, est déjà enregistré).\n3. **Il n’y a pas de notification** : l’ami découvre l’invitation en ouvrant l’appli.\n\n## Rejoindre\n\nSur l’accueil de la cuisine, l’ami voit « … t’invite à cuisiner. » et « Rejoindre ». Ensuite : « … cuisine — tu suis la session. » avec « Reprendre la session ». L’invitation reste visible tant que la session est en préparation, en cuisine ou au dressage, et que l’amitié tient.\n\n## Ce que fait le convié\n\nIl voit le même plan en direct et prend des gestes (« Je prends », « C’est fait »). Il lit : « Tu cuisines chez quelqu’un d’autre : tu prends des gestes, tu ne touches pas au plan. » Il ne réordonne rien, ne supprime rien, n’interrompt pas la session et ne la fait pas avancer : « J’ai fini · passer au dressage » ne s’affiche que chez l’hôte. Le dressage revient à l’hôte. Il peut « Quitter la session » et, à la fin (« C’est cuit. »), « Revenir chez moi ».\n\nIl voit le nom de tes recettes, pas celui des recettes qu’un autre foyer t’a prêtées.\n\nSi l’hôte a terminé : « Cette session n’est plus ouverte » (« Ton hôte l’a terminée, ou ne t’y attend plus. »), avec « Quitter cette session ».\n\n## Côté hôte\n\nSur l’écran de cuisine, la liste des convives montre chacun (« — invité, pas encore là » tant qu’il n’a pas rejoint) avec « Retirer ». Rompre l’amitié met aussi fin à la session pour lui.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-session",
    "titre": "La cuisine pas à pas",
    "ecrans": [
      "/cuisine"
    ],
    "questions": [
      "Comment fonctionne l’écran de cuisine ?",
      "Que veut dire « Je prends » et « C’est fait » ?",
      "Que signifie « Pendant ce temps » ?"
    ],
    "sources": [
      "src/pages/Cuisine.tsx",
      "src/lib/donnees/session.ts",
      "src/pages/Accueil.tsx",
      "src/lib/donnees/cycle.ts",
      "supabase/migrations/0013_cycle.sql",
      "supabase/migrations/0117_cuisine_corrections.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Ce que fait l’appli\n\nÉcran sombre, sans barre du bas : un seul geste à la fois, selon le plan de dimanche.\n\n## Comment faire\n\n1. En haut : « Session en cours · » et le temps écoulé.\n2. Le geste à faire s’affiche avec « À prendre · N sur M faites » et sa durée « prévues ». S’il sert plusieurs recettes : « Pour … et … à la fois. »\n3. **« Je prends »** met le geste à ton nom (« À toi » remplace « À prendre ») et lance un compte à rebours (« restantes »).\n4. **« C’est fait »** quand c’est fini : le geste suivant apparaît.\n\n- « Pendant ce temps » : les actions qui cuisent seules une fois prises, avec leur temps restant.\n- « Ensuite, si quelqu’un est libre » : au plus deux gestes déjà possibles, à prendre en touchant la ligne. Avec un geste en cours, le premier des suivants est masqué.\n- « Rien à faire, ça cuit. » : rien n’est à prendre ; « La suite s’ouvrira toute seule. »\n- Un geste pris par l’autre personne disparaît de ton écran.\n\n## Les règles\n\n- Un geste n’est proposé que lorsque ceux dont il dépend sont faits.\n- Deux téléphones suivent la même session en direct.\n- Une action qui cuit seule se prend aussi, mais ne se termine pas seule : à 0:00 celui qui l’a prise appuie sur « C’est fait ».\n- L’appli mesure la durée réelle de chaque geste ; « C’est fait » sans « Je prends » compte le début à la durée prévue en arrière.\n\n## Quand tout est cuit, ou fini\n\n« C’est cuit. » puis « Passer au dressage » ; « J’ai fini », « Interrompre » et la reprise : voir « cuisine-session-fin ».\n\n## Si tu es invité\n\nUn ami convié (voir « cuisine-session-partagee ») prend des gestes, ne touche pas au plan : ni « Interrompre », ni « J’ai fini ». Il a « Quitter la session » puis « Revenir chez moi ». Le dressage revient à l’hôte.\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui de notification ni de sonnerie à 0:00 : tu regardes l’écran.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-stock",
    "titre": "Le frigo : plats, ingrédients, congélateur, placard",
    "ecrans": [
      "/frigo"
    ],
    "questions": [
      "À quoi sert le frigo dans l’appli ?",
      "Que dit l’aimant sur la porte du frigo ?",
      "Combien de temps se garde une barquette au congélateur ?",
      "Comment retirer un ingrédient fini ?",
      "Le stock diminue-t-il quand je cuisine ?"
    ],
    "sources": [
      "src/pages/Frigo.tsx",
      "src/ui/frigo/FrigoFerme.tsx",
      "src/ui/frigo/Interieurs.tsx",
      "src/ui/frigo/FichePlat.tsx",
      "src/ui/frigo/FicheIngredient.tsx",
      "src/lib/frigo.ts",
      "src/lib/donnees/frigo.ts",
      "src/pages/AjoutManuel.tsx",
      "src/pages/Photo.tsx",
      "src/pages/Choisir.tsx",
      "src/lib/peremption.ts",
      "src/lib/donnees/barquettes.ts",
      "src/lib/quantite.ts",
      "supabase/migrations/0021_cocher_remplit.sql",
      "supabase/migrations/0047_peremption_donnee.sql",
      "supabase/migrations/0092_la_photo_et_les_gestes.sql",
      "supabase/migrations/0117_cuisine_corrections.sql",
      "supabase/migrations/0121_photo_des_plats.sql"
    ],
    "verifie_sur": "7a2a964",
    "corps": "## Ce que fait l’appli\n\n« Frigo », dans la barre du bas, dessine un frigo américain. À gauche le **congélateur**, à droite le **frigo**. L’ancien écran « Ce que j’ai » (`/stock`) renvoie ici.\n\nFermé, il parle sans qu’on y touche :\n\n- **L’afficheur** du congélateur : « Ce soir » et ton dîner prévu, ou « Rien de prévu ce soir ». S’ils ne se lisent pas, l’afficheur dit « Indisponible ».\n- **L’aimant** du frigo, un seul : des barquettes congelées à sortir, posées sur ce soir ou sur demain quand l’heure de les sortir est venue (« Sors les 2 wraps : c’est ce soir », « Sors la barquette de burger de feuilles de riz : c’est demain soir ») ; sinon des barquettes du frigo périmées (« 2 barquettes de pizza vietnamienne à jeter ») ou qui périment sous 72 heures sans qu’aucun repas les réclame (« 2 barquettes de pizza vietnamienne à prévoir avant jeudi ») ; sinon rien.\n- **La photo** du plat de demain, s’il en a une.\n\nTouche une porte : elle pivote, puis l’intérieur prend l’écran. Échap ou « Fermer la porte » le ferme.\n\n## Dedans\n\n- **Frigo** : une carte par plat (recette, lieu et état), avec la photo, « ×N » parts, et quand c’est prévu (« mar. midi à mer. midi ») ou le mot d’urgence. Dessous, les ingrédients par étagère (« Laitages et frais », « Viandes et poissons », « Autres »), le « Bac à légumes », « + Ajouter au frigo » et « Photo du frigo ».\n- **Congélateur** : les plats congelés, le « Tiroir du bas » pour les ingrédients, « + Ajouter au congélateur ».\n- **Le placard** : lien sous le frigo, une liste, « + Ajouter au placard ». « Peser ce qu’on compte à l’unité » est juste dessous.\n\nLe stock se remplit en cochant la liste de courses (le rayon décide du lieu : « Surgelés » au congélateur ; « Frais », « Fruits et légumes », « Boucherie, poissonnerie » au frigo ; le reste au placard ; ni Entretien ni Hygiène), à la main, par photo, et au dressage (« cuisine-on-range »).\n\nTouche une carte pour ouvrir sa **fiche** (« cuisine-fiche-plat » : parts, dates, photo ; « cuisine-fiche-plat-gestes » : manger, congeler, sortir, jeter, retirer).\n\n## Un ingrédient\n\nQuantité (« Enregistrer »), lieu (Frigo, Congélateur, Placard : le congélateur date la mise au froid), « À manger avant » (« Retirer la date »), « Fini » (supprime, sans confirmation). Changer de lieu recalcule la date comme pour une barquette : 90 jours au congélateur, 24 heures à la sortie vers le frigo, aucune vers le placard ; entre frigo et placard, elle reste.\n\n## Ce que l’appli ne fait pas\n\nSeul le rappel « Une barquette va périmer » (voir « rappels-les-sept »), que chacun active lui-même, prévient par mail, et il ne parle que des barquettes. Le stock ne diminue pas quand tu manges : seuls « On range » (ce que la session a pris), « Fini » et la liste de courses le font.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-ticket",
    "titre": "Le ticket de caisse et les prix appris",
    "ecrans": [
      "/ticket"
    ],
    "questions": [
      "Comment photographier mon ticket de caisse ?",
      "Comment l’appli connaît le prix de mes courses ?",
      "Que veut dire « écart avec le total imprimé » ?",
      "Comment corriger un article mal rattaché à ma liste ?",
      "Combien de tickets puis-je lire par mois ?",
      "Mon ticket est long, comment faire ?"
    ],
    "sources": [
      "src/pages/Ticket.tsx",
      "src/pages/Magasin.tsx",
      "src/pages/Bilan.tsx",
      "src/lib/prix.ts",
      "src/lib/donnees/prix.ts",
      "src/lib/donnees/bilan.ts",
      "supabase/functions/ticket/index.ts",
      "supabase/functions/ticket/lignes.ts",
      "supabase/migrations/0024_prix.sql",
      "supabase/migrations/0031_apprentissage.sql"
    ],
    "verifie_sur": "7a2a964",
    "corps": "## Ce que fait l’appli\n\nTon ticket est la seule source de prix : l’appli n’en devine aucun. Tu le photographies, un modèle de langage en tire les lignes, l’appli les **rapproche de ta liste de courses** et apprend le prix de chaque produit **chez cette enseigne**.\n\n## Comment faire\n\n1. Sur la liste : « J’ai payé — photographier le ticket ». Choisis l’« Enseigne » (sinon le magasin par défaut).\n2. « Photographier le ticket » : à plat, bien éclairé, de haut (environ vingt secondes). Ticket long : photographie-le en deux fois.\n3. Relis « Le ticket lu » : l’enseigne, la date, le total, puis « N lignes lues », « N rattachées à la liste » et, s’il y en a un, l’écart.\n4. Touche le ticket photographié pour le lire en grand (Échap le referme). Décoche une ligne fausse. Touche une ligne pour la rattacher ailleurs (« Rattacher à : » un article, ou « rien »).\n5. « Enregistrer N lignes · X € » (somme des lignes cochées) te ramène à la liste. « Reprendre une photo » recommence.\n\n## Les règles\n\n- Une ligne est cochée d’avance si la confiance du modèle est d’au moins 0,5. Une ligne rattachée à un article dit « sur la liste : » et son nom. Une ligne **absente de la liste** reste possible : « pas sur la liste : le prix s’apprend quand même ».\n- Le rapprochement compare les mots du libellé de caisse (« PDT CHARLOTTE 2.5KG ») à ceux de ta liste. Score d’au moins 0,72 : sûr. Entre 0,4 et 0,72 : proposé, « deviné, à vérifier ». En dessous : sans article. Un rapprochement deviné que tu ne changes pas est enregistré : vérifie-le.\n- **L’écart** compare la somme des lignes lues au total imprimé : « écart de X € avec le total imprimé ». Une ligne manquée se voit ici avant de se voir sur le papier. Sans écart, rien n’est écrit.\n- Une remise listée mais non soustraite est déduite, seulement si le compte tombe juste au centime : « remises déduites ».\n- Le **prix payé** des articles rattachés est reporté sur la liste.\n- Le prix appris est la **moyenne** des relevés, par enseigne et par libellé de caisse : 2,00 € puis 3,00 € donnent 2,50 €. L’appli préfère la même enseigne.\n- « Estimer les prix d’après mes tickets » (sur la liste, tant qu’une ligne n’a pas de prix) ne remplit que ces lignes.\n- Le total imprimé alimente « payés » du bilan, à la date d’achat ; sans total lu, la somme des lignes.\n\n## Quota\n\n**30 tickets par mois** pour le foyer ; il repart le 1er. « N tickets restants ce mois-ci » s’affiche sous « Reprendre une photo ». Au-delà : « Quota atteint : 30 tickets par mois. Il repart le 1er. »",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "cuisine-vue-ensemble",
    "titre": "La cuisine, du choix des recettes au bilan",
    "ecrans": [
      "/cuisine-accueil"
    ],
    "questions": [
      "Comment ça marche, la cuisine dans Popote ?",
      "Par où je commence pour préparer la semaine ?",
      "Que faire maintenant ? Quelle est la prochaine étape ?",
      "Pourquoi l’accueil me propose « Choisir les recettes » alors que j’ai déjà commencé ?",
      "Comment reprendre une session interrompue ?",
      "Pour quelle semaine je choisis les recettes ?"
    ],
    "sources": [
      "src/pages/Accueil.tsx",
      "src/lib/donnees/cycle.ts",
      "src/pages/Choisir.tsx",
      "src/pages/Cuisine.tsx",
      "src/pages/Bilan.tsx",
      "src/pages/Hub.tsx",
      "src/ui/coque.tsx",
      "src/lib/peremption.ts",
      "src/lib/frigo.ts",
      "supabase/migrations/0013_cycle.sql",
      "supabase/migrations/0117_cuisine_corrections.sql",
      "supabase/migrations/0119_reprendre_une_session_recente.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que fait l’appli\n\nOn choisit les recettes maintenant, on cuisine dimanche, on mange la semaine d’après. L’accueil de la cuisine (bouton « Cuisine » de l’accueil de Popote) ne pose qu’une question, « et maintenant ? » : un titre et un gros bouton. Au-dessus, le petit frigo (« N parts au frigo », « N au congélateur », « Ouvrir le frigo ») mène à « cuisine-stock ».\n\n## Les états, dans l’ordre\n\n1. **Rien de prévu** : « Choisir les recettes » ouvre la semaine et mène à « Choisir ». Tant que tu n’as pas touché « Faire la liste », l’accueil reste là.\n2. **Votre liste est prête** : « Je pars faire les courses ».\n3. **Tout est là** : « Voir le plan de dimanche ».\n4. **Session en cours** : « Reprendre la cuisine ».\n5. **Il reste à dresser** : « Dresser les barquettes ».\n6. **La semaine tourne** : « Voir la semaine ». Si un repas est prévu aujourd’hui, l’accueil l’affiche en carte sombre (« Ce soir, pour vous deux ») avec « Je l’ai mangé » et « Changer » — « Je les sors » (« Je le sors » s’il n’y en a qu’une) à la place quand la barquette est au congélateur —, puis « Demain, midi et soir » et « La semaine ». Un repas déjà noté mangé reste sous la carte avec « Pas mangé ? Annuler » (voir « cuisine-semaine-annuler »).\n\n« Clore et préparer la semaine prochaine » (dans « Bilan ») referme la semaine : retour à « Rien de prévu ». Une session à reprendre fait titrer « Session interrompue », avec « Reprendre la session interrompue » en gros bouton et « Choisir de nouvelles recettes » en second ; la carte sombre de l’accueil de Popote le dit aussi.\n\n## Les règles\n\n- Un foyer n’a **qu’une semaine ouverte à la fois**.\n- « Choisir les recettes » ouvre la semaine du **lundi suivant** ; on cuisine le dimanche, la veille. Par défaut : **10 parts** à couvrir.\n- Rouvrir la même semaine est refusé : « Cette semaine a déjà eu sa session : reprends-la, ou attends la semaine suivante. » Une semaine close ne se reprend pas.\n- « Interrompre la session » se fait depuis l’écran de cuisine ; la reprise a ses règles (voir « cuisine-session-fin »). Une semaine interrompue ne se rouvre pas : « Cette semaine a une session interrompue : reprends-la. »\n\n## Aussi sur l’accueil\n\n- Hors de « La semaine tourne », la carte sombre du repas d’aujourd’hui vient **sous** le gros bouton.\n- En bas, « À manger bientôt », sans titre visible : jusqu’à deux plats qui pressent, un par ligne avec son nombre de barquettes, avec « à manger aujourd'hui », « demain dernier délai », « périmée » ou « à sortir sous N j » quand leur date approche.\n- « Envie spéciale ? » invente une recette.\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas de notification sur le téléphone : tout se lit en ouvrant l’appli. Seuls les rappels par mail, que chacun active lui-même, préviennent hors de l’appli (voir « rappels-par-mail »).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "donnees-et-vie-privee",
    "titre": "Tes données et ta vie privée",
    "ecrans": [
      "/reglages"
    ],
    "questions": [
      "Léa voit-elle mon revenu ?",
      "Que voit l’intelligence artificielle de mes données ?",
      "L’IA voit-elle mes revenus ?",
      "Comment exporter mes données ?",
      "Comment supprimer mon compte ?"
    ],
    "sources": [
      "src/pages/Settings.tsx",
      "src/pages/Profil.tsx",
      "src/pages/BudgetReglages.tsx",
      "src/pages/AccepteAmi.tsx",
      "src/pages/Dictee.tsx",
      "src/lib/photo.ts",
      "src/lib/aliments/openfoodfacts.ts",
      "src/ui/aliments/LecteurDeCodes.tsx",
      "src/ui/aliments/Formulaire.tsx",
      "supabase/functions/frigo/index.ts",
      "supabase/functions/ticket/index.ts",
      "supabase/functions/etiquette/index.ts",
      "supabase/functions/charges/index.ts",
      "supabase/functions/revue-charges/index.ts",
      "supabase/functions/inventer/index.ts",
      "supabase/functions/importer/index.ts",
      "supabase/functions/_shared/llm.ts",
      "supabase/functions/aide/index.ts",
      "supabase/migrations/0118_aide_signalement.sql",
      "supabase/migrations/0005_policies.sql",
      "supabase/migrations/0035_amis.sql",
      "supabase/migrations/0037_cuisiner_ensemble.sql",
      "supabase/migrations/0038_convive_frontiere.sql",
      "supabase/migrations/0043_amitie_pas_transitive.sql",
      "supabase/migrations/0049_budget_fondations.sql",
      "supabase/migrations/0051_budget_socle_corrige.sql",
      "supabase/migrations/0097_budget_tables.sql",
      "supabase/migrations/0112_budget_depart.sql",
      "supabase/migrations/0126_rappels.sql",
      "supabase/migrations/0127_export_des_rappels.sql"
    ],
    "verifie_sur": "b730eb1",
    "corps": "## Ce que le foyer voit de l’autre\n\nDans le foyer, tout se partage, c’est voulu. **Le revenu de chacun est visible des deux** (« Réglages du budget » liste le net de chacun). Les objectifs nutritionnels, les charges (même celles marquées perso), les comptes, les courses et le stock aussi. Chacun ne modifie que son propre profil, son propre revenu et ses propres objectifs.\n\nUn **foyer ami** voit les prénoms et les recettes marquées « partagée ». S’il a rejoint une de tes sessions de cuisine, il voit aussi cette session tant qu’elle est prête, en cuisine ou au dressage : étapes, appareils et recettes de l’hôte, même non partagées. Rien d’autre : ni budget, ni objectifs, ni courses.\n\n**Tes rappels par mail sont à toi seul** : l’autre ne voit pas ceux que tu as activés (voir « rappels-par-mail »).\n\n## Ce que voient les modèles de langage\n\nCes appels partent vers un service d’IA extérieur :\n\n- **photo du frigo** : la photo et le lieu ;\n- **ticket** : la photo et l’enseigne si tu l’as choisie ; **étiquette** (« Nos aliments ») : jusqu’à trois photos et, si tu l’écris, ta consigne (300 caractères) ;\n- **dictée de charges** : le texte, avec la liste type des charges (la voix est transcrite par ton clavier : aucun son n’est envoyé) ;\n- **relecture des charges** : libellés, montants, rythmes, commun ou perso, comptes (nom écrit par toi), enveloppes, date de début ; ni revenus, ni parts, ni prénoms ;\n- **recette inventée** : ton envie (300 caractères), les aliments du stock, des limites chiffrées ; jamais de prénom, de poids ni d’objectif ;\n- **import de recette** : le texte collé et tes précisions ;\n- **aide « Demande à Popote »** : ta question, la précédente avec sa réponse, et quelques pages du manuel de l’appli ; jamais tes chiffres.\n\n**Code-barres** (« Nos aliments ») : ce n’est pas un modèle de langage. Les chiffres du code partent de ton téléphone, directement vers Open Food Facts, une base publique, sans passer par Popote. Lu avec l’appareil photo, le code se lit sur le téléphone : l’image ne part pas.\n\nAucun appel à un modèle ne lit les revenus ou les prénoms. Rien n’est enregistré sans que tu valides à l’écran. Aucun code ne garde les photos ; ce que le service extérieur en fait, le code ne le dit pas.\n\n## Exporter\n\nRéglages, ligne « Exporter mes données » (dans la carte du bas) : un fichier « mes-donnees.json » avec **tout ce que le foyer a enregistré**, y compris les données de l’autre (son revenu, par exemple) et les réponses de l’aide que tu as signalées comme fausses. Y figurent aussi tes réglages de rappel et l’historique de tes mails de rappel, pas ceux de l’autre.\n\n## Supprimer\n\n« Supprimer mon compte » demande « Supprimer ton compte et tes données ? C’est définitif. » Partent ton profil, ton revenu, tes objectifs, tes comptes perso, tes réglages de rappel et l’historique de tes mails. Tes charges à toi seul s’arrêtent ou disparaissent. Le foyer reste pour l’autre : les mois ouverts se repartagent entre ceux qui restent, les mois clôturés ne bougent pas. Il n’est supprimé que s’il ne reste personne.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "foyer-creer",
    "titre": "Créer son foyer",
    "ecrans": [],
    "questions": [
      "Comment créer mon foyer ?",
      "Pourquoi l’appli me dit « Il te faut une invitation » ?",
      "Je me suis connecté mais je n’ai pas de foyer, que faire ?",
      "Peut-on avoir deux foyers ?"
    ],
    "sources": [
      "src/pages/Onboarding.tsx",
      "src/App.tsx",
      "supabase/migrations/0009_create_household.sql",
      "supabase/migrations/0070_un_seul_foyer.sql",
      "supabase/migrations/0091_le_createur_choisit_son_prenom.sql"
    ],
    "verifie_sur": "02a9f37",
    "corps": "## Ce que fait l’appli\n\nUn foyer, c’est le groupe qui partage tout : les courses, le budget, les sessions de cuisine. Chaque personne appartient à un seul foyer.\n\nQuand tu es connecté(e) mais que tu n’as pas de foyer, l’appli te montre l’un de ces deux écrans.\n\n## Si la création est ouverte : « Votre foyer »\n\n1. Dans « Comment vous l’appelez », garde « Notre foyer » ou écris un autre nom.\n2. Appuie sur « Créer le foyer ».\n3. L’appli te demande ensuite de choisir un mot de passe (si tu n’en as pas encore), puis ton profil : prénom, revenu, date d’arrivée. Voir la page « compte-profil ».\n\nL’écran rappelle aussi : si quelqu’un t’a déjà invité(e), ouvre plutôt le lien qu’on t’a envoyé.\n\n## Si la création est fermée : « Il te faut une invitation »\n\nCet écran dit : « Cette application se rejoint sur invitation. » Il n’y a pas de bouton pour créer un foyer. Demande à la personne du foyer de t’envoyer son lien, puis ouvre-le : il te fait rejoindre le foyer. Ton compte est déjà créé, il ne te manque que le lien. Le bouton « Se déconnecter » est là pour changer de compte ; à la différence de « Me déconnecter » des réglages, il ferme aussi la session de tes autres appareils.\n\n## La règle\n\nCette appli est privée. Dès qu’un foyer existe, la création de nouveaux foyers se ferme toute seule : le seul chemin qui reste est le lien d’invitation. Cela évite qu’une personne qui n’a pas ouvert son lien se retrouve, d’un clic, dans un foyer vide à elle, avec un budget séparé de celui de l’autre.\n\nConcrètement : tant qu’un foyer existe, un nouveau compte sans lien voit « Il te faut une invitation ». Je ne sais pas dans quel état est ce réglage sur le serveur en ligne : il peut être rouvert à la main.\n\n## Ce que l’appli ne fait pas\n\n- Elle ne permet pas d’être dans deux foyers. Je n’ai pas trouvé d’écran pour changer de foyer, ni pour en quitter un sans supprimer son compte.\n- Je n’ai pas trouvé d’écran pour renommer le foyer après sa création.\n\nPour inviter quelqu’un : page « foyer-inviter ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "foyer-inviter",
    "titre": "Inviter quelqu’un dans le foyer",
    "ecrans": [
      "/reglages"
    ],
    "questions": [
      "Comment inviter Léa ?",
      "L’invitation part par mail ?",
      "Combien de temps le lien d’invitation marche ?",
      "Le lien d’invitation a expiré, que faire ?",
      "Je n’ai pas reçu l’invitation, que faire ?"
    ],
    "sources": [
      "src/pages/Settings.tsx",
      "src/pages/Hub.tsx",
      "src/pages/BudgetReglages.tsx",
      "supabase/functions/invite/index.ts",
      "supabase/functions/accept-invite/index.ts",
      "supabase/migrations/0071_invitation_trente_jours.sql",
      "supabase/migrations/0089_le_lien_suffit.sql"
    ],
    "verifie_sur": "5fc4aa2",
    "corps": "## Ce que fait l’appli\n\nInviter, c’est créer un lien. **Aucun e-mail n’est envoyé** : c’est toi qui transmets le lien, par SMS, WhatsApp ou mail. Les anciens mails d’invitation ont été supprimés, parce que leur lien mourait au bout d’une heure.\n\n## Comment faire\n\nTrois chemins mènent au même endroit, la carte « Inviter » des réglages :\n\n- sur l’accueil de Popote, la carte « Inviter quelqu’un. » (elle n’apparaît que tant que tu es seul(e) dans le foyer) ;\n- dans les réglages du budget, le bouton « Inviter quelqu’un » (même condition) ;\n- sur l’accueil de la cuisine, le rond avec ton initiale en haut à droite ouvre « Réglages » ; « Inviter » est la première carte.\n\nPuis :\n\n1. Écris l’adresse dans « Son e-mail ».\n2. Appuie sur « Créer l’invitation ».\n3. L’appli répond « Invitation créée pour … Envoie-lui ce lien. » et affiche « Son lien, valable 30 jours : ».\n4. Appuie sur « Partager » (si ton téléphone le permet) ou « Copier le lien », puis envoie-le.\n\n## Les règles\n\n- Le lien vaut **30 jours** et **ne sert qu’une fois**.\n- Sur l’écran d’inscription du lien, l’adresse saisie est affichée et ne se change pas. Quelqu’un qui a déjà un compte sans foyer peut aussi s’en servir, même avec une autre adresse.\n- Quiconque a le lien peut s’en servir une fois : ne le publie pas.\n- Si tu réinvites la même adresse alors qu’une invitation attend, tu récupères le même lien.\n- Si l’invitation a expiré, retape la même adresse : tu obtiens un nouveau lien, valable 30 jours (l’ancien ne marche plus).\n- Si l’adresse est déjà dans ton foyer, l’appli répond « Cette personne est déjà dans ton foyer. » Si elle est dans un autre foyer, le lien est créé, mais à l’ouverture l’appli répond « Cette adresse a déjà un compte Popote. »\n- Une adresse mal écrite donne « Adresse e-mail invalide ».\n\n## Exemple\n\nTu écris l’adresse de Léa, tu appuies sur « Créer l’invitation », tu copies le lien et tu le lui envoies sur WhatsApp. Elle l’ouvre sur son téléphone : voir la page « foyer-rejoindre ».\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas d’envoi automatique de l’invitation. Je n’ai pas trouvé d’écran qui liste les invitations en attente, ni de bouton pour en annuler une : retaper l’adresse redonne seulement le lien.\n\nÀ ne pas confondre avec « Inviter un foyer » (réglages, section « Vos amis »), qui sert à échanger des recettes : page « reglages ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "foyer-rejoindre",
    "titre": "Rejoindre un foyer avec un lien",
    "ecrans": [],
    "questions": [
      "J’ai reçu un lien d’invitation, que faire ?",
      "Faut-il avoir un compte pour rejoindre le foyer ?",
      "Le lien dit « Ce lien a expiré » ou « Ce lien a déjà servi »",
      "L’appli dit « Tu es déjà dans un foyer »",
      "J’ai déjà un compte et je reçois une invitation"
    ],
    "sources": [
      "src/pages/Rejoindre.tsx",
      "src/pages/AcceptInvite.tsx",
      "src/App.tsx",
      "supabase/functions/accept-invite/index.ts",
      "supabase/migrations/0089_le_lien_suffit.sql",
      "supabase/migrations/0071_invitation_trente_jours.sql",
      "supabase/migrations/0103_budget_arrivees.sql"
    ],
    "verifie_sur": "02a9f37",
    "corps": "## Ce que fait l’appli\n\nLe lien d’invitation suffit : **pas besoin d’avoir déjà un compte**. Tu choisis ton mot de passe, ton compte est créé et tu entres dans le foyer. Aucun mail à attendre.\n\n## Sans compte : comment faire\n\n1. Ouvre le lien. L’écran s’intitule « <prénom> t’invite » (ou « On t’attend dans un foyer » si l’invitant n’a pas de prénom).\n2. « Ton e-mail » est déjà rempli : c’est l’adresse pour laquelle l’invitation a été créée. Tu ne peux pas la modifier.\n3. Dans « Choisis ton mot de passe », tape au moins 8 caractères. « Afficher le mot de passe » sert à vérifier.\n4. Appuie sur « Créer mon compte ».\n5. Tu arrives dans l’appli, puis sur ton profil : prénom, revenu, date d’arrivée. Voir la page « compte-profil ».\n\n## Si tu as déjà un compte\n\n- Sur la page du lien, appuie sur « J’ai déjà un compte », connecte-toi, puis appuie sur « Rejoindre le foyer » (écran « On t’attend »). Cela ne marche que si ton compte n’a pas encore de foyer ; l’adresse de ton compte peut différer de celle de l’invitation.\n- Si l’adresse de l’invitation appartient déjà à quelqu’un qui est dans un foyer, l’appli répond « Cette adresse a déjà un compte Popote. Connecte-toi avec ton mot de passe. » Un lien ne reprend jamais le compte de quelqu’un qui est déjà dans un foyer. Si elle a un compte sans foyer, ce compte prend le mot de passe que tu choisis.\n\n## Les messages possibles\n\n- « Ce lien a expiré » : demande-en un nouveau (un lien vaut 30 jours).\n- « Ce lien a déjà servi » : un lien ne sert qu’une fois. Si c’était toi, appuie sur « Me connecter » avec ton e-mail et ton mot de passe.\n- « Ce lien ne mène nulle part » : il a sans doute été mal recopié.\n- « Ce lien n’a pas pu être lu » : vérifie ta connexion, puis « Recharger ».\n- « Tu es déjà dans un foyer » : tu es connecté(e) avec un compte qui a déjà un foyer. L’écran affiche « Compte ouvert ici : » et l’adresse. Si ce n’est pas toi, « Ce n’est pas moi » te déconnecte de cet appareil seulement.\n\n## La date d’arrivée\n\nEn rejoignant, ta date d’arrivée est posée au **1er du mois suivant**, pas à aujourd’hui. Tu ne participes donc à aucune charge avant.\n\n## Ce que l’appli ne fait pas\n\nJe n’ai pas trouvé de code qui envoie un mail de bienvenue. Les rappels par mail existent, mais chacun les active lui-même (voir « rappels-par-mail »).",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "installation-hors-ligne",
    "titre": "Installer Popote et la hors ligne",
    "ecrans": [],
    "questions": [
      "Comment installer Popote sur mon téléphone ?",
      "Est-ce que ça marche sans réseau ?",
      "L’appli dit « Hors ligne », que faire ?",
      "L’appli dit « Ça ne répond pas », pourquoi ?",
      "Ce que j’ai saisi est-il perdu si le réseau coupe ?"
    ],
    "sources": [
      "vite.config.ts",
      "index.html",
      "src/App.tsx",
      "src/pages/HorsLigne.tsx",
      "src/ui/BandeauDePanne.tsx",
      "src/lib/reseau.ts",
      "src/lib/client-requetes.ts",
      "src/lib/session-perdue.ts",
      "src/lib/budget/ecran.ts",
      ".github/workflows/reveil.yml"
    ],
    "verifie_sur": "02a9f37",
    "corps": "## Installer sur le téléphone\n\nPopote est une appli web qui peut s’installer comme une vraie appli : elle s’appelle « Popote », a son icône, et s’ouvre sans la barre du navigateur. L’installation passe par le menu de ton navigateur (l’ajout à l’écran d’accueil). Je n’ai pas trouvé de bouton « Installer » dans l’appli elle-même.\n\nElle se met à jour toute seule. Après une nouvelle version, il peut falloir l’ouvrir une fois de plus avant de voir la nouveauté.\n\n## Ce qui marche sans réseau\n\nPresque rien. Une fois chargée, l’appli s’ouvre sans réseau : son code, ses icônes et les photos du budget sont gardés sur l’appareil. Mais **toutes les données vivent en ligne** (recettes, courses, stock, budget, foyer). Je n’ai pas trouvé de copie des données sur l’appareil. À l’ouverture sans réseau, tu vois donc :\n\n- **« Hors ligne »** : « Pas de réseau : vérifie ta connexion, puis réessaie. » Le bouton « Réessayer » relit tout. Le retour du réseau relance tout seul.\n- Une photo du frigo, un ticket, une dictée ou une recette inventée demandent aussi le réseau.\n\n## Quand le réseau coupe en cours de route\n\n- Une saisie qui part échoue tout de suite, avec « Pas de réseau : vérifie ta connexion, puis réessaie. » Rien n’est mis en attente : refais le geste une fois le réseau revenu.\n- Si l’appli ne peut plus relire le foyer pendant que tu t’en sers, l’écran reste et un bandeau apparaît en haut : « … Ce que tu as saisi est gardé. » avec « Réessayer ». Tes champs à moitié remplis ne disparaissent pas.\n- Sur le budget, une lecture ratée dit « Je n’ai pas pu lire le budget : tu n’as plus de connexion. »\n\n## « Ça ne répond pas »\n\nL’écran dit « La base ne répond pas : réessaie dans un instant. » Le réseau est là, mais la lecture de ton foyer échoue (la base ne répond pas, ou répond par une erreur). Réessaie plus tard. Une base d’une offre gratuite se met en pause après sept jours sans activité : une requête automatique chaque matin est prévue pour l’éviter, mais je ne sais pas si elle tourne.\n\n## Session expirée ou simple panne ?\n\nUne coupure de réseau n’est pas une session expirée : tu n’es pas déconnecté(e). Quand la session a vraiment disparu, l’appli affiche l’écran de connexion avec « Ta session a expiré : reconnecte-toi. » (voir « compte-connexion »).\n\n## Ce que l’appli ne fait pas\n\nIl n’existe pas aujourd’hui de mode hors ligne qui laisse lire ou saisir sans réseau.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "limites",
    "titre": "Ce que Popote ne fait pas aujourd’hui",
    "ecrans": [],
    "questions": [
      "Popote marche-t-elle sans réseau ?",
      "Peut-on brancher sa banque ?",
      "Peut-on changer son adresse e-mail ?",
      "Peut-on avoir plusieurs foyers ou quitter un foyer ?",
      "Combien de photos ou de dictées par mois ?"
    ],
    "sources": [
      "src/App.tsx",
      "src/pages/Settings.tsx",
      "src/pages/SignIn.tsx",
      "src/pages/Onboarding.tsx",
      "src/pages/Password.tsx",
      "src/lib/client-requetes.ts",
      "src/lib/supabase.ts",
      "src/lib/donnees/convives.ts",
      "src/pages/Accueil.tsx",
      "src/pages/Cuisine.tsx",
      "src/pages/Inventer.tsx",
      "src/pages/AjoutManuel.tsx",
      "src/pages/Dictee.tsx",
      ".github/workflows/reveil.yml",
      "supabase/functions/invite/index.ts",
      "supabase/functions/frigo/index.ts",
      "supabase/functions/ticket/index.ts",
      "supabase/functions/etiquette/index.ts",
      "supabase/functions/charges/index.ts",
      "supabase/functions/revue-charges/index.ts",
      "supabase/functions/inventer/index.ts",
      "supabase/functions/importer/index.ts",
      "supabase/migrations/0070_un_seul_foyer.sql",
      "vite.config.ts"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "Chaque « je n’ai pas trouvé » vient d’une recherche dans les écrans, les fonctions et la base. Cette page ne couvre que le compte, le foyer et l’installation ; la cuisine et le budget ont leurs pages.\n\n## Compte et foyer\n\n- **Je n’ai pas trouvé de mode hors ligne.** Sans réseau, l’appli s’ouvre sans données (« installation-hors-ligne »).\n- **Je n’ai pas trouvé de notification qui s’affiche sur le téléphone.** Une invitation à cuisiner se découvre en ouvrant l’appli ; seuls les rappels par mail, que chacun active lui-même, préviennent hors de l’appli (voir « rappels-par-mail »).\n- **Je n’ai pas trouvé d’envoi d’e-mail pour inviter** : c’est toi qui envoies le lien. Je n’ai pas trouvé non plus d’écran qui liste ou annule une invitation de foyer en attente.\n- **Je n’ai pas trouvé de connexion par Google ou Apple.** On entre avec un e-mail et un mot de passe.\n- **Je n’ai pas trouvé de moyen de changer son adresse e-mail.**\n- **Une personne, un seul foyer.** Je n’ai pas trouvé d’écran pour changer de foyer, en quitter un sans supprimer son compte, ou renommer le foyer. Dès qu’un foyer existe, la création d’un autre est fermée.\n- **Je n’ai pas trouvé de bouton « me déconnecter partout ».** « Me déconnecter » ne vaut que pour l’appareil en main (sauf « Se déconnecter » de « Il te faut une invitation »).\n- **Je n’ai pas trouvé de lien avec une banque** : ni import de relevé, ni synchronisation de compte.\n- **Je n’ai pas trouvé d’export autre que le fichier « mes-donnees.json ».** Ni tableur ni PDF.\n- **Je n’ai pas trouvé de version pour les magasins d’applications** : on installe le site.\n- **Je n’ai pas trouvé de choix de thème ni de langue** : l’appli est en français ; certains écrans de cuisine sont sombres par conception.\n\n## Les plafonds de l’IA\n\nChaque foyer a un nombre d’usages **par mois**, qui repart le 1er. Au-delà, l’appli répond « Quota atteint : … Il repart le 1er. »\n\n- photos du frigo : 30\n- tickets : 30\n- étiquettes : 40\n- dictées de charges : 20\n- relectures des charges : 30\n- recettes inventées : 10 (le reste s’affiche sous la recette)\n- imports de recette : 40\n\nLe plafond en euros des Réglages (« Ce que coûtent les photos ») n’est pas ce qui bloque : je n’ai pas trouvé de code qui l’applique.\n\n## Du côté de l’hébergement\n\nUne base d’une offre gratuite se met en pause après sept jours sans activité ; l’appli répond alors « Ça ne répond pas ». Une requête automatique quotidienne est prévue pour l’éviter ; je ne sais pas si elle tourne.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "rappels-les-sept",
    "titre": "Les sept rappels, leurs heures et « C’est fait »",
    "ecrans": [
      "/rappels"
    ],
    "questions": [
      "À quelle heure arrive le mail pour sortir du congélateur ?",
      "Que veut dire « C’est fait, c’est au frigo » dans le mail ?",
      "Quand reçois-je le rappel pour clôturer le mois ?",
      "Pourquoi je reçois un rappel de facture annuelle ?",
      "Quels sont les rappels par mail ?"
    ],
    "sources": [
      "src/lib/rappels.ts",
      "src/ui/frigo/SortirParLien.tsx",
      "src/pages/Semaine.tsx",
      "supabase/migrations/0126_rappels.sql",
      "supabase/functions/_shared/rappels/mails.ts",
      "supabase/functions/_shared/rappels/texte.ts"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Les sept rappels (heure de Paris)\n\nLe mail part à l’heure dite, à quelques minutes près. Un rappel est dû dès son heure et jusqu’à la fin du jour : un passage manqué se rattrape. Chacun ne part qu’une fois pour son jour, sa semaine ou son mois (voir « rappels-un-seul-mail »).\n\n- **« Sortir du congélateur »** : la veille à 19 h, quand un repas prévu demain porte une barquette du congélateur.\n- **« Une barquette va périmer »** : le matin à 8 h, un seul mail qui liste les barquettes du frigo qui périment avant demain soir (ou ont péri depuis moins de 24 heures) et ne sont prévues dans aucun repas.\n- **« Choisir les repas »** : le dimanche à 18 h, s’il reste des dîners sans repas choisi dans les 7 jours qui viennent.\n- **« Noter les dépenses »** : le dimanche à 20 h, si personne n’a déclaré de dépense depuis 7 jours et que tu as une ligne « Plusieurs dépenses dans le mois ».\n- **« Confirmer les charges »** : le 1er du mois à 9 h, s’il reste des factures (« Une facture chaque mois ») du mois fini à confirmer, tant qu’il n’est pas clôturé.\n- **« Clôturer le mois »** : le dernier jour du mois à 19 h, si le mois n’est pas clôturé. On ne peut le clôturer qu’à partir du lendemain, et seulement si tu y as un revenu.\n- **« Une facture annuelle approche »** : à 9 h, 15 jours avant le mois où ta dernière facture saisie d’une charge annuelle avait été payée, si la facture de l’année n’est pas déjà saisie. Sans facture déjà saisie, il n’y a pas de rappel.\n\n## « C’est fait, c’est au frigo »\n\nDans le mail « Sortir du congélateur », ce bouton ouvre le frigo et demande « Sortir 4 wraps du congélateur ? » (« Sortir 2 barquettes de petit salé aux lentilles du congélateur ? » pour un plat de plusieurs mots) avec « Oui, je les sors » et « Pas maintenant ». Rien ne bouge avant ta réponse. Les barquettes passent au frigo, décongelées, à manger dans les 24 heures. Déjà sorties ou mangées : « Rien à sortir ». « Changer les repas de demain » ouvre « La semaine » ce jour-là.\n\nDans « La semaine », sous un plat congelé, ton rappel activé change le bandeau bleu : « Mail mardi à 19 h : sortir 2 wraps du congélateur pour la nuit au frigo. »\n\nFrigo illisible : « Je n’ai pas pu lire ton frigo », rien n’est sorti, le lien reste valable.",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "rappels-par-mail",
    "titre": "Les rappels par mail",
    "ecrans": [
      "/rappels"
    ],
    "questions": [
      "Comment activer un rappel par mail ?",
      "Léa voit-elle mes rappels ?",
      "Pourquoi je ne reçois pas de mail de rappel ?",
      "Comment tester le mail avant de l’activer ?",
      "Où sont les rappels par mail ?"
    ],
    "sources": [
      "src/pages/Rappels.tsx",
      "src/lib/rappels.ts",
      "src/lib/donnees/rappels.ts",
      "src/pages/Settings.tsx",
      "supabase/migrations/0126_rappels.sql",
      "supabase/functions/rappels/index.ts",
      "supabase/functions/_shared/rappels/mails.ts",
      "supabase/functions/_shared/rappels/service.ts"
    ],
    "verifie_sur": "84225ae",
    "corps": "## Ce que fait l’appli\n\nElle t’envoie des mails de la part de « Popote », à l’adresse avec laquelle tu te connectes, seulement quand il y a quelque chose à faire. Il y a sept rappels. **Tous sont coupés tant que tu ne les actives pas** : rien ne part à qui n’a rien demandé.\n\n## Où les régler\n\n« Réglages », carte « Les rappels par mail », bouton « Régler mes rappels ». L’écran « Les rappels par mail » a une carte par rappel : son moment, une phrase qui dit quand il part, un interrupteur (« Activé » ou « Coupé ») et « M’envoyer un exemple ». L’interrupteur agit tout de suite ; il est grisé le temps que la demande parte, et si elle échoue il revient à l’état d’avant.\n\n## Chacun les siens\n\nTes réglages sont à toi seul. L’autre personne du foyer ne voit pas les tiens, tu ne vois ni ne règles les siens. Léa ne reçoit donc rien tant qu’elle n’a rien activé elle-même.\n\n## Tester\n\n« M’envoyer un exemple » envoie UN mail d’exemple, avec « [Exemple] » devant le sujet, à ton adresse seulement. Il faut que ton adresse soit confirmée, sinon l’écran répond « Confirme d’abord ton adresse e-mail. ». Les données sont inventées ; il ne compte pour rien et n’empêche aucun vrai rappel de partir. Un seul exemple par rappel et par heure : un second, dans la même heure, répond « Tu as déjà demandé cet exemple pendant cette heure ».\n\n## Si rien n’arrive\n\nVérifie que l’interrupteur dit « Activé » et regarde dans les indésirables. Un rappel ne part que s’il y a quelque chose à rappeler. Il n’existe pas aujourd’hui d’historique des envois à l’écran (j’ai cherché).\n\n## Ce que l’appli ne fait pas\n\nPas de notification sur le téléphone : des mails seulement. Les jours et les heures sont fixes, on ne les change pas. Il n’existe pas de rappel pour les courses ni pour la session de cuisine.\n\nLe détail des sept rappels, leurs heures et le lien « C’est fait, c’est au frigo » : voir « rappels-les-sept ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "rappels-un-seul-mail",
    "titre": "Un seul mail par jour, et ce qui ne repart pas",
    "ecrans": [
      "/rappels"
    ],
    "questions": [
      "Pourquoi je n’ai pas reçu de mail pour la barquette que j’ai ajoutée ?",
      "Pourquoi un seul mail pour plusieurs barquettes qui périment ?",
      "Que veut dire « Prévue samedi, mais elle périme mercredi » ?",
      "Pourquoi le mail de clôture parle du revenu de quelqu’un d’autre ?",
      "Pourquoi je n’ai pas reçu un deuxième mail ?"
    ],
    "sources": [
      "supabase/migrations/0126_rappels.sql",
      "supabase/functions/_shared/rappels/mails.ts",
      "supabase/functions/_shared/rappels/texte.ts"
    ],
    "verifie_sur": "8748fad",
    "corps": "## Un mail perdu vaut mieux qu’un doublon\n\nPopote n’envoie jamais deux fois le même mail. Quand un rappel est parti pour un jour, une semaine ou un mois, il ne repart pas, même si la situation change après coup. Un rappel coupé juste avant son heure ne part pas : Popote revérifie l’interrupteur au moment d’envoyer.\n\n## Après le mail de 19 h\n\n« Sortir du congélateur » part une fois, à 19 h, pour le lendemain. Si tu prévois une barquette congelée pour demain APRÈS ce mail, aucun second mail ne part : sors-la toi-même, ou dans le doute décongèle-la au micro-ondes. Même chose pour une barquette posée au frigo après le mail de 8 h : elle attend le lendemain.\n\n## Les barquettes qui périment\n\n« Une barquette va périmer » est UN mail par jour, qui liste tous les plats concernés, du plus pressé au moins pressé. Il compte les barquettes du frigo qui périment avant demain soir et ne sont prévues dans aucun repas, et celles qui ont péri depuis moins de 24 heures : celles-ci sont annoncées « Périmée : à jeter ».\n\nUne barquette prévue pour un repas APRÈS sa péremption compte comme non prévue, et le mail le dit : « Prévue samedi, mais elle périme mercredi ».\n\n## Les factures annuelles\n\nPlusieurs charges annuelles qui tombent le même jour : un seul mail, qui les liste.\n\n## Clôturer le mois\n\nLe mail du dernier jour du mois te prévient que tu pourras clôturer le lendemain. La clôture est refusée tant qu’une autre personne du foyer n’a pas posé son revenu de ce mois : le mail le dit alors (« Léa doit encore poser son revenu de novembre ») au lieu de promettre la clôture.\n\n## Les exemples\n\n« M’envoyer un exemple » est limité à un exemple par rappel et par heure : un second répond « Tu as déjà demandé cet exemple pendant cette heure ».",
    "verifie_le": "2026-10-27"
  },
  {
    "id": "reglages",
    "titre": "Les réglages",
    "ecrans": [
      "/reglages"
    ],
    "questions": [
      "Où sont les réglages ?",
      "À quoi sert « Ce que coûtent les photos » ?",
      "Comment fixer le budget des courses ?",
      "Comment inviter un foyer ami ?",
      "Comment exporter mes données ?",
      "Comment me déconnecter ?",
      "Comment ajouter ou retirer un magasin ?",
      "Où est le sélecteur Objectifs et Réglages ?",
      "Où régler mes rappels par mail ?"
    ],
    "sources": [
      "src/pages/Settings.tsx",
      "src/pages/Accueil.tsx",
      "src/ui/reglages/coque.tsx",
      "src/ui/reglages/cartes.tsx",
      "src/lib/donnees/amis.ts",
      "src/lib/donnees/foyer.ts",
      "supabase/migrations/0001_class_c.sql",
      "supabase/migrations/0014_magasin.sql",
      "supabase/migrations/0024_prix.sql",
      "supabase/migrations/0007_llm_budget.sql",
      "supabase/migrations/0027_ecriture_croisee.sql",
      "supabase/migrations/0035_amis.sql",
      "supabase/migrations/0037_cuisiner_ensemble.sql"
    ],
    "verifie_sur": "9b03c3e",
    "corps": "## Où\n\nAccueil de Popote, « Cuisine » en haut de la carte sombre, puis le rond avec ton initiale : « Réglages ». En haut de l’écran, un sélecteur « Objectifs | Réglages » passe de l’un à l’autre, et « Accueil » (en haut à gauche) ramène à l’accueil de la cuisine. Le budget a ses « Réglages du budget ».\n\n## Les cartes, de haut en bas\n\n- **« Inviter »** : voir « foyer-inviter ».\n- **« Budget des courses »** : le repère du bilan. « Par mois (€) », puis « Enregistrer ». Vide : pas de jauge. Zéro ou moins : « Un budget se compte en euros, au-dessus de zéro. »\n- **« Tes magasins »** (dans la même carte que le budget des courses) : écris le nom puis « Ajouter ». Le premier magasin créé est « par défaut ». « Retirer » demande confirmation : les articles qui portaient ce magasin deviennent « sans magasin », et les prix notés pour lui partent avec. Après une sortie de courses dans ce magasin, il ne peut plus être retiré : « <nom> a déjà servi pour une sortie de courses : il ne peut plus être retiré. »\n- **« Nos aliments »** : « Ouvrir nos aliments » mène à la liste des aliments du foyer, avec leurs vraies valeurs (page « cuisine-nos-aliments »).\n- **« Ce que coûtent les photos »** : un plafond en euros par mois pour lire une photo du frigo ou un ticket, 5 € au départ. Le montant « restants ce mois-ci » s’affiche en grand ; champ « Plafond mensuel (€) », bouton « Enregistrer ». Aucun coût n’est jamais enregistré : les euros restants ne baissent pas, et rien ne bloque au plafond. Seuls les quotas par mois limitent (page « limites »).\n- **« Vos amis »** : d’autres foyers, pour échanger des recettes. « Inviter un foyer » donne un lien valable **7 jours**, à usage unique (« Copier le lien », « Annuler »). « Rompre » met fin à l’amitié des deux côtés, après confirmation. Seules les recettes marquées « partagée » circulent, avec le prénom de qui les a ajoutées ; courses, barquettes, prix et objectifs ne sortent jamais du foyer. Exception : une session de cuisine où tu convies un foyer ami (« donnees-et-vie-privee »).\n- **« Les rappels par mail »** : « Régler mes rappels » ouvre l’écran des rappels (voir « rappels-par-mail »). Chacun règle les siens, et tout est coupé au départ.\n- **Trois lignes dans une même carte** : « Changer mon mot de passe » (ouvre son écran, voir « compte-connexion »), « Exporter mes données » et « Me déconnecter » (sur cet appareil seulement).\n- **« Supprimer mon compte »**, seul, en rouge, tout en bas (voir « donnees-et-vie-privee »).\n\n## Ce que l’appli ne fait pas\n\nAucun réglage pour renommer le foyer, changer l’adresse e-mail, ni choisir la langue ou un thème ; les quotas du mois, le poids d’un dîner (35 %) et les 10 recettes par page sont fixes.",
    "verifie_le": "2026-10-27"
  }
]
