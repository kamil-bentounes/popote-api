import type { Echelle } from './duree.ts'

/**
 * Le vocabulaire du plan de session.
 *
 * Une TÂCHE est une action à faire, pas une étape de recette : deux recettes
 * qui demandent toutes deux d'émincer des oignons donnent UNE tâche portant
 * les deux recettes (D35). La fusion se fait dans `fusion.ts`, en amont.
 */

/** Ce qu'une action occupe pendant qu'elle dure. */
export type Tache = {
  id: string
  label: string
  dureeMin: number
  /**
   * D30 : une cuisson au four dure 40 min mais n'occupe personne. Seules les
   * tâches actives consomment un cuisinier — c'est ce qui rend « 2 h dispo »
   * compatible avec « 1 h 52 de session ».
   */
  actif: boolean
  /** Code de `appliance_catalog`, ou null pour un geste à la main. */
  appareil: string | null
  /** Identifiants de tâches qui doivent être FINIES avant que celle-ci commence. */
  dependDe: string[]
  /** Recettes servies par cette action : plusieurs si elle a été fusionnée. */
  recettes: string[]
  verbe: string | null
  quantiteG: number | null
  /**
   * Comment la durée réagit à la quantité (D19). Portée par la tâche parce que
   * la FUSION doit pouvoir recalculer : 300 g puis 200 g d'oignons émincés
   * ensemble ne font pas la somme des deux durées.
   */
  echelle: Echelle | null
  /** Durée pour `QUANTITE_REFERENCE_G`, avant mise à l'échelle. */
  dureeBaseMin: number | null
}

/** Ce dont on dispose. Les capacités viennent de `session_appliance` (D8). */
export type Ressources = {
  /** Nombre de personnes qui cuisinent. Deux mains ne font pas deux cuisiniers. */
  cuisiniers: number
  /** code d'appareil → nombre de plats qu'il prend à la fois. */
  appareils: Record<string, number>
}

export type TachePlanifiee = Tache & {
  debutMin: number
  finMin: number
  /** Index du cuisinier à qui l'action revient, ou null si elle n'en occupe aucun. */
  cuisinier: number | null
}

export type Plan = {
  taches: TachePlanifiee[]
  /** Du premier geste au dernier signal, repos compris. */
  dureeMin: number
  /**
   * Le moment où l'on peut quitter la cuisine. C'est CELA que l'écran annonce
   * comme « la session ».
   *
   * La nuance qui compte : un four qui tourne vous RETIENT — il faudra sortir le
   * plat. Un gratin qui repose 3 h 30 au réfrigérateur ne retient personne : on
   * s'en va. Annoncer « 4 h 57 » serait exact et parfaitement inutile.
   */
  finEnCuisineMin: number
  /** Somme des durées actives, toutes personnes confondues. Le vrai coût humain. */
  travailMin: number
  /** Temps pendant lequel au moins une personne a les mains prises. */
  occupeMin: number
  /**
   * D31 : le score de l'optimiseur. Ce n'est pas un détail d'affichage — c'est
   * ce qu'on minimise, parce que c'est ce qui rend une session pénible.
   */
  attenteMin: number
  /** La chaîne qui fixe la durée : la raccourcir est la seule façon de gagner. */
  chemin: string[]
}
