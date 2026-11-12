/**
 * Open Food Facts : un code-barres → les valeurs pour 100 g d'un produit.
 *
 * `https://world.openfoodfacts.org/api/v2/product/<code>.json` rend `nutriments` pour 100 g et, quand l'emballage
 * l'annonce, `serving_quantity` (le poids d'une portion, en grammes). Aucune clé, aucun compte ; la base est
 * collaborative : une valeur peut être fausse ou manquer, d'où « Vérifie-les avant d'enregistrer » à l'écran.
 *
 * La LECTURE de la réponse (`lisLaReponse`) est pure et éprouvée sur une vraie réponse enregistrée
 * (`fixtures/off-skyr-danone.json`) : aucun test n'appelle le réseau. L'appel (`cherche`) n'est qu'un `fetch`.
 */

import { phraseDesVides } from './absents.ts'

/** Un code-barres valide : 8, 12, 13 ou 14 chiffres dont la clé (le dernier chiffre) est juste. */
export function codeBarresValide(code: string): boolean {
  if (!/^\d+$/.test(code) || ![8, 12, 13, 14].includes(code.length)) return false
  const chiffres = [...code].map(Number)
  const cle = chiffres.pop()!
  /* En partant de la droite, les poids alternent 3, 1, 3, 1… (GS1). */
  const somme = chiffres.reverse().reduce((s, c, i) => s + c * (i % 2 === 0 ? 3 : 1), 0)
  return (10 - (somme % 10)) % 10 === cle
}

/**
 * Ce que l'écran reprend d'un produit. Un chiffre qu'Open Food Facts ne donne pas est `null` : l'écran laisse le champ
 * VIDE et le dit (jamais un 0 écrit à sa place). `label` vaut `''` quand le produit n'a pas de nom ; `uniteG` est `null`
 * quand l'emballage n'annonce aucune unité.
 */
export type Produit = {
  label: string
  kcal: number
  protein: number | null
  carb: number | null
  fat: number | null
  fiber: number | null
  uniteG: number | null
}

export type Lecture =
  | { etat: 'ok'; produit: Produit }
  /** Open Food Facts ne connaît pas ce code. */
  | { etat: 'introuvable' }
  /** Il le connaît, mais sans calories : rien d'utile à remplir. */
  | { etat: 'sans_valeurs'; label: string }
  /** Il le connaît, mais ses chiffres ne tiennent pas (900 kcal pour 100 g au plus, 100 g de macros) : une erreur de saisie chez eux. */
  | { etat: 'incoherent'; label: string }

/** Open Food Facts rend des nombres, parfois des chaînes (« 125 »), parfois rien. */
function nombre(x: unknown): number | null {
  if (typeof x === 'number') return Number.isFinite(x) ? x : null
  if (typeof x === 'string' && x.trim() !== '') {
    const n = Number(x.replace(',', '.'))
    return Number.isFinite(n) ? n : null
  }
  return null
}

const KJ_PAR_KCAL = 4.184

const texte = (x: unknown) => (typeof x === 'string' ? x.trim() : '')

/**
 * Le nom du produit, en français d'abord (`product_name_fr`), avec sa première marque quand le nom ne la dit pas :
 * « Skyr » + « Danone » → « Skyr Danone ». Pas de nom : `''` — une marque seule n'est pas un nom.
 */
function nomDuProduit(p: Record<string, unknown>): string {
  const nom = texte(p.product_name_fr) || texte(p.product_name)
  if (nom === '') return ''
  const marque = typeof p.brands === 'string' ? p.brands.split(',')[0].trim() : ''
  const complet = marque && !nom.toLowerCase().includes(marque.toLowerCase()) ? `${nom} ${marque}`.trim() : nom
  return complet.slice(0, 80)
}

/** Lit une réponse d'Open Food Facts (le JSON déjà décodé). Ne lève jamais. */
export function lisLaReponse(reponse: unknown): Lecture {
  const r = (reponse && typeof reponse === 'object' ? reponse : {}) as Record<string, unknown>
  const p = r.product && typeof r.product === 'object' ? r.product as Record<string, unknown> : null
  if (r.status === 0 || !p) return { etat: 'introuvable' }

  const label = nomDuProduit(p)
  const n = (p.nutriments && typeof p.nutriments === 'object' ? p.nutriments : {}) as Record<string, unknown>

  /* Les kcal d'abord ; à défaut les kJ (`energy_100g` est en kJ), convertis. Des kcal à 0 quand les kJ disent autre
     chose sont une case jamais remplie : on les recalcule depuis les kJ (un vrai 0, l'eau, n'a pas de kJ). */
  const kj = nombre(n['energy-kj_100g']) ?? nombre(n['energy_100g'])
  const direct = nombre(n['energy-kcal_100g'])
  const kcal = direct !== null && !(direct === 0 && kj !== null && kj > 0)
    ? direct
    : (kj !== null ? Math.round(kj / KJ_PAR_KCAL) : null)
  if (kcal === null) return { etat: 'sans_valeurs', label }

  /* Une valeur absente reste `null` : le champ de l'écran reste vide, la personne est prévenue. */
  const protein = nombre(n['proteins_100g'])
  const carb = nombre(n['carbohydrates_100g'])
  const fat = nombre(n['fat_100g'])
  const fiber = nombre(n['fiber_100g'])
  const macros = [protein, carb, fat, fiber]
  const bornes = kcal >= 0 && kcal <= 900 && macros.every(v => v === null || (v >= 0 && v <= 100))
    && (protein ?? 0) + (carb ?? 0) + (fat ?? 0) <= 105
  if (!bornes) return { etat: 'incoherent', label }

  return { etat: 'ok', produit: { label, kcal, protein, carb, fat, fiber, uniteG: poidsDeLUnite(p) } }
}

const dansLesBornes = (g: number | null): g is number => g !== null && g >= 1 && g <= 5000

/**
 * Le poids d'UNE unité : la portion annoncée (`serving_quantity`) ; à défaut, le poids net d'un emballage à une seule
 * unité (`quantity` « 140 g » → `product_quantity`), ou l'unité d'un lot (« 4 x 125 g » → 125). Un poids net qui
 * couvre plusieurs unités (« 500 g » pour quatre pots) n'est pas le poids d'une : `null`, la personne le dit.
 */
function poidsDeLUnite(p: Record<string, unknown>): number | null {
  const portion = nombre(p.serving_quantity)
  if (dansLesBornes(portion)) return portion
  const quantite = texte(p.quantity)
  const lot = /(\d+)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*g\b/i.exec(quantite)
  if (lot) {
    const unite = nombre(lot[2])
    return dansLesBornes(unite) ? unite : null
  }
  if (/^\d+(?:[.,]\d+)?\s*g$/i.test(quantite)) {
    const net = nombre(p.product_quantity)
    return dansLesBornes(net) ? net : null
  }
  return null
}

/** Ce que l'écran dit d'un produit trouvé, hors ses valeurs : un doute par phrase, dans l'ordre où l'on vérifie. */
export function notesDuProduit(x: Produit): string[] {
  const notes: string[] = []
  if (x.label === '') notes.push('Open Food Facts n’a pas de nom pour ce produit : donne-lui le tien.')
  if (x.protein === null) notes.push('Open Food Facts n’indique pas les protéines : écris-les d’après l’étiquette.')
  const vides = phraseDesVides('Open Food Facts n’indique pas', [
    ...(x.carb === null ? ['glucides'] : []), ...(x.fat === null ? ['lipides'] : []), ...(x.fiber === null ? ['fibres'] : []),
  ])
  if (vides) notes.push(vides)
  if (x.uniteG === null) notes.push('Open Food Facts n’indique pas le poids d’une unité : dis-le toi-même.')
  return notes
}

export const urlDuProduit = (code: string) =>
  `https://world.openfoodfacts.org/api/v2/product/${code}.json`
  + '?fields=product_name_fr,product_name,brands,quantity,product_quantity,serving_quantity,serving_size,nutriments'

/** Une panne à dire telle quelle : une phrase française, jamais « Failed to fetch ». */
export class ErreurOpenFoodFacts extends Error {}

/**
 * Cherche un code-barres. `lit` est `fetch` — remplacé dans les tests, qui n'appellent jamais le réseau. Délai de
 * 10 s : un `fetch` suspendu ne doit pas laisser « Je cherche… » à l'écran pour toujours.
 */
export async function cherche(code: string, lit: typeof fetch = fetch): Promise<Lecture> {
  if (!codeBarresValide(code)) throw new ErreurOpenFoodFacts('Ce code ne ressemble pas à un code-barres : un chiffre doit être faux.')
  let res: Response
  try {
    res = await lit(urlDuProduit(code), { signal: AbortSignal.timeout(10_000) })
  } catch {
    throw new ErreurOpenFoodFacts('Open Food Facts ne répond pas. Vérifie ta connexion, ou remplis à la main.')
  }
  /* 404 : « inconnu » aussi. Le reste (429, 5xx) est une panne de leur côté. */
  if (res.status === 404) return { etat: 'introuvable' }
  if (!res.ok) throw new ErreurOpenFoodFacts('Open Food Facts est indisponible pour l’instant. Réessaie dans un moment, ou remplis à la main.')
  try {
    return lisLaReponse(await res.json())
  } catch {
    throw new ErreurOpenFoodFacts('Open Food Facts a répondu quelque chose d’illisible. Remplis à la main.')
  }
}
