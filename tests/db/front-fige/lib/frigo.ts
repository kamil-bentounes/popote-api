/**
 * Le frigo : ce que le frigo américain dit, sans aucune requête.
 *
 * Les barquettes se regroupent en PLATS (une carte par recette, lieu et état), les repas posés dessus se
 * lisent en puces (« mar. midi »), et deux phrases sortent de là : celle de l'afficheur du congélateur (le
 * dîner de ce soir) et celle du magnet du frigo (ce qui presse). Pur, donc éprouvé sans base ni navigateur.
 */
import { jour } from './semaine.ts'
import type { Repas } from './semaine.ts'
import { JOURS_AU_CONGELO, JOURS_AU_FRAIS, jourAbrege, pourLeFoyer } from './ranger.ts'
import { rayonDe } from './rayons.ts'
import type { Rayon } from './rayons.ts'
import { plusDeJours, urgence } from './peremption.ts'
import type { Lieu, Urgence } from './peremption.ts'

/** Ce que la fiche et les cartes lisent d'une barquette (une ligne de `portion`). */
export type Part = {
  id: string
  recipe_id: string | null
  label: string
  location: string
  state: string
  grams: number | string
  kcal: number | string
  protein_g: number | string
  prepared_at: string
  frozen_at: string | null
  expires_at: string
  /** Pour qui est cette part (les grammes et les calories ne sont pas les mêmes pour deux personnes) ; `null` : pour n'importe qui. */
  for_user_id?: string | null
}

/** Un repas posé sur une barquette : une ligne `meal_slot` encore « prévue ». */
export type Prevu = {
  id: string
  day: string
  meal: string
  user_profile_id: string
  portion_id: string | null
}

export type Groupe<P extends Part = Part> = {
  cle: string
  recipeId: string | null
  label: string
  /** Le nom court, celui des cartes et de l'afficheur. */
  nom: string
  location: Lieu
  state: string
  /** Les plus pressées d'abord. */
  parts: P[]
}

// ── Les noms ────────────────────────────────────────────────────────────────

/**
 * « Lasagnes au saumon-poireaux » → « Lasagnes saumon-poireaux », « Pizza vietnamienne protéinée » →
 * « Pizza vietnamienne » : les cartes et l'afficheur n'ont pas la place du nom entier (la fiche, si).
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
 * (s, x, z ne changent pas).
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

/**
 * Combien de parts d'un plat, et de quoi : « 2 wraps », « 1 wrap » quand le libellé est UN mot (« Wrap », « Burger »),
 * qu'on sait mettre au pluriel ; « 2 barquettes de petit salé aux lentilles », « 1 barquette de … » sinon. Mettre
 * un « s » au premier mot d'un libellé qui en compte plusieurs disait « les petits retournent au frigo » (petit salé),
 * « 2 pot-au-feus », « 2 gâteaus » (gâteau de patates douces). Devant une voyelle : « d’agneau ».
 * `defini` : « les 2 wraps », « les 2 barquettes de … », « la barquette de … » (une seule part d'un plat qui n'a pas un seul mot) ; une part d'un mot seul reste « 1 wrap ».
 */
export function partsDuPlat(label: string, n: number, defini = false): string {
  const nom = sansProteinee(label)
  const les = defini && n > 1 ? 'les ' : ''
  if (unSeulMot(label)) {
    const mot = nom.toLowerCase()
    return `${les}${n} ${n > 1 ? plurielDuMot(mot) : mot}`
  }
  const bas = nom.replace(/^\p{Lu}/u, c => c.toLowerCase())
  const de = /^[aeiouyàâäéèêëîïôöùûü]/i.test(bas) ? 'd’' : 'de '
  if (n > 1) return `${les}${n} barquettes ${de}${bas}`
  return defini ? `la barquette ${de}${bas}` : `1 barquette ${de}${bas}`
}

// ── Les groupes ─────────────────────────────────────────────────────────────

/** Les barquettes encore là, regroupées par recette, libellé, lieu et état : une carte par plat. */
export function groupeLesParts<P extends Part>(parts: P[]): Groupe<P>[] {
  const par = new Map<string, Groupe<P>>()
  for (const p of parts) {
    if (p.state !== 'au_frais' && p.state !== 'decongelee') continue
    if (p.location !== 'frigo' && p.location !== 'congelateur') continue
    const cle = [p.recipe_id ?? '', p.label, p.location, p.state].join('|')
    let g = par.get(cle)
    if (!g) {
      g = {
        cle, recipeId: p.recipe_id, label: p.label, nom: nomCourt(p.label),
        location: p.location as Lieu, state: p.state, parts: [],
      }
      par.set(cle, g)
    }
    g.parts.push(p)
  }
  const groupes = [...par.values()]
  /* Des égalités départagées par l'identifiant : deux rendus du même foyer rendent le même ordre. */
  for (const g of groupes) g.parts.sort((a, b) => a.expires_at.localeCompare(b.expires_at) || a.id.localeCompare(b.id))
  return groupes.sort((a, b) => a.parts[0].expires_at.localeCompare(b.parts[0].expires_at)
    || a.label.localeCompare(b.label) || a.cle.localeCompare(b.cle))
}

// ── Les repas posés ─────────────────────────────────────────────────────────

const MOT_REPAS: Record<string, string> = {
  petit_dejeuner: 'matin', dejeuner: 'midi', diner: 'soir', collation: 'goûter',
}
const JOUR_SEMAINE = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.']
export const JOUR_ENTIER = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi']

/** « 2026-10-27 » lu en heure locale (jamais `new Date('2026-10-27')`, qui est minuit UTC). */
export function lisLeJour(j: string): Date {
  const [a, m, d] = j.split('-').map(Number)
  return new Date(a, m - 1, d)
}

/** Nombre de jours de calendrier entre aujourd'hui et `j` (négatif : passé). */
export function ecartEnJours(j: string, maintenant: Date): number {
  const a = lisLeJour(j)
  const b = lisLeJour(jour(maintenant))
  return Math.round((a.getTime() - b.getTime()) / 86_400_000)
}

/**
 * « ce soir », « ce midi », sinon « mar. midi » ; au-delà d'une semaine le quantième lève le doute
 * (« lun. 2 midi »).
 */
export function repasEnMots(j: string, repas: string, maintenant: Date): string {
  const mot = MOT_REPAS[repas] ?? repas
  const ecart = ecartEnJours(j, maintenant)
  if (ecart === 0) return repas === 'diner' ? 'ce soir' : repas === 'dejeuner' ? 'ce midi' : `ce ${mot}`
  const d = lisLeJour(j)
  const jr = ecart > 6 || ecart < 0 ? `${JOUR_SEMAINE[d.getDay()]} ${d.getDate()}` : JOUR_SEMAINE[d.getDay()]
  return `${jr} ${mot}`
}

/** Le repas qu'on est en train de vivre : de quoi poser « j'en mange une maintenant ». */
export function repasEnCours(maintenant: Date): Repas {
  const h = maintenant.getHours()
  return h < 10 ? 'petit_dejeuner' : h < 16 ? 'dejeuner' : 'diner'
}

/** Les repas d'aujourd'hui et d'après : un repas posé AVANT aujourd'hui est un repas passé que personne n'a noté, pas une réservation. */
export function prevusAVenir(prevus: Prevu[], maintenant: Date): Prevu[] {
  const j = jour(maintenant)
  return prevus.filter(r => r.day >= j)
}

/** Les repas posés sur les barquettes de ce groupe, dans l'ordre du calendrier. Avec `maintenant`, sans les jours passés. */
export function prevusDe(g: Groupe, prevus: Prevu[], maintenant?: Date): Prevu[] {
  const ids = new Set(g.parts.map(p => p.id))
  return (maintenant ? prevusAVenir(prevus, maintenant) : prevus)
    .filter(r => r.portion_id && ids.has(r.portion_id))
    .sort((a, b) => a.day.localeCompare(b.day) || ordreDuRepas(a.meal) - ordreDuRepas(b.meal) || a.id.localeCompare(b.id))
}

export const ordreDuRepas = (m: string) => ['petit_dejeuner', 'dejeuner', 'collation', 'diner'].indexOf(m)

/**
 * Les barquettes du groupe qu'aucun repas ne réclame. Avec `maintenant`, les réclamations d'avant aujourd'hui
 * ne comptent pas (un repas passé qu'on n'a pas noté ne retient pas sa part).
 */
export function partsLibres<P extends Part>(g: Groupe<P>, prevus: Prevu[], maintenant?: Date): P[] {
  const posees = new Set((maintenant ? prevusAVenir(prevus, maintenant) : prevus).map(r => r.portion_id))
  return g.parts.filter(p => !posees.has(p.id))
}

// ── L'heure des repas, et quand on peut sortir du congélateur ───────────────

/** L'heure où l'on se met à table : de quoi dire si une part sera encore bonne, et quand la sortir. */
const HEURE_DU_REPAS: Record<string, number> = { petit_dejeuner: 8, dejeuner: 12, collation: 16, diner: 19 }

export function momentDuRepas(j: string, repas: string): Date {
  const d = lisLeJour(j)
  d.setHours(HEURE_DU_REPAS[repas] ?? 12, 0, 0, 0)
  return d
}

/**
 * À partir de quand on peut sortir du congélateur une part posée sur ce repas : vingt-quatre heures avant. Une
 * part décongelée se mange dans les 24 h (`tg_portion_peremption`, 0047) : sortie plus tôt, elle périrait
 * avant le repas. Le jour même, c'est donc toujours possible ; la veille, seulement à l'heure du repas.
 */
export function sortableDes(j: string, repas: string): Date {
  return new Date(momentDuRepas(j, repas).getTime() - 24 * 3_600_000)
}

/** « ce soir », « demain soir », sinon « mar. soir » : le repas comme on le dit pour sortir une part. */
export function repasPourSortir(j: string, repas: string, maintenant: Date): string {
  return ecartEnJours(j, maintenant) === 1 ? `demain ${MOT_REPAS[repas] ?? repas}` : repasEnMots(j, repas, maintenant)
}

const majuscule = (t: string) => `${t[0].toUpperCase()}${t.slice(1)}`

/** Le premier repas à venir de ce groupe dont la part peut sortir MAINTENANT (aujourd'hui, ou demain si l'heure y est). */
function premierASortir(g: Groupe, prevus: Prevu[], maintenant: Date): Prevu | null {
  return prevusDe(g, prevus, maintenant).find(r => sortableDes(r.day, r.meal).getTime() <= maintenant.getTime()) ?? null
}

/** Le premier repas de DEMAIN dont la part ne peut pas encore sortir, et l'heure à partir de laquelle elle le peut. */
function premierPlusTard(g: Groupe, prevus: Prevu[], maintenant: Date): { r: Prevu; des: Date } | null {
  const r = prevusDe(g, prevus, maintenant)
    .find(x => ecartEnJours(x.day, maintenant) === 1 && sortableDes(x.day, x.meal).getTime() > maintenant.getTime())
  return r ? { r, des: sortableDes(r.day, r.meal) } : null
}

/**
 * Les parts à sortir du congélateur MAINTENANT : celles posées sur un repas d'aujourd'hui, et sur un repas de
 * demain quand l'heure y est (voir `sortableDes`) ; sinon `null` (c'est à la personne de dire combien).
 */
export function partsASortir<P extends Part>(g: Groupe<P>, prevus: Prevu[], maintenant: Date): P[] | null {
  const prets = prevusDe(g, prevus, maintenant).filter(r => sortableDes(r.day, r.meal).getTime() <= maintenant.getTime())
  const parts = g.parts.filter(p => prets.some(r => r.portion_id === p.id))
  return parts.length > 0 ? parts : null
}

/**
 * « Prévues pour vous deux » / « Prévues pour Kamil » et les puces qui vont avec.
 * Quand les repas n'ont pas tous le même public, la puce le dit (« mar. midi · Kamil ») et le titre reste
 * « Prévues ». Les repas d'avant aujourd'hui n'y sont plus.
 */
export function prevuesPour(
  g: Groupe, prevus: Prevu[], membres: { id: string; prenom: string }[], maintenant: Date,
): { titre: string; puces: string[] } {
  const mes = prevusDe(g, prevus, maintenant)
  const accord = g.parts.length > 1 ? 'Prévues' : 'Prévue'
  if (mes.length === 0) return { titre: accord, puces: [] }
  const parRepas = new Map<string, { j: string; m: string; qui: Set<string> }>()
  for (const r of mes) {
    const k = `${r.day}|${r.meal}`
    if (!parRepas.has(k)) parRepas.set(k, { j: r.day, m: r.meal, qui: new Set() })
    parRepas.get(k)!.qui.add(r.user_profile_id)
  }
  const repas = [...parRepas.values()]
  const tous = membres.length
  const nom = (id: string) => membres.find(m => m.id === id)?.prenom ?? 'quelqu’un'
  const memePublic = repas.every(r => r.qui.size === repas[0].qui.size
    && [...r.qui].every(q => repas[0].qui.has(q)))
  if (memePublic) {
    const qui = [...repas[0].qui]
    const pour = qui.length >= tous && tous > 1
      ? ['', '', 'vous deux', 'vous trois', 'vous quatre'][tous] ?? `vous ${tous}`
      : qui.map(nom).join(' et ')
    return {
      titre: `${accord} pour ${pour}`,
      puces: repas.map(r => repasEnMots(r.j, r.m, maintenant)),
    }
  }
  return {
    titre: accord,
    puces: repas.map(r => {
      const publicDuRepas = r.qui.size >= tous ? '' : ` · ${[...r.qui].map(nom).join(' et ')}`
      return `${repasEnMots(r.j, r.m, maintenant)}${publicDuRepas}`
    }),
  }
}

// ── Ce que disent les cartes ────────────────────────────────────────────────

/** `encre` : la couleur du texte (l'urgence, ou l'ocre d'un geste à faire, ou le doux d'un repos). */
export type Quand = { texte: string; encre: string }

const OCRE = 'var(--color-ocre)'
const DOUX = 'var(--color-doux)'
const GLACE = 'var(--color-congel-encre)'

/**
 * Ce qui presse déjà, et que le calendrier ne rattrape pas : des parts PÉRIMÉES, ou réclamées par un repas
 * d'APRÈS leur péremption. Le mot d'urgence, dans sa couleur — le planning (« mar. midi à mer. midi ») dirait
 * le contraire de ce qui est vrai.
 */
function enRetard(g: Groupe, mes: Prevu[], maintenant: Date): Quand | null {
  const n = g.parts.length
  const perimees = g.parts.filter(p => new Date(p.expires_at).getTime() <= maintenant.getTime())
  if (perimees.length > 0) {
    const u = urgence(perimees[0].expires_at, g.location, maintenant)
    const k = perimees.length
    return { texte: k === n ? u.mot : `${k} périmée${k > 1 ? 's' : ''}`, encre: u.encre }
  }
  let pire: { p: Part; r: Prevu } | null = null
  for (const r of mes) {
    const p = g.parts.find(x => x.id === r.portion_id)
    if (p && momentDuRepas(r.day, r.meal).getTime() > new Date(p.expires_at).getTime()
        && (!pire || p.expires_at < pire.p.expires_at)) pire = { p, r }
  }
  if (!pire) return null
  const u = urgence(pire.p.expires_at, g.location, maintenant)
  return u.niveau !== 'ok'
    ? { texte: u.mot, encre: u.encre }
    : { texte: `périme avant ${repasEnMots(pire.r.day, pire.r.meal, maintenant)}`, encre: OCRE }
}

/**
 * La ligne sous le nom d'une carte : ce qui est périmé ou le sera avant son repas, puis ce qu'il faut sortir,
 * puis le plus pressé, puis ce qui est prévu, puis l'urgence. `prevus` `null` : les repas ne sont pas lus
 * (chargement, erreur) — la carte ne dit que ce que la barquette sait d'elle-même.
 */
export function quand(g: Groupe, prevus: Prevu[] | null, maintenant: Date): Quand {
  const u = urgence(g.parts[0].expires_at, g.location, maintenant)
  const repos = g.location === 'congelateur' ? GLACE : DOUX
  if (prevus === null) return { texte: u.mot, encre: u.niveau !== 'ok' ? u.encre : repos }
  const mes = prevusDe(g, prevus, maintenant)
  const retard = enRetard(g, mes, maintenant)
  if (retard) return retard
  if (g.location === 'congelateur') {
    const pret = premierASortir(g, prevus, maintenant)
    if (pret) {
      return { texte: `${majuscule(repasPourSortir(pret.day, pret.meal, maintenant))} : à sortir maintenant`, encre: OCRE }
    }
    const plusTard = premierPlusTard(g, prevus, maintenant)
    if (plusTard) {
      const { r, des } = plusTard
      return {
        texte: `${majuscule(repasPourSortir(r.day, r.meal, maintenant))} : à sortir dès ${des.getHours()} h`, encre: OCRE,
      }
    }
  }
  const libres = partsLibres(g, prevus, maintenant).length
  if (g.location === 'frigo' && libres > 0 && u.niveau !== 'ok') {
    return { texte: u.mot, encre: u.encre }
  }
  if (mes.length > 0) {
    const premier = repasEnMots(mes[0].day, mes[0].meal, maintenant)
    const dernier = repasEnMots(mes[mes.length - 1].day, mes[mes.length - 1].meal, maintenant)
    return { texte: premier === dernier ? premier : `${premier} à ${dernier}`, encre: repos }
  }
  return { texte: u.mot, encre: u.niveau !== 'ok' ? u.encre : repos }
}

/** Le texte lu par un lecteur d'écran sur la carte : « Lasagnes, 6 parts, mar. midi à mer. midi ». */
export function ariaDeCarte(g: Groupe, q: Quand): string {
  const n = g.parts.length
  return `${g.nom}, ${n} part${n > 1 ? 's' : ''}, ${q.texte}`
}

// ── La porte gauche : l'afficheur ───────────────────────────────────────────

export type Afficheur = { titre: string; plat: string | null }

/**
 * Ce que l'afficheur du congélateur dit : le dîner de ce soir pour cette personne, ou rien.
 * `prevus` `null` : les repas ne sont pas lus — on ne dit pas « rien de prévu » de ce qu'on n'a pas lu.
 */
export function afficheur(prevus: Prevu[] | null, parts: Part[], moi: string, maintenant: Date): Afficheur {
  if (prevus === null) return { titre: 'Indisponible', plat: null }
  const j = jour(maintenant)
  const mien = prevus.find(r => r.user_profile_id === moi && r.day === j && r.meal === 'diner' && r.portion_id)
  const part = mien && parts.find(p => p.id === mien.portion_id)
  return part
    ? { titre: 'Ce soir', plat: nomCourt(part.label) }
    : { titre: 'Rien de prévu ce soir', plat: null }
}

// ── La porte droite : le magnet ─────────────────────────────────────────────

export type Magnet = { texte: string; sorsLesAujourdhui: boolean }

/**
 * Le plus pressé, et un seul :
 *  1. des barquettes congelées posées sur un repas d'aujourd'hui, ou de demain quand on peut déjà les sortir
 *     (voir `sortableDes`) : « Sors les 2 burgers : c'est ce soir », « … : c'est demain soir » — le repas
 *     nommé, c'est ce qui se fait la veille ;
 *  2. sinon, des barquettes du frigo périmées (« 2 pizzas à jeter »), ou qui périment sous 72 h et que rien ne
 *     réclame : « 2 pizzas à prévoir avant jeudi » ;
 *  3. sinon rien : pas de magnet. Les repas pas lus (`null`) : pas de magnet non plus — on ne dirait pas
 *     « libre » d'une part que des repas réclament peut-être.
 * À urgence égale, le nom du plat départage : deux rendus du même foyer disent la même chose.
 */
export function magnet(parts: Part[], prevus: Prevu[] | null, maintenant: Date): Magnet | null {
  if (prevus === null) return null
  const groupes = groupeLesParts(parts)
  const congeles = groupes.filter(g => g.location === 'congelateur')
    .map(g => ({ g, r: premierASortir(g, prevus, maintenant), bientot: partsASortir(g, prevus, maintenant) ?? [] }))
    .filter((x): x is { g: Groupe; r: Prevu; bientot: Part[] } => x.r !== null && x.bientot.length > 0)
    .sort((a, b) =>
      momentDuRepas(a.r.day, a.r.meal).getTime() - momentDuRepas(b.r.day, b.r.meal).getTime()
      || a.g.label.localeCompare(b.g.label) || a.g.cle.localeCompare(b.g.cle))
  if (congeles.length > 0) {
    const { g, r, bientot } = congeles[0]
    const n = bientot.length
    return {
      texte: `Sors ${partsDuPlat(g.label, n, true)} : c’est ${repasPourSortir(r.day, r.meal, maintenant)}`,
      sorsLesAujourdhui: ecartEnJours(r.day, maintenant) === 0,
    }
  }
  const limite = maintenant.getTime() + 72 * 3_600_000
  const presses = groupes.filter(g => g.location === 'frigo')
    .map(g => ({
      g,
      libres: partsLibres(g, prevus, maintenant).filter(p => new Date(p.expires_at).getTime() <= limite),
    }))
    .filter(x => x.libres.length > 0)
    .sort((a, b) => a.libres[0].expires_at.localeCompare(b.libres[0].expires_at)
      || a.g.label.localeCompare(b.g.label) || a.g.cle.localeCompare(b.g.cle))
  if (presses.length > 0) {
    const { g, libres } = presses[0]
    const perimees = libres.filter(p => new Date(p.expires_at).getTime() <= maintenant.getTime())
    if (perimees.length > 0) {
      const k = perimees.length
      return { texte: `${partsDuPlat(g.label, k)} à jeter`, sorsLesAujourdhui: false }
    }
    const n = libres.length
    return { texte: `${partsDuPlat(g.label, n)} à prévoir avant ${avant(new Date(libres[0].expires_at), maintenant)}`, sorsLesAujourdhui: false }
  }
  return null
}

/** « ce soir », « demain », ou le jour de la semaine : « avant jeudi ». */
export function avant(fin: Date, maintenant: Date): string {
  const e = ecartEnJours(jour(fin), maintenant)
  if (e <= 0) return 'ce soir'
  if (e === 1) return 'demain'
  return JOUR_ENTIER[fin.getDay()]
}

// ── La fiche ────────────────────────────────────────────────────────────────

const DANS_LES_24_H = 'une part décongelée se mange dans les 24 heures'

/** `n` barquettes : « sors-les », « sors-la » quand il n'y en a qu'une. */
const sorsLes = (n: number) => `sors-${n > 1 ? 'les' : 'la'}`

/** « C'est pour ce soir : sors-les maintenant, ou passe-les au micro-ondes avant de manger. » */
export function noteDuSoir(n: number): string {
  return `C’est pour ce soir : ${sorsLes(n)} maintenant, ou passe-${n > 1 ? 'les' : 'la'} au micro-ondes avant de manger.`
}

/** « C'est pour ce soir : … » quand des barquettes encore congelées sont posées sur un repas d'aujourd'hui. */
export const NOTE_DU_SOIR = noteDuSoir(2)

/**
 * La note de la fiche d'un plat congelé : pour ce soir, sors-les ; pour demain, à partir de quand — une part
 * décongelée se mange dans les 24 heures, sortie le matin elle périrait avant le dîner du lendemain.
 */
export function noteDeLaFiche(g: Groupe, prevus: Prevu[], maintenant: Date): string {
  if (g.location !== 'congelateur') return ''
  const mes = prevusDe(g, prevus, maintenant)
  const ceSoir = mes.filter(r => ecartEnJours(r.day, maintenant) === 0)
  if (ceSoir.length > 0) return noteDuSoir(new Set(ceSoir.map(r => r.portion_id)).size)
  const demain = mes.find(r => ecartEnJours(r.day, maintenant) === 1)
  if (!demain) return ''
  const n = new Set(mes.filter(r => r.day === demain.day && r.meal === demain.meal).map(r => r.portion_id)).size
  return noteDeSortie(demain.day, demain.meal, maintenant, n)
}

/**
 * La phrase du repas de DEMAIN : sors-les maintenant si l'heure y est, sinon à partir de quand. Le frigo (la fiche
 * d'un plat) et la semaine (le bandeau bleu d'un repas) la disent de la même façon, avec les mêmes mots ; `n`
 * barquettes sont posées sur ce repas (« sors-la » pour une seule).
 */
export function noteDeSortie(j: string, repas: string, maintenant: Date, n = 2): string {
  const des = sortableDes(j, repas)
  const pour = repasPourSortir(j, repas, maintenant)
  return des.getTime() <= maintenant.getTime()
    ? `C’est pour ${pour} : ${sorsLes(n)} maintenant, ${DANS_LES_24_H}.`
    : `C’est pour ${pour} : ${sorsLes(n)} à partir de ${des.getHours()} h, ${DANS_LES_24_H}.`
}

/**
 * Ce que pèse une part, dit comme il faut : « 784 g, 682 kcal et 56 g de protéines la part » quand toutes les
 * parts sont pareilles ; sinon une ligne PAR PERSONNE (« Kamil : 784 g, 682 kcal, 56 g de protéines ») — les
 * portions sont faites pour quelqu'un (`for_user_id`), et une moyenne ne serait la part de personne.
 */
export function macrosDuGroupe(g: Groupe, membres: { id: string; prenom: string }[] = []): string[] {
  const dit = (p: Part) =>
    `${Math.round(Number(p.grams))} g, ${Math.round(Number(p.kcal))} kcal, ${Math.round(Number(p.protein_g))} g de protéines`
  const distinctes = new Set(g.parts.map(dit))
  if (distinctes.size <= 1) {
    const p = g.parts[0]
    return [`${Math.round(Number(p.grams))} g, ${Math.round(Number(p.kcal))} kcal et ${Math.round(Number(p.protein_g))} g de protéines la part`]
  }
  const parQui = new Map<string | null, Set<string>>()
  for (const p of g.parts) {
    const k = p.for_user_id ?? null
    if (!parQui.has(k)) parQui.set(k, new Set())
    parQui.get(k)!.add(dit(p))
  }
  const rang = (k: string | null) => k === null ? 1e6 : (i => i < 0 ? 1e5 : i)(membres.findIndex(m => m.id === k))
  return [...parQui.entries()]
    .sort(([a], [b]) => rang(a) - rang(b))
    .map(([k, valeurs]) => {
      const nom = k === null ? 'Pour tous' : membres.find(m => m.id === k)?.prenom ?? 'quelqu’un'
      return `${nom} : ${[...valeurs].join(' ou ')}`
    })
}

/** Un nombre choisi dans `Combien`, ramené entre 1 et `max` : le groupe peut rétrécir pendant qu'on décide. */
export function borne(n: number, max: number): number {
  return Math.max(1, Math.min(n, Math.max(1, max)))
}

// ── Les repas qui lâchent leur part ─────────────────────────────────────────

const GENRE_REPAS: Record<string, string> = {
  petit_dejeuner: 'le petit déjeuner', dejeuner: 'le déjeuner', diner: 'le dîner', collation: 'la collation',
}

/**
 * « Le dîner de dimanche n'a plus de barquette. » : les repas qu'un geste vient de priver de leur part
 * (la base les rend). Pour un repas d'un autre membre, son prénom suit. `''` sans repas libéré.
 */
export function phraseDesRepasLibres(
  libres: { day: string; meal: string; user_profile_id: string }[],
  moi: string, membres: { id: string; prenom: string }[], maintenant: Date,
): string {
  if (libres.length === 0) return ''
  const dits = libres.map(l => {
    const e = ecartEnJours(l.day, maintenant)
    const d = lisLeJour(l.day)
    const quand = e === 0 ? 'd’aujourd’hui' : e === 1 ? 'de demain'
      : `de ${JOUR_ENTIER[d.getDay()]}${e > 6 ? ` ${d.getDate()}` : ''}`
    const qui = l.user_profile_id === moi ? '' : ` (${membres.find(m => m.id === l.user_profile_id)?.prenom ?? 'quelqu’un'})`
    return `${GENRE_REPAS[l.meal] ?? l.meal} ${quand}${qui}`
  })
  const liste = dits.length > 1 ? `${dits.slice(0, -1).join(', ')} et ${dits[dits.length - 1]}` : dits[0]
  return `${majuscule(liste)} ${dits.length > 1 ? 'n’ont' : 'n’a'} plus de barquette.`
}

/**
 * La date de péremption que la base poserait (`tg_portion_peremption`, migration 0047) : quatre jours après
 * la préparation au frigo, quatre-vingt-dix après la mise au congélateur. Le front la recalcule quand on
 * corrige « Au frigo depuis » ou « Congelés le », exactement comme le ferait le trigger à l'insertion — un
 * UPDATE, lui, ne touche pas à `expires_at` si on la lui donne.
 *
 * Une barquette DÉCONGELÉE ne suit pas cette règle (elle se mange dans les 24 h de la décongélation, pas
 * quatre jours après la préparation) : `null`, on ne recalcule rien.
 */
export function peremptionApres(lieu: Lieu, etat: string, debut: Date): Date | null {
  if (lieu === 'congelateur') return plusDeJours(debut, JOURS_AU_CONGELO)
  if (etat === 'decongelee') return null
  return plusDeJours(debut, JOURS_AU_FRAIS)
}

export type ChampsDates = { prepared_at?: string; frozen_at?: string; expires_at?: string }

/**
 * Ce qu'il faut ÉCRIRE pour que les parts d'un groupe aient ces dates — et seulement ce qui change, part par
 * part. Écrire la même date sur toutes réécrasait des péremptions DIFFÉRENTES (deux parts rangées à des
 * heures différentes) par celle de la première, même quand on n'avait rien changé. Les parts qui demandent
 * la même écriture sont regroupées : une requête. `expiresParJour` : « À manger avant » se saisit au jour près,
 * une part déjà ce jour-là garde son heure.
 */
export function ecrituresDesDates(
  parts: Part[], voulu: ChampsDates, { expiresParJour = false }: { expiresParJour?: boolean } = {},
): { ids: string[]; champs: ChampsDates }[] {
  const lots = new Map<string, { ids: string[]; champs: ChampsDates }>()
  for (const p of parts) {
    const champs: ChampsDates = {}
    for (const k of ['prepared_at', 'frozen_at', 'expires_at'] as const) {
      const v = voulu[k]
      if (v === undefined) continue
      const actuel = p[k]
      const pareil = actuel != null && (k === 'expires_at' && expiresParJour
        ? jour(new Date(actuel)) === jour(new Date(v))
        : new Date(actuel).getTime() === new Date(v).getTime())
      if (!pareil) champs[k] = v
    }
    if (Object.keys(champs).length === 0) continue
    const cle = JSON.stringify(champs)
    const lot = lots.get(cle)
    if (lot) lot.ids.push(p.id)
    else lots.set(cle, { ids: [p.id], champs })
  }
  return [...lots.values()]
}

/**
 * La péremption d'un INGRÉDIENT qu'on déplace, comme celle d'une barquette (`tg_portion_peremption`) :
 *  · vers le congélateur : trois mois à partir de maintenant ;
 *  · du congélateur au frigo : une décongélation, vingt-quatre heures ;
 *  · du congélateur au placard : plus de date (sortie du froid, la date de congélation ne dit plus rien) ;
 *  · entre le frigo et le placard : la date saisie reste, c'est celle de l'emballage.
 * `null` : on ne touche pas à `expires_at`.
 */
export function peremptionDeplacee(de: string, vers: string, maintenant: Date): { expires_at: string | null } | null {
  if (de === vers) return null
  if (vers === 'congelateur') return { expires_at: plusDeJours(maintenant, JOURS_AU_CONGELO).toISOString() }
  if (de === 'congelateur') {
    return { expires_at: vers === 'frigo' ? plusDeJours(maintenant, 1).toISOString() : null }
  }
  return null
}

export type Presse = { label: string; n: number; u: Urgence }

/**
 * « À manger bientôt » : ce qui presse, plat par plat. Deux barquettes du même plat qui pressent pareil
 * (« Burger de feuilles de riz — à manger aujourd'hui » deux fois) font UNE ligne et un nombre. Le plus
 * pressé d'abord, `max` plats au plus.
 */
export function pressesGroupees(
  barquettes: { label: string; expires_at: string; location: string }[], maintenant: Date, max = 2,
): Presse[] {
  const groupes = new Map<string, Presse>()
  for (const b of barquettes) {
    const u = urgence(b.expires_at, b.location === 'congelateur' ? 'congelateur' : 'frigo', maintenant)
    if (u.niveau === 'ok') continue
    const cle = `${b.label}|${u.mot}`
    const g = groupes.get(cle)
    if (g) { g.n += 1; if (u.heuresRestantes < g.u.heuresRestantes) g.u = u } else groupes.set(cle, { label: b.label, n: 1, u })
  }
  return [...groupes.values()].sort((a, b) => a.u.heuresRestantes - b.u.heuresRestantes).slice(0, max)
}

/** La ligne « À manger avant » : la date, et au frigo ce qu'en dit l'urgence (« jeu. 29 oct., encore 3 jours »). */
export function auPlusTard(g: Groupe, maintenant: Date): string {
  const fin = new Date(g.parts[0].expires_at)
  const date = jourAbrege(fin)
  return g.location === 'frigo' ? `${date}, ${urgence(fin, 'frigo', maintenant).mot}` : date
}

/**
 * Les parts à bouger pour « Congeler » ou « Jeter » : les libres d'abord, puis celles posées le plus tard. Avec
 * `maintenant`, un repas d'avant aujourd'hui ne réclame plus sa part.
 */
export function partsAChoisir<P extends Part>(g: Groupe<P>, prevus: Prevu[], n: number, maintenant?: Date): P[] {
  const libres = partsLibres(g, prevus, maintenant)
  const dernier = new Map<string, string>()
  for (const r of maintenant ? prevusAVenir(prevus, maintenant) : prevus) {
    if (!r.portion_id) continue
    const v = `${r.day}|${ordreDuRepas(r.meal)}`
    if (!dernier.has(r.portion_id) || v > dernier.get(r.portion_id)!) dernier.set(r.portion_id, v)
  }
  const posees = g.parts.filter(p => dernier.has(p.id))
    .sort((a, b) => dernier.get(b.id)!.localeCompare(dernier.get(a.id)!) || a.id.localeCompare(b.id))
  return [...libres, ...posees].slice(0, n)
}

// ── Les ingrédients ─────────────────────────────────────────────────────────

export type Etagere = 'Laitages et frais' | 'Viandes et poissons' | 'Autres' | 'Bac à légumes'

const LAITAGE = /yaourt|yogourt|skyr|fromage|\blaits?\b|crème|creme|beurre|œuf|oeuf|faisselle|kéfir|kefir|mozzarella|jambon|lardon/i

/**
 * L'étagère d'un ingrédient du frigo : le rayon du magasin (`rayonDe`) dit où il vit — les laitages et le
 * frais ensemble, la viande et le poisson, le reste — et les fruits et légumes vont au bac.
 * Un yaourt sans aliment connu n'a pas de groupe : son nom le range (« Yaourts dessert protéinés »).
 */
export function etagereDe(
  item: { label: string; groupe?: string | null; sousGroupe?: string | null },
): Etagere {
  let rayon: Rayon = rayonDe({ groupe: item.groupe, sousGroupe: item.sousGroupe, libelle: item.label })
  if (rayon === 'Autre' && LAITAGE.test(item.label)) rayon = 'Frais'
  if (rayon === 'Frais') return 'Laitages et frais'
  if (rayon === 'Boucherie, poissonnerie') return 'Viandes et poissons'
  if (rayon === 'Fruits et légumes') return 'Bac à légumes'
  return 'Autres'
}

export const ORDRE_DES_ETAGERES: Etagere[] = ['Laitages et frais', 'Viandes et poissons', 'Autres', 'Bac à légumes']

/** « 8 parts prêtes, et des yaourts » : le sous-titre de l'intérieur du frigo. */
export function soustitreDuFrigo(parts: number, ingredients: number): string {
  const p = parts > 0 ? `${parts} part${parts > 1 ? 's' : ''} prête${parts > 1 ? 's' : ''}` : ''
  const i = ingredients > 0 ? `${ingredients} ingrédient${ingredients > 1 ? 's' : ''}` : ''
  if (p && i) return `${p}, et ${i}`
  return p || i || 'Vide pour l’instant'
}

/** « 22 parts, jusqu'en janvier » : le sous-titre de l'intérieur du congélateur. */
export function soustitreDuCongelo(parts: number, plusTard: Date | null): string {
  if (parts === 0) return 'Vide pour l’instant'
  const mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
    'octobre', 'novembre', 'décembre']
  return `${parts} part${parts > 1 ? 's' : ''}${plusTard ? `, jusqu’en ${mois[plusTard.getMonth()]}` : ''}`
}

// ── Pour qui ────────────────────────────────────────────────────────────────

/**
 * « vous deux », « toi », « Thauba », « Kamil et Thauba » : pour qui un repas est posé, vu de `moi`.
 * Tout le foyer (à plusieurs) se dit comme `pourLeFoyer`.
 */
export function pourQui(
  convives: string[], membres: { id: string; prenom: string }[], moi: string,
): string {
  const ids = [...new Set(convives)]
  if (ids.length > 1 && ids.length >= membres.length) return pourLeFoyer(membres.length)
  if (ids.length === 1) return ids[0] === moi ? 'toi' : membres.find(m => m.id === ids[0])?.prenom ?? 'quelqu’un'
  return ids.map(i => membres.find(m => m.id === i)?.prenom ?? 'quelqu’un').join(' et ')
}

/** Les repas d'un jour dits comme « midi et soir », « midi », « soir » (dans l'ordre de la journée). */
export function repasDuJour(repas: string[]): string {
  const ordre = ['petit_dejeuner', 'dejeuner', 'collation', 'diner']
  const mots = [...new Set(repas)].sort((a, b) => ordre.indexOf(a) - ordre.indexOf(b))
    .map(r => MOT_REPAS[r] ?? r)
  return mots.length > 1 ? `${mots.slice(0, -1).join(', ')} et ${mots[mots.length - 1]}` : mots[0] ?? ''
}

// ── Les couleurs de ce qui n'a pas de photo ─────────────────────────────────

const TEINTES = ['#EADBC2', '#F1E2C6', '#F6EAD2', '#E6DCCF', '#EFE3CB']
/** Le fond d'un plat sans photo : une teinte chaude, toujours la même pour le même nom. */
export function fondDuPlat(label: string): string {
  let h = 0
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return TEINTES[h % TEINTES.length]
}

