/**
 * Les huit catégories du budget (D74), leurs couleurs (§ 6.1), et ce qu'un
 * article du catalogue en dit.
 *
 * L'ordre du tableau EST l'ordre de repli quand deux catégories pèsent autant.
 * La couleur n'est jamais seule : la légende et les cartes portent le nom.
 */
export type Categorie = 'vie_courante' | 'maison' | 'credits' | 'auto' | 'abonnements'
  | 'sante' | 'impots' | 'autre'
export type Mode = 'fixe' | 'facture' | 'au_fil' | 'mis_de_cote'

export const CATEGORIES: readonly { cle: Categorie; nom: string; clair: string; sombre: string }[] = [
  { cle: 'vie_courante', nom: 'Vie courante', clair: '#E8A33D', sombre: '#E8A33D' },
  { cle: 'maison',       nom: 'Maison',       clair: '#2F5D45', sombre: '#86C29F' },
  { cle: 'credits',      nom: 'Crédits',      clair: '#7A68C9', sombre: '#B9ADF2' },
  { cle: 'auto',         nom: 'Auto',         clair: '#3B82C4', sombre: '#86BFEF' },
  { cle: 'abonnements',  nom: 'Abonnements',  clair: '#D9694A', sombre: '#F2A88D' },
  { cle: 'sante',        nom: 'Santé',        clair: '#B5527A', sombre: '#E59BB8' },
  { cle: 'impots',       nom: 'Impôts',       clair: '#8B7355', sombre: '#C9B48F' },
  { cle: 'autre',        nom: 'Autre',        clair: '#7D8A93', sombre: '#B4BEC5' },
]

export function infoCategorie(cle: string) {
  return CATEGORIES.find(c => c.cle === cle) ?? CATEGORIES[CATEGORIES.length - 1]
}

export function rangDeCategorie(cle: string): number {
  return CATEGORIES.findIndex(c => c.cle === infoCategorie(cle).cle)
}

const PAR_SECTION: Record<string, Categorie> = {
  'Logement': 'maison', 'Vie courante': 'vie_courante', 'Auto': 'auto',
  'Crédits': 'credits', 'Abonnements': 'abonnements', 'Santé': 'sante', 'Impôts': 'impots',
}

/** La catégorie d'un article : sa section — sauf la résidence, qui est la maison, le toit
    qu'on paie. La base dit la même chose (`categorie_de_l_article`, 0096). */
export function categorieDeLArticle(a: { section: string; libelle: string }): Categorie {
  if (a.libelle === 'Crédit immobilier — résidence') return 'maison'
  return PAR_SECTION[a.section] ?? 'autre'
}

/** La façon d'un article (§ 3.7) : un article qui se plafonne se dépense au fil du mois ;
    Électricité et Gaz sont des factures du mois ; ce qui n'est pas mensuel se met de
    côté ; le reste est fixe. */
export function modeDeLArticle(a: { periode: string; plafond_ordre: number | null; libelle: string }): Mode {
  if (a.periode !== 'mensuel') return 'mis_de_cote'
  if (a.plafond_ordre !== null && a.plafond_ordre !== undefined) return 'au_fil'
  if (a.libelle === 'Électricité' || a.libelle === 'Gaz') return 'facture'
  return 'fixe'
}

/** Ce que « Mes charges » dit de chaque façon (§ 3.7). */
export const NOM_DU_MODE: Record<Mode, string> = {
  fixe: 'Fixe', facture: 'Une facture chaque mois',
  au_fil: 'Plusieurs dépenses dans le mois', mis_de_cote: 'Mise de côté',
}
