#!/usr/bin/env node
/**
 * Recalculer ce qui manque sur les recettes DÉJÀ ingérées.
 *
 * Il existe une raison précise à ce script : les colonnes et les triggers du
 * lot 4 ont été posés APRÈS une grande ingestion. Un trigger ne rattrape pas le
 * passé — les 1 400 recettes déjà en base avaient `active_time_min` vide,
 * `appliances` vide, et pas une ligne de macros. Les filtres du catalogue ne
 * rendaient rien. La spec du 19/10/2026 y ajoute les titres et les gestes.
 *
 * Les passes, dans cet ordre, parce qu'elles dépendent l'une de l'autre :
 *
 *   T. les TITRES du catalogue ingéré, sans leur réclame (R5) ;
 *   0. le RATTACHEMENT à CIQUAL, quand la règle de score a changé — c'est la
 *      passe qui répare le plus, parce qu'un aliment faux fausse tout ce qui
 *      suit ;
 *   1. les GRAMMES des lignes au compte (« 2 oignons »), maintenant que les
 *      poids unitaires de référence sont chargés (lot 0c) ;
 *   2. les MACROS par part, qui se calculent sur ces grammes — sauf quand la
 *      part est impossible (R7) ;
 *   G. les GESTES de chaque étape : le temps actif compte au moins ce que les
 *      mains font (R6) ;
 *   3. les AGRÉGATS d'étapes — temps actif, appareils, nombre d'étapes — qu'on
 *      obtient en refaisant jouer le trigger.
 *
 * Aucune page n'est retéléchargée : tout est déjà en base. C'est ce qui rend
 * l'opération possible en quelques minutes plutôt qu'en une nuit.
 *
 * À SEC, rien n'est écrit et TOUT est dit : chaque titre qui change, les
 * recettes à 0 min avant et après, les plus fortes hausses, les macros
 * écartées. C'est ce relevé qu'on lit avant d'écrire en prod.
 *
 *   npm run recalcule -- --prod --sec
 *   npm run recalcule -- --prod
 *   npm run recalcule -- --prod --limite 20      (pour regarder avant)
 *   npm run recalcule -- --recette <uuid>        (une seule recette)
 *
 * Les options sont strictes (`--cle valeur` ou `--cle=valeur`) : une option
 * inconnue, sans valeur ou illisible arrête le script avant tout appel réseau.
 */
import { config } from 'dotenv'
import { createClient } from '@supabase/supabase-js'
import { agrege, parPart, plausible, pour100De } from '../tests/db/front-fige/lib/nutrition/macros.ts'
import { entierPositif, lireOptions, uuid } from '../tests/db/front-fige/lib/recettes/options.ts'
import { decodeEntites, titrePropre } from '../tests/db/front-fige/lib/recettes/texte.ts'
import { minutesDeMains } from '../tests/db/front-fige/lib/recettes/temps.ts'
import { indexer, rattacher } from '../worker/src/aliment.ts'
import { gestesMin, pliure } from '../worker/src/etape.ts'
import { analyser } from '../worker/src/ingredient.ts'

// Les options se lisent AVANT tout appel réseau, et sans rien deviner : une option
// mal écrite arrête le script. `--limite` sans valeur ou à 0 rendait « pas de limite »,
// donc tout le catalogue ; `--dry-run` à côté de `--prod` écrivait en prod.
const lues = lireOptions(process.argv.slice(2), {
  '--prod': 'drapeau', '--sec': 'drapeau', '--sans-rattachement': 'drapeau',
  '--limite': entierPositif, '--recette': uuid,
})
if (!lues.ok) {
  console.error(`${lues.erreur}\nUsage : npm run recalcule -- [--prod] [--sec] [--sans-rattachement] `
    + '[--limite <entier>] [--recette <uuid>]')
  process.exit(2)
}
const o = lues.options
const PROD = o['--prod'] === true
const LIMITE = o['--limite'] ?? null
const SEC = o['--sec'] === true
const SANS_RATTACHEMENT = o['--sans-rattachement'] === true
// Une seule recette : pour regarder de près, ou pour éprouver le script sans
// recalculer toute une base.
const RECETTE = o['--recette'] ?? null

// ⚠️ `override` : sans lui, `.env` gagne et on écrirait en LOCAL avec la clé de
//    PROD — une heure perdue à comprendre pourquoi rien ne changeait.
config({ path: PROD ? '.env.production' : '.env', override: true })
const URL = process.env.VITE_SUPABASE_URL
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY
if (!URL || !KEY) { console.error('URL ou clé de service manquante.'); process.exit(1) }
const db = createClient(URL, KEY, { auth: { persistSession: false } })

console.log(`Cible : ${URL}${SEC ? '  (à sec, rien ne sera écrit)' : ''}\n`)

/** PostgREST plafonne à 1 000 lignes en silence. On pagine, toujours. */
async function tout(table, select, filtre = q => q, cle = 'id') {
  const pages = []
  for (let de = 0; ; de += 1000) {
    // ⚠️ `order('id')` n'est pas décoratif : sans ordre TOTAL, deux pages
    //    successives peuvent sauter des lignes ou en rendre deux fois. Sur
    //    17 000 ingrédients, la couverture se calculait alors sur une liste
    //    tronquée et sortait à 1.0 sur un quart de plat.
    const { data, error } = await filtre(db.from(table).select(select))
      .order(cle).range(de, de + 999)
    if (error) throw new Error(`${table} : ${error.message}`)
    pages.push(...data)
    if (data.length < 1000) break
  }
  return pages
}

/** Écrit par paquets de deux cents : assez pour aller vite, pas assez pour tout bloquer. */
async function parPaquets(lignes, ecrire, quoi) {
  for (let d = 0; d < lignes.length; d += 200) {
    await Promise.all(lignes.slice(d, d + 200).map(ecrire))
    process.stdout.write(`   ${Math.min(d + 200, lignes.length)}/${lignes.length}\r`)
  }
  console.log(`   ${lignes.length}/${lignes.length} ${quoi}.      `)
}

const mediane = l => {
  if (l.length === 0) return 0
  const t = [...l].sort((a, b) => a - b)
  return Math.round(t[Math.floor(t.length / 2)] * 10) / 10
}

// ── Le référentiel ─────────────────────────────────────────────────────────
console.log('Chargement du référentiel…')
const aliments = await tout('food', 'id, name, state, nutrients, ciqual_subgroup')
const nutriments = new Map(aliments.map(a => [a.id, a.nutrients]))
const sousGroupes = new Map(aliments.map(a => [a.id, a.ciqual_subgroup]))

const typiquesL = await tout('typical_quantity', 'ciqual_subgroup, grams',
  q => q, 'ciqual_subgroup')
const typiques = new Map(typiquesL.map(t => [t.ciqual_subgroup, Number(t.grams)]))

const poidsL = await tout('unit_weight', 'food_id, grams, confidence')
const poidsUnitaires = new Map([...poidsL]
  .sort((a, b) => Number(a.confidence) - Number(b.confidence))
  .filter(w => w.food_id)
  .map(w => [w.food_id, Number(w.grams)]))

// Les verbes, pour les gestes : la base, pas le fichier — comme l'ingestion.
const [rDurees, rAlias, rNonActions] = await Promise.all([
  db.from('default_duration').select('verb, appliance_type, base_minutes, load_type, scaling'),
  db.from('verbe_alias').select('depuis, vers'),
  db.from('non_action_pattern').select('pattern'),
])
for (const r of [rDurees, rAlias, rNonActions]) if (r.error) throw new Error(r.error.message)
const referentiel = {
  durees: rDurees.data.map(d => ({ ...d, base_minutes: Number(d.base_minutes) })),
  alias: Object.fromEntries(rAlias.data.map(a => [a.depuis, a.vers])),
  nonActions: rNonActions.data.map(p => new RegExp(pliure(p.pattern), 'i')),
}
console.log(`  ${aliments.length} aliments · ${poidsUnitaires.size} poids unitaires · `
  + `${referentiel.durees.length} durées\n`)

// ── Les recettes ───────────────────────────────────────────────────────────
let recettes = await tout('recipe',
  'id, title, yield_servings, origin, owner_household_id, total_time_min, active_time_min')
if (RECETTE) recettes = recettes.filter(r => r.id === RECETTE)
if (RECETTE && recettes.length === 0) { console.error(`Aucune recette ${RECETTE} sur cette cible.`); process.exit(2) }
if (LIMITE) recettes = recettes.slice(0, LIMITE)
const ids = new Set(recettes.map(r => r.id))
console.log(`${recettes.length} recettes à reprendre.\n`)

// ── Passe T : les titres (R5) ──────────────────────────────────────────────
// Seulement le catalogue INGÉRÉ : un titre de foyer, quelqu'un l'a écrit.
const ingerees = recettes.filter(r => r.origin === 'importee' && r.owner_household_id === null && r.title)
const titres = ingerees
  .map(r => ({ id: r.id, avant: r.title, apres: titrePropre(r.title) }))
  .filter(t => t.apres !== t.avant)
console.log(`T. Titres : ${titres.length} à nettoyer.`)
if (SEC) {
  for (const t of titres) console.log(`   ${t.avant}\n     → ${t.apres}`)
  const douteux = ingerees.map(r => titrePropre(r.title))
    .filter(t => /recette|\s[-–—|:]\s/i.test(t))
  console.log(`   ${douteux.length} titres portent encore « recette » ou un séparateur, à relire :`)
  for (const t of douteux) console.log(`   ? ${t}`)
} else {
  await parPaquets(titres, async t => {
    const { error } = await db.from('recipe').update({ title: t.apres }).eq('id', t.id)
    if (error) throw new Error(`titre ${t.id} : ${error.message}`)
  }, 'titres écrits')
}

const ingredients = await tout('recipe_ingredient',
  'id, recipe_id, food_id, qty, unit, grams_reference, raw_text, resolution_source, confidence')
const parRecette = new Map()
for (const i of ingredients) {
  if (!ids.has(i.recipe_id)) continue
  if (!parRecette.has(i.recipe_id)) parRecette.set(i.recipe_id, [])
  parRecette.get(i.recipe_id).push(i)
}

// ── Passe 0 : le rattachement à CIQUAL ─────────────────────────────────────
// Mesuré le 18/09/2026 : dix-sept des trente ingrédients les plus courants
// tombaient à côté — « beurre » rendait « Haricot beurre », « tomate » rendait
// « Tomate, séchée ». Chaque erreur fausse les macros de toutes les recettes
// qui citent l'ingrédient, et le score, écrit dans `confidence`, verrouillait
// même la ligne contre toute correction au-delà de 0,8.
//
// On ne retouche QUE ce que l'ingestion avait rattaché ou laissé de côté : une
// ligne corrigée à la main par un foyer porte `resolution_source` différent.
const index = indexer(aliments.map(a => ({ id: a.id, name: a.name, state: a.state ?? 'cru' })))
const rattachements = []
if (!SANS_RATTACHEMENT) {
  for (const i of ingredients) {
    if (!ids.has(i.recipe_id)) continue
    if (i.resolution_source !== 'reference' && i.resolution_source !== 'aucune') continue
    const ligne = analyser(i.raw_text)
    if (ligne.forme === 'section') continue
    const corr = rattacher(ligne.aliment, index)
    const nouveau = corr?.foodId ?? null
    if (nouveau === i.food_id) continue
    const c = {
      id: i.id, food_id: nouveau,
      resolution_source: corr ? 'reference' : 'aucune',
      confidence: Math.min(1, Math.max(0, corr?.score ?? 0)),
    }
    // La suite des passes lit la version corrigée.
    i.food_id = nouveau
    // Un aliment qui change invalide les grammes déduits d'un poids unitaire — EN BASE
    // aussi : sans cela, « 2 saucisses » rattaché à « Saucisse » garderait les 999 g
    // de l'ancien « Haricot beurre », et la passe 1 (qui ne regarde que les lignes à
    // grammes vides) ne les recalculerait jamais.
    if (i.unit === null && i.qty !== null && i.grams_reference !== null) {
      i.grams_reference = null
      c.grams_reference = null
    }
    rattachements.push(c)
  }
}
console.log(`0. Rattachement : ${rattachements.length} lignes changent d'aliment.`)
if (!SEC) {
  for (let d = 0; d < rattachements.length; d += 200) {
    await Promise.all(rattachements.slice(d, d + 200).map(async c => {
      const { id, ...champs } = c
      const { error } = await db.from('recipe_ingredient').update(champs).eq('id', id)
      if (error) throw new Error(`rattachement ${c.id} : ${error.message}`)
    }))
    process.stdout.write(`   ${Math.min(d + 200, rattachements.length)}/${rattachements.length}\r`)
  }
  console.log(`   ${rattachements.length}/${rattachements.length} écrites.      `)
}

// ── Passe 1 : les grammes des lignes au compte ─────────────────────────────
// « 2 oignons » : `qty` posée, `unit` vide. C'est exactement ce que l'ingestion
// ne savait pas convertir avant que les poids unitaires existent.
const corrections = []
for (const i of ingredients) {
  if (!ids.has(i.recipe_id)) continue
  if (i.grams_reference !== null || i.qty === null || i.unit !== null || !i.food_id) continue
  const unitaire = poidsUnitaires.get(i.food_id)
  if (unitaire === undefined) continue
  corrections.push({ id: i.id, grams: Math.round(Number(i.qty) * unitaire * 10) / 10 })
  i.grams_reference = Math.round(Number(i.qty) * unitaire * 10) / 10
}
console.log(`1. Grammes : ${corrections.length} lignes au compte deviennent pesables.`)
if (!SEC) {
  for (let d = 0; d < corrections.length; d += 200) {
    await Promise.all(corrections.slice(d, d + 200).map(async c => {
      const { error } = await db.from('recipe_ingredient')
        .update({ grams_reference: c.grams }).eq('id', c.id)
      if (error) throw new Error(`grammes ${c.id} : ${error.message}`)
    }))
    process.stdout.write(`   ${Math.min(d + 200, corrections.length)}/${corrections.length}\r`)
  }
  console.log(`   ${corrections.length}/${corrections.length} écrites.      `)
}

// ── Passe 2 : les macros par part ──────────────────────────────────────────
// Le seuil de 75 % de couverture est celui de l'ingestion : une valeur calculée
// sur la moitié d'une recette est PIRE qu'aucune valeur, parce qu'elle sert
// ensuite à filtrer (D18). Une part IMPOSSIBLE aussi (R7).
const macros = []
const aberrantes = []
let insuffisantes = 0
for (const r of recettes) {
  const lignes = (parRecette.get(r.id) ?? []).map(g => ({
    grammes: g.grams_reference === null ? null : Number(g.grams_reference),
    grammesTypiques: g.food_id ? typiques.get(sousGroupes.get(g.food_id) ?? '') ?? null : null,
    pour100: g.food_id ? pour100De(nutriments.get(g.food_id)) : null,
  }))
  if (lignes.length === 0) { insuffisantes++; continue }

  const a = agrege(lignes)
  const grammesPlat = lignes.reduce(
    (s, l) => s + (l.pour100 ? (l.grammes ?? l.grammesTypiques ?? 0) : 0), 0)
  const parts = Math.max(1, r.yield_servings ?? 1)
  if (a.couverture < 0.75 || grammesPlat <= 0) { insuffisantes++; continue }

  const p = parPart(a, grammesPlat, grammesPlat / parts)
  const m = {
    recipe_id: r.id,
    grams: Math.round(grammesPlat / parts),
    kcal: p.valeur.kcal, protein_g: p.valeur.proteinG,
    fiber_g: p.valeur.fiberG, carb_g: p.valeur.carbG, fat_g: p.valeur.fatG,
    kcal_margin: p.marge.kcal, protein_g_margin: p.marge.proteinG,
    coverage: Math.round(a.couverture * 100) / 100,
  }
  if (!plausible(m)) { aberrantes.push({ titre: r.title, kcal: m.kcal, grams: m.grams, parts }); continue }
  macros.push(m)
}
console.log(`2. Macros : ${macros.length} recettes calculées, ${insuffisantes} trop incomplètes, `
  + `${aberrantes.length} impossibles.`)
// Une recette devenue trop incomplète — ou impossible — ne doit pas garder ses
// anciennes macros : elles serviraient à filtrer, et elles seraient fausses.
const gardees = new Set(macros.map(m => m.recipe_id))
const aEffacer = recettes.map(r => r.id).filter(id => !gardees.has(id))
if (SEC) {
  for (const x of aberrantes) {
    console.log(`   ✗ ${x.titre} — ${x.kcal} kcal, ${x.grams} g la part, ${x.parts} parts`)
  }
  // On annonce les lignes qui existent vraiment, pas les recettes écartées : la
  // plupart n'ont jamais eu de macros.
  const ecartees = new Set(aEffacer)
  const perimees = (await tout('recipe_nutrition', 'recipe_id', q => q, 'recipe_id'))
    .filter(n => ecartees.has(n.recipe_id)).length
  console.log(`   ${perimees} macros périmées seraient effacées.`)
} else {
  let effacees = 0
  for (let d = 0; d < aEffacer.length; d += 200) {
    const { error, count } = await db.from('recipe_nutrition')
      .delete({ count: 'exact' }).in('recipe_id', aEffacer.slice(d, d + 200))
    if (error) throw new Error(error.message)
    effacees += count ?? 0
  }
  console.log(`   ${effacees} macros périmées effacées.`)
  for (let d = 0; d < macros.length; d += 300) {
    const { error } = await db.from('recipe_nutrition')
      .upsert(macros.slice(d, d + 300), { onConflict: 'recipe_id' })
    if (error) throw new Error(error.message)
    process.stdout.write(`   ${Math.min(d + 300, macros.length)}/${macros.length}\r`)
  }
  console.log(`   ${macros.length}/${macros.length} écrites.      `)
}

// ── Passe G : les gestes de chaque étape (R6) ──────────────────────────────
const etapesG = await tout('recipe_step', 'id, recipe_id, text, verb, load_type, duration_min, '
  + 'duration_source, appliance_type, gesture_min, edited_by_household_id')
const gestes = []
const etapesDe = new Map()
for (const e of etapesG) {
  if (!ids.has(e.recipe_id)) continue
  // Une durée qu'une personne a confirmée ou corrigée fait foi : pas de plancher.
  const humaine = e.duration_source === 'confirmee' || e.edited_by_household_id !== null
  // Les anciennes étapes peuvent porter des entités (« M&eacute;langez ») : sans le
  // décodage, elles perdraient leurs gestes.
  const g = humaine ? null : gestesMin(decodeEntites(e.text), referentiel)
  const avant = e.gesture_min === null ? null : Number(e.gesture_min)
  if (g !== avant) gestes.push({ id: e.id, gesture_min: g })
  if (!etapesDe.has(e.recipe_id)) etapesDe.set(e.recipe_id, [])
  etapesDe.get(e.recipe_id).push({ ...e, gesture_min: g })
}
console.log(`G. Gestes : ${gestes.length} étapes changent.`)

// Le relevé : ce que chaque recette deviendra, calculé comme le trigger le fera.
const releve = recettes.filter(r => etapesDe.has(r.id)).map(r => ({
  titre: r.title,
  avant: Number(r.active_time_min ?? 0),
  apres: Math.round(etapesDe.get(r.id).reduce((s, e) => s + minutesDeMains(e), 0) * 10) / 10,
  total: r.total_time_min === null ? null : Number(r.total_time_min),
  etapes: etapesDe.get(r.id),
}))
const aZero = cote => releve.filter(x => x[cote] === 0)
const sousLeTotal = cote => releve.filter(x => x.total !== null && x.total > 0 && x.total < x[cote])
const hausses = releve.filter(x => x.apres > x.avant)
  .sort((a, b) => (b.apres - b.avant) - (a.apres - a.avant))
const sansVerbe = etapesG.filter(e => ids.has(e.recipe_id) && e.verb === null
  && e.appliance_type !== null && e.load_type === 'actif').length
console.log(`   0 min actives : ${aZero('avant').length} recettes avant, ${aZero('apres').length} après.`)
console.log(`   ${hausses.length} recettes montent, de ${mediane(hausses.map(x => x.apres - x.avant))} min `
  + `en médiane.`)
console.log(`   Total sous le temps actif : ${sousLeTotal('avant').length} avant, ${sousLeTotal('apres').length} après.`)
console.log(`   Hors champ (spec § 10) : ${sansVerbe} étapes sans verbe, avec un appareil, comptées actives.`)
if (SEC) {
  console.log('   Encore à 0 min :')
  for (const x of aZero('apres')) {
    console.log(`   · ${x.titre}`)
    for (const e of x.etapes) console.log(`       ${e.load_type ?? '—'} · ${e.text.slice(0, 90)}`)
  }
  // Les comptes seuls ne disent pas QUELLES recettes se contredisent : on les nomme,
  // avant et après, pour que le relevé se lise recette par recette.
  for (const cote of ['avant', 'apres']) {
    const l = sousLeTotal(cote)
    console.log(`   Total sous le temps actif, ${cote === 'avant' ? 'avant' : 'après'} (${l.length}) :`)
    for (const x of l) console.log(`   ! ${x.titre} : total ${x.total} min, actif ${x[cote]} min`)
  }
  console.log('   Les dix plus fortes hausses :')
  for (const x of hausses.slice(0, 10)) console.log(`   ↑ ${x.titre} : ${x.avant} → ${x.apres} min`)
} else {
  await parPaquets(gestes, async c => {
    const { error } = await db.from('recipe_step').update({ gesture_min: c.gesture_min }).eq('id', c.id)
    if (error) throw new Error(`gestes ${c.id} : ${error.message}`)
  }, 'étapes écrites')
}

// ── Passe 3 : les agrégats d'étapes ────────────────────────────────────────
// Le trigger `tg_recipe_agrege` ne rattrape pas le passé. On le refait jouer en
// réécrivant une étape par recette — la valeur ne change pas, le trigger si.
//
// ⚠️ Cette passe reste même après la G. La passe G réécrit les étapes par paquets
//    de deux cents, en parallèle : deux étapes d'UNE MÊME recette, réécrites en même
//    temps, jouent le trigger chacune sur un état que l'autre n'a pas encore validé,
//    et la dernière à finir peut laisser un `active_time_min` périmé. Passer ici,
//    une étape par recette et après la G, remet l'agrégat d'aplomb.
const etapes = await tout('recipe_step', 'id, recipe_id, ordinal')
const premiere = new Map()
for (const e of etapes) {
  if (!ids.has(e.recipe_id)) continue
  const d = premiere.get(e.recipe_id)
  if (!d || e.ordinal < d.ordinal) premiere.set(e.recipe_id, e)
}
console.log(`3. Agrégats : ${premiere.size} recettes à réveiller.`)
if (!SEC) {
  const liste = [...premiere.values()]
  for (let d = 0; d < liste.length; d += 200) {
    await Promise.all(liste.slice(d, d + 200).map(async e => {
      const { error } = await db.from('recipe_step')
        .update({ ordinal: e.ordinal }).eq('id', e.id)
      if (error) throw new Error(`agrégat ${e.id} : ${error.message}`)
    }))
    process.stdout.write(`   ${Math.min(d + 200, liste.length)}/${liste.length}\r`)
  }
  console.log(`   ${liste.length}/${liste.length} réveillées.      `)
}

console.log('\nTerminé.')
