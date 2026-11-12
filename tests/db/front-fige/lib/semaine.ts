/**
 * Le calendrier des repas, la barquette qu'une case porte vraiment, et ce qu'on en a consommé.
 *
 * Pur : aucune requête. Le choix des repas se fait à l'écran « La semaine » (`choix.ts`, et `choisir_un_repas` côté
 * base) : plus aucune distribution automatique ne vit ici.
 */


export const REPAS = ['petit_dejeuner', 'dejeuner', 'diner', 'collation'] as const
export type Repas = (typeof REPAS)[number]

export const NOM_REPAS: Record<Repas, string> = {
  petit_dejeuner: 'Petit déjeuner',
  dejeuner: 'Déjeuner',
  diner: 'Dîner',
  collation: 'Collation',
}

/**
 * Une date locale au format que Postgres attend.
 *
 * JAMAIS `toISOString().slice(0,10)` : à 23 h en France, cela rend la veille.
 * C'est exactement le genre d'erreur qui fait manquer un repas dans l'app.
 */
export function jour(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * La barquette qu'une case porte VRAIMENT : celle que l'écran peut montrer.
 *
 * Une case « prévue » dont la part a été jetée, ou mangée par un AUTRE repas, ne porte plus rien : la
 * montrer ferait manger ce soir une barquette qui n'existe plus, et compter ses calories. (La base lâche
 * ces cases quand on jette ou qu'on retire — `ecarte_des_parts`, `mange_une_part`, 0122 —, mais une
 * ancienne écriture ou un autre téléphone peut en avoir laissé une.)
 */
export function portionVivante<P extends { state: string }>(c: { state: string; portion: P | null }): P | null {
  const p = c.portion
  if (!p) return null
  if (p.state === 'jetee') return null
  if (p.state === 'mangee' && c.state !== 'mange') return null
  return p
}

export type CaseConsommee = {
  day: string
  user_profile_id: string
  state: string
  portion: { kcal: number | string; protein_g: number | string } | null
  extras: { kcal: number | string; protein_g: number | string; planifie?: boolean }[]
}

/**
 * Un extra compte-t-il au bilan ? Ce qu'on a noté APRÈS coup (« en plus » : `planifie` faux) compte toujours — on ne
 * l'a pas écrit par erreur. Ce que la feuille de choix a PLANIFIÉ (« autre chose » : un restaurant, un sandwich) ne
 * compte QUE si la case est « mangé » : un restaurant choisi pour jeudi n'est pas encore dans l'assiette, et un repas
 * remis à « prévu » (« Pas mangé ? Annuler », 0129) n'y est plus, ni demain, ni sur un jour passé. Un jour passé se note
 * (0128) : un repas qu'on n'a pas noté reste « pas encore noté », il ne compte pas de lui-même.
 */
export function extraCompte(e: { planifie?: boolean }, c: { state: string }): boolean {
  return !e.planifie || c.state === 'mange'
}

/**
 * Ce qu'une personne a consommé un jour donné, barquettes et extras confondus.
 *
 * D33 : `renseignes` et `prevus` ne sont pas décoratifs. Un repas non renseigné
 * n'est PAS un repas à zéro, et l'écran doit pouvoir faire la différence plutôt
 * que d'afficher « 900 kcal aujourd'hui » à quelqu'un qui n'a rien coché.
 */
export function bilanDuJour(cases: CaseConsommee[], userId: string, j: string) {
  const duJour = cases.filter(c => c.day === j && c.user_profile_id === userId)

  /*
   * ⚠️ Deux règles, et pas une seule.
   *
   *  · La BARQUETTE ne compte que si la case est « mangée » : on peut très bien
   *    ne pas l'avoir mangée.
   *  · L'EXTRA compte, lui, même sur une case « prévue » : un déjeuner au
   *    restaurant n'a pas de barquette, donc sa case reste « prévue », et
   *    l'exiger « mangée » revenait à ne jamais compter les repas hors
   *    barquette. C'est précisément ce que D26 dit de ne pas faire : sans eux,
   *    le tableau de bord ment de ~900 kcal par jour. MAIS un extra que la
   *    feuille de choix a seulement PLANIFIÉ (« autre chose ») ne compte que
   *    quand sa case est mangée (`extraCompte`).
   */
  const comptes = (c: CaseConsommee) => c.extras.filter(e => extraCompte(e, c))
  const somme = (barquette: (c: CaseConsommee) => number,
                 extra: (e: CaseConsommee['extras'][number]) => number) =>
    duJour.reduce((s, c) =>
      s + (c.state === 'mange' ? barquette(c) : 0) + comptes(c).reduce((t, e) => t + Number(extra(e)), 0), 0)

  return {
    kcal: Math.round(somme(c => Number(c.portion?.kcal ?? 0), e => Number(e.kcal))),
    proteinG: Math.round(somme(
      c => Number(c.portion?.protein_g ?? 0), e => Number(e.protein_g))),
    // Un jour où l'on a noté un resto EST renseigné, même si la case est restée
    // « prévue » faute de barquette à cocher — pas un resto seulement planifié.
    renseignes: duJour.filter(c => c.state !== 'prevu' || comptes(c).length > 0).length,
    prevus: duJour.length,
  }
}
