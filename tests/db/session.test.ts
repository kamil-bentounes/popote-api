/**
 * La session : mesurer plutôt que demander (D48), et ne pas se rattacher chez
 * les autres.
 *
 * Personne ne répond honnêtement à « ça t'a pris combien ? » les mains grasses.
 * On chronomètre donc entre « je prends » et « c'est fait », et cette mesure
 * nourrit la durée par défaut du verbe — jamais l'inverse.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor
let cycleAlice: string
let cycleBob: string

async function cyclePour(a: Actor, semaine: string) {
  const { data, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of: semaine }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!.id as string
}

async function action(cycle: string, foyer: string, champs: Record<string, unknown> = {}) {
  const { data, error } = await admin().from('session_task').insert({
    cycle_id: cycle,
    household_id: foyer,
    label: 'Émince 500 g d’oignons',
    verb: 'emincer',
    quantity_g: 500,
    duration_min: 6,
    is_active: true,
    planned_start_min: 0,
    ...champs,
  }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}

beforeAll(async () => {
  alice = await makeActor('sess-alice')
  bob = await makeActor('sess-bob')
  cycleAlice = await cyclePour(alice, '2028-02-07')
  cycleBob = await cyclePour(bob, '2028-02-14')
})

describe('la durée se mesure (D48)', () => {
  it('chronomètre entre le début et la fin, sans rien demander', async () => {
    const t = await action(cycleAlice, alice.householdId)
    const debut = new Date(Date.now() - 9 * 60_000).toISOString()

    await admin().from('session_task').update({ started_at: debut }).eq('id', t.id)
    const { data } = await admin().from('session_task')
      .update({ done_at: new Date().toISOString() }).eq('id', t.id).select().single()

    expect(data!.actual_min, 'aucune durée mesurée').not.toBeNull()
    expect(Number(data!.actual_min)).toBeCloseTo(9, 0)
  })

  it('en tire une observation rattachée au verbe, pas à l’étape', async () => {
    // Une étape n'est jamais refaite ; un verbe l'est toutes les semaines.
    const t = await action(cycleAlice, alice.householdId, { verb: 'raper' })
    await admin().from('session_task')
      .update({ started_at: new Date(Date.now() - 4 * 60_000).toISOString() }).eq('id', t.id)
    await admin().from('session_task')
      .update({ done_at: new Date().toISOString() }).eq('id', t.id)

    const { data } = await admin().from('duration_observation')
      .select('verb, planned_min, actual_min').eq('household_id', alice.householdId)
      .eq('verb', 'raper')
    expect(data!.length, 'la mesure n’a pas été consignée').toBe(1)
    expect(Number(data![0].planned_min)).toBe(6)
    expect(Number(data![0].actual_min)).toBeCloseTo(4, 0)
  })

  it('ne consigne rien pour une action sans verbe reconnu', async () => {
    const t = await action(cycleAlice, alice.householdId, { verb: null })
    const avant = await admin().from('duration_observation')
      .select('id').eq('household_id', alice.householdId)
    await admin().from('session_task')
      .update({ started_at: new Date(Date.now() - 60_000).toISOString() }).eq('id', t.id)
    await admin().from('session_task')
      .update({ done_at: new Date().toISOString() }).eq('id', t.id)
    const apres = await admin().from('duration_observation')
      .select('id').eq('household_id', alice.householdId)
    expect(apres.data!.length).toBe(avant.data!.length)
  })

  it('refuse une action finie qui n’a jamais commencé', async () => {
    const t = await action(cycleAlice, alice.householdId)
    const { error } = await admin().from('session_task')
      .update({ done_at: new Date().toISOString(), started_at: null }).eq('id', t.id)
    expect(error, 'une action s’est terminée sans avoir commencé').not.toBeNull()
  })

  it('ne remesure pas une action déjà terminée', async () => {
    const t = await action(cycleAlice, alice.householdId, { verb: 'melanger' })
    await admin().from('session_task')
      .update({ started_at: new Date(Date.now() - 3 * 60_000).toISOString() }).eq('id', t.id)
    await admin().from('session_task').update({ done_at: new Date().toISOString() }).eq('id', t.id)
    await admin().from('session_task')
      .update({ done_at: new Date(Date.now() + 60_000).toISOString() }).eq('id', t.id)

    const { data } = await admin().from('duration_observation')
      .select('id').eq('household_id', alice.householdId).eq('verb', 'melanger')
    expect(data!.length, 'une seconde observation a été consignée').toBe(1)
  })

  it('n’enregistre jamais une durée nulle', async () => {
    // Cocher une action qu'on a faite sans toucher au téléphone arrive : la
    // mesure doit rester strictement positive pour ne pas fausser la médiane.
    const t = await action(cycleAlice, alice.householdId, { verb: 'saler' })
    const instant = new Date().toISOString()
    await admin().from('session_task').update({ started_at: instant }).eq('id', t.id)
    const { data, error } = await admin().from('session_task')
      .update({ done_at: instant }).eq('id', t.id).select().single()
    expect(error).toBeNull()
    expect(Number(data!.actual_min)).toBeGreaterThan(0)
  })
})

describe('le rattachement au foyer', () => {
  it('redérive le foyer depuis le cycle, quoi qu’on déclare', async () => {
    const { data } = await admin().from('session_task').insert({
      cycle_id: cycleAlice,
      household_id: bob.householdId,      // mensonge
      label: 'Test', duration_min: 1, planned_start_min: 0,
    }).select().single()
    expect(data!.household_id, 'le foyer déclaré a été cru sur parole')
      .toBe(alice.householdId)
  })

  it('refuse une action accrochée à un cycle qui n’existe pas', async () => {
    const { error } = await admin().from('session_task').insert({
      cycle_id: '00000000-0000-0000-0000-000000000000',
      household_id: alice.householdId,
      label: 'Fantôme', duration_min: 1, planned_start_min: 0,
    })
    expect(error).not.toBeNull()
  })

  it('empêche un foyer de lire le plan d’un autre', async () => {
    await action(cycleBob, bob.householdId)
    const { data } = await alice.client.from('session_task')
      .select('id').eq('cycle_id', cycleBob)
    expect(data ?? [], 'fuite de plan entre foyers').toHaveLength(0)
  })

  it('empêche un foyer de cocher une action chez un autre', async () => {
    const t = await action(cycleBob, bob.householdId)
    await alice.client.from('session_task')
      .update({ started_at: new Date().toISOString() }).eq('id', t.id)
    const { data } = await admin().from('session_task')
      .select('started_at').eq('id', t.id).single()
    expect(data!.started_at, 'une action a été prise par un autre foyer').toBeNull()
  })
})

describe('le journal des mesures', () => {
  it('se lit par le foyer, et ne se réécrit pas', async () => {
    const { data: miennes } = await alice.client.from('duration_observation').select('id')
    expect(miennes!.length, 'le foyer ne voit pas ses propres mesures').toBeGreaterThan(0)

    const { data: modifiee } = await alice.client.from('duration_observation')
      .update({ actual_min: 999 }).eq('id', miennes![0].id).select()
    expect(modifiee ?? [], 'une mesure a pu être réécrite').toHaveLength(0)
  })

  it('ne fuit pas vers les autres foyers', async () => {
    const { data } = await bob.client.from('duration_observation')
      .select('id').eq('household_id', alice.householdId)
    expect(data ?? [], 'fuite de mesures entre foyers').toHaveLength(0)
  })
})
