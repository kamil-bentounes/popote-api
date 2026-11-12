/**
 * Ce qu'une lecture (étiquette, Open Food Facts) n'a pas donné : on le dit, on ne l'invente pas.
 *
 * Un chiffre absent reste un CHAMP VIDE. Glucides, lipides et fibres vides comptent pour 0 g à l'enregistrement
 * (`lis`), mais la personne doit savoir qu'ils ne viennent pas de l'emballage : un 0 écrit à sa place serait un chiffre
 * inventé, qui entrerait dans le bilan sans que personne s'en aperçoive.
 */

/** « les glucides », « les glucides et les fibres », « les glucides, les lipides et les fibres ». */
export function listeDeNoms(noms: string[]): string {
  const avec = noms.map(n => `les ${n}`)
  return avec.length <= 1 ? (avec[0] ?? '') : `${avec.slice(0, -1).join(', ')} et ${avec[avec.length - 1]}`
}

/** La phrase des chiffres absents (glucides, lipides, fibres), ou `null` quand rien ne manque. */
export function phraseDesVides(intro: string, noms: string[]): string | null {
  if (noms.length === 0) return null
  return `${intro} ${listeDeNoms(noms)} : je les laisse vides (comptés pour 0 g). Complète-les d’après l’étiquette.`
}
