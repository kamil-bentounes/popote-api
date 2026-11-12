/**
 * « Ce dont tu disposes aujourd'hui » : la lecture de la dernière session qui avait un équipement
 * (`lisLEquipementPrecedent`, src/lib/donnees/session.ts), contre la vraie base.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, connecteLeClientPartage, makeActor, type Actor } from './helpers/db'
import { lisLEquipementPrecedent } from './front-fige/lib/donnees/session.ts'

let alice: Actor
let bob: Actor

async function cycleAvec(a: Actor, week_of: string, state: string, appareils: Record<string, number>) {
  const { data: c, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of, state }).select().single()
  expect(error, "l'amorce a échoué").toBeNull()
  const lignes = Object.entries(appareils).map(([appliance_code, capacity]) =>
    ({ cycle_id: c!.id, household_id: a.householdId, appliance_code, capacity }))
  if (lignes.length > 0) {
    const { error: e } = await admin().from('session_appliance').insert(lignes)
    expect(e, "l'amorce des appareils a échoué").toBeNull()
  }
  return c!.id as string
}

beforeAll(async () => {
  alice = await makeActor('equip-alice')
  bob = await makeActor('equip-bob')
  await connecteLeClientPartage(alice)
})

describe('lisLEquipementPrecedent', () => {
  it('rend l’équipement de la session la plus récente qui en a un, pas celui d’un voisin', async () => {
    await cycleAvec(alice, '2034-01-02', 'cloture', { four: 1, plaques: 4 })
    await cycleAvec(alice, '2034-01-09', 'cloture', { four: 2, air_fryer: 1 })
    // une session plus récente SANS équipement ne masque pas la précédente
    await cycleAvec(alice, '2034-01-16', 'cloture', {})
    await cycleAvec(bob, '2034-01-23', 'cloture', { robot_cuiseur: 1 })
    const courant = await cycleAvec(alice, '2034-01-30', 'interrompue', {})
    expect(await lisLEquipementPrecedent(courant)).toEqual({ four: 2, air_fryer: 1 })
  })

  it('n’inclut jamais la session courante', async () => {
    const courant = await cycleAvec(alice, '2034-02-06', 'interrompue', { plaques: 2 })
    expect(await lisLEquipementPrecedent(courant)).toEqual({ four: 2, air_fryer: 1 })
  })

  it('rend {} quand le foyer n’a jamais choisi', async () => {
    const neuf = await makeActor('equip-neuf')
    await connecteLeClientPartage(neuf)
    const c = await cycleAvec(neuf, '2034-03-06', 'selection', {})
    expect(await lisLEquipementPrecedent(c)).toEqual({})
    await connecteLeClientPartage(alice)
  })
})
