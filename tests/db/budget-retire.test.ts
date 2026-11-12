/**
 * « Retirer » une charge (0088, § 4.5).
 *
 * Une saisie, c'est de l'argent dont on a dit qu'il était sorti : elle ne part
 * pas sans qu'on l'ait vue. Et une année soldée ne bouge plus : retirer la
 * copropriété effaçait ses douze lignes de 2026, la facture-relevé de 1 200 €
 * restait, et plus rien ne recomptait ces 1 200 €.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin, type Actor } from './helpers/db'
import { ajustementEnAdmin, ajustements, clore, clos, declare, foyerDOctobre, foyerSolo, ligne,
         ou, ouvre, ouvreLAnnee, poseCharge, soldeEnAdmin } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-10T12:00:00+01:00'))
afterAll(remetLHeure)

const retire = (a: Actor, charge: string, avec = false) =>
  a.client.rpc('retire_charge', { p_charge: charge, ...(avec ? { avec_les_saisies: true } : {}) })

const totalDe2026 = async (charge: string) => {
  const { data } = await admin().from('depense').select('montant_cents, source, regularise_annee, mois')
    .eq('charge_id', charge)
  return (data ?? []).filter(l => l.mois.startsWith('2026') || l.regularise_annee === 2026)
    .reduce((s, l) => s + l.montant_cents, 0)
}

describe('une charge au fil du mois', () => {
  it('refuse avec le total ; retire si on le dit ; garde le mois clôturé et ses saisies', async () => {
    const { f, id } = await foyerDOctobre('ret-saisies')
    await ouvre(f, '2026-09-01')
    const sept = (await ligne(id.courses, '2026-09-01'))!.id
    ou(await declare(f, sept, '2026-09-14', 5_000))
    await clos(f, '2026-09-01')
    const oct = (await ligne(id.courses, '2026-10-01'))!.id
    ou(await declare(f, oct, '2026-10-02', 30_000))
    ou(await declare(f, oct, '2026-10-09', 13_000))

    const r = await retire(f, id.courses)
    expect(r.error?.message).toBe('Courses a 430 € de dépenses déclarées en octobre.')
    expect(r.error?.hint).toBe('avec_les_saisies')
    expect(r.error?.details).toBe('43000')

    expect(ou(await retire(f, id.courses, true))).toBe('archivee')
    expect(await ligne(id.courses, '2026-10-01')).toBeNull()
    expect(await ligne(id.courses, '2026-09-01')).not.toBeNull()
    const { data } = await admin().from('saisie').select('montant_cents').eq('depense_id', sept)
    expect(data).toEqual([{ montant_cents: 5_000 }])
  })

  it('le refus ne compte que ce qui partirait, pas l’amorce confirmée de septembre', async () => {
    const { f, id } = await foyerDOctobre('ret-amorce')
    await ouvre(f, '2026-09-01')
    const sept = (await ligne(id.courses, '2026-09-01'))!.id
    ou(await declare(f, sept, '2026-09-30', 80_000))
    ou(await admin().from('depense').update({ confirme_le: '2026-09-30T20:00:00Z' })
      .eq('id', sept).select())
    ou(await declare(f, (await ligne(id.courses, '2026-10-01'))!.id, '2026-10-02', 4_300))
    expect((await retire(f, id.courses)).error?.message)
      .toBe('Courses a 43 € de dépenses déclarées en octobre.')
  })
})

describe('une charge mise de côté', () => {
  it('Entretien : septembre et octobre clôturés, 320 € le 10/11, retrait le 15/11', async () => {
    const f = await foyerSolo('ret-entretien')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    await clos(f, '2026-09-01')
    await clos(f, '2026-10-01')
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 32_000, paye_le: '2026-11-10' }))
    await regleLHeure('2026-11-15T12:00:00+01:00')
    expect(ou(await retire(f, entretien))).toBe('archivee')
    // Novembre et décembre perdent leur provision : Pl tombe à 83,34 €, +83,34 € tout de suite.
    expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents]))
      .toEqual([['2026-11-01', 15_332], ['2026-11-01', 8_334]])

    await regleLHeure('2027-01-05T10:00:00+01:00')
    ou(await clore(f, { mois: '2026-12-01', mis: 0 }))
    expect((await ajustements(entretien)).map(l => l.montant_cents),
      'la clôture de décembre a reposé un écart').toEqual([15_332, 8_334])
    expect(await totalDe2026(entretien)).toBe(32_000)
    await regleLHeure('2026-11-10T12:00:00+01:00')
  })

  it('la copropriété garde ses 1 200 € de 2026, la taxe foncière ses 1 450 €', async () => {
    const f = await foyerSolo('ret-soldees')
    const copro = await poseCharge(f, { libelle: 'Charges de copropriété', cents: 30_000,
                                        mode: 'mis_de_cote', periodicite: 'trimestriel' })
    const taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                                       mode: 'mis_de_cote' })
    await ouvreLAnnee(f, copro, 2026)
    await ouvreLAnnee(f, taxe, 2026)
    await soldeEnAdmin(f, copro, 2026, { reel: 120_000, prevu: 120_000 })
    await soldeEnAdmin(f, taxe, 2026, { reel: 145_000, prevu: 144_996 })
    await ajustementEnAdmin(f, taxe, '2026-09-01', 2026, 4)
    expect(ou(await retire(f, copro))).toBe('archivee')
    expect(ou(await retire(f, taxe))).toBe('archivee')
    expect(await totalDe2026(copro)).toBe(120_000)
    expect(await totalDe2026(taxe)).toBe(145_000)
  })

  it('le 20/01/2027, l’ajustement « — solde 2026 » de 60 € posé sur janvier reste', async () => {
    await regleLHeure('2027-01-15T12:00:00+01:00')
    const f = await foyerSolo('ret-janvier')
    const taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                                       mode: 'mis_de_cote' })
    await ouvreLAnnee(f, taxe, 2026)
    await soldeEnAdmin(f, taxe, 2026, { reel: 145_000, prevu: 144_996 })
    await ajustementEnAdmin(f, taxe, '2026-09-01', 2026, 4)
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: taxe,
                                                montant_cents: 6_000, paye_le: '2026-12-20' }))
    await regleLHeure('2027-01-20T12:00:00+01:00')
    expect(ou(await retire(f, taxe))).toBe('archivee')
    expect((await ajustements(taxe)).map(l => [l.mois, l.montant_cents, l.libelle]))
      .toContainEqual(['2027-01-01', 6_000, 'Taxe foncière — solde 2026'])
    await regleLHeure('2026-11-10T12:00:00+01:00')
  })
})

describe('ce que « Retirer » ne touche pas', () => {
  it('ni une ligne confirmée, ni un mois clôturé, ni le foyer voisin', async () => {
    const f = await foyerSolo('ret-garde')
    const voisin = await foyerSolo('ret-garde-voisin')
    const internet = await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
    for (const m of ['2026-08-01', '2026-09-01', '2026-10-01']) await ouvre(f, m)
    ou(await f.client.rpc('confirme_la_depense', {
      la_depense: (await ligne(internet, '2026-08-01'))!.id, reel_cents: 3_700 }))
    await clos(f, '2026-09-01')
    expect((await retire(voisin, internet)).error?.message).toMatch(/introuvable/)
    expect(ou(await retire(f, internet))).toBe('archivee')
    expect(await ligne(internet, '2026-08-01')).not.toBeNull()
    expect(await ligne(internet, '2026-09-01')).not.toBeNull()
    expect(await ligne(internet, '2026-10-01')).toBeNull()
  })

  it('une charge ajoutée par erreur part entièrement, sans rien recaler', async () => {
    const f = await foyerSolo('ret-erreur')
    const netflix = await poseCharge(f, { libelle: 'Netflix', cents: 1_399 })
    await ouvre(f, '2026-11-01')
    expect(ou(await retire(f, netflix))).toBe('supprimee')
    expect((await admin().from('charge').select('id').eq('id', netflix)).data).toEqual([])
  })
})
