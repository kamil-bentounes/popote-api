/**
 * Les mots des mails : l'accord au nombre, les dates à la française (heure de Paris), l'échappement.
 * Pur : aucun accès à Deno, à la base ni au réseau.
 */

const FUSEAU = 'Europe/Paris'

/** Tout ce qui vient de la base (un nom de plat, un prénom) passe par ici avant d'entrer dans du HTML. */
export function echappe(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

export const majuscule = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t)
const minuscule = (t: string) => (t ? t[0].toLowerCase() + t.slice(1) : t)

/**
 * « Lasagnes au saumon-poireaux » → « Lasagnes saumon-poireaux ». COPIE de `nomCourt` (src/lib/frigo.ts) : le
 * bundle d'une fonction ne contient que son dossier, il ne peut pas importer le front.
 */
export function nomCourt(label: string): string {
  const court = label.trim()
    .replace(/\s+(?:au|aux|à la|à l[’'])\s+/i, ' ')
    .replace(/\s+prot[ée]in[ée]e?s?$/i, '')
    .replace(/\s{2,}/g, ' ')
  return court || label.trim()
}

/**
 * Le pluriel d'UN mot : « wrap » → « wraps », « gâteau » → « gâteaux » ; « pizzas », « burgers », « choux » restent
 * (s, x, z ne changent pas). COPIE de `plurielDuMot` (src/lib/frigo.ts du dépôt principal).
 */
function plurielDuMot(mot: string): string {
  if (/[sxz]$/.test(mot)) return mot
  if (/(?:eau|au)$/.test(mot)) return `${mot}x`
  return `${mot}s`
}

/* Le « protéinée » des recettes du foyer n'ajoute rien à l'oreille (c'est aussi ce que `nomCourt` retire). */
const sansProteinee = (label: string) => label.trim().replace(/\s+prot[ée]in[ée]e?s?$/i, '')

/** Un libellé d'un seul mot (« Wrap »), qu'on sait mettre au pluriel : ni espace ni trait d'union (« pot-au-feu »). */
export const unSeulMot = (label: string): boolean => !/[\s-]/.test(sansProteinee(label))

/** « de » devant un nom : « d’agneau », « de lasagnes ». */
function de(mot: string): string {
  return /^[aeiouyàâäéèêëîïôöùûü]/i.test(mot) ? 'd’' : 'de '
}

/**
 * Combien de parts d'un plat, et de quoi : « 2 wraps », « 1 wrap » quand le libellé est UN mot (« Wrap », « Burger »),
 * qu'on sait mettre au pluriel ; « 2 barquettes de petit salé aux lentilles », « 1 barquette de … » sinon. Mettre
 * un « s » au premier mot d'un libellé qui en compte plusieurs disait « les petits retournent au frigo » (petit salé),
 * « 2 pot-au-feus », « 2 gâteaus ». `defini` : « les 2 wraps », « les 2 barquettes de … », « la barquette de … » (une
 * seule part d'un plat qui n'a pas un seul mot) ; une part d'un mot seul reste « 1 wrap ».
 *
 * C'est LA règle de `partsDuPlat` (src/lib/frigo.ts), mot pour mot. Le bundle d'une fonction ne contient que son
 * dossier : on la copie, et `src/lib/accord-au-nombre.test.ts` fait répondre les deux copies aux mêmes libellés.
 */
export function partsDuPlat(label: string, n: number, defini = false): string {
  const nom = sansProteinee(label)
  const les = defini && n > 1 ? 'les ' : ''
  if (unSeulMot(label)) {
    const mot = nom.toLowerCase()
    return `${les}${n} ${n > 1 ? plurielDuMot(mot) : mot}`
  }
  const bas = nom.replace(/^\p{Lu}/u, c => c.toLowerCase())
  if (n > 1) return `${les}${n} barquettes ${de(bas)}${bas}`
  return defini ? `la barquette ${de(bas)}${bas}` : `1 barquette ${de(bas)}${bas}`
}

/** Un prénom, normalisé comme la base (`rappel_prenom`) : le premier mot, 40 signes au plus, un repli s'il est vide. */
export function prenomSur(nom: unknown, repli: string): string {
  const mot = String(nom ?? '').trim().split(/\s+/)[0].slice(0, 40)
  return mot || repli
}

/** « 1 barquette », « 3 barquettes ». */
export const barquettes = (n: number) => `${n} barquette${n > 1 ? 's' : ''}`

/**
 * « la barquette de petit salé aux lentilles », « les 3 barquettes de lasagnes », « la barquette d’agneau ».
 * Le nom du plat est entier (la fiche, pas la carte) et passe en minuscule.
 */
export function laBarquetteDe(label: string, n: number): string {
  const nom = minuscule(sansProteinee(label))
  return n > 1 ? `les ${n} barquettes ${de(nom)}${nom}` : `la barquette ${de(nom)}${nom}`
}

// ── Les dates, à l'heure de Paris ───────────────────────────────────────────

type Parties = { annee: number; mois: number; jour: number; heure: number; semaine: number }

/** L'heure de Paris d'un instant : année, mois (1-12), jour, heure, jour de la semaine (0 = dimanche). */
export function parisDe(d: Date): Parties {
  const p = new Intl.DateTimeFormat('en-US', {
    timeZone: FUSEAU, year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', hourCycle: 'h23',
    weekday: 'short',
  }).formatToParts(d)
  const v = (t: string) => p.find(x => x.type === t)?.value ?? ''
  const semaine = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(v('weekday'))
  return { annee: Number(v('year')), mois: Number(v('month')), jour: Number(v('day')), heure: Number(v('hour')), semaine }
}

export const JOURS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi']
export const JOURS_COURTS = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.']
export const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
  'octobre', 'novembre', 'décembre']
const MOIS_COURTS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']

/** Une donnée de la base qui n'a pas la forme promise arrête le mail : mieux vaut ne rien envoyer que « NaN ». */
export function exige(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Données de rappel invalides : ${message}`)
}
export const estUnJour = (j: unknown): j is string => typeof j === 'string' && /^\d{4}-\d{2}-\d{2}/.test(j)

export const premier = (j: number) => (j === 1 ? '1er' : String(j))

/** « 2030-06-12 » lu comme un JOUR (jamais comme un instant : pas de fuseau en jeu). */
export function lisLeJour(iso: string): { annee: number; mois: number; jour: number; semaine: number } {
  const [a, m, j] = iso.slice(0, 10).split('-').map(Number)
  return { annee: a, mois: m, jour: j, semaine: new Date(Date.UTC(a, m - 1, j, 12)).getUTCDay() }
}

/** « mercredi 12 juin ». */
export function jourEnToutesLettres(iso: string): string {
  const d = lisLeJour(iso)
  return `${JOURS[d.semaine]} ${premier(d.jour)} ${MOIS[d.mois - 1]}`
}

/** « juin » : le mois d'un jour ISO (« 2030-06-01 »). */
export const moisEnToutesLettres = (iso: string) => MOIS[lisLeJour(iso).mois - 1]

/** « de juin », « d’avril », « d’août » : le mois après « le budget ». */
export function deMois(iso: string): string {
  const m = moisEnToutesLettres(iso)
  return `${de(m)}${m}`
}

/** « mercredi 28 oct., 19 h » : le coin du mail, l'heure de Paris à laquelle il part. */
export function quandEnvoye(d: Date): string {
  const p = parisDe(d)
  return `${JOURS[p.semaine]} ${premier(p.jour)} ${MOIS_COURTS[p.mois - 1]}, ${p.heure} h`
}

/** Le jour ISO (heure de Paris) d'un instant. */
export function jourDeParis(d: Date): string {
  const p = parisDe(d)
  return `${p.annee}-${String(p.mois).padStart(2, '0')}-${String(p.jour).padStart(2, '0')}`
}

/** Combien de jours entre deux jours ISO (b - a). */
export function ecartJours(a: string, b: string): number {
  const x = lisLeJour(a), y = lisLeJour(b)
  return Math.round((Date.UTC(y.annee, y.mois - 1, y.jour) - Date.UTC(x.annee, x.mois - 1, x.jour)) / 86_400_000)
}

/**
 * Le moment où une barquette périme, dit comme on le dit : « ce soir », « demain matin », « jeudi soir ».
 * `maintenant` fixe ce que « demain » veut dire.
 */
export function momentDePeremption(expire: Date, maintenant: Date): { mots: string; pastille: string } {
  const p = parisDe(expire)
  const partie = p.heure < 12 ? 'matin' : p.heure < 18 ? 'après-midi' : 'soir'
  const ecart = ecartJours(jourDeParis(maintenant), jourDeParis(expire))
  const heure = `${p.heure} h`
  if (ecart <= 0) return { mots: partie === 'après-midi' ? 'cet après-midi' : `ce ${partie}`, pastille: `Aujourd’hui, ${heure}` }
  if (ecart === 1) return { mots: `demain ${partie}`, pastille: `Demain, ${heure}` }
  return { mots: `${JOURS[p.semaine]} ${partie}`, pastille: `${majuscule(JOURS[p.semaine])}, ${heure}` }
}

/** « 82,40 € », « 1 420 € » : des euros, avec des espaces qui ne coupent pas. */
export function euros(cents: number): string {
  const v = cents / 100
  const entier = Number.isInteger(v)
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency', currency: 'EUR', minimumFractionDigits: entier ? 0 : 2, maximumFractionDigits: 2,
  }).format(v)
}

/** « Kamil et Léa », « vous deux », « toi » : pour qui, vu du destinataire. */
export function pourDit(pour: string[], destinataire: string): string {
  const noms = [...new Set(pour)]
  if (noms.length === 0) return ''
  if (noms.length === 1) return noms[0] === destinataire ? 'pour toi' : `pour ${noms[0]}`
  if (noms.length === 2 && noms.includes(destinataire)) return 'pour vous deux'
  return `pour ${noms.slice(0, -1).join(', ')} et ${noms[noms.length - 1]}`
}

/** Les moments d'un repas, comme on le dit : « midi », « soir ». */
export const MOT_DU_REPAS: Record<string, { titre: string; mot: string }> = {
  petit_dejeuner: { titre: 'Matin', mot: 'matin' },
  dejeuner: { titre: 'Midi', mot: 'midi' },
  collation: { titre: 'Goûter', mot: 'goûter' },
  diner: { titre: 'Soir', mot: 'soir' },
}

/** « midi », « midi et soir », « matin, midi et soir » : ce qui suit « demain ». */
export function listeDeRepas(repas: string[]): string {
  const mots = repas.map(r => MOT_DU_REPAS[r]?.mot ?? r)
  return mots.length <= 1 ? (mots[0] ?? '') : `${mots.slice(0, -1).join(', ')} et ${mots[mots.length - 1]}`
}

/**
 * La typographie française : une espace avant « : », « ? », « ! », « » », après « « », et entre un nombre et son
 * unité (« 16 wraps », « 19 h ») ne coupe jamais une ligne. Appliquée au TEXTE seulement, jamais dans une balise :
 * `margin:0 auto` ne doit pas changer.
 */
export function insecables(html: string): string {
  const typo = (t: string) => t
    .replace(/« /g, '«&nbsp;').replace(/ »/g, '&nbsp;»')
    .replace(/ ([?:!;])/g, '&nbsp;$1')
    .replace(/(\d) (?=[A-Za-zÀ-ÿ€%])/g, '$1&nbsp;')
  /* Une feuille de style est du texte entre deux balises, elle aussi : `!important` ne doit pas changer. */
  return html.split(/(<style[\s\S]*?<\/style>)/).map(morceau =>
    morceau.startsWith('<style') ? morceau
      : morceau.replace(/(>)([^<]+)(<)/g, (_m, a: string, t: string, b: string) => a + typo(t) + b)).join('')
}
