/**
 * La chaîne complète, sur de VRAIES recettes.
 *
 * Les blocs JSON-LD de `fixtures/recettes.json` ont été relevés tels quels sur
 * des pages publiées. C'est tout l'intérêt : des phrases inventées valideraient
 * l'analyseur contre lui-même, et c'est exactement l'erreur qui avait fait
 * passer une hypothèse fausse pour une mesure.
 *
 * De la page au plan de session, sans réseau et sans base.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { indexer } from '../src/aliment.ts'
import { pliure } from '../src/etape.ts'
import { preparer } from '../src/ingere.ts'
import type { Contexte } from '../src/ingere.ts'
import { etapes as lireEtapes, ingredients as lireIngredients, dureeIso, parts }
  from '../src/jsonld.ts'
import type { RecetteBrute } from '../src/jsonld.ts'
import { actionsDeLaSession } from '../../tests/db/front-fige/lib/plan/fusion.ts'
import { planifie } from '../../tests/db/front-fige/lib/plan/ordonnance.ts'

const lire = (f: string) =>
  JSON.parse(readFileSync(new URL(f, import.meta.url), 'utf8'))

const seed = lire('../../seed/conversions.json')
const ciqual = lire('../../seed/ciqual.json')
const fixtures: { url: string; recette: Record<string, unknown> }[] =
  lire('./fixtures/recettes.json')

const CTX: Contexte = {
  referentiel: {
    durees: seed.default_duration,
    alias: seed.verbe_alias.alias,
    nonActions: seed.non_action.motifs.map((m: string) => new RegExp(pliure(m), 'i')),
    temperatures: seed.default_temperature,
  },
  aliments: indexer(ciqual.map((a: { code: string; nom: string; etat: string }) => ({
    id: a.code, name: a.nom, state: a.etat,
  }))),
  conversions: seed.unit_conversion,
  sousGroupes: new Map<string, string | null>(
    ciqual.map((a: { code: string; sous_groupe: string | null }) => [a.code, a.sous_groupe])),
  densites: new Map(),
}

function brutes(): RecetteBrute[] {
  return fixtures.map(({ url, recette: r }) => ({
    url,
    titre: (r.name as string) ?? null,
    source: 'Ptitchef',
    parts: parts(r.recipeYield),
    totalMin: dureeIso(r.totalTime),
    prepMin: dureeIso(r.prepTime),
    cuissonMin: dureeIso(r.cookTime),
    ingredients: lireIngredients(r.recipeIngredient),
    etapes: lireEtapes(r.recipeInstructions),
    licence: null,
    image: null,
  }))
}

describe('sur de vraies pages', () => {
  it('a bien trois recettes à éprouver', () => {
    expect(fixtures.length, 'les fixtures ont disparu').toBe(3)
  })

  it('les rend toutes planifiables', () => {
    for (const b of brutes()) {
      const r = preparer(b, CTX)
      expect(r.recipe.plannable, `${b.titre} refusée : ${r.motifs.join(' ; ')}`).toBe(true)
    }
  })

  it('date toutes les étapes retenues', () => {
    for (const b of brutes()) {
      const r = preparer(b, CTX)
      const sansDuree = r.etapes.filter(e => e.duration_min === null)
      expect(sansDuree, `${b.titre} : étapes sans durée`).toHaveLength(0)
    }
  })

  it('rattache au moins 80 % des ingrédients à CIQUAL', () => {
    const tous = brutes().flatMap(b => preparer(b, CTX).ingredients)
    const rattaches = tous.filter(g => g.food_id !== null)
    expect(tous.length).toBeGreaterThan(30)
    expect(rattaches.length / tous.length).toBeGreaterThanOrEqual(0.8)
  })

  it('n’attribue jamais une confiance hors de [0, 1]', () => {
    for (const g of brutes().flatMap(b => preparer(b, CTX).ingredients)) {
      expect(g.confidence).toBeGreaterThanOrEqual(0)
      expect(g.confidence).toBeLessThanOrEqual(1)
    }
  })

  it('écarte les phrases qui ne sont pas des gestes', () => {
    for (const b of brutes()) {
      const r = preparer(b, CTX)
      expect(r.etapes.length, `${b.titre} : aucune étape`).toBeGreaterThan(0)
      expect(r.etapes.length, `${b.titre} : rien n'a été écarté ni gardé`)
        .toBeLessThanOrEqual(b.etapes.length)
    }
  })
})

describe('de la page au plan de session', () => {
  it('ordonnance les trois recettes ensemble', () => {
    const pretes = brutes().map(b => ({ b, r: preparer(b, CTX) }))

    const etapes = pretes.flatMap(({ b, r }) => {
      const parOrdinal = new Map(r.etapes.map(e => [e.ordinal, `${b.url}#${e.ordinal}`]))
      return r.etapes.map(e => ({
        id: parOrdinal.get(e.ordinal)!,
        recetteId: b.url,
        texte: e.text,
        ordinal: e.ordinal,
        dureeMin: e.duration_min,
        verbe: e.verb,
        quantiteG: e.quantity_g,
        appareil: e.appliance_type,
        charge: e.load_type,
        dependDe: r.dependances
          .filter(([, apres]) => apres === e.ordinal)
          .map(([avant]) => parOrdinal.get(avant)!)
          .filter(Boolean),
      }))
    })

    const actions = actionsDeLaSession(etapes)
    const plan = planifie(actions, {
      cuisiniers: 2,
      appareils: { four: 2, plaques: 4, air_fryer: 1 },
    }, { graine: 'chaine' })

    // Toutes les actions sont planifiées, une fois chacune.
    expect(plan.taches.length).toBe(actions.length)
    expect(new Set(plan.taches.map(t => t.id)).size).toBe(actions.length)

    // Une session de trois recettes retient en cuisine plus d'une demi-heure et
    // moins de quatre. Sa DURÉE totale peut être bien plus longue — l'une des
    // trois repose 3 h 30 au réfrigérateur — et c'est très bien ainsi.
    expect(plan.finEnCuisineMin).toBeGreaterThan(30)
    expect(plan.finEnCuisineMin).toBeLessThan(240)
    expect(plan.dureeMin).toBeGreaterThanOrEqual(plan.finEnCuisineMin)

    // Le four et l'air fryer travaillent pendant qu'on prépare : le temps les
    // mains prises est nettement inférieur au temps passé en cuisine.
    expect(plan.occupeMin).toBeLessThan(plan.finEnCuisineMin)
    expect(plan.attenteMin).toBeGreaterThan(0)

    // Et le plan sait dire ce qui fixe sa durée.
    expect(plan.chemin.length).toBeGreaterThan(0)
  })

  it('fusionne les gestes communs aux trois recettes', () => {
    const pretes = brutes().map(b => ({ b, r: preparer(b, CTX) }))
    const etapes = pretes.flatMap(({ b, r }) => r.etapes.map(e => ({
      id: `${b.url}#${e.ordinal}`,
      recetteId: b.url,
      texte: e.text,
      ordinal: e.ordinal,
      dureeMin: e.duration_min,
      verbe: e.verb,
      quantiteG: e.quantity_g,
      appareil: e.appliance_type,
      charge: e.load_type,
      dependDe: [],
    })))

    const actions = actionsDeLaSession(etapes)
    expect(actions.length, 'aucune fusion sur trois recettes')
      .toBeLessThan(etapes.length)

    const fusionnees = actions.filter(a => a.recettes.length > 1)
    expect(fusionnees.length, 'aucun geste partagé trouvé').toBeGreaterThan(0)
  })

  it('rend le même plan deux fois de suite', () => {
    const etapes = brutes().flatMap(b => {
      const r = preparer(b, CTX)
      return r.etapes.map(e => ({
        id: `${b.url}#${e.ordinal}`, recetteId: b.url, texte: e.text, ordinal: e.ordinal,
        dureeMin: e.duration_min, verbe: e.verb, quantiteG: e.quantity_g,
        appareil: e.appliance_type, charge: e.load_type, dependDe: [],
      }))
    })
    const actions = actionsDeLaSession(etapes)
    const ressources = { cuisiniers: 2, appareils: { four: 2, plaques: 4, air_fryer: 1 } }
    const a = planifie(actions, ressources, { graine: 'meme' })
    const b = planifie(actions, ressources, { graine: 'meme' })
    expect(b.taches.map(t => [t.id, t.debutMin]))
      .toEqual(a.taches.map(t => [t.id, t.debutMin]))
  })
})
