/**
 * Une ligne du mois naît avec sa façon, et un mois clôturé n'en gagne plus.
 *
 * Sans la façon, une ligne passerait pour un ajustement et sauterait les étapes
 * 2 et 3 de la clôture. Et une ligne qui naît dans un mois clôturé s'ajoute à
 * un mois dont le reste est déjà mis de côté.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { clos, foyerSolo, ligne, ou, ouvre, poseCharge, type Foyer } from './helpers/budget'

let f: Foyer
let charges: Record<'fixe' | 'facture' | 'au_fil' | 'mis_de_cote', string>

beforeAll(async () => {
  f = await foyerSolo('lignes')
  charges = {
    fixe: await poseCharge(f, { libelle: 'Internet', cents: 3_700, mode: 'fixe' }),
    facture: await poseCharge(f, { libelle: 'Électricité', cents: 5_000, mode: 'facture' }),
    au_fil: await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil' }),
    mis_de_cote: await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                       mode: 'mis_de_cote' }),
  }
})

describe('une ligne naît avec sa façon', () => {
  it('ouvre_le_mois écrit la façon de la charge, et la nature qui va avec', async () => {
    await ouvre(f, '2026-10-01')
    for (const [mode, id] of Object.entries(charges)) {
      const l = await ligne(id, '2026-10-01')
      expect(l?.facon, mode).toBe(mode)
      expect(l?.nature, mode).toBe(mode === 'fixe' ? 'connue' : 'estimee')
    }
  })

  it('ouvre_la_charge aussi', async () => {
    ou(await f.client.rpc('ouvre_la_charge', {
      la_charge: charges.au_fil, foyer: f.householdId, le_mois: '2026-09-01' }))
    expect((await ligne(charges.au_fil, '2026-09-01'))?.facon).toBe('au_fil')
  })

  it('aucune ligne modèle du foyer n’est sans façon', async () => {
    const { data } = await admin().from('depense').select('id')
      .eq('household_id', f.householdId).eq('source', 'modele').is('facon', null)
    expect(data).toEqual([])
  })
})

describe('un mois clôturé ne gagne plus de ligne', () => {
  it('ni par ouvre_le_mois, ni par ouvre_la_charge, ni pour une charge ajoutée après', async () => {
    await clos(f, '2026-07-01')
    const tard = await poseCharge(f, { libelle: 'Netflix', cents: 1_399 })
    await ouvre(f, '2026-07-01')
    ou(await f.client.rpc('ouvre_la_charge', {
      la_charge: tard, foyer: f.householdId, le_mois: '2026-07-01' }))
    expect(await ligne(tard, '2026-07-01')).toBeNull()
    expect(await ligne(charges.fixe, '2026-07-01')).toBeNull()
  })
})
