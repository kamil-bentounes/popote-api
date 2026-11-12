/**
 * Extraction d'une recette depuis une page web (D12).
 *
 * Presque tous les sites de cuisine publient un bloc `application/ld+json` au
 * format `schema.org/Recipe` — parce que c'est ce qui leur donne les vignettes
 * de Google. On lit CE bloc, jamais le HTML : il est structuré, stable, et
 * légalement destiné à être lu par des machines.
 *
 * Mesuré : 98 % de pages exploitables sur le corpus.
 */

import { decodeEntites } from './partage/texte.ts'

export interface RecetteBrute {
  url: string
  titre: string | null
  source: string | null
  parts: number | null
  totalMin: number | null
  prepMin: number | null
  cuissonMin: number | null
  ingredients: string[]
  etapes: string[]
  licence: string | null
  /** La photo du site, en LIEN : rien n'est copié chez nous (R3). */
  image: string | null
}

/** Parcourt un JSON quelconque et rend tous les objets de type `Recipe`. */
export function* recettesDans(o: unknown): Generator<Record<string, unknown>> {
  if (Array.isArray(o)) {
    for (const v of o) yield* recettesDans(v)
    return
  }
  if (o && typeof o === 'object') {
    const t = (o as Record<string, unknown>)['@type']
    if (t === 'Recipe' || (Array.isArray(t) && t.includes('Recipe'))) {
      yield o as Record<string, unknown>
    }
    for (const v of Object.values(o as Record<string, unknown>)) yield* recettesDans(v)
  }
}

/** Les blocs ld+json d'une page, ceux qui se parsent. */
export function blocsJsonLd(html: string): unknown[] {
  const blocs: unknown[] = []
  for (const m of html.matchAll(
    /<script[^>]*application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      blocs.push(JSON.parse(m[1].trim()))
    } catch {
      // Un bloc mal formé n'est pas une erreur de page : les sites en publient
      // régulièrement, et les autres blocs restent exploitables.
    }
  }
  return blocs
}

/** `PT1H30M`, `PT25M`, `P0DT0H45M` — la durée ISO 8601 de schema.org. */
export function dureeIso(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v !== 'string') return null
  const m = v.match(/P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?/i)
  if (!m || (!m[1] && !m[2] && !m[3])) return null
  return (Number(m[1] ?? 0) * 1440) + (Number(m[2] ?? 0) * 60) + Number(m[3] ?? 0)
}

/** `recipeYield` s'écrit « 4 », « 4 personnes », « pour 6 », « 4 parts ». */
export function parts(v: unknown): number | null {
  const liste = Array.isArray(v) ? v : [v]
  for (const x of liste) {
    if (typeof x === 'number' && x > 0) return Math.round(x)
    if (typeof x !== 'string') continue

    /*
     * ⚠️ Prendre le PREMIER nombre est faux sur la forme la plus courante des
     *    tartes, quiches et cakes français : « 1 tarte pour 8 personnes »
     *    rendait 1, donc des macros multipliées par huit.
     *
     *    On cherche d'abord le nombre qui porte le mot « personne » ou « part » ;
     *    à défaut seulement, le premier nombre plausible.
     */
    const nomme = x.match(/(\d+)\s*(?:à\s*\d+\s*)?(?:personnes?|parts?|portions?|convives?)/i)
    if (nomme) {
      const n = Number(nomme[1])
      if (n > 0 && n <= 50) return n
    }
    const apres = x.match(/pour\s+(\d+)/i)
    if (apres) {
      const n = Number(apres[1])
      if (n > 0 && n <= 50) return n
    }
    const m = x.match(/(\d+)/)
    if (m) {
      const n = Number(m[1])
      // Au-delà, ce n'est plus un nombre de parts : c'est un poids ou un volume.
      if (n > 0 && n <= 50) return n
    }
  }
  return null
}

function texte(v: unknown): string | null {
  if (typeof v === 'string') return decodeEntites(v).trim() || null
  if (Array.isArray(v)) return texte(v[0])
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    return texte(o.name ?? o['@id'] ?? o.text)
  }
  return null
}

/** `recipeInstructions` : chaîne, liste de chaînes, HowToStep, HowToSection. */
export function etapes(v: unknown): string[] {
  const sorties: string[] = []
  // `s` est DÉJÀ décodé : `texte()` décode ce qu'il rend, et `visite` décode les
  // chaînes qu'il reçoit. Décoder ici aussi ferait deux passes de plus sur un
  // `HowToStep` que sur une chaîne simple.
  const pousse = (s: string | null) => {
    if (!s) return
    // Une seule chaîne contenant toute la recette : on la découpe aux phrases
    // numérotées ou aux retours à la ligne, jamais au point (« 180 °C. »).
    const morceaux = s.includes('\n')
      ? s.split(/\r?\n+/)
      : s.split(/(?=(?:^|\s)(?:Étape|Etape)\s*\d+)/i)
    for (const m of morceaux) {
      const t = m.replace(/^\s*(?:Étape|Etape)\s*\d+\s*[:.–-]?\s*/i, '').trim()
      if (t.length > 2) sorties.push(t)
    }
  }

  const visite = (x: unknown): void => {
    if (typeof x === 'string') return pousse(decodeEntites(x))
    if (Array.isArray(x)) { for (const e of x) visite(e); return }
    if (!x || typeof x !== 'object') return
    const o = x as Record<string, unknown>
    // HowToSection porte ses étapes ; HowToStep porte son texte.
    if (o.itemListElement) return visite(o.itemListElement)
    pousse(texte(o.text ?? o.name))
  }
  visite(v)
  return sorties
}

export function ingredients(v: unknown): string[] {
  const liste = Array.isArray(v) ? v : [v]
  return liste
    .map(x => texte(x))
    .filter((s): s is string => !!s && s.length > 1)
}

/**
 * Les nœuds de la page (tous ses blocs) qui portent un `@id`, pour suivre les renvois.
 *
 * ⚠️ Un objet qui ne porte QUE son `@id` est un renvoi, pas un nœud. Dans un graphe
 *    Yoast, l'`Article` et la `WebPage` renvoient à `…#primaryimage` avant que
 *    l'`ImageObject` complet n'arrive : ranger le premier vu gardait le renvoi
 *    vide, et la photo devenait introuvable.
 */
function noeuds(o: unknown, sortie = new Map<string, Record<string, unknown>>()) {
  if (Array.isArray(o)) {
    for (const v of o) noeuds(v, sortie)
  } else if (o && typeof o === 'object') {
    const r = o as Record<string, unknown>
    const id = r['@id']
    const plein = Object.keys(r).some(k => k !== '@id')
    if (typeof id === 'string' && plein && !sortie.has(id)) sortie.set(id, r)
    for (const v of Object.values(r)) noeuds(v, sortie)
  }
  return sortie
}

const RESSEMBLE_A_UNE_IMAGE = /\.(?:jpe?g|png|webp|avif|gif)(?:[?#]|$)/i

/**
 * La photo de la recette, en LIEN : rien n'est copié chez nous (R3).
 *
 * `image` s'écrit de quatre façons — une adresse, une liste d'adresses, un
 * `ImageObject` (`url`, puis `contentUrl`), une liste d'`ImageObject`. On prend
 * la PREMIÈRE adresse utilisable : celle que le site met en avant.
 *
 * Un objet qui ne porte qu'un `@id` renvoie ailleurs dans le graphe : on l'y
 * cherche. Introuvable, on ne le garde que s'il finit comme une image — sinon
 * c'est l'ancre d'une page (`…/#primaryimage`), pas une photo.
 *
 * L'adresse est décodée, résolue contre la page, passée en https (le navigateur
 * le ferait de toute façon, l'appli étant servie en https), et refusée au-delà
 * de 2 048 caractères — la limite de la colonne.
 */
export function photo(
  v: unknown, page: string, graphe = new Map<string, Record<string, unknown>>(),
): string | null {
  const candidates: string[] = []
  const visite = (x: unknown, profondeur: number): void => {
    if (profondeur > 3) return
    if (typeof x === 'string') { candidates.push(x); return }
    if (Array.isArray(x)) { for (const e of x) visite(e, profondeur + 1); return }
    if (!x || typeof x !== 'object') return
    const o = x as Record<string, unknown>
    // Les deux sont des candidates, `url` d'abord : le choix se fait à la
    // validation, sinon un `url` vide ou en `data:` cache un `contentUrl` valide.
    const directes = [o.url, o.contentUrl]
      .filter((a): a is string => typeof a === 'string' && a.trim() !== '')
    if (directes.length > 0) { candidates.push(...directes); return }
    const id = typeof o['@id'] === 'string' ? o['@id'] : null
    if (!id) return
    const renvoi = graphe.get(id)
    if (renvoi && renvoi !== o) { visite(renvoi, profondeur + 1); return }
    if (RESSEMBLE_A_UNE_IMAGE.test(id)) candidates.push(id)
  }
  visite(v, 0)

  for (const c of candidates) {
    const brut = decodeEntites(c.trim())
    if (!brut) continue
    let u: URL
    try { u = new URL(brut, page) } catch { continue }
    if (u.protocol === 'http:') u.protocol = 'https:'
    if (u.protocol !== 'https:') continue
    const adresse = u.toString()
    if (adresse.length <= 2048) return adresse
  }
  return null
}

/**
 * Le nom du SITE, pour l'attribution : TOUJOURS le domaine.
 *
 * `publisher` existe, mais il n'est pas fiable — relevé sur 225 pages réelles :
 * « Marmiton_Recettes », « Jow », « Rinoa Keller », « Anonyme », et même une URL
 * de schéma (`.../#/schema/person/3b50…`). Se rabattre sur `author` était pire
 * encore : l'écran affichait le nom d'un inconnu là où il fallait dire d'où
 * venait la recette.
 *
 * Le domaine, lui, n'est jamais faux et se reconnaît d'un coup d'œil. Une seule
 * règle, aucune surprise.
 */
function editeur(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

/**
 * Rend la recette d'une page, ou `null` si la page n'en publie pas.
 *
 * On ne devine jamais : pas de bloc `Recipe`, pas de recette. Une page sans
 * JSON-LD n'est pas un échec d'extraction, c'est un site qui n'en publie pas.
 */
export function extraire(html: string, url: string): RecetteBrute | null {
  const blocs = blocsJsonLd(html)
  // Le renvoi `@id` se résout dans le graphe de la PAGE : un site peut publier
  // l'`ImageObject` dans un bloc et la `Recipe` dans un autre.
  const graphe = noeuds(blocs)
  for (const bloc of blocs) {
    for (const r of recettesDans(bloc)) {
      const etapesLues = etapes(r.recipeInstructions)
      const ingredientsLus = ingredients(r.recipeIngredient ?? r.ingredients)
      // Une recette sans ingrédients ni étapes n'est pas exploitable : mieux
      // vaut ne rien ingérer qu'un titre seul, qui polluerait le catalogue.
      if (etapesLues.length === 0 || ingredientsLus.length === 0) continue

      return {
        url,
        titre: texte(r.name),
        source: editeur(url),
        parts: parts(r.recipeYield),
        totalMin: dureeIso(r.totalTime),
        prepMin: dureeIso(r.prepTime),
        cuissonMin: dureeIso(r.cookTime),
        ingredients: ingredientsLus,
        etapes: etapesLues,
        licence: texte(r.license),
        image: photo(r.image, url, graphe),
      }
    }
  }
  return null
}
