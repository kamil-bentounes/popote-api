/**
 * Le client n'écrit plus l'argent des lignes, dans aucun mois.
 *
 * Il écrivait tout. En octobre encore ouvert, il mettait à 0 les parts d'une
 * facture de 50 € non confirmée, et la clôture gonflait le reste de 50 €,
 * balayés vers l'épargne. Dans un mois clôturé, il remettait `confirme_le` à
 * null, puis supprimait la ligne et ses saisies.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { ajustementEnAdmin, clos, foyerSolo, ligne, ou, ouvre, poseCharge, type Foyer }
  from './helpers/budget'

let f: Foyer
let internet: string
let octobre: string
let septembre: string

beforeAll(async () => {
  f = await foyerSolo('ecritures')
  internet = await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
  await ouvre(f, '2026-09-01')
  await ouvre(f, '2026-10-01')
  octobre = (await ligne(internet, '2026-10-01'))!.id
  septembre = (await ligne(internet, '2026-09-01'))!.id
  await clos(f, '2026-09-01')
})

describe('depense', () => {
  it('le client n’en crée pas', async () => {
    const { error } = await f.client.from('depense').insert({
      household_id: f.householdId, charge_id: internet, mois: '2026-12-01',
      libelle: 'Ajout', montant_cents: 100, source: 'manuel' }).select()
    expect(error?.code).toBe('42501')
  })

  it('ni n’en supprime : la ligne reste', async () => {
    const { data } = await f.client.from('depense').delete().eq('id', octobre).select()
    expect(data).toEqual([])
    expect(await ligne(internet, '2026-10-01')).not.toBeNull()
  })

  it.each([
    ['montant_cents', 1], ['facon', 'mis_de_cote'], ['libelle', 'Autre'],
    ['confirme_le', '2026-10-31T00:00:00Z'], ['nature', 'estimee'],
  ])('ni ne change %s', async (colonne, valeur) => {
    const { error } = await f.client.from('depense').update({ [colonne]: valeur })
      .eq('id', octobre).select()
    expect(error?.message).toMatch(/à la main/)
  })

  it('il coche encore « réglé » sur un mois ouvert (l’ancien paquet le fait)', async () => {
    const { error } = await f.client.from('depense').update({ regle_le: '2026-10-31' })
      .eq('id', octobre).select()
    expect(error).toBeNull()
  })

  it('mais pas sur un mois clôturé', async () => {
    const { error } = await f.client.from('depense').update({ regle_le: '2026-09-30' })
      .eq('id', septembre).select()
    expect(error?.message).toMatch(/Septembre est clôturé\. Recharge la page\./)
  })
})

describe('depense_part', () => {
  it('le client n’en pose pas, n’en change pas, n’en supprime pas', async () => {
    const ins = await f.client.from('depense_part').insert({
      depense_id: octobre, user_profile_id: f.userId, household_id: f.householdId,
      part_cents: 1, part_bps: 1 }).select()
    expect(ins.error?.code).toBe('42501')
    const maj = await f.client.from('depense_part').update({ part_cents: 1 })
      .eq('depense_id', octobre).select()
    expect(maj.error?.message).toMatch(/ne se retouche pas/)
    const sup = await f.client.from('depense_part').delete().eq('depense_id', octobre).select()
    expect(sup.data).toEqual([])
  })
})

describe('releve_annuel', () => {
  it('ne s’écrit plus par le client : seul le solde le pose', async () => {
    const ins = await f.client.from('releve_annuel').insert({
      household_id: f.householdId, charge_id: internet, annee: 2026, reel_cents: 0,
      ecart_cents: 0 }).select()
    expect(ins.error?.code).toBe('42501')
  })
})

describe('les ajustements', () => {
  it('une charge-année peut en porter plusieurs', async () => {
    await ajustementEnAdmin(f, internet, '2026-10-01', 2026, 1_000)
    await ajustementEnAdmin(f, internet, '2026-11-01', 2026, -400)
    const { data } = await admin().from('depense').select('id')
      .eq('charge_id', internet).eq('regularise_annee', 2026)
    expect(data).toHaveLength(2)
  })
})

describe('un versement de clôture', () => {
  let poche: string
  let versement: string
  beforeAll(async () => {
    poche = (ou(await admin().from('poche_epargne').insert({
      household_id: f.householdId, libelle: 'Urgence', genre: 'urgence' })
      .select().single()) as { id: string }).id
    versement = (ou(await admin().from('versement_epargne').insert({
      household_id: f.householdId, poche_id: poche, user_profile_id: f.userId,
      montant_cents: 31_680, motif: 'balayage' }).select().single()) as { id: string }).id
    const k = ou(await admin().from('cloture').select('id')
      .eq('household_id', f.householdId).eq('mois', '2026-09-01').single()) as { id: string }
    ou(await admin().from('cloture_choix').insert({
      cloture_id: k.id, household_id: f.householdId, user_profile_id: f.userId,
      reste_cents: 31_680, mis_de_cote_cents: 31_680, poche_id: poche,
      versement_id: versement }).select())
  })

  it('ne se modifie ni ne se supprime en direct', async () => {
    const maj = await f.client.from('versement_epargne').update({ montant_cents: 1 })
      .eq('id', versement).select()
    expect(maj.error?.message).toMatch(/clôture de septembre/)
    const sup = await f.client.from('versement_epargne').delete().eq('id', versement).select()
    expect(sup.error?.message).toMatch(/Reviens sur septembre/)
  })

  it('un versement ordinaire, si', async () => {
    const v = ou(await f.client.from('versement_epargne').insert({
      household_id: f.householdId, poche_id: poche, user_profile_id: f.userId,
      montant_cents: 1_000 }).select().single()) as { id: string }
    const { error } = await f.client.from('versement_epargne').delete().eq('id', v.id).select()
    expect(error).toBeNull()
  })

  it('vider la poche l’emporte quand même, et le choix garde son montant', async () => {
    ou(await admin().from('poche_epargne').delete().eq('id', poche).select())
    const { data } = await admin().from('cloture_choix')
      .select('versement_id, mis_de_cote_cents').eq('household_id', f.householdId)
    expect(data).toEqual([{ versement_id: null, mis_de_cote_cents: 31_680 }])
  })
})
