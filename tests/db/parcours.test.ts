/**
 * Le parcours complet, du mercredi au dimanche suivant.
 *
 * Chaque brique est éprouvée ailleurs. Ce test-ci vérifie qu'elles s'enchaînent
 * — c'est exactement ce qui manquait à l'app quand elle était « brouillonne » :
 * des écrans qui marchaient chacun sans qu'aucune séquence ne les relie.
 *
 * Il fait, dans l'ordre et avec les droits d'un utilisateur ordinaire :
 * ouvrir → choisir → liste → courses → plan → cuisine → dressage → semaine →
 * manger → clôture.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'
import { actionsDeLaSession } from './front-fige/lib/plan/fusion.ts'
import { planifie } from './front-fige/lib/plan/ordonnance.ts'
import { organise } from './front-fige/lib/liste.ts'

let kamil: Actor
let thauba: Actor
let dahl: string
let basquaise: string

/** Deux recettes qui partagent un geste : la fusion doit les rapprocher. */
async function amorceRecettes() {
  const a = admin()
  const faire = async (titre: string, parts: number) => {
    const { data: r, error } = await a.from('recipe')
      .insert({ title: titre, yield_servings: parts, origin: 'importee' })
      .select().single()
    expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()

    await a.from('recipe_ingredient').insert([
      { recipe_id: r!.id, ordinal: 1, raw_text: '400 g d’oignons', qty: 400, unit: 'g', grams_reference: 400 },
      { recipe_id: r!.id, ordinal: 2, raw_text: '500 g de poulet', qty: 500, unit: 'g', grams_reference: 500 },
    ])
    await a.from('recipe_step').insert([
      {
        recipe_id: r!.id, ordinal: 1, text: 'Émince les oignons',
        verb: 'emincer', quantity_g: 400, duration_min: 6, load_type: 'actif',
      },
      {
        recipe_id: r!.id, ordinal: 2, text: `Cuis ${titre.toLowerCase()} au four`,
        verb: 'cuire', duration_min: 35, load_type: 'passif', appliance_type: 'four',
      },
    ])
    return r!.id as string
  }
  dahl = await faire('Dahl de lentilles', 4)
  basquaise = await faire('Poulet basquaise', 4)
}

beforeAll(async () => {
  kamil = await makeActor('parcours-kamil')
  // Thauba partage le foyer de Kamil : c'est le cas réel de l'app.
  const { error } = await admin().from('user_profile').insert({
    id: (await admin().auth.admin.createUser({
      email: `thauba-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true,
    })).data.user!.id,
    household_id: kamil.householdId,
    display_name: 'Thauba',
  })
  expect(error).toBeNull()

  const { data: profils } = await admin().from('user_profile')
    .select('id, display_name').eq('household_id', kamil.householdId)
  thauba = { ...kamil, userId: profils!.find(p => p.display_name === 'Thauba')!.id }

  for (const p of profils!) {
    await admin().from('nutrition_target').insert({
      user_profile_id: p.id, household_id: kamil.householdId,
      kcal: p.display_name === 'Thauba' ? 1700 : 2000,
      protein_g: p.display_name === 'Thauba' ? 120 : 140,
      fiber_g: 30, carb_g: 200, fat_g: 60,
    })
  }
  await amorceRecettes()
})

describe('le parcours complet', () => {
  let cycle: string
  let taches: { id: string; duration_min: number }[] = []

  it('mercredi : ouvre la semaine et choisit deux recettes', async () => {
    const { data, error } = await kamil.client.rpc('open_cycle', {
      p_week_of: '2029-01-08', p_servings: 8,
    })
    expect(error).toBeNull()
    cycle = data!

    for (const [id, parts] of [[dahl, 4], [basquaise, 4]] as const) {
      const { error: e } = await kamil.client.from('cycle_recipe').insert({
        cycle_id: cycle, household_id: kamil.householdId, recipe_id: id, servings: parts,
      })
      expect(e, 'une recette n’a pas pu être choisie').toBeNull()
    }
    await kamil.client.from('cycle').update({ state: 'selection' }).eq('id', cycle)

    const { data: choisies } = await kamil.client.from('cycle_recipe')
      .select('id').eq('cycle_id', cycle)
    expect(choisies).toHaveLength(2)
  })

  it('mercredi : la liste se génère, un magasin par défaut', async () => {
    const { data: magasin } = await kamil.client.from('store')
      .insert({ household_id: kamil.householdId, name: 'Lidl', is_default: true })
      .select().single()

    const { error } = await kamil.client.from('shopping_item').insert([
      { cycle_id: cycle, household_id: kamil.householdId, store_id: magasin!.id,
        label: 'Oignons', aisle: 'Fruits et légumes', quantity: 800, unit: 'g', source: 'recette' },
      { cycle_id: cycle, household_id: kamil.householdId, store_id: magasin!.id,
        label: 'Poulet', aisle: 'Boucherie, poissonnerie', quantity: 1000, unit: 'g', source: 'recette' },
      { cycle_id: cycle, household_id: kamil.householdId, store_id: magasin!.id,
        label: 'Lessive', aisle: 'Entretien', source: 'suggestion' },
    ])
    expect(error).toBeNull()
    await kamil.client.from('cycle').update({ state: 'courses' }).eq('id', cycle)

    // L'écran range par magasin puis par rayon, sans rien perdre.
    const { data: articles } = await kamil.client.from('shopping_item')
      .select('id, label, store_id, aisle, checked_at').eq('cycle_id', cycle)
    const sorties = organise(articles!, [], [{ id: magasin!.id, name: 'Lidl' }])
    expect(sorties).toHaveLength(1)
    expect(sorties[0].total).toBe(3)
    expect(sorties[0].groupes[0].rayon).toBe('Fruits et légumes')
  })

  it('samedi : cocher remplit l’inventaire et apprend le magasin', async () => {
    const { data: articles } = await kamil.client.from('shopping_item')
      .select('*').eq('cycle_id', cycle)

    for (const a of articles!) {
      const { error } = await kamil.client.from('shopping_item')
        .update({ checked_at: new Date().toISOString() }).eq('id', a.id)
      expect(error).toBeNull()
    }

    const { data: stock } = await kamil.client.from('stock_item')
      .select('label').eq('household_id', kamil.householdId)
    expect(stock!.map(s => s.label).sort(), 'l’inventaire n’a pas été rempli')
      // 0117 : la lessive (rayon Entretien) se coche, mais ne se range pas au frigo.
      .toEqual(['Oignons', 'Poulet'])

    const { data: rayons } = await kamil.client.from('aisle_order').select('aisle')
    expect(rayons!.length, 'aucun ordre de rayon appris').toBe(3)

    await kamil.client.from('cycle').update({ state: 'pret' }).eq('id', cycle)
  })

  it('dimanche : le plan fusionne les gestes et tient dans le temps', async () => {
    const { data: etapes } = await kamil.client.from('recipe_step')
      .select('*').in('recipe_id', [dahl, basquaise]).order('recipe_id').order('ordinal')

    const actions = actionsDeLaSession(etapes!.map((e, i, tous) => ({
      id: e.id, recetteId: e.recipe_id, texte: e.text, ordinal: e.ordinal,
      dureeMin: e.duration_min === null ? null : Number(e.duration_min),
      verbe: e.verb, quantiteG: e.quantity_g === null ? null : Number(e.quantity_g),
      appareil: e.appliance_type, charge: e.load_type,
      dependDe: i > 0 && tous[i - 1].recipe_id === e.recipe_id ? [tous[i - 1].id] : [],
    })))

    // Deux « émince » pour deux recettes : une seule action, 800 g au total.
    const emince = actions.filter(a => a.verbe === 'emincer')
    expect(emince, 'les deux gestes identiques n’ont pas fusionné').toHaveLength(1)
    expect(emince[0].quantiteG).toBe(800)
    expect(emince[0].recettes).toHaveLength(2)

    const plan = planifie(actions, { cuisiniers: 2, appareils: { four: 1 } },
      { graine: cycle })

    // Le four ne prend qu'un plat : les deux cuissons se suivent, mais elles
    // n'occupent personne — le temps actif reste celui du seul émincé.
    expect(plan.dureeMin).toBeGreaterThan(70)
    expect(plan.occupeMin).toBeLessThan(15)
    expect(plan.attenteMin).toBeGreaterThan(50)

    const { error } = await kamil.client.from('session_task').insert(
      plan.taches.map((t, i) => ({
        id: t.id, cycle_id: cycle, household_id: kamil.householdId,
        label: t.label, verb: t.verbe, quantity_g: t.quantiteG,
        appliance_code: t.appareil, duration_min: t.dureeMin, is_active: t.actif,
        planned_start_min: t.debutMin, position: i,
      })))
    expect(error, 'le plan n’a pas pu être enregistré').toBeNull()

    await kamil.client.from('cycle').update({ state: 'en_cuisine' }).eq('id', cycle)
    const { data: posees } = await kamil.client.from('session_task')
      .select('id, duration_min').eq('cycle_id', cycle)
    taches = posees!.map(t => ({ id: t.id, duration_min: Number(t.duration_min) }))
    expect(taches.length).toBe(plan.taches.length)
  })

  it('dimanche : cuisiner mesure les durées sans rien demander', async () => {
    for (const t of taches) {
      await kamil.client.from('session_task')
        .update({ started_at: new Date(Date.now() - 5 * 60_000).toISOString() }).eq('id', t.id)
      const { error } = await kamil.client.from('session_task')
        .update({ done_at: new Date().toISOString() }).eq('id', t.id)
      expect(error).toBeNull()
    }

    const { data: faites } = await kamil.client.from('session_task')
      .select('actual_min').eq('cycle_id', cycle)
    expect(faites!.every(t => Number(t.actual_min) > 0), 'une durée n’a pas été mesurée')
      .toBe(true)

    const { data: mesures } = await kamil.client.from('duration_observation')
      .select('verb').eq('household_id', kamil.householdId)
    expect(mesures!.length, 'aucune mesure consignée').toBeGreaterThan(0)

    await kamil.client.from('cycle').update({ state: 'dressage' }).eq('id', cycle)
  })

  it('dimanche : le dressage produit des barquettes datées', async () => {
    const lots = [
      ...Array.from({ length: 4 }, () => ({ pour: kamil.userId, grammes: 380 })),
      ...Array.from({ length: 4 }, () => ({ pour: thauba.userId, grammes: 320 })),
    ]
    const { error } = await kamil.client.from('portion').insert(lots.map((l, i) => ({
      household_id: kamil.householdId, cycle_id: cycle,
      recipe_id: i % 2 === 0 ? dahl : basquaise,
      label: i % 2 === 0 ? 'Dahl de lentilles' : 'Poulet basquaise',
      grams: l.grammes, kcal: l.grammes * 1.4, protein_g: l.grammes * 0.08,
      fiber_g: 10, carb_g: 40, fat_g: 12,
      for_user_id: l.pour,
      location: i < 4 ? 'frigo' : 'congelateur',
    })))
    expect(error, 'le dressage a échoué').toBeNull()

    const { data: barquettes } = await kamil.client.from('portion')
      .select('*').eq('cycle_id', cycle)
    expect(barquettes).toHaveLength(8)
    expect(barquettes!.every(b => b.expires_at !== null), 'une barquette sans date limite')
      .toBe(true)

    // Le journal a suivi, tout seul.
    const { data: journal } = await kamil.client.from('portion_event')
      .select('kind').eq('household_id', kamil.householdId)
    expect(journal!.filter(e => e.kind === 'dressee')).toHaveLength(8)
  })

  it('dimanche soir : la semaine se distribue, personne n’est oublié', async () => {
    const { data: barquettes } = await kamil.client.from('portion')
      .select('id, expires_at, for_user_id').eq('cycle_id', cycle)

    /* Plus de distribution automatique (chantier 3) : chacun pose ses barquettes sur ses dîners, comme `choisir_un_repas`. */
    const jourDe = (i: number) => `2029-01-${String(8 + i).padStart(2, '0')}`
    const cases = [kamil.userId, thauba.userId].flatMap(u =>
      barquettes!.filter(b => b.for_user_id === u).map((b, i) => (
        { userId: u, jour: jourDe(i), repas: 'diner', portionId: b.id })))
    expect(cases).toHaveLength(8)

    const { error } = await kamil.client.from('meal_slot').upsert(cases.map(c => ({
      household_id: kamil.householdId, cycle_id: cycle,
      user_profile_id: c.userId, day: c.jour, meal: c.repas, portion_id: c.portionId,
    })), { onConflict: 'household_id,user_profile_id,day,meal' })
    expect(error, 'la distribution a échoué').toBeNull()

    await kamil.client.from('cycle').update({ state: 'semaine' }).eq('id', cycle)

    const { data: semaine } = await kamil.client.from('meal_slot')
      .select('user_profile_id').eq('cycle_id', cycle)
    const parQui = new Map<string, number>()
    for (const s of semaine!) parQui.set(s.user_profile_id, (parQui.get(s.user_profile_id) ?? 0) + 1)
    expect(parQui.get(kamil.userId), 'Kamil n’a rien à manger').toBe(4)
    expect(parQui.get(thauba.userId), 'Thauba n’a rien à manger').toBe(4)
  })

  it('la semaine : manger est UN geste, et il consomme la barquette', async () => {
    const { data: cas } = await kamil.client.from('meal_slot')
      .select('id, portion_id').eq('cycle_id', cycle)
      .eq('user_profile_id', kamil.userId).order('day').limit(1).single()

    const { error } = await kamil.client.from('meal_slot').update({
      state: 'mange', eaten_at: new Date().toISOString(),
    }).eq('id', cas!.id)
    expect(error).toBeNull()

    const { data: barquette } = await kamil.client.from('portion')
      .select('state').eq('id', cas!.portion_id!).single()
    expect(barquette!.state, 'la barquette est restée au frigo après le repas')
      .toBe('mangee')
  })

  it('dimanche suivant : le bilan se remplit tout seul, puis on clôt', async () => {
    const { data: barquettes } = await kamil.client.from('portion')
      .select('state').eq('cycle_id', cycle)
    expect(barquettes!.filter(b => b.state === 'mangee')).toHaveLength(1)

    const { error } = await kamil.client.from('cycle')
      .update({ state: 'cloture' }).eq('id', cycle)
    expect(error, 'la clôture a échoué').toBeNull()

    const { data: clos } = await kamil.client.from('cycle')
      .select('closed_at').eq('id', cycle).single()
    expect(clos!.closed_at, 'la clôture n’a pas été horodatée').not.toBeNull()

    // Et la semaine suivante peut s'ouvrir.
    const { data: suivant, error: e2 } = await kamil.client.rpc('open_cycle', {
      p_week_of: '2029-01-15', p_servings: 8,
    })
    expect(e2, 'impossible d’enchaîner sur la semaine suivante').toBeNull()
    expect(suivant).not.toBe(cycle)
  })

  it('tout est resté dans le foyer', async () => {
    const etranger = await makeActor('parcours-etranger')
    for (const table of ['cycle', 'portion', 'shopping_item', 'session_task',
      'meal_slot', 'stock_item', 'store', 'aisle_order'] as const) {
      const { data } = await etranger.client.from(table)
        .select('id').eq('household_id', kamil.householdId)
      expect(data ?? [], `fuite depuis ${table}`).toHaveLength(0)
    }
  })
})
