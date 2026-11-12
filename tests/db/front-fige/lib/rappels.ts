/**
 * Les rappels par mail, côté écran : le catalogue (nom, moment, phrase), les barquettes que « C'est fait » désigne
 * et la phrase de la confirmation. Pur : aucune requête.
 *
 * Les sept types et leurs moments sont ceux de la base (`rappels_a_envoyer`, 0126) et des mails
 * (`supabase/functions/_shared/rappels/`). `tests/rappels-mails.test.ts` vérifie que la liste est la même.
 */
import { groupeLesParts, partsDuPlat } from './frigo.ts'
import type { Groupe, Part } from './frigo.ts'

export const TYPES_DE_RAPPEL = [
  'sortir_du_congelateur', 'barquette_perime', 'choisir_les_repas', 'noter_les_depenses',
  'confirmer_les_charges', 'cloturer_le_mois', 'facture_annuelle',
] as const
export type TypeDeRappel = (typeof TYPES_DE_RAPPEL)[number]

export type Famille = 'bleu' | 'encre' | 'herbe' | 'sable'

export type RappelDecrit = {
  type: TypeDeRappel
  groupe: 'Cuisine' | 'Budget'
  /** Le nom du rappel, tel que le mail le dit dans son pied. */
  nom: string
  /** Le moment, en trois mots : « La veille à 19 h ». */
  moment: string
  /** Une phrase qui dit QUAND il part, et pourquoi. */
  quand: string
  /** La couleur de son héros dans le mail. */
  famille: Famille
}

export const RAPPELS: RappelDecrit[] = [
  {
    type: 'sortir_du_congelateur', groupe: 'Cuisine', nom: 'Sortir du congélateur', famille: 'bleu',
    moment: 'La veille à 19 h',
    quand: 'Part la veille au soir quand un repas prévu demain porte une barquette du congélateur. « C’est fait » les passe au frigo.',
  },
  {
    type: 'barquette_perime', groupe: 'Cuisine', nom: 'Une barquette va périmer', famille: 'encre',
    moment: 'Le matin à 8 h',
    quand: 'Part le matin si une barquette du frigo périme avant demain soir et n’est prévue dans aucun repas.',
  },
  {
    type: 'choisir_les_repas', groupe: 'Cuisine', nom: 'Choisir les repas', famille: 'herbe',
    moment: 'Le dimanche à 18 h',
    quand: 'Part le dimanche soir s’il reste des dîners sans repas choisi dans les 7 jours qui viennent.',
  },
  {
    type: 'noter_les_depenses', groupe: 'Budget', nom: 'Noter les dépenses', famille: 'sable',
    moment: 'Le dimanche à 20 h',
    quand: 'Part le dimanche soir si aucune dépense n’a été déclarée depuis 7 jours.',
  },
  {
    type: 'confirmer_les_charges', groupe: 'Budget', nom: 'Confirmer les charges', famille: 'sable',
    moment: 'Le 1er du mois à 9 h',
    quand: 'Part le 1er du mois s’il reste des factures du mois fini à confirmer.',
  },
  {
    type: 'cloturer_le_mois', groupe: 'Budget', nom: 'Clôturer le mois', famille: 'sable',
    moment: 'Le dernier jour à 19 h',
    quand: 'Part le dernier jour du mois si le mois n’est pas clôturé : on peut le clôturer dès le lendemain.',
  },
  {
    type: 'facture_annuelle', groupe: 'Budget', nom: 'Une facture annuelle approche', famille: 'sable',
    moment: '15 jours avant, à 9 h',
    quand: 'Part 15 jours avant le mois où se paie une charge annuelle, d’après sa dernière facture saisie.',
  },
]

/**
 * Le temps que l'écran attend « M'envoyer un exemple » : AU MOINS celui que la fonction se donne
 * (`DELAI_ESSAI_MS`, supabase/functions/_shared/rappels/service.ts) — sinon l'écran dirait « pas de réseau » d'un mail
 * qui part. `tests/rappels-service.test.ts` garde l'inégalité.
 */
export const DELAI_ESSAI_CLIENT_MS = 30_000

export const estUnType = (t: unknown): t is TypeDeRappel =>
  typeof t === 'string' && (TYPES_DE_RAPPEL as readonly string[]).includes(t)

// ── « C'est fait » : /frigo?sortir=<ids> ────────────────────────────────────

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
/** Au plus : un lien plus long n'est pas celui d'un mail de Popote. */
export const MAXIMUM_SORTIES = 40

/**
 * Les identifiants du lien « C'est fait » : `?sortir=a,b,c`. Tout ce qui n'est pas un identifiant est écarté, les
 * doublons aussi ; `null` quand le lien n'en porte pas (l'écran ne demande alors rien).
 */
export function lisLesSorties(recherche: string): string[] | null {
  const brut = new URLSearchParams(recherche).get('sortir')
  if (brut === null) return null
  const ids = [...new Set(brut.split(',').map(x => x.trim().toLowerCase()).filter(x => UUID.test(x)))]
  return ids.slice(0, MAXIMUM_SORTIES)
}

export type Sortie<P extends Part> = {
  /** Les barquettes qui sont bien au congélateur, du foyer, et encore là : ce qu'on peut sortir. */
  asortir: P[]
  /** Combien d'identifiants du lien ne désignent rien de sortable (inconnus, déjà sortis, d'un autre foyer). */
  ignores: number
}

/**
 * Parmi les barquettes que le lien désigne, celles qu'on peut vraiment sortir. `barquettes` est ce que la base montre
 * à CE foyer (la RLS cache les autres) : un identifiant inconnu, d'un autre foyer, mangé, jeté ou déjà au frigo n'y
 * est pas, ou n'est pas au congélateur — il est ignoré, sans message d'erreur.
 */
export function sortablesDuLien<P extends Part>(ids: string[], barquettes: P[]): Sortie<P> {
  const voulus = new Set(ids)
  const asortir = barquettes.filter(p =>
    voulus.has(p.id.toLowerCase()) && p.location === 'congelateur' && p.state === 'au_frais')
  return { asortir, ignores: ids.length - asortir.length }
}

/** « 4 wraps », « 1 wrap » : combien, de quoi, pour un groupe de barquettes. */
const quoi = (g: Groupe, n: number) => partsDuPlat(g.label, n)

/** « Sortir 4 wraps du congélateur ? » ; plusieurs plats : « Sortir 6 barquettes du congélateur ? ». */
export function questionDeSortie(parts: Part[]): string {
  const groupes = groupeLesParts(parts)
  if (groupes.length === 1) return `Sortir ${quoi(groupes[0], parts.length)} du congélateur\u00a0?`
  return `Sortir ${parts.length} barquettes du congélateur\u00a0?`
}

/** Le détail quand il y a plusieurs plats : « 4 wraps, 2 lasagnes ». */
export function detailDeSortie(parts: Part[]): string {
  return groupeLesParts(parts).map(g => quoi(g, g.parts.length)).join(', ')
}

/** Ce qui est dit une fois sorties : « 4 wraps sont au frigo, à manger dans les 24 heures. » */
export function phraseDApresSortie(parts: Part[]): string {
  const groupes = groupeLesParts(parts)
  const quoiDit = groupes.length === 1 ? quoi(groupes[0], parts.length) : `${parts.length} barquettes`
  return `${quoiDit} ${parts.length > 1 ? 'sont' : 'est'} au frigo, à manger dans les 24 heures.`
}
