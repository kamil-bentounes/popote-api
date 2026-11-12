/**
 * Des étapes de recettes aux actions d'une session (D35).
 *
 * Cinq recettes le dimanche, c'est trois fois « émince les oignons » et deux
 * fois « préchauffe le four ». Les faire séparément est absurde : on sort la
 * planche, on la lave, on la range — trois fois. La fusion rapproche les gestes
 * identiques et ADDITIONNE les quantités, ce qui change à la fois le plan et ce
 * que l'écran affiche : « Émince 500 g d'oignons — pour le dahl et la basquaise ».
 *
 * Ce qu'on économise n'est PAS le geste, c'est sa mise en place — sauf quand le
 * référentiel dit comment la durée réagit à la quantité (`scaling`, D19) : on
 * recalcule alors depuis le total, plafond compris.
 */
import { dureeDe } from './duree.ts'
import type { Echelle } from './duree.ts'
import type { Tache } from './types.ts'

/**
 * Sortir la planche, la laver, la ranger : ce qu'on ne paie qu'une fois. Deux
 * minutes et demie, pas davantage — tout ce qui dépasse serait une invention,
 * et les durées réelles finiront par le dire (D48).
 */
const MISE_EN_PLACE_MIN = 2.5

/** Une étape de recette, telle que la base la rend. */
export type Etape = {
  id: string
  recetteId: string
  texte: string
  ordinal: number
  dureeMin: number | null
  verbe: string | null
  quantiteG: number | null
  appareil: string | null
  /** `actif` | `passif` | `bloquant` — voir recipe_step.load_type. */
  charge: string | null
  dependDe: string[]
  /** Du référentiel `default_duration`. Sert à recalculer après fusion. */
  echelle?: Echelle | null
  dureeBaseMin?: number | null
}

/**
 * Une étape passive n'occupe personne : c'est tout l'intérêt du four. Une étape
 * bloquante occupe l'appareil ET la personne — remuer un risotto se fait à côté
 * de la casserole, pas en épluchant autre chose.
 */
function estActive(charge: string | null): boolean {
  return charge !== 'passif'
}

/**
 * Quand une étape n'a pas de durée, on ne la planifie pas à zéro : elle
 * disparaîtrait du plan sans que personne s'en aperçoive. Une minute, et
 * l'écran de confirmation des durées s'en occupera (D17, révision paresseuse).
 */
const DUREE_PAR_DEFAUT_MIN = 1

export function construitTaches(etapes: Etape[]): Tache[] {
  return etapes.map(e => ({
    id: e.id,
    label: e.texte,
    dureeMin: e.dureeMin && e.dureeMin > 0 ? e.dureeMin : DUREE_PAR_DEFAUT_MIN,
    actif: estActive(e.charge),
    appareil: e.appareil,
    dependDe: e.dependDe,
    recettes: [e.recetteId],
    verbe: e.verbe,
    quantiteG: e.quantiteG,
    echelle: e.echelle ?? null,
    dureeBaseMin: e.dureeBaseMin ?? null,
  }))
}

/**
 * Les seuls gestes qu'on rapproche SANS connaître les quantités.
 *
 * Un seul, et il mérite son exception : deux recettes qui préchauffent le même
 * four ne le préchauffent qu'une fois. Partout ailleurs, l'absence de quantité
 * veut dire qu'on ne sait pas si c'est le même travail — et deux gratins au
 * four sont deux gratins, pas un. On préfère un plan trop long à un plan faux.
 */
const PARTAGEABLES = new Set(['préchauffer'])

/** Deux actions ne se rapprochent que si elles font vraiment la même chose. */
function memeGeste(a: Tache, b: Tache): boolean {
  const mesurable = a.quantiteG !== null && b.quantiteG !== null
  if (!mesurable && !(a.verbe !== null && PARTAGEABLES.has(a.verbe))) return false

  return (
    a.verbe !== null && a.verbe === b.verbe &&
    a.appareil === b.appareil &&
    a.actif === b.actif &&
    a.echelle === b.echelle &&
    // Deux recettes, pas deux fois la même : fusionner deux étapes d'une seule
    // recette casserait sa séquence (« émince » avant et après la cuisson).
    a.recettes.every(r => !b.recettes.includes(r))
  )
}

/**
 * La durée d'un geste fusionné. Trois cas, dans cet ordre :
 *
 * 1. `lineaire_plafonne` avec les deux quantités connues — on RECALCULE depuis
 *    la quantité totale (D19). C'est le cas juste, et c'est là que le plafond
 *    joue : émincer 800 g ne prend pas trois fois émincer 250 g.
 * 2. Ni l'une ni l'autre n'a de quantité — préchauffer, laisser reposer. Deux
 *    préchauffages du même four n'en font qu'un : `max`, pas la somme.
 * 3. Sinon — on additionne, moins la mise en place payée une seule fois. C'est
 *    un repli conservateur : il ne prétend jamais gagner plus qu'une planche.
 */
function dureeFusionnee(a: Tache, b: Tache): number {
  if (a.echelle === 'lineaire_plafonne' && a.dureeBaseMin !== null
      && a.quantiteG !== null && b.quantiteG !== null) {
    return dureeDe(a.dureeBaseMin, a.echelle, a.quantiteG + b.quantiteG)
  }
  if (a.quantiteG === null && b.quantiteG === null) {
    return Math.max(a.dureeMin, b.dureeMin)
  }
  const economie = Math.min(MISE_EN_PLACE_MIN, Math.min(a.dureeMin, b.dureeMin) / 2)
  return a.dureeMin + b.dureeMin - economie
}

/** Un tri topologique qui échoue plutôt que de boucler. */
function acyclique(taches: Tache[]): boolean {
  const restant = new Map(taches.map(t => [t.id, new Set(t.dependDe.filter(
    d => taches.some(x => x.id === d)))]))
  let bouge = true
  while (bouge && restant.size > 0) {
    bouge = false
    for (const [id, deps] of restant) {
      if (deps.size > 0) continue
      restant.delete(id)
      for (const autres of restant.values()) autres.delete(id)
      bouge = true
    }
  }
  return restant.size === 0
}

function fusionneDeux(a: Tache, b: Tache): Tache {
  const quantite = a.quantiteG !== null && b.quantiteG !== null
    ? a.quantiteG + b.quantiteG
    : null
  return {
    id: a.id,
    label: quantite !== null && a.verbe
      ? `${a.verbe} ${Math.round(quantite)} g`
      : a.label,
    dureeMin: dureeFusionnee(a, b),
    actif: a.actif,
    appareil: a.appareil,
    dependDe: [...new Set([...a.dependDe, ...b.dependDe])],
    recettes: [...new Set([...a.recettes, ...b.recettes])],
    verbe: a.verbe,
    quantiteG: quantite,
    echelle: a.echelle,
    dureeBaseMin: a.dureeBaseMin,
  }
}

/** Fait pointer vers `garde` tout ce qui pointait vers `absorbee`. */
function redirige(taches: Tache[], absorbee: string, garde: string): Tache[] {
  return taches.map(t => t.dependDe.includes(absorbee)
    ? {
        ...t,
        dependDe: [...new Set(t.dependDe.map(d => (d === absorbee ? garde : d)))]
          .filter(d => d !== t.id),
      }
    : t)
}

/**
 * Fusionne ce qui peut l'être, en refusant toute fusion qui rendrait le graphe
 * circulaire — cas réel : A précède X qui précède B ; rapprocher A et B ferait
 * dépendre le résultat de lui-même. On vérifie après coup plutôt que d'essayer
 * de le prévoir, c'est moins malin et ça ne se trompe pas.
 */
export function fusionne(entree: Tache[]): Tache[] {
  let taches = entree.map(t => ({ ...t }))

  for (let i = 0; i < taches.length; i++) {
    for (let j = i + 1; j < taches.length; j++) {
      const a = taches[i]
      const b = taches[j]
      if (!memeGeste(a, b)) continue

      const essai = redirige(
        taches.filter(t => t.id !== b.id).map(t => (t.id === a.id ? fusionneDeux(a, b) : t)),
        b.id, a.id)

      if (!acyclique(essai)) continue
      taches = essai
      j--   // b a disparu : la place j porte maintenant la tâche suivante
    }
  }
  return taches
}

/** Le pipeline complet, du rang de base à la liste d'actions. */
export function actionsDeLaSession(etapes: Etape[]): Tache[] {
  return fusionne(construitTaches(etapes))
}
