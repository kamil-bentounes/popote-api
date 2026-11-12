/**
 * « Revenir dessus » : le mois se rouvre, l'épargne revient à son niveau, et
 * une nouvelle clôture refait exactement le même calcul que la première.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { choixDe, clore, declare, foyerDOctobre, ligne, membre, ou } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-01T10:00:00+01:00'))
afterAll(remetLHeure)

const montant = async (charge: string) => (await ligne(charge, '2026-10-01'))!.montant_cents

/** Ce que la poche contient, au centime : la somme de ses versements. */
const dansLaPoche = async (poche: string) =>
  ((ou(await admin().from('versement_epargne').select('montant_cents')
    .eq('poche_id', poche)) as { montant_cents: number }[])
    .reduce((s, v) => s + v.montant_cents, 0))

describe('revenir sur un mois', () => {
  it('le versement part, les lignes restent confirmées, et l’on déclare de nouveau', async () => {
    const { f, id, poche } = await foyerDOctobre('rouvre')
    const r = ou(await clore(f, { poche })) as { cloture: string }
    const { versement_id } = await choixDe(f)
    expect(await dansLaPoche(poche), 'le reste d’octobre : 432 500 − 142 867').toBe(289_633)
    ou(await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
    expect(await dansLaPoche(poche), 'la poche est revenue à son niveau d’avant').toBe(0)
    expect((await admin().from('versement_epargne').select('id').eq('id', versement_id!)).data)
      .toEqual([])
    expect((await admin().from('cloture').select('id').eq('id', r.cloture)).data).toEqual([])
    expect((await admin().from('depense').select('id').eq('household_id', f.householdId)
      .eq('mois', '2026-10-01').is('confirme_le', null)).data).toEqual([])
    ou(await declare(f, (await ligne(id.courses, '2026-10-01'))!.id, '2026-10-30', 1_501))
    // Reclôturer : la saisie de 15,01 € compte, et la poche ne garde QU'UN versement.
    ou(await clore(f, { poche }))
    expect((await choixDe(f)).reste_cents).toBe(432_500 - 142_867 + 80_000 - 1_501)
    expect(await dansLaPoche(poche)).toBe(432_500 - 142_867 + 80_000 - 1_501)
  })

  it('reclôturer refait le même calcul : une saisie retirée rend le prévu, une bascule défaite aussi',
    async () => {
      const { f, id } = await foyerDOctobre('reclot')
      const s = randomUUID()
      ou(await declare(f, (await ligne(id.courses, '2026-10-01'))!.id, '2026-10-12', 31_000, s))
      ou(await clore(f, { rien: [id.sorties], mis: 0 }))
      expect([await montant(id.courses), await montant(id.sorties)]).toEqual([31_000, 0])
      ou(await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
      ou(await f.client.from('saisie').delete().eq('id', s).select())
      ou(await clore(f, { mis: 0 }))
      expect([await montant(id.courses), await montant(id.sorties)]).toEqual([80_000, 10_000])
    })

  it('un revenu posé après la clôture ne change pas son reste ; reclôturer le recalcule',
    async () => {
      const { f } = await foyerDOctobre('reclot-revenu')
      ou(await clore(f, { mis: 0 }))
      const avant = (await choixDe(f)).reste_cents!
      ou(await admin().from('revenu').insert({ household_id: f.householdId,
        user_profile_id: f.userId, net_mensuel_cents: 450_000, valid_from: '2026-10-01' }).select())
      expect((await choixDe(f)).reste_cents).toBe(avant)
      ou(await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
      ou(await clore(f, { mis: 0 }))
      expect((await choixDe(f)).reste_cents).toBe(avant + 450_000 - 432_500)
    })

  it('le versement d’un membre parti reste dans la poche, et son choix disparaît', async () => {
    const { f, poche } = await foyerDOctobre('rouvre-parti')
    const thauba = await membre(f, 'Thauba', { revenu: 240_000 })
    const r = ou(await clore(f, { poche })) as { cloture: string }
    // Son choix, tel que le lot 4 le posera : un versement à son nom.
    const v = ou(await admin().from('versement_epargne').insert({
      household_id: f.householdId, poche_id: poche, user_profile_id: thauba.userId,
      montant_cents: 20_000, motif: 'balayage' }).select().single()) as { id: string }
    ou(await admin().from('cloture_choix').insert({
      cloture_id: r.cloture, household_id: f.householdId, user_profile_id: thauba.userId,
      reste_cents: 20_000, mis_de_cote_cents: 20_000, poche_id: poche, versement_id: v.id,
    }).select())
    ou(await admin().from('user_profile').delete().eq('id', thauba.userId).select())

    // Thauba a rejoint le foyer avant la clôture : il partage les communes, la
    // part de Kamil baisse, son reste monte. Le reste de Kamil est donc lu, pas recalculé ici.
    const miens = (await choixDe(f)).mis_de_cote_cents
    expect(miens).toBeGreaterThan(432_500 - 142_867)
    expect(await dansLaPoche(poche)).toBe(miens + 20_000)
    ou(await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
    expect((await admin().from('versement_epargne').select('id').eq('id', v.id)).data,
      'l’argent de Thauba est sorti de la poche').toHaveLength(1)
    expect(await dansLaPoche(poche), 'seul le versement de Thauba reste, à 200 €').toBe(20_000)
    expect((await admin().from('cloture_choix').select('user_profile_id')
      .eq('cloture_id', r.cloture)).data).toEqual([])
  })

  it('refuse un mois qui n’est pas clôturé', async () => {
    const { f } = await foyerDOctobre('rouvre-ouvert')
    expect((await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' })).error?.message)
      .toMatch(/Octobre n'est pas clôturé/)
  })
})
