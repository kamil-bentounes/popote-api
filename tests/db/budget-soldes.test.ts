/**
 * La clôture solde les années (étape 1) : décembre dans décembre, même clôturé
 * en janvier ; une année antérieure encore ouverte dans le mois qu'on clôture ;
 * une charge archivée aussi ; et l'aperçu dit, au centime, ce qui sera posé.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { ajustements, clore, foyerSolo, ligne, membre, ou, ouvre, ouvreLAnnee, poseCharge }
  from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

afterAll(remetLHeure)

async function avecEntretien(nom: string, o: { revenu?: number } = {}) {
  const f = await foyerSolo(nom, { revenu: o.revenu })
  const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                          mode: 'mis_de_cote', categorie: 'auto' })
  await ouvreLAnnee(f, entretien, 2026)
  return { f, entretien }
}
const poses = async (charge: string) =>
  (await ajustements(charge)).map(l => [l.mois, l.montant_cents, l.libelle, !!l.confirme_le])

describe('la clôture solde les années', () => {
  it('décembre solde 2026 dans décembre, même clôturé en janvier ; l’aperçu le disait', async () => {
    await regleLHeure('2027-01-05T10:00:00+01:00')
    const { f, entretien } = await avecEntretien('soldes-decembre')
    await ouvre(f, '2026-12-01')
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' }))
    // Ouvrir l'écran de clôture ne pose rien.
    expect(await ajustements(entretien)).toEqual([])
    const r = ou(await clore(f, { mois: '2026-12-01', mis: 0 })) as { non_soldees: unknown[] }
    expect(r.non_soldees).toEqual([])
    expect(await poses(entretien))
      .toEqual([['2026-12-01', -16_668, 'Entretien auto — solde 2026', true]])
    expect(apercu).toEqual([{ charge: entretien, libelle: 'Entretien auto', annee: 2026,
                              cents: -16_668 }])
    const { data } = await admin().from('cloture_choix').select('reste_cents')
      .eq('household_id', f.householdId).single()
    expect(data!.reste_cents).toBe(432_500 - 4_167 + 16_668)
  })

  it('janvier 2027 clôturé avant décembre 2026 solde 2026 pour de bon, une seule fois', async () => {
    await regleLHeure('2027-02-03T10:00:00+01:00')
    const { f, entretien } = await avecEntretien('soldes-janvier')
    await ouvre(f, '2027-01-01')
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2027-01-01' }))
    expect(apercu).toEqual([{ charge: entretien, libelle: 'Entretien auto', annee: 2026,
                              cents: -16_668 }])
    ou(await clore(f, { mois: '2027-01-01', mis: 0 }))
    ou(await clore(f, { mois: '2026-12-01', mis: 0 }))
    expect((await poses(entretien)).map(p => [p[0], p[1]])).toEqual([['2027-01-01', -16_668]])
  })

  it('une facture de 320 € en novembre : décembre ne pose plus rien', async () => {
    await regleLHeure('2026-11-10T12:00:00+01:00')
    const { f, entretien } = await avecEntretien('soldes-320')
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 32_000, paye_le: '2026-11-10' }))
    await regleLHeure('2027-01-05T10:00:00+01:00')
    ou(await clore(f, { mois: '2026-12-01', mis: 0 }))
    expect((await poses(entretien)).map(p => p[1])).toEqual([15_332])
    const { data } = await admin().from('releve_annuel')
      .select('reel_cents, prevu_cents, ecart_cents').eq('charge_id', entretien).single()
    expect(data).toEqual({ reel_cents: 32_000, prevu_cents: 16_668, ecart_cents: 15_332 })
  })

  it('une charge archivée se solde aussi', async () => {
    await regleLHeure('2027-01-05T10:00:00+01:00')
    const { f, entretien } = await avecEntretien('soldes-archivee')
    ou(await admin().from('charge').update({ archive_le: '2026-11-20T10:00:00Z' })
      .eq('id', entretien).select())
    ou(await clore(f, { mois: '2026-12-01', mis: 0 }))
    const { data } = await admin().from('releve_annuel').select('annee').eq('charge_id', entretien)
    expect(data).toEqual([{ annee: 2026 }])
  })

  it('un solde qui refuse laisse son année ouverte, et la clôture passe en la nommant', async () => {
    await regleLHeure('2027-01-05T10:00:00+01:00')
    const f = await foyerSolo('soldes-refus', { revenu: 300_000 })
    /* Thauba arrive en septembre : son premier revenu remonte au mois de son
       arrivée (0103). Arrivé en janvier, il aurait porté onze mois positifs, et
       le mélange de signes qu'on éprouve n'existerait pas. */
    const thauba = await membre(f, 'Thauba', { revenu: 300_000, arrivee: '2026-09-01' })
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
      mode: 'mis_de_cote', commun: true, participants: [f.userId, thauba.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    /* Des parts de signes mêlés : sur l'année, Thauba a porté au total un montant
       NÉGATIF (−15 833 + 3 × ~2 083). La proportion n'existe pas (0069). */
    const sept = (await ligne(entretien, '2026-09-01'))!.id
    ou(await admin().from('depense_part').delete().eq('depense_id', sept).select())
    ou(await admin().from('depense_part').insert([
      { depense_id: sept, user_profile_id: f.userId, household_id: f.householdId,
        part_cents: 20_000, part_bps: 10000 },
      { depense_id: sept, user_profile_id: thauba.userId, household_id: f.householdId,
        part_cents: -15_833, part_bps: 0 },
    ]).select())
    const r = ou(await clore(f, { mois: '2026-12-01', mis: 0 })) as {
      non_soldees: { charge: string; annee: number; raison: string }[] }
    expect(r.non_soldees).toHaveLength(1)
    expect(r.non_soldees[0]).toMatchObject({ charge: entretien, annee: 2026 })
    expect(r.non_soldees[0].raison).toMatch(/même sens/)
    const { data } = await admin().from('releve_annuel').select('annee').eq('charge_id', entretien)
    expect(data, 'l’année refusée a été marquée soldée').toEqual([])
  })
})
