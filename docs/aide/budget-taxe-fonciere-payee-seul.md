---
id: budget-taxe-fonciere-payee-seul
titre: La taxe foncière payée tout seul
ecrans: [/charges]
questions:
  - J’ai payé la taxe foncière tout seul, si je la pose en charge commune, que se passe-t-il ?
  - Est-ce que l’autre va me rembourser ce que j’ai avancé ?
  - Existe-t-il une notion de « payé par l’un pour le foyer, à rembourser » ?
  - Comment entrer une taxe foncière déjà payée avant d’utiliser Popote ?
  - Les mois d’avant son arrivée sont-ils partagés ?
sources:
  - src/pages/Charges.tsx
  - src/lib/budget/charges.ts
  - src/lib/budget/feuilles.ts
  - src/ui/budget/FeuilleMiseDeCote.tsx
  - src/lib/donnees/budget.ts
  - supabase/migrations/0050_catalogue_charges.sql
  - supabase/migrations/0100_budget_mois_gele.sql
  - supabase/migrations/0102_budget_mois_suivis.sql
  - supabase/migrations/0103_budget_arrivees.sql
  - supabase/migrations/0105_budget_cible.sql
  - supabase/migrations/0106_budget_factures.sql
  - supabase/migrations/0107_budget_solde.sql
  - supabase/migrations/0108_budget_cloture.sql
  - supabase/functions/accept-invite/index.ts
verifie_sur: fa94f4a
---
## Ce que fait l’appli

La taxe foncière du catalogue est annuelle et commune. Posée quand tu es seul, avec « Elle se partagera avec le foyer » cochée, c’est une « Mise de côté » : un douzième par mois (1 200 € : 100 €), une ligne par mois depuis « Elle court depuis » (jamais avant ton arrivée), à 100 % sur toi.

« Payée depuis » n’est qu’un renseignement : l’appli ignore que tu l’as déjà payée et ne débite aucun compte.

## L’année en cours, déjà payée

- **Payée un mois que Popote suivait** (depuis le premier mois avec un revenu) : touche la ligne « mis de côté chaque mois », « Autre jour », « Ajouter la facture ». L’appli ne pose que l’écart avec le prévu de l’année, sur le mois où tu saisis : ligne « Taxe foncière — facture 2026 ». Facture de 1 320 € pour 1 200 € prévus : 120 €. Facture plus basse : rien.
- **Payée avant le premier mois suivi** : facture refusée (« Popote ne suivait pas encore septembre 2026 : cette facture n'y compte pas. »). Les mises de côté courent jusqu’en décembre ; sans facture, la clôture de décembre (dès le 1er janvier) solde l’année et te les rend, en ligne négative « Taxe foncière — solde 2026 ». Pour 2026 tu récupères tout ; dès janvier 2027, tu mets de côté pour la facture de 2027.

## Quand l’autre arrive

Elle entre dans la charge (par défaut le 1er du mois suivant son acceptation). Dès son mois d’arrivée, les lignes ouvertes se partagent selon la règle du foyer. Les mois d’avant restent à toi.

Exemple : 1 200 € par an, suivi depuis janvier, arrivée le 1er novembre, « Moitié-moitié ». Janvier à octobre : 1 000 € à toi ; novembre et décembre : 50 € chacun. Facture de 1 320 € saisie en décembre : l’écart de 120 € se répartit selon ce que chacun a porté (1 100 € et 100 €), soit 110 € et 10 €. Saisie avant son arrivée, la facture est à toi seul.

## Payé par l’un, à rembourser

Il n’existe pas aujourd’hui de notion « payé par l’un, à rembourser par l’autre » : la feuille de facture ne demande que le montant et la date, et aucun écran n’affiche de somme que l’autre te doit, ni de virement. L’autre paie sa part des lignes de ses mois dans le foyer et sa part de l’écart, pas ce que tu as avancé avant son arrivée.

Décoche « Elle se partagera avec le foyer » pour la garder à toi.
