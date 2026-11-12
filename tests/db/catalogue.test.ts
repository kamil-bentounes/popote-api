/**
 * Ce que la BASE doit tenir pour que les filtres existent.
 *
 * Le temps actif, les appareils requis et le nombre d'étapes sont
 * **matérialisés** : les recalculer à chaque frappe coûterait une seconde par
 * lettre tapée. Qui dit matérialisé dit divergence possible — d'où ces tests,
 * qui vérifient que le trigger suit l'insertion, la modification ET la
 * suppression d'une étape.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let recette: string

async function etape(p: Record<string, unknown>) {
  const { error } = await admin().from('recipe_step').insert({ recipe_id: recette, ...p })
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
}

async function relis() {
  const { data } = await admin().from('recipe')
    .select('active_time_min, appliances, step_count').eq('id', recette).single()
  return data!
}

beforeAll(async () => {
  alice = await makeActor('catalogue')
  const { data } = await admin().from('recipe')
    .insert({ title: 'Recette du banc', yield_servings: 4 }).select().single()
  recette = data!.id
})

describe('le temps actif', () => {
  it('ne compte que ce qui occupe quelqu’un', async () => {
    // Dix minutes de gestes et quarante de four ne font pas cinquante minutes
    // de travail. C'est toute la raison d'être de la colonne.
    await etape({ ordinal: 1, text: 'Émince', duration_min: 6, load_type: 'actif' })
    await etape({ ordinal: 2, text: 'Enfourne', duration_min: 40, load_type: 'passif',
      appliance_type: 'four' })
    await etape({ ordinal: 3, text: 'Remue', duration_min: 4, load_type: 'bloquant',
      appliance_type: 'plaques' })

    const r = await relis()
    expect(Number(r.active_time_min), 'la cuisson passive a été comptée').toBe(10)
    expect(r.step_count).toBe(3)
  })

  it('liste les appareils requis, sans doublon', async () => {
    await etape({ ordinal: 4, text: 'Enfourne encore', duration_min: 15, load_type: 'passif',
      appliance_type: 'four' })
    const r = await relis()
    expect([...r.appliances].sort()).toEqual(['four', 'plaques'])
  })

  it('suit la modification d’une étape', async () => {
    const { data } = await admin().from('recipe_step')
      .select('id').eq('recipe_id', recette).eq('ordinal', 1).single()
    await admin().from('recipe_step').update({ duration_min: 20 }).eq('id', data!.id)
    expect(Number((await relis()).active_time_min), 'le trigger ne suit pas les updates')
      .toBe(24)
  })

  it('suit la suppression d’une étape', async () => {
    await admin().from('recipe_step').delete().eq('recipe_id', recette).eq('ordinal', 3)
    const r = await relis()
    expect(Number(r.active_time_min)).toBe(20)
    expect(r.step_count).toBe(3)
    expect([...r.appliances]).toEqual(['four'])
  })

  it('retombe à zéro quand il ne reste aucune étape', async () => {
    await admin().from('recipe_step').delete().eq('recipe_id', recette)
    const r = await relis()
    expect(Number(r.active_time_min)).toBe(0)
    expect(r.step_count).toBe(0)
    expect([...r.appliances]).toEqual([])
  })
})

describe('les macros par part', () => {
  it('se lisent par tout le monde : le catalogue est partagé', async () => {
    const { error } = await admin().from('recipe_nutrition').insert({
      recipe_id: recette, grams: 340, kcal: 520, protein_g: 31,
      fiber_g: 12, carb_g: 60, fat_g: 14,
      kcal_margin: 40, protein_g_margin: 3, coverage: 0.92,
    })
    expect(error).toBeNull()

    const { data } = await alice.client.from('recipe_nutrition')
      .select('protein_g, protein_g_margin').eq('recipe_id', recette).single()
    expect(Number(data!.protein_g)).toBe(31)
  })

  it('refusent une couverture hors de [0, 1]', async () => {
    const { error } = await admin().from('recipe_nutrition').insert({
      recipe_id: recette, grams: 1, kcal: 1, protein_g: 1,
      fiber_g: 1, carb_g: 1, fat_g: 1, coverage: 1.4,
    })
    expect(error, 'une couverture de 140 % a été acceptée').not.toBeNull()
  })

  it('disparaissent avec leur recette', async () => {
    const { data: r2 } = await admin().from('recipe')
      .insert({ title: 'Éphémère' }).select().single()
    await admin().from('recipe_nutrition').insert({
      recipe_id: r2!.id, grams: 100, kcal: 100, protein_g: 5,
      fiber_g: 1, carb_g: 1, fat_g: 1, coverage: 1,
    })
    await admin().from('recipe').delete().eq('id', r2!.id)
    const { data } = await admin().from('recipe_nutrition').select('recipe_id').eq('recipe_id', r2!.id)
    expect(data ?? [], 'des macros ont survécu à leur recette').toHaveLength(0)
  })
})

describe('« se congèle »', () => {
  it('accepte les trois états, et « inconnu » n’est pas « non »', async () => {
    for (const v of [true, false, null]) {
      const { error } = await admin().from('recipe').update({ freezable: v }).eq('id', recette)
      expect(error).toBeNull()
    }
    const { data } = await admin().from('recipe').select('freezable').eq('id', recette).single()
    expect(data!.freezable).toBeNull()
  })
})
