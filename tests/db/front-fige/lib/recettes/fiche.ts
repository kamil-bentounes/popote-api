/**
 * Ce que la fiche (i) écrit, sans réseau (R2).
 */
import { decodeEntites } from './texte.ts'

const UNITES = [
  'kg', 'g', 'gr', 'mg', 'l', 'cl', 'dl', 'ml',
  // « c. à soupe », « c.à.s », « càs », « c à café » : les points et les blancs varient.
  String.raw`c\.?\s*à\.?\s*(?:soupe|café|s|c)\.?`,
  String.raw`cuill(?:è|e)res?\s+à\s+(?:soupe|café)`,
  'cs', 'cc', 'pincées?', 'gousses?', 'tranches?', 'sachets?', 'bo(?:i|î)tes?', 'brins?',
  'feuilles?', 'verres?', 'bols?', 'tasses?', 'poignées?', 'morceaux?', 'filets?',
  'branches?', 'pots?',
].join('|')
const FRACTION = String.raw`(?:\d+\s*/\s*\d+|[½¼¾⅓⅔])`
// Un nombre mixte (« 1 ½ », « 1 1/2 ») d'abord : sinon « 1 » s'en irait seul.
const NOMBRE = String.raw`(?:\d+\s*${FRACTION}|\d+(?:[.,]\d+)?|${FRACTION})`
// « 3 x 100 g » : un nombre de fois la quantité.
const FOIS = String.raw`(?:\d+\s*[x×]\s*)?`
const QTE = String.raw`${FOIS}${NOMBRE}(?:\s*(?:à|-)\s*${NOMBRE})?(?:\s*(?:${UNITES})\.?)?`
const QUANTITE = new RegExp(String.raw`^(${QTE})\s+(?:(?:de|d['’])\s*)?(.+)$`, 'i')
// Rien après la quantité et l'unité : « 250 g », « 2 à 3 ».
const QUANTITE_SEULE = new RegExp(String.raw`^${QTE}$`, 'i')

const majuscule = (s: string) => (s ? s[0].toLocaleUpperCase('fr') + s.slice(1) : s)

/**
 * Une ligne d'ingrédient en deux colonnes, comme la maquette : la quantité en
 * gras, le nom à côté. Sans quantité lisible, ou sans rien après elle, tout va
 * dans le nom — on ne devine pas.
 */
export function ingredientEnDeux(brut: string): { qte: string; nom: string } {
  const t = decodeEntites(brut).replace(/\s+/g, ' ').trim()
  const m = QUANTITE_SEULE.test(t) ? null : t.match(QUANTITE)
  if (!m) return { qte: '', nom: majuscule(t) }
  return { qte: m[1].trim(), nom: majuscule(m[2].trim()) }
}

/**
 * Les mots qui disent COMMENT l'aliment a été préparé, mesuré ou emballé pour le tableau CIQUAL —
 * pas CE QU'ON ACHÈTE. Un segment fait seulement de ces mots disparaît du libellé de courses.
 */
const MOTS_D_ETAT = new Set([
  'cru', 'crue', 'crus', 'crues', 'cuit', 'cuite', 'cuits', 'cuites', 'cuisiné', 'cuisinée',
  'cuisinés', 'cuisinées', 'bouilli', 'bouillie', 'bouillis', 'bouillies', 'rôti', 'rôtie', 'rôtis',
  'rôties', 'grillé', 'grillée', 'grillés', 'grillées', 'poêlé', 'poêlée', 'poêlés', 'poêlées',
  'sauté', 'sautée', 'sautés', 'sautées', 'frit', 'frite', 'frits', 'frites', 'préfrit', 'préfrite',
  'vapeur', 'poêle', 'eau', 'four',
  'appertisé', 'appertisée', 'appertisés', 'appertisées', 'égoutté', 'égouttée', 'égouttés',
  'égouttées', 'préemballé', 'préemballée', 'préemballés', 'préemballées', 'embouteillé',
  'embouteillée', 'embouteillés', 'embouteillées', 'déshydraté', 'déshydratée', 'déshydratés',
  'déshydratées', 'reconstitué', 'reconstituée', 'séché', 'séchée', 'séchés', 'séchées', 'sec',
  'sèche', 'secs', 'sèches', 'surgelé', 'surgelée', 'surgelés', 'surgelées', 'congelé', 'congelée',
  'pulpe', 'peau', 'viande', 'rayon',
  // les liaisons de ces segments (« à la vapeur », « cuit à l'eau », « pulpe et peau »)
  'à', 'a', 'la', 'le', 'l', 'au', 'aux', 'et', 'ou', 'de', 'du', 'des', 'd',
])

/** Les segments à retirer en entier, quels que soient les mots qu'ils contiennent. */
const SEGMENT_SANS_INTERET = [
  /^rayon frais$/i,
  /^prélev/i,
  /^lait fermenté ou spécialité laitière$/i,
  /^sans précision\b/i,
  /^aliment moyen$/i,
  /^enrichie?s?\b/i,
]

/**
 * Le nom d'un aliment CIQUAL tel qu'on le lit sur une LISTE DE COURSES.
 *
 * CIQUAL écrit « Poulet, cuisse, viande, rôti/cuit au four » : un nom de catalogue, fait pour être
 * indexé. En magasin on cherche « Poulet cuisse ». On découpe sur « , », on garde le premier
 * segment et ceux qui distinguent encore deux produits au rayon (cuisse, filet, nature, doux,
 * 0 % MG, entier, sans peau…), on retire ceux qui ne parlent que de cuisson, d'état ou
 * d'emballage, on joint par une espace et on plafonne à trois segments. Si tout part, le premier
 * reste.
 */
export function nomCourt(nomCiqual: string): string {
  const [tete, ...suite] = segments(nomCiqual.replace(/\s*\((?:[^)]*\s)?aliment moyen\)/gi, ''))
  if (!tete) return nomCiqual.trim()
  const utile = (segment: string) => {
    if (SEGMENT_SANS_INTERET.some(m => m.test(segment))) return false
    const mots = segment.toLowerCase().split(/[\s/'’]+/).filter(m => m.length > 0)
    return !mots.every(m => MOTS_D_ETAT.has(m))
  }
  // Une parenthèse (« (Arcens, 07) », « (Italie) ») n'aide personne au rayon, sauf dans le nom lui-même.
  const sansParentheses = (segment: string) => segment.replace(/\s*\([^)]*\)/g, '').trim()
  return [tete, ...suite.map(sansParentheses).filter(utile)].filter(x => x.length > 0).slice(0, 3).join(' ')
}

/** Découpe sur « , » HORS parenthèses : « moyennement minéralisée (Arcens, 07) » reste d'un bloc. */
function segments(nom: string): string[] {
  const morceaux: string[] = []
  let profondeur = 0
  let courant = ''
  for (const c of nom) {
    if (c === '(') profondeur++
    else if (c === ')') profondeur = Math.max(0, profondeur - 1)
    if (c === ',' && profondeur === 0) { morceaux.push(courant); courant = '' } else courant += c
  }
  morceaux.push(courant)
  return morceaux.map(x => x.trim()).filter(x => x.length > 0)
}

/**
 * Le libellé d'une ligne de COURSES : le nom court de l'aliment reconnu, sinon le texte de la
 * recette SANS sa quantité. La quantité du texte (« 500 g d'agneau haché ») est celle de la
 * recette ; la liste porte la sienne, mise à l'échelle des parts (250 g) : les deux côte à
 * côte se contredisaient (« 500 g d'agneau haché — 250 g »).
 */
export function libelleDeCourse(aliment: string | null | undefined, brut: string): string {
  if (aliment) return nomCourt(aliment)
  const { nom } = ingredientEnDeux(brut)
  return nom || decodeEntites(brut).trim()
}

/** PostgREST rend parfois les `numeric` en chaîne ; une valeur illisible compte
    zéro, comme un temps illisible (temps.ts). */
const lu = (v: number | string): number => {
  const x = Number(v)
  return Number.isFinite(x) ? x : 0
}

/**
 * La pastille de la carte « Par part » : ce que vaut la fourchette. Ce qu'on ne
 * connaît pas passe avant ce qu'on connaît mal.
 */
export function precision(n: {
  kcal_margin: number | string; protein_g_margin: number | string; coverage: number | string
}): string {
  // Ce qu'on compare est ce qu'on écrit : 0,8999 s'affiche « 90 % », il ne peut
  // donc pas passer sous le seuil de 90 %.
  const pourcent = Math.round(lu(n.coverage) * 100)
  if (pourcent < 90) return `${pourcent} % des ingrédients connus`
  const km = Math.round(lu(n.kcal_margin))
  return km < 1 ? 'Tout est pesé' : `à ${km} kcal près`
}
