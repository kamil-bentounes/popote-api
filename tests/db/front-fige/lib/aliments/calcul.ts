/**
 * Ce que vaut une unité d'un aliment à soi (« un pot »), et ce qu'on en écrit.
 *
 * Une étiquette donne des valeurs POUR 100 G ; on mange un pot de 125 g. Une unité = valeurs × poids / 100. Pur, sans
 * base : la feuille de choix de la semaine, « en plus » et l'écran des aliments disent TOUS le même chiffre, parce
 * qu'ils passent tous par ici.
 *
 * Les arrondis sont ceux d'une étiquette : les calories à l'unité, les grammes au dixième. 76 kcal × 125 g → 95, 10 g
 * de protéines → 12,5 — et pas 12,500000000000002.
 */

/** Les valeurs d'un aliment pour 100 g. */
export type Pour100g = { kcal: number; protein: number; carb: number; fat: number; fiber: number }

/** Les valeurs d'UNE unité : ce qui s'écrit dans le repas. */
export type ValeursDeLUnite = Pour100g

const arrondi = (n: number, decimales: number) => {
  const k = 10 ** decimales
  return Math.round(n * k + (n < 0 ? -1e-9 : 1e-9)) / k
}

/** Les valeurs pour 100 g, ramenées à `grammes`. */
export function pourUneUnite(v: Pour100g, grammes: number): ValeursDeLUnite {
  const f = grammes / 100
  return {
    kcal: arrondi(v.kcal * f, 0),
    protein: arrondi(v.protein * f, 1),
    carb: arrondi(v.carb * f, 1),
    fat: arrondi(v.fat * f, 1),
    fiber: arrondi(v.fiber * f, 1),
  }
}

/** Ce que la base range d'un aliment (colonnes de `aliment`). */
export type AlimentLu = {
  id?: string
  label: string
  kcal_100g: number | string
  protein_100g: number | string
  carb_100g: number | string
  fat_100g: number | string
  fiber_100g: number | string
  unite: string
  unite_g: number | string
}

export function valeursDeLUnite(a: AlimentLu): ValeursDeLUnite {
  return pourUneUnite({
    kcal: Number(a.kcal_100g), protein: Number(a.protein_100g), carb: Number(a.carb_100g),
    fat: Number(a.fat_100g), fiber: Number(a.fiber_100g),
  }, Number(a.unite_g))
}

/**
 * Le geste « un pot » : ce qu'on écrit dans le repas (`choisir_un_repas`, type `repere`), avec les VRAIES valeurs de
 * l'aliment. Une COPIE : corriger l'aliment demain ne réécrit pas le bilan d'hier.
 */
export function choixDeLUnite(a: AlimentLu) {
  const v = valeursDeLUnite(a)
  return {
    type: 'repere' as const, label: a.label, grams: Number(a.unite_g),
    kcal: v.kcal, protein_g: v.protein, carb_g: v.carb, fat_g: v.fat, fiber_g: v.fiber,
  }
}

/** Le même geste pour « en plus » (`useAjouteExtra`). */
export function extraDeLUnite(a: AlimentLu) {
  const v = valeursDeLUnite(a)
  return {
    label: a.label, grammes: Number(a.unite_g),
    kcal: v.kcal, proteinG: v.protein, carbG: v.carb, fatG: v.fat, fiberG: v.fiber,
  }
}

/** Un nombre à la française : « 12,5 », « 95 », « 1 250 ». */
export function ecrit(n: number): string {
  return n.toLocaleString('fr-FR', { maximumFractionDigits: 1 })
}

/** « 1 pot (125 g) » : l'unité qu'on mange, et ce qu'elle pèse. */
export function uniteEtPoids(a: Pick<AlimentLu, 'unite' | 'unite_g'>): string {
  /* Un aliment au gramme (son unité EST le gramme) : « 100 g », pas « 1 g (100 g) ». */
  if (/^(g|gr|gramme|grammes)$/i.test(a.unite.trim())) return `${ecrit(Number(a.unite_g))} g`
  return `1 ${a.unite} (${ecrit(Number(a.unite_g))} g)`
}

/** La ligne sous le nom, dans la feuille de choix : « 1 pot (125 g) · 12,5 g de protéines ». */
export function detailDeLUnite(a: AlimentLu): string {
  return `${uniteEtPoids(a)} · ${ecrit(valeursDeLUnite(a).protein)} g de protéines`
}
