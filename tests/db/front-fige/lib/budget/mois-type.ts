/**
 * Le mois type : vos charges, ramenées au mois, et ce que chacun en paie.
 *
 * Ce n'est pas l'écran du mois. Le mois vit de LIGNES que la base fait naître et fige (§ 4.1) ; le mois type
 * se calcule sur les CHARGES telles qu'elles sont posées, pour un mois donné — y compris celui qui n'a pas
 * encore commencé (Kamil et Thauba ont tout posé en octobre pour un budget qui part en novembre, et l'écran ne
 * leur disait que « Pas encore »).
 *
 * Le partage est celui de la base : les parts du foyer viennent de `parts_du_foyer` (prorata des revenus,
 * moitié-moitié si un revenu manque, rien pour qui n'est pas encore là), et chaque charge partage entre SES
 * participants, au poids de leurs parts — comme `0112` le fait pour une ligne du mois.
 *
 * Ramener au mois : un trimestre compte un tiers, une année un douzième. C'est ce qu'une « Mise de côté » met
 * de côté ; pour une facture annuelle, c'est ce qu'il faudrait mettre de côté.
 */
import { CATEGORIES, infoCategorie, type Categorie, type Mode } from './categories.ts'
import { pourquoiElleNeComptePas } from './charges.ts'
import { revenuDuMois, type Revenu } from './mois.ts'

export type Periodicite = 'mensuel' | 'trimestriel' | 'annuel'

export type ChargeDuMoisType = {
  id: string; libelle: string; montant_cents: number; periodicite: Periodicite; mode: Mode
  categorie: Categorie | string; commun: boolean; cle: 'prorata' | 'moitie' | null; debut: string
  archive_le: string | null; participants: string[]
}

/** Les parts (en points de base) que la base donne à chacun, pour la clé du foyer et pour chaque clé. */
export type PartsParCle = Record<'foyer' | 'prorata' | 'moitie', Record<string, number>>

export type LigneType = {
  id: string; libelle: string; categorie: Categorie; periodicite: Periodicite; mode: Mode; commun: boolean
  montant_cents: number
  /** Ce que la charge pèse par mois, en centimes. */
  mensuel: number
  /** Ce que chacun en paie par mois, en centimes ; la somme vaut `mensuel`. */
  parts: Record<string, number>
  /** Elle ne compte pas ce mois-ci, et se montre grisée : elle commence plus tard (`debut`), ou aucun de ses
      participants n'est encore dans le foyer (`arrivee`) — la base ne lui crée alors aucune ligne (0098). */
  plusTard: boolean
  pourquoi: 'debut' | 'arrivee' | null
}

export type CategorieType = {
  cle: Categorie; nom: string; couleur: string; total: number
  parPersonne: Record<string, number>; lignes: LigneType[]
}

export type PersonneType = {
  id: string; commun: number; perso: number; total: number; revenu: number | null; reste: number | null
}

export type MoisType = { lignes: LigneType[]; categories: CategorieType[]; personnes: PersonneType[]; total: number }

const DIVISEUR: Record<Periodicite, number> = { mensuel: 1, trimestriel: 3, annuel: 12 }

/**
 * `cents` réparti selon des poids, au centime, sans en perdre un : chacun reçoit sa part arrondie vers le bas,
 * puis les centimes qui restent vont aux plus grands restes. Des poids tous nuls partagent à parts égales.
 */
function repartis(cents: number, poids: [string, number][]): Record<string, number> {
  const total = poids.reduce((t, [, p]) => t + p, 0)
  const justes = total > 0 ? poids : poids.map(([q]) => [q, 1] as [string, number])
  const somme = justes.reduce((t, [, p]) => t + p, 0)
  const bruts = justes.map(([q, p]) => ({ q, exact: (cents * p) / somme }))
  const parts = Object.fromEntries(bruts.map(b => [b.q, Math.floor(b.exact)]))
  let reste = cents - Object.values(parts).reduce((t, c) => t + c, 0)
  for (const b of [...bruts].sort((a, z) => (z.exact % 1) - (a.exact % 1))) {
    if (reste <= 0) break
    parts[b.q] += 1
    reste -= 1
  }
  return parts
}

export function moisType(o: {
  charges: ChargeDuMoisType[]; parts: PartsParCle; membres: string[]; revenus: Revenu[]; mois: string
}): MoisType {
  const lignes: LigneType[] = o.charges
    .filter(c => c.archive_le === null)
    .map(c => {
      const mensuel = Math.round(c.montant_cents / DIVISEUR[c.periodicite])
      const cle = o.parts[c.cle ?? 'foyer']
      /* `parts_du_foyer` ne rend que ceux qui sont là ce mois-là : qui n'y est pas n'a pas de part. */
      const presents = c.participants.filter(q => q in o.parts.foyer)
      const pourquoi = pourquoiElleNeComptePas(c, o.mois, new Set(Object.keys(o.parts.foyer)))
      const parts = presents.length === 0 ? {} : repartis(mensuel, presents.map(q => [q, cle[q] ?? 0]))
      return {
        id: c.id, libelle: c.libelle, categorie: infoCategorie(c.categorie).cle, periodicite: c.periodicite,
        mode: c.mode, commun: c.commun, montant_cents: c.montant_cents, mensuel,
        /* Chaque membre a sa case, même à zéro : le tableau a une colonne par personne. */
        parts: { ...Object.fromEntries(o.membres.map(q => [q, 0])), ...parts },
        plusTard: pourquoi !== null, pourquoi,
      }
    })

  const comptees = lignes.filter(l => !l.plusTard)
  const somme = (ls: LigneType[], qui?: string) =>
    ls.filter(l => !l.plusTard).reduce((t, l) => t + (qui === undefined ? l.mensuel : l.parts[qui] ?? 0), 0)

  const categories = CATEGORIES
    .map(c => {
      const ls = lignes.filter(l => l.categorie === c.cle).sort((a, z) => z.mensuel - a.mensuel)
      return {
        cle: c.cle, nom: c.nom, couleur: c.clair, total: somme(ls),
        parPersonne: Object.fromEntries(o.membres.map(q => [q, somme(ls, q)])), lignes: ls,
      }
    })
    .filter(c => c.lignes.length > 0)
    /* Stable : à poids égal, l'ordre de `CATEGORIES` (D74). */
    .sort((a, z) => z.total - a.total)

  const personnes = o.membres.map(id => {
    const commun = comptees.filter(l => l.commun).reduce((t, l) => t + (l.parts[id] ?? 0), 0)
    const perso = comptees.filter(l => !l.commun).reduce((t, l) => t + (l.parts[id] ?? 0), 0)
    const revenu = revenuDuMois(o.revenus, id, o.mois)
    return { id, commun, perso, total: commun + perso, revenu, reste: revenu === null ? null : revenu - commun - perso }
  })

  return { lignes, categories, personnes, total: somme(lignes) }
}

/**
 * Comment le commun se partage, dit comme la base le fera (`parts_du_mois`, 0102) : un revenu manquant chez
 * quelqu'un qui est là fait tout passer à parts égales, quelle que soit la règle.
 */
export function phraseDuPartage(o: { regle: 'prorata' | 'moitie'; revenuManque: boolean }): string {
  if (o.revenuManque) return 'Le commun se partage à parts égales tant qu’un revenu manque.'
  return o.regle === 'moitie'
    ? 'Le commun se partage moitié-moitié, sauf une charge réglée « Au prorata ».'
    : 'Le commun se partage au prorata des revenus, sauf une charge réglée « Moitié-moitié ».'
}

/* ── Le tableau de toutes les charges, et ses filtres ─────────────────────── */

export type FiltreDuTableau = {
  /** `tout`, `commun`, ou l'id d'une personne : tout ce dont elle paie une part. */
  qui: string
  categorie: Categorie | 'toutes'
  rythme: Periodicite | 'tous'
  facon: Mode | 'toutes'
  cherche: string
}

export const sansFiltre = (): FiltreDuTableau =>
  ({ qui: 'tout', categorie: 'toutes', rythme: 'tous', facon: 'toutes', cherche: '' })

export function estSansFiltre(f: FiltreDuTableau): boolean {
  return f.qui === 'tout' && f.categorie === 'toutes' && f.rythme === 'tous' && f.facon === 'toutes'
    && f.cherche.trim() === ''
}

const lisible = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim()

export function filtreLesLignes(lignes: LigneType[], f: FiltreDuTableau): LigneType[] {
  const cherche = lisible(f.cherche)
  return lignes.filter(l =>
    (f.qui === 'tout' || (f.qui === 'commun' ? l.commun : (l.parts[f.qui] ?? 0) > 0))
    && (f.categorie === 'toutes' || l.categorie === f.categorie)
    && (f.rythme === 'tous' || l.periodicite === f.rythme)
    && (f.facon === 'toutes' || l.mode === f.facon)
    && (cherche === '' || lisible(l.libelle).includes(cherche)))
}

/** Les totaux d'un ensemble de lignes : ce qui commence plus tard ne compte pas. */
export function totauxDe(lignes: LigneType[], membres: string[]): { total: number; parPersonne: Record<string, number> } {
  const comptees = lignes.filter(l => !l.plusTard)
  return {
    total: comptees.reduce((t, l) => t + l.mensuel, 0),
    parPersonne: Object.fromEntries(membres.map(q => [q, comptees.reduce((t, l) => t + (l.parts[q] ?? 0), 0)])),
  }
}
