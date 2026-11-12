/**
 * Le texte des recettes, tel qu'il arrive des sites (R5).
 *
 * Deux défauts relevés dans le catalogue : des entités HTML restées dans le texte
 * (« Fish &amp; chips »), et des titres qui finissent en réclame (« Poulet
 * basquaise : la meilleure recette »). Le premier se lit comme une faute ; le
 * second allonge chaque ligne de la liste pour ne rien dire.
 *
 * Pur et sans réseau : l'ingestion, le recalcul et l'écran s'en servent tous les
 * trois, et ils doivent dire la même chose.
 */

const NOMMEES: Record<string, string> = {
  amp: '&', quot: '"', apos: '\'', lt: '<', gt: '>', nbsp: ' ',
  rsquo: '’', lsquo: '‘', laquo: '«', raquo: '»', hellip: '…', ndash: '–', mdash: '—',
  eacute: 'é', egrave: 'è', ecirc: 'ê', euml: 'ë', agrave: 'à', acirc: 'â',
  ccedil: 'ç', icirc: 'î', iuml: 'ï', ocirc: 'ô', ucirc: 'û', ugrave: 'ù',
  oelig: 'œ', deg: '°',
}

/**
 * « &amp; », « &#039; », « &eacute; » : ce que le JSON-LD a gardé du HTML.
 *
 * Deux passes, parce que l'échappement double existe (« &amp;amp; »). Une entité
 * inconnue reste telle quelle : mieux vaut un « &zz; » visible qu'un caractère
 * inventé.
 */
export function decodeEntites(s: string): string {
  let t = s
  for (let passe = 0; passe < 2; passe++) {
    t = t.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (tout, code: string) => {
      if (code[0] === '#') {
        const n = code[1] === 'x' || code[1] === 'X'
          ? parseInt(code.slice(2), 16)
          : Number(code.slice(1))
        // Une moitié de paire de substitution (0xD800–0xDFFF) n'est pas un caractère :
        // on la laisse visible plutôt que d'écrire « � ».
        const substitut = n >= 0xD800 && n <= 0xDFFF
        return n > 0 && n < 0x110000 && !substitut ? String.fromCodePoint(n) : tout
      }
      return NOMMEES[code.toLowerCase()] ?? tout
    })
  }
  return t
}

/**
 * Minuscules, sans accents, une seule apostrophe : on compare des mots, pas des
 * orthographes. Les sites écrivent « d’agneau » (’ ‘ ` ´), le clavier tape
 * « d'agneau » : la recherche doit trouver l'un avec l'autre.
 */
export function plie(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/œ/g, 'oe').replace(/æ/g, 'ae')
    .replace(/[’‘`´]/g, '\'')
}

/** Ce qui sépare le nom du plat de ce que le site y a collé. Le tiret doit être
    entouré d'espaces : « Saint-Jacques » n'est pas un séparateur. */
const SEPARATEUR = String.raw`\s*(?:[:|–—,]|\s-)\s*`
/** Le texte d'une fin de titre : il ne franchit ni un séparateur ni un tiret entouré
    d'espaces. Sans cela, la coupe démarrerait à la première virgule du NOM du plat
    (« Poulet, riz et petits pois - Recette facile ») et le mangerait. */
const CORPS = String.raw`(?:(?!\s-\s)[^:|–—,])*`
/** Une marque SEULE après le séparateur : un appareil ou un site, pas un plat. */
const MARQUE = String.raw`(?:cookeo|thermomix|companion|monsieur cuisine|air ?fryer|marmiton|ptitchef|cuisineaz|jow)`

const FIN_RECETTE = new RegExp(`${SEPARATEUR}${CORPS}\\brecettes?\\b${CORPS}$`, 'i')
const PARENTHESE_RECETTE = /\s*\([^()]*\brecettes?\b[^()]*\)\s*$/i
const FIN_MARQUE = new RegExp(`${SEPARATEUR}${MARQUE}\\s*$`, 'i')
const DEBUT_RECETTE = /^recettes?\s*(?::\s*|de\s+(?:la\s+|l['’]\s*)?|du\s+|des\s+|d['’]\s*)/i

/** Garde-fou des boucles « jusqu'à ce que ça ne bouge plus » : chaque passe retire au
    moins un caractère, donc ça finit ; le plafond n'est là que pour ne jamais tourner
    dans le vide si une règle future se mettait à en ajouter. */
const PASSES_MAX = 10

/** Les étapes 2 à 7, une fois. */
function nettoyeUnePasse(t: string): string {
  return t
    .replace(FIN_RECETTE, '')
    .replace(PARENTHESE_RECETTE, '')
    .replace(FIN_MARQUE, '')
    .replace(DEBUT_RECETTE, '')
    .replace(/(\S) a (l['’]|la )/g, '$1 à $2')
    .replace(/[\s.]+$/, '')
    .trim()
}

/**
 * Le titre, sans ce que le site y a ajouté pour les moteurs de recherche.
 *
 * Dans l'ordre : les entités ; une fin introduite par un séparateur et qui
 * contient « recette » (« : la meilleure recette », « - Recette Ptitchef ») ; une
 * parenthèse finale qui en contient ; une marque seule en fin (« - Cookeo ») ;
 * « Recette de… » en tête ; l'accent que le clavier a perdu (« a l' » → « à l' ») ;
 * la majuscule.
 *
 * Ces étapes se rejouent jusqu'à ce que le titre ne bouge plus : « Lasagnes |
 * Recette | Marmiton » perd sa marque à la première, puis sa réclame à la seconde ;
 * quatre fins empilées en demandent quatre. Sans quoi un second passage changerait
 * encore le titre.
 *
 * Prudente : un titre qui ne ressemble à aucun motif passe tel quel, et un
 * nettoyage qui ne laisserait pas trois caractères rend le titre d'origine.
 */
export function titrePropre(brut: string | null): string | null {
  if (brut === null) return null
  // Les entités d'abord, jusqu'à ce qu'elles ne bougent plus : « &amp;amp;amp; » en
  // compte trois étages, et `decodeEntites` n'en défait que deux par appel.
  let decode = brut
  for (let passe = 0; passe < PASSES_MAX; passe++) {
    const suivant = decodeEntites(decode)
    if (suivant === decode) break
    decode = suivant
  }
  decode = decode.replace(/\s+/g, ' ').trim()
  let t = decode
  for (let passe = 0; passe < PASSES_MAX; passe++) {
    const suivant = nettoyeUnePasse(t)
    if (suivant === t) break
    t = suivant
  }
  if (t.length < 3) return decode
  return t[0].toLocaleUpperCase('fr') + t.slice(1)
}
