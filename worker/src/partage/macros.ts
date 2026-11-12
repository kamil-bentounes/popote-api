/**
 * Les macros d'une recette, avec leur incertitude (D18).
 *
 * 16 % des lignes d'ingrédients relevées n'ont AUCUNE quantité (« sel »,
 * « un filet d'huile », « quelques brins de persil »). Afficher « 512 kcal »
 * dans ces conditions est un mensonge poli. On affiche une fourchette, et on
 * refuse de répondre quand trop de lignes manquent.
 *
 * C'est aussi ce qui distingue une recette pesée d'une recette inventée : la
 * seconde n'a que des fourchettes, et l'écran le dit.
 */

export type Macros = {
  kcal: number
  proteinG: number
  fiberG: number
  carbG: number
  fatG: number
}

/** Valeurs pour 100 g, telles que CIQUAL les donne. */
export type Pour100 = Macros

export type LigneIngredient = {
  /** Grammes résolus. `null` quand la ligne ne porte pas de quantité. */
  grammes: number | null
  /** Repli du référentiel (`typical_quantity`), quand il en existe un. */
  grammesTypiques: number | null
  /** `null` quand l'ingrédient n'a pas été rattaché à un aliment. */
  pour100: Pour100 | null
}

export type Agregat = {
  /** La valeur centrale, pour le plat entier. */
  valeur: Macros
  /** La demi-largeur de la fourchette. Zéro quand tout est pesé. */
  marge: Macros
  /**
   * Part des lignes d'ingrédients réellement prises en compte, de 0 à 1.
   * En dessous de `COUVERTURE_MINIMALE`, la valeur ne veut rien dire.
   */
  couverture: number
  /** Nombre de lignes dont la quantité a été devinée. */
  devinees: number
}

/**
 * Une quantité typique est une médiane de référentiel, pas une mesure : on lui
 * accorde la moitié de sa valeur en incertitude. « Un filet d'huile » entre
 * 5 et 15 g, c'est à peu près ce que fait tout le monde.
 */
const INCERTITUDE_TYPIQUE = 0.5

/**
 * En dessous, on n'affiche pas de chiffre du tout. Mieux vaut « on ne sait pas »
 * qu'un total qui ignore la moitié de la recette.
 */
export const COUVERTURE_MINIMALE = 0.75

const ZERO: Macros = { kcal: 0, proteinG: 0, fiberG: 0, carbG: 0, fatG: 0 }

function ajoute(a: Macros, b: Pour100, grammes: number): Macros {
  const r = grammes / 100
  return {
    kcal: a.kcal + b.kcal * r,
    proteinG: a.proteinG + b.proteinG * r,
    fiberG: a.fiberG + b.fiberG * r,
    carbG: a.carbG + b.carbG * r,
    fatG: a.fatG + b.fatG * r,
  }
}

function arrondi(m: Macros): Macros {
  return {
    kcal: Math.round(m.kcal),
    proteinG: Math.round(m.proteinG * 10) / 10,
    fiberG: Math.round(m.fiberG * 10) / 10,
    carbG: Math.round(m.carbG * 10) / 10,
    fatG: Math.round(m.fatG * 10) / 10,
  }
}

export function agrege(lignes: LigneIngredient[]): Agregat {
  let valeur = ZERO
  let marge = ZERO
  let comptees = 0
  let devinees = 0

  for (const l of lignes) {
    if (!l.pour100) continue                       // aliment non rattaché : perdu
    const grammes = l.grammes ?? l.grammesTypiques
    if (grammes === null || grammes <= 0) continue // quantité introuvable : perdue

    comptees++
    valeur = ajoute(valeur, l.pour100, grammes)
    if (l.grammes === null) {
      devinees++
      marge = ajoute(marge, l.pour100, grammes * INCERTITUDE_TYPIQUE)
    }
  }

  return {
    valeur: arrondi(valeur),
    marge: arrondi(marge),
    couverture: lignes.length > 0 ? comptees / lignes.length : 0,
    devinees,
  }
}

/** Ramène l'agrégat du plat entier à une part de `grammes`. */
export function parPart(a: Agregat, grammesPlat: number, grammesPart: number): Agregat {
  if (grammesPlat <= 0) return { ...a, valeur: ZERO, marge: ZERO }
  const r = grammesPart / grammesPlat
  const mise = (m: Macros): Macros => ({
    kcal: m.kcal * r,
    proteinG: m.proteinG * r,
    fiberG: m.fiberG * r,
    carbG: m.carbG * r,
    fatG: m.fatG * r,
  })
  return { ...a, valeur: arrondi(mise(a.valeur)), marge: arrondi(mise(a.marge)) }
}

/**
 * Comment l'écran doit écrire un chiffre incertain. Jamais « 512 kcal » quand
 * on ne le sait pas : « 480 à 545 kcal », ou rien.
 */
export function ecrit(valeur: number, marge: number, unite = ''): string {
  const suffixe = unite ? ` ${unite}` : ''
  if (marge < 1) return `${Math.round(valeur)}${suffixe}`
  const bas = Math.round(valeur - marge)
  const haut = Math.round(valeur + marge)
  if (bas === haut) return `${bas}${suffixe}`
  return `${bas}–${haut}${suffixe}`
}

/**
 * Les nutriments CIQUAL tels que la base les stocke, ramenés à ce dont on a
 * besoin. Deux pièges, tous deux vus dans les données réelles :
 *
 *   · `energie_kcal` manque sur une partie des aliments. On la reconstitue alors
 *     par Atwater (4/4/9, plus 2 pour les fibres), ce qui est l'approximation
 *     réglementaire — pas une invention, mais pas une mesure non plus.
 *   · toutes les valeurs peuvent être nulles. Un aliment sans protéines connues
 *     n'a pas zéro protéine : il ne compte simplement pas dans l'agrégat, et la
 *     couverture le dit.
 */
export function pour100De(nutriments: unknown): Pour100 | null {
  if (!nutriments || typeof nutriments !== 'object') return null
  const n = nutriments as Record<string, unknown>
  const lire = (cle: string): number | null => {
    const v = n[cle]
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }

  const proteinG = lire('proteines_g')
  const carbG = lire('glucides_g')
  const fatG = lire('lipides_g')
  const fiberG = lire('fibres_g')
  if (proteinG === null && carbG === null && fatG === null) return null

  const kcal = lire('energie_kcal')
    ?? 4 * (proteinG ?? 0) + 4 * (carbG ?? 0) + 9 * (fatG ?? 0) + 2 * (fiberG ?? 0)

  return {
    kcal,
    proteinG: proteinG ?? 0,
    carbG: carbG ?? 0,
    fatG: fatG ?? 0,
    fiberG: fiberG ?? 0,
  }
}

/** Peut-on montrer ce chiffre ? Une seule règle, appliquée partout. */
export function affichable(a: Agregat): boolean {
  return a.couverture >= COUVERTURE_MINIMALE
}

/**
 * Une part qui ne peut pas exister (R7).
 *
 * Les bornes visent les ERREURS — un nombre de parts mal lu, un poids faux —, pas
 * les petites parts : une truffe protéinée de 20 g est une vraie part.
 *
 *  · plus de 900 kcal pour 100 g : plus gras que l'huile ;
 *  · plus de 1,5 kg : c'est le plat entier, pas une part ;
 *  · moins de 20 ou plus de 2 000 kcal : un verre d'eau, ou une journée entière.
 *
 * Hors de ces bornes, on ne garde PAS de macros : une valeur fausse sert à
 * filtrer, et elle est pire qu'aucune (D18).
 */
export const PART_PLAUSIBLE = {
  kcalMin: 20, kcalMax: 2000, grammesMax: 1500, densiteMax: 900,
} as const

export function plausible(n: { grams: number; kcal: number }): boolean {
  const g = Number(n.grams)
  const k = Number(n.kcal)
  if (!(g > 0) || !Number.isFinite(k)) return false
  if (k < PART_PLAUSIBLE.kcalMin || k > PART_PLAUSIBLE.kcalMax) return false
  if (g > PART_PLAUSIBLE.grammesMax) return false
  // Tolérance relative : le produit en flottants dépasse d'un cheveu une part exactement à la borne.
  return k * 100 <= PART_PLAUSIBLE.densiteMax * g * (1 + 1e-9)
}
