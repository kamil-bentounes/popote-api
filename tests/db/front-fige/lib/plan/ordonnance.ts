/**
 * L'ordonnancement d'une session de batch cooking.
 *
 * C'est un RCPSP (resource-constrained project scheduling problem), NP-difficile
 * dans le cas général. On n'en cherche pas l'optimum : on cherche un plan bon,
 * calculé en moins de 100 ms sur un téléphone, et surtout EXPLICABLE — l'écran
 * doit pouvoir dire « le four est le goulot », pas « faites confiance ».
 *
 * Méthode : schéma sériel de génération (SSGS) piloté par une liste de priorité,
 * puis recherche locale sur cette liste. Le SSGS garantit un plan faisable quelle
 * que soit la permutation, ce qui rend la recherche locale triviale à écrire et
 * impossible à casser.
 *
 * DÉTERMINISME : deux téléphones doivent afficher le MÊME plan (D50). Le tirage
 * aléatoire est donc semé par l'identifiant du cycle, jamais par l'horloge.
 */
import type { Plan, Ressources, Tache, TachePlanifiee } from './types.ts'

/** Les durées sont des nombres à virgule ; on ne compare jamais deux flottants. */
const EPS = 1e-9

/** Pool des mains humaines. Le dièse ne peut heurter aucun code d'appareil. */
const CUISINIER = '#cuisinier'

type Reservation = { debut: number; fin: number }

/**
 * Les réservations d'un pool, UNITÉ PAR UNITÉ.
 *
 * ⚠️ C'est le cœur du modèle, et la première version s'y est trompée. Elle
 *    comptait les occupants INSTANT PAR INSTANT : tant qu'il restait une place
 *    à chaque moment, le créneau passait. Or une tâche ne se passe pas de main
 *    en main, et un gratin ne change pas de four à mi-cuisson.
 *
 *    Trouvé par le test de propriétés, sur une session à trois cuisiniers : A
 *    occupé de 0 à 21, B de 0 à 24, C de 24 à 33. À chaque instant il restait
 *    une place libre — mais personne n'était libre sur tout [0,9 ; 45[. Le plan
 *    posait quand même la tâche, et l'attribution, ne trouvant aucun cuisinier
 *    libre, retombait en silence sur le numéro 0, déjà occupé.
 *
 *    On suit donc chaque unité séparément, et une tâche doit en trouver UNE
 *    libre du début à la fin.
 */
/**
 * Une unité garde son total de charge et sa dernière fin.
 *
 * Les deux sont maintenus à l'écriture plutôt que recalculés à la lecture. Le
 * suivi unité par unité avait fait passer une grosse session de 300 à 430 ms
 * sur un téléphone : `charge()` reparcourait toutes les réservations à chaque
 * unité et à chaque créneau candidat, et `libre()` aussi. Avec `fin`, une unité
 * libre depuis longtemps se reconnaît en une comparaison.
 */
type Unite = { res: Reservation[]; charge: number; fin: number }
type Pool = Unite[]
type Occupation = Map<string, Pool>

/** Capacité d'un pool. Un appareil inconnu de la session compte pour un. */
function capacite(ressources: Ressources, pool: string): number {
  if (pool === CUISINIER) return Math.max(1, ressources.cuisiniers)
  return ressources.appareils[pool] ?? 1
}

/** Les pools qu'une tâche occupe pendant toute sa durée. */
function pools(t: Tache): string[] {
  const p: string[] = []
  if (t.actif) p.push(CUISINIER)
  if (t.appareil) p.push(t.appareil)
  return p
}

function poolDe(occ: Occupation, nom: string, cap: number): Pool {
  let p = occ.get(nom)
  if (!p) {
    p = Array.from({ length: cap }, () => ({ res: [], charge: 0, fin: 0 }))
    occ.set(nom, p)
  }
  return p
}

/** Cette unité est-elle libre sur TOUT l'intervalle ? */
function libre(u: Unite, debut: number, fin: number): boolean {
  // Le cas courant, réglé sans rien parcourir : plus rien après `debut`.
  if (debut >= u.fin - EPS) return true
  // Une réservation de durée nulle n'occupe rien : elle ne bloque personne.
  return u.res.every(r => r.fin <= r.debut + EPS
    || r.fin <= debut + EPS || fin <= r.debut + EPS)
}

/**
 * La première unité libre du pool, la moins chargée d'abord.
 *
 * Répartir plutôt que remplir la première : c'est ce qui fait que deux
 * personnes qui cuisinent se partagent vraiment le travail. L'index départage,
 * pour que deux téléphones attribuent pareil (D50).
 */
function uniteLibre(pool: Pool, debut: number, fin: number): number | null {
  let choix: number | null = null
  let min = Infinity
  for (let i = 0; i < pool.length; i++) {
    if (!libre(pool[i], debut, fin)) continue
    if (pool[i].charge < min - EPS) { min = pool[i].charge; choix = i }
  }
  return choix
}

/** Une unité libre par pool à cet instant précis, ou `null` si l'un manque. */
function essaie(
  t: Tache, debut: number, occ: Occupation, ressources: Ressources, concernes: string[],
): Map<string, number> | null {
  const unites = new Map<string, number>()
  for (const nom of concernes) {
    const i = uniteLibre(poolDe(occ, nom, capacite(ressources, nom)), debut, debut + t.dureeMin)
    if (i === null) return null
    unites.set(nom, i)
  }
  return unites
}

/**
 * Le plus tôt possible à partir de `apres`, avec UNE unité libre par pool sur
 * toute la durée.
 *
 * Un créneau ne peut s'ouvrir qu'au moment où quelque chose se libère : on
 * n'essaie que `apres` et les fins de réservation.
 */
function premierCreneau(
  t: Tache, apres: number, occ: Occupation, ressources: Ressources,
): { debut: number; unites: Map<string, number> } {
  const concernes = pools(t)
  if (concernes.length === 0) return { debut: apres, unites: new Map() }

  /*
   * Le cas courant d'abord : commencer TOUT DE SUITE.
   *
   * La plupart des tâches le peuvent, et le vérifier coûte une comparaison par
   * unité. Construire l'ensemble des créneaux candidats, le trier et le
   * parcourir pour retomber sur `apres` était le gros du temps de calcul —
   * répété quinze cents fois par la recherche locale.
   */
  const tout_de_suite = essaie(t, apres, occ, ressources, concernes)
  if (tout_de_suite) return { debut: apres, unites: tout_de_suite }

  const candidats = new Set<number>()
  for (const nom of concernes) {
    for (const u of poolDe(occ, nom, capacite(ressources, nom))) {
      // Une unité déjà libre à `apres` n'ouvre aucun créneau plus tard : ses
      // fins de réservation ne sont pas des candidats utiles.
      if (u.fin <= apres + EPS) continue
      for (const r of u.res) if (r.fin > apres + EPS) candidats.add(r.fin)
    }
  }

  for (const c of [...candidats].sort((a, b) => a - b)) {
    const unites = essaie(t, c, occ, ressources, concernes)
    if (unites) return { debut: c, unites }
  }

  // Inatteignable : passé la dernière fin de tous les pools concernés, tout est
  // libre. On le garde pour ne jamais rendre un plan sans début.
  const apresTout = Math.max(apres, ...concernes.flatMap(nom =>
    poolDe(occ, nom, capacite(ressources, nom)).map(u => u.fin)))
  const unites = new Map<string, number>()
  for (const nom of concernes) unites.set(nom, 0)
  return { debut: apresTout, unites }
}


/**
 * Schéma sériel : on prend les tâches une à une dans l'ordre de priorité, en
 * ne retenant à chaque tour que celles dont tous les prédécesseurs sont posés.
 * Toute permutation donne un plan faisable ; c'est ce qui permet à la recherche
 * locale de brasser la liste sans jamais produire d'aberration.
 */
export function ordonnance(
  taches: Tache[], ressources: Ressources, priorite: string[],
): Plan {
  const parId = new Map(taches.map(t => [t.id, t]))
  const rang = new Map(priorite.map((id, i) => [id, i]))
  const occ: Occupation = new Map()
  const posees = new Map<string, TachePlanifiee>()
  const planifiees: TachePlanifiee[] = []
  const restantes = new Set(taches.map(t => t.id))

  while (restantes.size > 0) {
    const eligibles = [...restantes]
      .filter(id => parId.get(id)!.dependDe.every(d => !restantes.has(d)))
      .sort((a, b) => (rang.get(a) ?? 1e9) - (rang.get(b) ?? 1e9))

    if (eligibles.length === 0) {
      // Rien d'éligible alors qu'il reste des tâches : le graphe a une boucle.
      // On refuse plutôt que de rendre un plan qui oublierait des actions.
      throw new Error(`dépendances circulaires : ${[...restantes].join(', ')}`)
    }

    const t = parId.get(eligibles[0])!
    const apres = t.dependDe.reduce((m, d) => Math.max(m, posees.get(d)?.finMin ?? 0), 0)
    const { debut, unites } = premierCreneau(t, apres, occ, ressources)
    const fin = debut + t.dureeMin

    const pl: TachePlanifiee = {
      ...t,
      debutMin: debut,
      finMin: fin,
      // Le cuisinier n'est plus choisi à part : c'est l'unité du pool des mains
      // que le créneau vient de réserver. Les deux décisions ne peuvent plus
      // diverger — c'est exactement ainsi qu'un cuisinier se retrouvait à deux
      // endroits à la fois.
      cuisinier: t.actif ? unites.get(CUISINIER) ?? 0 : null,
    }
    for (const nom of pools(t)) {
      const u = poolDe(occ, nom, capacite(ressources, nom))[unites.get(nom) ?? 0]
      u.res.push({ debut, fin })
      u.charge += fin - debut
      if (fin > u.fin) u.fin = fin
    }
    posees.set(t.id, pl)
    planifiees.push(pl)
    restantes.delete(t.id)
  }

  planifiees.sort((a, b) => a.debutMin - b.debutMin || a.label.localeCompare(b.label, 'fr'))
  return { ...mesure(planifiees), taches: planifiees, chemin: cheminCritique(planifiees) }
}

/** Les trois chiffres que l'écran affiche, et le seul que l'on minimise. */
function mesure(taches: TachePlanifiee[]): Omit<Plan, 'taches' | 'chemin'> {
  const dureeMin = taches.reduce((m, t) => Math.max(m, t.finMin), 0)
  const travailMin = taches.reduce((s, t) => s + (t.actif ? t.dureeMin : 0), 0)
  // Ce qui retient en cuisine : un geste, ou un appareil qu'il faudra vider.
  // Un repos sans appareil — au frigo, à température ambiante — ne retient pas.
  const finEnCuisineMin = taches.reduce(
    (m, t) => (t.actif || t.appareil !== null ? Math.max(m, t.finMin) : m), 0)

  // Union des intervalles actifs : deux personnes qui travaillent en même temps
  // ne font pas passer le temps deux fois.
  const actifs = taches.filter(t => t.actif)
    .map(t => [t.debutMin, t.finMin] as const)
    .sort((a, b) => a[0] - b[0])
  let occupeMin = 0
  let curDeb = -1
  let curFin = -1
  for (const [d, f] of actifs) {
    if (curFin < 0) { curDeb = d; curFin = f; continue }
    if (d <= curFin + EPS) { curFin = Math.max(curFin, f); continue }
    occupeMin += curFin - curDeb
    curDeb = d
    curFin = f
  }
  if (curFin >= 0) occupeMin += curFin - curDeb

  return {
    dureeMin, finEnCuisineMin, travailMin, occupeMin,
    attenteMin: Math.max(0, finEnCuisineMin - occupeMin),
  }
}

/**
 * La chaîne qui fixe la durée. On remonte depuis la fin en suivant, à chaque
 * pas, la tâche qui se termine exactement quand la suivante commence — qu'elle
 * la précède par recette ou parce qu'elle lui tenait le four.
 */
function cheminCritique(taches: TachePlanifiee[]): string[] {
  if (taches.length === 0) return []
  const fin = taches.reduce((m, t) => Math.max(m, t.finMin), 0)
  let courante = taches.find(t => Math.abs(t.finMin - fin) < EPS)
  const chaine: string[] = []
  const vus = new Set<string>()

  while (courante && !vus.has(courante.id)) {
    const ici = courante
    vus.add(ici.id)
    chaine.unshift(ici.id)
    if (ici.debutMin < EPS) break
    const partages = new Set(pools(ici))
    courante = taches.find(t =>
      t.id !== ici.id && Math.abs(t.finMin - ici.debutMin) < EPS &&
      (ici.dependDe.includes(t.id) || pools(t).some(p => partages.has(p))))
  }
  return chaine
}

/** Générateur semé : le même cycle donne toujours le même plan (D50). */
function semeur(graine: number): () => number {
  let a = graine >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function graineDe(texte: string): number {
  let h = 2166136261
  for (let i = 0; i < texte.length; i++) {
    h ^= texte.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/**
 * Priorité initiale : le plus long chemin restant jusqu'à la fin, d'abord.
 * C'est l'heuristique classique sur le graphe, et elle donne déjà un plan
 * raisonnable — la recherche locale ne fait que gratter les derniers pourcents.
 */
function prioriteInitiale(taches: Tache[]): string[] {
  const parId = new Map(taches.map(t => [t.id, t]))
  const successeurs = new Map<string, string[]>()
  for (const t of taches)
    for (const d of t.dependDe) {
      if (!successeurs.has(d)) successeurs.set(d, [])
      successeurs.get(d)!.push(t.id)
    }

  const reste = new Map<string, number>()
  const calcule = (id: string, pile: Set<string>): number => {
    const connu = reste.get(id)
    if (connu !== undefined) return connu
    if (pile.has(id)) return 0            // boucle : `ordonnance` la signalera
    pile.add(id)
    const suite = (successeurs.get(id) ?? [])
      .reduce((m, s) => Math.max(m, calcule(s, pile)), 0)
    pile.delete(id)
    const v = (parId.get(id)?.dureeMin ?? 0) + suite
    reste.set(id, v)
    return v
  }
  for (const t of taches) calcule(t.id, new Set())

  return [...taches]
    .sort((a, b) =>
      (reste.get(b.id) ?? 0) - (reste.get(a.id) ?? 0) ||
      b.dureeMin - a.dureeMin ||
      a.id.localeCompare(b.id))
    .map(t => t.id)
}

export type OptionsPlan = {
  /** Sème le tirage. Passer `cycle.id` : le plan devient reproductible. */
  graine?: string
  /**
   * Nombre d'essais. Par défaut, proportionnel au nombre d'actions.
   *
   * ⚠️ PAS de budget en millisecondes : s'arrêter à l'horloge rendrait un plan
   *    différent sur un téléphone lent et sur un rapide, ce qui viole D50 —
   *    deux téléphones doivent voir la MÊME chose. Le coût est borné par la
   *    taille du problème, et mesuré (voir le test de tenue en charge).
   */
  iterationsMax?: number
}

/**
 * Essais par action. Au-delà, la recherche locale ne gratte plus rien.
 *
 * MESURÉ le 19 septembre 2026, sur douze sessions de quarante actions, en
 * regardant ce que les itérations achètent vraiment — le temps passé en
 * cuisine, qui est ce qu'on minimise (D31) :
 *
 *   itérations │   0     100    250    500   1000   1500   3000
 *   en cuisine │ 434    400    398    397    394    392    392  min
 *   coût       │   1     24     54     92    194    290    578  ms
 *
 * Tout le gain est dans les cent premières : 34 minutes. Les mille quatre
 * cents suivantes en rendent sept, pour dix fois le temps de calcul — et
 * au-delà de mille cinq cents, plus rien du tout.
 *
 * Six cents tient donc le plan à une demi-minute de l'optimum atteignable, et
 * laisse la marge qu'il faut sur un téléphone : c'est un calcul qu'on ATTEND,
 * l'écran ne montre rien pendant ce temps.
 */
const ESSAIS_PAR_ACTION = 30
const ESSAIS_MAX = 600

/**
 * Le point d'entrée. Rend le meilleur plan trouvé dans le budget, jamais un
 * plan infaisable, et le même plan pour la même graine.
 */
export function planifie(
  taches: Tache[], ressources: Ressources, options: OptionsPlan = {},
): Plan {
  if (taches.length === 0) {
    return {
      taches: [], dureeMin: 0, finEnCuisineMin: 0,
      travailMin: 0, occupeMin: 0, attenteMin: 0, chemin: [],
    }
  }
  const {
    graine = 'batch',
    iterationsMax = Math.min(ESSAIS_MAX, ESSAIS_PAR_ACTION * taches.length),
  } = options

  let meilleureListe = prioriteInitiale(taches)
  let meilleur = ordonnance(taches, ressources, meilleureListe)

  const rnd = semeur(graineDe(graine))
  for (let i = 0; i < iterationsMax; i++) {

    // Voisinage : on déplace UNE tâche ailleurs dans la liste. Déplacer plutôt
    // qu'échanger, parce que c'est ce qui débloque un goulot — remonter la
    // cuisson longue avant les six gestes qui l'attendent.
    const liste = [...meilleureListe]
    const de = Math.floor(rnd() * liste.length)
    const vers = Math.floor(rnd() * liste.length)
    if (de === vers) continue
    const [x] = liste.splice(de, 1)
    liste.splice(vers, 0, x)

    const essai = ordonnance(taches, ressources, liste)
    // On minimise d'abord le temps passé EN CUISINE (D31) : c'est ce qui rend
    // une session pénible. La durée totale, repos compris, ne départage qu'après.
    if (essai.finEnCuisineMin < meilleur.finEnCuisineMin - EPS ||
        (Math.abs(essai.finEnCuisineMin - meilleur.finEnCuisineMin) < EPS &&
         essai.dureeMin < meilleur.dureeMin - EPS) ||
        (Math.abs(essai.finEnCuisineMin - meilleur.finEnCuisineMin) < EPS &&
         Math.abs(essai.dureeMin - meilleur.dureeMin) < EPS &&
         essai.attenteMin < meilleur.attenteMin - EPS)) {
      meilleur = essai
      meilleureListe = liste
    }
  }
  return meilleur
}
