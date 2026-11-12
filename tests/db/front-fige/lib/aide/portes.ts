/**
 * Les écrans que l'aide peut proposer d'ouvrir. COPIE de `supabase/functions/_shared/portes.ts` (le front ne peut pas
 * importer le dossier des fonctions) : `tests/aide.test.ts` vérifie que les deux listes sont identiques.
 */
export const PORTES = {
  hub:             { chemin: '/',                  bouton: 'Ouvrir l’accueil' },
  budget:          { chemin: '/budget',            bouton: 'Ouvrir le budget' },
  charges:         { chemin: '/charges',           bouton: 'Ouvrir les charges' },
  'budget-reglages': { chemin: '/budget-reglages', bouton: 'Ouvrir les réglages du budget' },
  epargne:         { chemin: '/epargne',           bouton: 'Ouvrir l’épargne' },
  'mois-type':     { chemin: '/mois-type',         bouton: 'Ouvrir le mois type' },
  'toutes-les-charges': { chemin: '/toutes-les-charges', bouton: 'Ouvrir le tableau des charges' },
  inviter:         { chemin: '/reglages#inviter',  bouton: 'Ouvrir « Inviter quelqu’un »' },
  profil:          { chemin: '/profil',            bouton: 'Ouvrir mon profil' },
  motdepasse:      { chemin: '/motdepasse',        bouton: 'Ouvrir le mot de passe' },
  reglages:        { chemin: '/reglages',          bouton: 'Ouvrir les réglages' },
  rappels:         { chemin: '/rappels',           bouton: 'Ouvrir les rappels par mail' },
  objectifs:       { chemin: '/objectifs',         bouton: 'Ouvrir mes objectifs' },
  cuisine:         { chemin: '/cuisine-accueil',   bouton: 'Ouvrir la cuisine' },
  semaine:         { chemin: '/semaine',           bouton: 'Ouvrir la semaine' },
  frigo:           { chemin: '/frigo',             bouton: 'Ouvrir le frigo' },
  bilan:           { chemin: '/bilan',             bouton: 'Ouvrir le bilan' },
  aliments:        { chemin: '/aliments',          bouton: 'Ouvrir nos aliments' },
  choisir:         { chemin: '/choisir',           bouton: 'Ouvrir le choix des recettes' },
  magasin:         { chemin: '/magasin',           bouton: 'Ouvrir le magasin' },
  plan:            { chemin: '/plan',              bouton: 'Ouvrir le plan' },
  importer:        { chemin: '/importer',          bouton: 'Ouvrir l’import d’une recette' },
  inventer:        { chemin: '/inventer',          bouton: 'Ouvrir « Inventer »' },
  photo:           { chemin: '/photo',             bouton: 'Ouvrir la photo du frigo' },
  ticket:          { chemin: '/ticket',            bouton: 'Ouvrir le ticket de caisse' },
} as const

export type PorteId = keyof typeof PORTES

export const IDS_DES_PORTES = Object.keys(PORTES) as PorteId[]
