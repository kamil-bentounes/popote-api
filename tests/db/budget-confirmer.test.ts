/**
 * Confirmer une ligne du mois.
 *
 * Confirmer l'Entretien d'octobre à 320 € faisait passer Pl à 445,01 €, et un
 * ajustement confirmé à 0 € effaçait ses 60 € : seules une facture du mois et
 * une ligne fixe se confirment. Et une facture d'électricité à −50 € grossissait
 * le reste de 100 €.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { ajustementEnAdmin, clos, foyerSolo, ligne, ouvre, poseCharge, type Foyer }
  from './helpers/budget'

let f: Foyer
const id: Record<string, string> = {}

beforeAll(async () => {
  f = await foyerSolo('confirmer')
  const fixe = await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
  const facture = await poseCharge(f, { libelle: 'Électricité', cents: 5_000, mode: 'facture' })
  const auFil = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil' })
  const misDeCote = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                          mode: 'mis_de_cote' })
  await ouvre(f, '2026-09-01')
  await ouvre(f, '2026-10-01')
  id.fixe = (await ligne(fixe, '2026-10-01'))!.id
  id.facture = (await ligne(facture, '2026-10-01'))!.id
  id.auFil = (await ligne(auFil, '2026-10-01'))!.id
  id.misDeCote = (await ligne(misDeCote, '2026-10-01'))!.id
  id.factureSeptembre = (await ligne(facture, '2026-09-01'))!.id
  id.ajustement = await ajustementEnAdmin(f, misDeCote, '2026-10-01', 2026, 6_000)
  await clos(f, '2026-09-01')
})

const confirme = (depense: string, cents: number) =>
  f.client.rpc('confirme_la_depense', { la_depense: depense, reel_cents: cents })

describe('confirme_la_depense', () => {
  it('valide une facture du mois, au centime, parts comprises', async () => {
    expect((await confirme(id.facture, 6_200)).error).toBeNull()
    const { data } = await f.client.from('depense')
      .select('montant_cents, nature, confirme_le, depense_part(part_cents)')
      .eq('id', id.facture).single()
    expect(data!.montant_cents).toBe(6_200)
    expect(data!.nature).toBe('connue')
    expect(data!.confirme_le).not.toBeNull()
    expect(data!.depense_part.reduce((s, p) => s + p.part_cents, 0)).toBe(6_200)
  })

  it('et une ligne fixe', async () => {
    expect((await confirme(id.fixe, 3_700)).error).toBeNull()
  })

  it('refuse une ligne au fil du mois : l’ancien paquet doit se recharger', async () => {
    expect((await confirme(id.auFil, 78_000)).error?.message)
      .toMatch(/au fil du mois\. Recharge la page\./)
  })

  it('refuse une ligne mise de côté, et un ajustement', async () => {
    expect((await confirme(id.misDeCote, 32_000)).error?.message).toMatch(/ne se confirme pas/)
    expect((await confirme(id.ajustement, 0)).error?.message).toMatch(/ne se confirme pas/)
  })

  it('refuse un montant négatif, ou au-delà de 1 000 000 €', async () => {
    expect((await confirme(id.facture, -5_000)).error?.message).toMatch(/entre 0/)
    expect((await confirme(id.facture, 100_000_001)).error?.message).toMatch(/entre 0/)
  })

  it('refuse une ligne d’un mois clôturé', async () => {
    expect((await confirme(id.factureSeptembre, 5_000)).error?.message)
      .toMatch(/Septembre est clôturé/)
  })

  it('confirme_la_ligne reste fermée au client', async () => {
    const { error } = await f.client.rpc('confirme_la_ligne',
      { la_ligne: id.facture, reel_cents: 1 })
    expect(error).not.toBeNull()
  })
})
