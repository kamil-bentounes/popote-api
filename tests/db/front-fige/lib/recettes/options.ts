/**
 * Les options d'un script en ligne de commande, lues SANS rien deviner.
 *
 * Né du recalcul du catalogue : `--limite` sans valeur ou à 0 rendait « pas de
 * limite » (donc tout le catalogue), et `--dry-run` pour `--sec`, à côté de
 * `--prod`, ÉCRIVAIT en production. Une option mal écrite ne doit jamais se lire
 * comme une option absente : elle arrête le script, avant le moindre appel réseau.
 *
 * Pur : le script passe `process.argv.slice(2)`, il affiche l'erreur et sort.
 */

/** Ce qui décrit une option : `'drapeau'` (sans valeur) ou une fonction qui lit la
    valeur et LÈVE une erreur dont le message dit ce qu'on attendait. */
export type SpecOption = 'drapeau' | ((valeur: string) => unknown)
export type Resultat =
  | { ok: true, options: Record<string, unknown> }
  | { ok: false, erreur: string }

/** « 20 » : jamais « 0 », « -3 », « 1.5 », « 20abc » ni « 1e3 ». */
export function entierPositif(v: string): number {
  const n = Number(v)
  if (!/^[1-9]\d*$/.test(v) || !Number.isSafeInteger(n)) throw new Error('un entier positif')
  return n
}

export function uuid(v: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v)) {
    throw new Error('un uuid')
  }
  return v
}

/** `--cle valeur` et `--cle=valeur`. Une option inconnue, donnée deux fois, sans
    valeur ou à valeur illisible rend une erreur — jamais une valeur par défaut. */
export function lireOptions(argv: string[], spec: Record<string, SpecOption>): Resultat {
  const options: Record<string, unknown> = {}
  for (let i = 0; i < argv.length; i++) {
    const brut = argv[i]
    if (!brut.startsWith('--')) return { ok: false, erreur: `argument inattendu : « ${brut} »` }
    const egal = brut.indexOf('=')
    const cle = egal >= 0 ? brut.slice(0, egal) : brut
    if (!Object.hasOwn(spec, cle)) return { ok: false, erreur: `option inconnue : ${cle}` }
    if (Object.hasOwn(options, cle)) return { ok: false, erreur: `${cle} donné deux fois` }

    const lecteur = spec[cle]
    if (lecteur === 'drapeau') {
      if (egal >= 0) return { ok: false, erreur: `${cle} : sans valeur (reçu « ${brut.slice(egal + 1)} »)` }
      options[cle] = true
      continue
    }
    let valeur: string | undefined
    if (egal >= 0) valeur = brut.slice(egal + 1)
    else if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) valeur = argv[++i]
    if (valeur === undefined || valeur === '') return { ok: false, erreur: `${cle} : valeur manquante` }
    try {
      options[cle] = lecteur(valeur)
    } catch (e) {
      return { ok: false, erreur: `${cle} : attendu ${(e as Error).message}, reçu « ${valeur} »` }
    }
  }
  return { ok: true, options }
}
