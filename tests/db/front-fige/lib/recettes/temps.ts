/**
 * Le temps des MAINS, d'une étape et d'une recette (R6, R7).
 *
 * La même règle que `tg_recipe_agrege` (migration 0092), écrite une seconde fois
 * parce que la fiche et le recalcul à sec en ont besoin sans base. Le banc de la
 * base (`tests/recettes.test.ts`) vérifie que les deux disent la même chose : si
 * l'une change, l'autre doit suivre.
 */
export type Charge = 'actif' | 'passif' | 'bloquant'

/** Ce qu'il faut d'une étape pour compter ses minutes. PostgREST rend parfois les
    `numeric` en chaîne : on accepte les deux. */
export type EtapeTemps = {
  load_type: string | null
  duration_min: number | string | null
  gesture_min: number | string | null
}

const nombre = (v: number | string | null | undefined): number => {
  if (v === null || v === undefined || v === '') return 0
  const n = Number(v)
  return Number.isNaN(n) ? 0 : n
}

/**
 * Active ou bloquante : sa durée, ou ses gestes s'ils la dépassent.
 * Passive : ses gestes seulement — le four cuit seul, mais quelqu'un a versé la
 * pâte dans le moule.
 */
export function minutesDeMains(e: EtapeTemps): number {
  if (e.load_type === 'actif' || e.load_type === 'bloquant') {
    return Math.max(nombre(e.duration_min), nombre(e.gesture_min))
  }
  return nombre(e.gesture_min)
}

export function tempsActif(etapes: EtapeTemps[]): number {
  return Math.round(etapes.reduce((s, e) => s + minutesDeMains(e), 0) * 10) / 10
}

/**
 * Un temps actif nul ne se croit pas : aucune recette ne se fait sans les mains.
 * Il veut dire « aucun geste reconnu », et se lit « inconnu » (R6).
 */
export function actifConnu(min: number | string | null | undefined): boolean {
  return min !== null && min !== undefined && nombre(min) > 0
}

/**
 * « En tout », dans la fiche (R7).
 *
 * Le total vient du site, le temps actif de nos étapes. Quand le site annonce
 * moins que nos gestes, l'un des deux a tort — on ne finit pas avant d'avoir fini
 * ses gestes. On montre alors la somme de nos étapes, chacune comptée au moins
 * pour ses gestes : c'est déjà ce qu'une recette collée appelle « en tout ». La
 * donnée, elle, ne change pas.
 */
export function enTout(
  declare: number | string | null, actif: number | string | null, etapes: EtapeTemps[],
): number | null {
  const site = declare === null ? null : nombre(declare)
  if (site !== null && site > 0 && site >= nombre(actif)) return site
  const somme = etapes.reduce((s, e) => s + Math.max(nombre(e.duration_min), minutesDeMains(e)), 0)
  return somme > 0 ? Math.round(somme * 10) / 10 : null
}

/** Ce que la pilule d'une étape dit de sa charge, dans la fiche. */
export const MOT_DE_CHARGE: Record<Charge, string> = {
  actif: 'tes gestes',
  bloquant: 'à surveiller',
  passif: 'sans toi',
}
