/**
 * Les fonctions du budget ne lisent ni n'écrivent le foyer du voisin.
 *
 * Toutes sont `security definer` : la RLS ne les protège pas, seule leur propre
 * garde le fait. Chaque cas passe un identifiant du foyer A au client du foyer B,
 * et vérifie que A n'a pas bougé d'un centime.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { clore, foyerDOctobre, foyerSolo, ou, ouvreLAnnee, poseCharge, soldeEnAdmin, type Foyer }
  from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

let a: Foyer
let entretienA: string
let voisin: Foyer
let entretienVoisin: string
let factureA: string

beforeAll(async () => {
  await regleLHeure('2026-11-10T12:00:00+01:00')
  const o = await foyerDOctobre('iso-a')
  a = o.f
  entretienA = o.id.entretien
  voisin = await foyerSolo('iso-voisin')
  entretienVoisin = await poseCharge(voisin, { libelle: 'Entretien auto', cents: 50_004,
                                               mode: 'mis_de_cote' })
  await ouvreLAnnee(a, entretienA, 2026)
  await ouvreLAnnee(voisin, entretienVoisin, 2026)
  factureA = randomUUID()
  ou(await a.client.rpc('paie_une_facture', { la_facture: factureA, la_charge: entretienA,
                                              montant_cents: 32_000, paye_le: '2026-11-05' }))
})
afterAll(remetLHeure)

const facturesDe = async (foyer: string) =>
  ou(await admin().from('facture').select('id, montant_cents').eq('household_id', foyer)
    .order('id')) as { id: string; montant_cents: number }[]

describe('le voisin ne touche pas au foyer A', () => {
  it('paie_une_facture sur la charge d’un autre foyer est refusé', async () => {
    const avant = await facturesDe(a.householdId)
    const { error } = await voisin.client.rpc('paie_une_facture', {
      la_facture: randomUUID(), la_charge: entretienA, montant_cents: 1_000, paye_le: '2026-11-05' })
    expect(error?.message).toMatch(/pas celle de ton foyer/)
    expect(await facturesDe(a.householdId)).toEqual(avant)
  })

  it('paie_une_facture avec l’identifiant d’une facture d’un autre foyer n’est PAS un succès', async () => {
    const avant = await facturesDe(a.householdId)
    const { error } = await voisin.client.rpc('paie_une_facture', {
      la_facture: factureA, la_charge: entretienVoisin, montant_cents: 1_000,
      paye_le: '2026-11-05' })
    expect(error, 'un renvoi « réussi » sur la facture du voisin').not.toBeNull()
    expect(await facturesDe(a.householdId)).toEqual(avant)
    expect(await facturesDe(voisin.householdId)).toEqual([])
  })

  it('retire_une_facture d’une facture d’un autre foyer est refusé', async () => {
    const { error } = await voisin.client.rpc('retire_une_facture', { la_facture: factureA })
    expect(error?.message).toMatch(/n.existe plus/)
    expect((await facturesDe(a.householdId)).map(f => f.id)).toContain(factureA)
  })

  it('corrige_le_releve d’un relevé d’un autre foyer est refusé', async () => {
    const taxe = await poseCharge(a, { libelle: 'Taxe foncière', cents: 145_000,
                                       mode: 'mis_de_cote', commun: true })
    await soldeEnAdmin(a, taxe, 2026, { reel: 145_000, prevu: 144_996 })
    const { data: releve } = await admin().from('facture').select('id')
      .eq('household_id', a.householdId).eq('origine', 'releve').single()
    const { error } = await voisin.client.rpc('corrige_le_releve',
      { la_facture: releve!.id, montant_cents: 1 })
    expect(error?.message).toMatch(/n.existe plus/)
    const { data } = await admin().from('facture').select('montant_cents')
      .eq('id', releve!.id).single()
    expect(data!.montant_cents).toBe(145_000)
  })

  it('apercu_des_soldes ne rend que le foyer de celui qui demande', async () => {
    const chez = async (f: Foyer) => ou(await f.client.rpc('apercu_des_soldes',
      { le_mois: '2026-12-01' })) as { charge: string }[]
    // Une charge de A sans facture : ses provisions non dépensées reviendraient au solde.
    const controle = await poseCharge(a, { libelle: 'Contrôle technique', cents: 12_000,
                                           mode: 'mis_de_cote' })
    await ouvreLAnnee(a, controle, 2026)
    expect((await chez(a)).map(l => l.charge), 'le foyer A a bien quelque chose à solder')
      .toContain(controle)
    expect((await chez(voisin)).map(l => l.charge)).not.toContain(controle)
    expect((await chez(voisin)).map(l => l.charge)).toContain(entretienVoisin)
  })

  it('rouvre_le_mois ne rouvre pas le mois clôturé d’un autre foyer', async () => {
    const o = await foyerDOctobre('iso-rouvre')
    ou(await clore(o.f, { poche: o.poche }))
    const { error } = await voisin.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' })
    expect(error?.message).toMatch(/n.est pas clôturé/)
    const { data } = await admin().from('cloture').select('id')
      .eq('household_id', o.f.householdId).eq('mois', '2026-10-01')
    expect(data).toHaveLength(1)
  })

  it('cloture_le_mois refuse la poche d’un autre foyer, et ne clôture rien', async () => {
    const o = await foyerDOctobre('iso-poche')
    const pocheVoisine = ou(await admin().from('poche_epargne').insert({
      household_id: voisin.householdId, libelle: 'Poche du voisin', genre: 'urgence' })
      .select().single()) as { id: string }
    const { error } = await clore(o.f, { poche: pocheVoisine.id })
    expect(error, 'la clôture a versé dans la poche du voisin').not.toBeNull()
    const { data: k } = await admin().from('cloture').select('id')
      .eq('household_id', o.f.householdId)
    expect(k, 'le mois est clôturé malgré le refus').toEqual([])
    const { data: v } = await admin().from('versement_epargne').select('id')
      .eq('poche_id', pocheVoisine.id)
    expect(v).toEqual([])
  })
})
