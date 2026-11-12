/**
 * Les tables nouvelles du budget, et ce que chacun y peut.
 *
 * `saisie` s'écrit par le client, dans son foyer, à son nom. `facture`,
 * `cloture` et `cloture_choix` ne s'écrivent QUE par les fonctions : une facture
 * écrite en direct n'aurait pas d'ajustement, une clôture pas de gel.
 */
import { randomUUID } from 'node:crypto'
import { beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { foyerSolo, ou, poseCharge, type Foyer } from './helpers/budget'

let f: Foyer
let voisin: Foyer
let ligne: string
let charge: string

beforeAll(async () => {
  f = await foyerSolo('tables')
  voisin = await foyerSolo('tables-voisin')
  charge = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil' })
  /* La ligne est écrite par la clé de service, avec sa façon : la garde des
     saisies (1.7) l'exige, et `ouvre_le_mois` ne l'écrit qu'à partir de 1.6. */
  ligne = (ou(await admin().from('depense').insert({
    household_id: f.householdId, charge_id: charge, mois: '2026-10-01', libelle: 'Courses',
    montant_cents: 80_000, montant_prevu_cents: 80_000, nature: 'estimee',
    source: 'modele', facon: 'au_fil',
  }).select().single()) as { id: string }).id
})

describe('saisie', () => {
  it('s’écrit à son propre nom', async () => {
    const { error } = await f.client.from('saisie').insert({
      id: randomUUID(), household_id: f.householdId, depense_id: ligne,
      fait_le: '2026-10-03', montant_cents: 4_790, saisi_par: f.userId }).select()
    expect(error).toBeNull()
  })
  it('pas au nom de quelqu’un d’autre', async () => {
    const { error } = await f.client.from('saisie').insert({
      id: randomUUID(), household_id: f.householdId, depense_id: ligne,
      fait_le: '2026-10-03', montant_cents: 100, saisi_par: voisin.userId }).select()
    expect(error, 'saisi_par n’est pas forcé').not.toBeNull()
  })
  it('le voisin ne la lit pas, et n’y écrit pas', async () => {
    const { data } = await voisin.client.from('saisie').select('id').eq('depense_id', ligne)
    expect(data).toEqual([])
    const { error } = await voisin.client.from('saisie').insert({
      id: randomUUID(), household_id: f.householdId, depense_id: ligne,
      fait_le: '2026-10-03', montant_cents: 100, saisi_par: voisin.userId }).select()
    expect(error).not.toBeNull()
  })
  it('refuse un montant nul ou négatif', async () => {
    for (const cents of [0, -500]) {
      const { error } = await f.client.from('saisie').insert({
        id: randomUUID(), household_id: f.householdId, depense_id: ligne,
        fait_le: '2026-10-03', montant_cents: cents, saisi_par: f.userId }).select()
      expect(error?.code, `${cents} accepté`).toBe('23514')
    }
  })
})

describe('facture, cloture, cloture_choix : par les fonctions seulement', () => {
  it('le client ne pose ni facture, ni clôture, ni choix', async () => {
    const facture = await f.client.from('facture').insert({
      id: randomUUID(), household_id: f.householdId, charge_id: charge, annee: 2026,
      paye_le: '2026-10-03', montant_cents: 100 }).select()
    expect(facture.error).not.toBeNull()
    const cloture = await f.client.from('cloture').insert({
      household_id: f.householdId, mois: '2026-09-01', cloture_le: new Date().toISOString(),
    }).select()
    expect(cloture.error).not.toBeNull()
  })
  it('le foyer les lit, le voisin non', async () => {
    const k = ou(await admin().from('cloture').insert({
      household_id: f.householdId, mois: '2026-08-01', cloture_le: new Date().toISOString(),
    }).select().single()) as { id: string }
    ou(await admin().from('cloture_choix').insert({
      cloture_id: k.id, household_id: f.householdId, user_profile_id: f.userId,
      reste_cents: 1_000 }).select())
    expect((await f.client.from('cloture').select('id').eq('id', k.id)).data).toHaveLength(1)
    expect((await f.client.from('cloture_choix').select('reste_cents')
      .eq('cloture_id', k.id)).data).toEqual([{ reste_cents: 1_000 }])
    expect((await voisin.client.from('cloture').select('id').eq('id', k.id)).data).toEqual([])
    expect((await voisin.client.from('cloture_choix').select('reste_cents')
      .eq('cloture_id', k.id)).data).toEqual([])
  })
  it('une facture d’une charge garde la charge (restrict)', async () => {
    ou(await admin().from('facture').insert({
      id: randomUUID(), household_id: f.householdId, charge_id: charge, annee: 2026,
      paye_le: '2026-10-03', montant_cents: 32_000 }).select())
    const { error } = await admin().from('depense').delete().eq('charge_id', charge).select()
    expect(error).toBeNull()
    const { error: e2 } = await admin().from('charge').delete().eq('id', charge).select()
    expect(e2?.code, 'la charge est partie avec sa facture').toBe('23503')
  })
})

describe('l’export', () => {
  it('rend saisies, factures, clôtures et choix', async () => {
    const { data, error } = await f.client.rpc('export_my_data')
    expect(error).toBeNull()
    for (const cle of ['saisies', 'factures', 'clotures', 'cloture_choix']) {
      expect(data, cle).toHaveProperty(cle)
    }
  })
})
