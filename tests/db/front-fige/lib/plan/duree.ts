/**
 * La durée d'un geste en fonction de sa quantité (D19).
 *
 * Éplucher 2 kg d'oignons n'est pas éplucher un oignon — mais ce n'est pas non
 * plus huit fois éplucher 250 g : on prend le rythme, la planche reste sortie,
 * la poubelle est déjà là. D'où le plafond.
 *
 * Une cuisson au four, elle, ne dépend pas du nombre de portions : `constant`.
 *
 * ⚠️ Les deux constantes ci-dessous sont des HYPOTHÈSES, pas des mesures. Elles
 *    sont là pour être remplacées : `duration_observation` enregistre la durée
 *    réelle ET la quantité à chaque session (D48), ce qui rend la courbe
 *    mesurable au bout de quelques dimanches. Ne pas les « affiner » à vue.
 */

export type Echelle = 'constant' | 'lineaire_plafonne'

/** Quantité pour laquelle `base_minutes` a été relevé. */
export const QUANTITE_REFERENCE_G = 250

/** Au-delà, la durée cesse de croître : on a pris le rythme. */
export const PLAFOND = 3

export function dureeDe(
  baseMin: number,
  echelle: Echelle | null,
  quantiteG: number | null,
): number {
  if (echelle !== 'lineaire_plafonne' || quantiteG === null || quantiteG <= 0) return baseMin
  const facteur = Math.min(PLAFOND, Math.max(1, quantiteG / QUANTITE_REFERENCE_G))
  // Un dixième de minute : l'ordonnanceur travaille en flottants, l'écran
  // arrondit. Garder de la précision ici évite des écarts qui s'accumulent.
  return Math.round(baseMin * facteur * 10) / 10
}

/**
 * Les appareils du référentiel des durées ne sont pas ceux que l'on coche.
 *
 * `default_duration` parle de poêle et de casserole ; l'utilisateur coche
 * « plaques de cuisson », et c'est le bon modèle de ressource : une poêle et
 * une casserole occupent chacune un feu, et il y en a quatre.
 */
const VERS_CATALOGUE: Record<string, string> = {
  poele: 'plaques',
  casserole: 'plaques',
  plaque: 'plaques',
}

export function appareilDuCatalogue(type: string | null): string | null {
  if (!type) return null
  return VERS_CATALOGUE[type] ?? type
}

/**
 * Une recette se PLANIFIE quand l'ordonnanceur sait en faire quelque chose : elle a des étapes, et chacune a une durée.
 * Sans durée il ne peut pas, et la recette resterait invisible dans « Choisir » (qui ne liste que les planifiables).
 * Oubliée au moment de garder une recette d'« Inventer », elle a laissé des recettes enregistrées sans jamais pouvoir être
 * choisies : `plannable` vaut faux par défaut en base.
 */
export function planifiable(durees: (number | null | undefined)[]): boolean {
  return durees.length > 0 && durees.every(d => typeof d === 'number' && d > 0)
}
