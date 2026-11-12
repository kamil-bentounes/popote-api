/**
 * Clôturer un mois (D78, § 4.5).
 *
 * Trois étapes — les factures, les dépenses au fil du mois, ce qui reste — puis
 * le gel. Le résultat ne dépend que de ce que montre l'écran (saisies et
 * bascules), jamais d'une confirmation antérieure.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { choixDe, clore, declare, foyerDOctobre, foyerSolo, ligne, membre, ou, ouvre,
         poseCharge } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-01T10:00:00+01:00'))
afterAll(remetLHeure)

const montant = async (charge: string, mois = '2026-10-01') =>
  (await ligne(charge, mois))!.montant_cents

describe('les gardes', () => {
  it('refuse le mois en cours, même son dernier jour', async () => {
    const { f } = await foyerDOctobre('clo-courant')
    await regleLHeure('2026-10-31T23:00:00+01:00')
    expect((await clore(f)).error?.message)
      .toMatch(/On clôture octobre une fois fini, à partir du 1er novembre/)
    await regleLHeure('2026-11-01T10:00:00+01:00')
  })

  it('refuse un mois sans revenu', async () => {
    const { f } = await foyerDOctobre('clo-sans-revenu')
    expect((await clore(f, { mois: '2026-08-01' })).error?.message)
      .toMatch(/Ajoute ton revenu d'août pour clôturer août/)
  })

  it('refuse une seconde clôture', async () => {
    const { f, poche } = await foyerDOctobre('clo-deux-fois')
    ou(await clore(f, { poche }))
    expect((await clore(f, { poche })).error?.message).toMatch(/Octobre est déjà clôturé/)
  })

  it('exige une poche du foyer pour mettre de côté', async () => {
    const { f } = await foyerDOctobre('clo-sans-poche')
    expect((await clore(f, { mis: 1_000 })).error?.message).toMatch(/poche/)
  })
})

describe('les trois étapes', () => {
  it('factures, saisies, « Rien dépensé », prévu ; tout gelé ; le reste au centime ; le versement',
    async () => {
      const { f, id, poche } = await foyerDOctobre('clo-etapes')
      const courses = (await ligne(id.courses, '2026-10-01'))!.id
      for (const [jour, cents] of [['2026-10-03', 6_240], ['2026-10-07', 11_850],
                                   ['2026-10-10', 4_790]] as const) {
        ou(await declare(f, courses, jour, cents))
      }
      const electricite = (await ligne(id.electricite, '2026-10-01'))!.id
      const r = ou(await clore(f, {
        factures: [{ depense: electricite, montant_cents: 6_200 }], rien: [id.sorties], poche,
      })) as { cloture: string; non_soldees: unknown[] }
      expect(r.non_soldees).toEqual([])

      expect(await montant(id.electricite)).toBe(6_200)
      expect(await montant(id.courses)).toBe(22_880)
      expect(await montant(id.sorties)).toBe(0)
      expect(await montant(id.restaurants), 'sans réponse, la ligne garde son prévu').toBe(40_000)
      expect(await montant(id.internet)).toBe(3_700)
      expect(await montant(id.entretien)).toBe(4_167)
      const { data: libres } = await admin().from('depense').select('id')
        .eq('household_id', f.householdId).eq('mois', '2026-10-01').is('confirme_le', null)
      expect(libres, 'une ligne du mois a échappé au gel').toEqual([])

      const c = await choixDe(f)
      expect(c.reste_cents).toBe(432_500 - 76_947)
      expect(c.mis_de_cote_cents, '« tout ce qui reste » met de côté le reste exact')
        .toBe(432_500 - 76_947)
      const { data: v } = await admin().from('versement_epargne')
        .select('montant_cents, motif, poche_id').eq('id', c.versement_id!).single()
      expect(v).toEqual({ montant_cents: 355_553, motif: 'balayage', poche_id: poche })
    })

  it('une facture validée par sa feuille garde son montant, sauf si on la modifie à la clôture',
    async () => {
      const a = await foyerDOctobre('clo-feuille')
      const el = (await ligne(a.id.electricite, '2026-10-01'))!.id
      ou(await a.f.client.rpc('confirme_la_depense', { la_depense: el, reel_cents: 6_200 }))
      ou(await clore(a.f, { mis: 0 }))
      expect(await montant(a.id.electricite)).toBe(6_200)

      const b = await foyerDOctobre('clo-feuille-modifiee')
      const el2 = (await ligne(b.id.electricite, '2026-10-01'))!.id
      ou(await b.f.client.rpc('confirme_la_depense', { la_depense: el2, reel_cents: 6_200 }))
      ou(await clore(b.f, { factures: [{ depense: el2, montant_cents: 5_800 }], mis: 0 }))
      expect(await montant(b.id.electricite)).toBe(5_800)
    })

  it('au-delà du reste, ramené au reste ; un reste négatif ne verse rien, et la clôture passe',
    async () => {
      const a = await foyerDOctobre('clo-ramene')
      ou(await clore(a.f, { mis: 999_999_999, poche: a.poche }))
      expect((await choixDe(a.f)).mis_de_cote_cents).toBe(432_500 - 142_867)

      const b = await foyerDOctobre('clo-negatif', { revenu: 50_000 })
      ou(await clore(b.f, { poche: b.poche }))
      expect(await choixDe(b.f)).toMatchObject({
        reste_cents: 50_000 - 142_867, mis_de_cote_cents: 0, versement_id: null })
    })

  it('une ligne sans part ne fait pas échouer la clôture : elle n’est que gelée', async () => {
    const { f, poche } = await foyerDOctobre('clo-sans-part')
    const sansPart = async (libelle: string, mode: string) => {
      const c = ou(await admin().from('charge').insert({
        household_id: f.householdId, libelle, montant_cents: 5_000, periodicite: 'mensuel',
        mode, debut: '2026-01-01' }).select().single()) as { id: string }
      ou(await admin().from('depense').insert({
        household_id: f.householdId, charge_id: c.id, mois: '2026-10-01', libelle,
        montant_cents: 5_000, montant_prevu_cents: 5_000, nature: 'estimee',
        source: 'modele', facon: mode }).select())
      return c.id
    }
    const gaz = await sansPart('Gaz', 'facture')
    const essence = await sansPart('Essence', 'au_fil')
    expect((await clore(f, { poche })).error).toBeNull()
    for (const c of [gaz, essence]) {
      const l = (await ligne(c, '2026-10-01'))!
      expect(l.confirme_le).not.toBeNull()
      expect(l.montant_cents).toBe(5_000)
      expect(l.depense_part).toEqual([])
    }
  })

  it('la clôture ouvre d’abord le mois : une charge posée sans rouvrir l’écran y compte',
    async () => {
      const { f, poche } = await foyerDOctobre('clo-ouvre')
      const pharmacie = await poseCharge(f, { libelle: 'Pharmacie', cents: 2_000,
                                              mode: 'au_fil', debut: '2026-10-01' })
      expect(await ligne(pharmacie, '2026-10-01')).toBeNull()
      ou(await clore(f, { poche }))
      expect(await montant(pharmacie)).toBe(2_000)
      expect((await choixDe(f)).reste_cents).toBe(432_500 - 142_867 - 2_000)
    })
})

describe('à deux', () => {
  it('Thauba arrivée le 15/11 sans revenu : novembre attend ; son revenu le débloque, au prorata',
    async () => {
      await regleLHeure('2026-12-02T10:00:00+01:00')
      const f = await foyerSolo('clo-thauba', { revenu: 370_000 })
      const thauba = await membre(f, 'Thauba', { arrivee: '2026-11-15' })
      const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 100_000, commun: true,
                                          participants: [f.userId, thauba.userId] })
      await ouvre(f, '2026-11-01')
      expect((await clore(f, { mois: '2026-11-01', mis: 0 })).error?.message)
        .toMatch(/Thauba n'a pas encore posé son revenu : novembre attend/)
      ou(await thauba.client.from('revenu').insert({
        household_id: f.householdId, user_profile_id: thauba.userId,
        net_mensuel_cents: 240_000, valid_from: '2026-12-01' }).select())
      ou(await clore(f, { mois: '2026-11-01', mis: 0 }))
      const sienne = (await ligne(loyer, '2026-11-01'))!.depense_part
        .find(p => p.user_profile_id === f.userId)!.part_cents
      expect(sienne, 'novembre n’est pas au prorata (370 / 610)').toBeGreaterThan(60_000)
      expect(sienne).toBeLessThan(61_000)
      await regleLHeure('2026-11-01T10:00:00+01:00')
    })

  it('montants impairs, deux revenus : les parts font le total au centime, le reste est celui de Kamil',
    async () => {
      const f = await foyerSolo('clo-impairs', { revenu: 370_000 })
      const thauba = await membre(f, 'Thauba', { revenu: 240_001 })
      const both = [f.userId, thauba.userId]
      const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 100_001, commun: true,
                                          participants: both })
      const courses = await poseCharge(f, { libelle: 'Courses', cents: 80_001, mode: 'au_fil',
                                            commun: true, participants: both })
      const internet = await poseCharge(f, { libelle: 'Internet', cents: 3_701 })
      await ouvre(f, '2026-10-01')
      const poche = (ou(await admin().from('poche_epargne').insert({
        household_id: f.householdId, libelle: 'Urgence', genre: 'urgence', objectif_cents: 100_000,
      }).select().single()) as { id: string }).id
      const idCourses = (await ligne(courses, '2026-10-01'))!.id
      ou(await declare(f, idCourses, '2026-10-04', 6_241))
      ou(await declare(thauba, idCourses, '2026-10-09', 11_851))
      ou(await clore(f, { poche }))

      const lignes = [[loyer, 100_001], [courses, 18_092], [internet, 3_701]] as const
      let sesParts = 0
      for (const [charge, total] of lignes) {
        const l = (await ligne(charge, '2026-10-01'))!
        expect(l.montant_cents).toBe(total)
        expect(l.depense_part.reduce((s, p) => s + p.part_cents, 0),
          'les parts doivent faire le total, au centime').toBe(total)
        sesParts += l.depense_part.find(p => p.user_profile_id === f.userId)!.part_cents
      }
      // Loyer : le partage se fait au point de base (0064) — 6 066 / 10 000 pour
      // Kamil (370 000 sur 610 001), soit 60 661 sur 100 001 ; Thauba, le reste.
      const loyerParts = (await ligne(loyer, '2026-10-01'))!.depense_part
      expect(loyerParts.find(p => p.user_profile_id === f.userId)!.part_cents).toBe(60_661)
      expect(loyerParts.find(p => p.user_profile_id === thauba.userId)!.part_cents).toBe(39_340)
      const c = await choixDe(f)
      expect(c.reste_cents).toBe(370_000 - sesParts)
      expect(c.mis_de_cote_cents).toBe(370_000 - sesParts)
      const { data: v } = await admin().from('versement_epargne')
        .select('montant_cents').eq('id', c.versement_id!).single()
      expect(v!.montant_cents).toBe(370_000 - sesParts)
    })

  it('un membre parti le 03/11 : octobre se clôture le 05/11 avec les parts d’octobre', async () => {
    await regleLHeure('2026-11-05T10:00:00+01:00')
    const f = await foyerSolo('clo-depart', { revenu: 300_000 })
    const thauba = await membre(f, 'Thauba', { revenu: 300_000 })
    const communes = await poseCharge(f, { libelle: 'Communes', cents: 167_853, commun: true,
                                           participants: [f.userId, thauba.userId] })
    await ouvre(f, '2026-10-01')
    ou(await admin().from('user_profile').delete().eq('id', thauba.userId).select())
    ou(await clore(f, { mis: 0 }))
    const parts = (await ligne(communes, '2026-10-01'))!.depense_part
    expect(parts, 'octobre a été repartagé sur Kamil seul').toHaveLength(2)
    const sienne = parts.find(p => p.user_profile_id === f.userId)!.part_cents
    expect([83_926, 83_927]).toContain(sienne)
    expect((await choixDe(f)).reste_cents).toBe(300_000 - sienne)
    await regleLHeure('2026-11-01T10:00:00+01:00')
  })

  it('retiré d’une charge en octobre, plus de part en octobre ; retiré le 1er novembre, il la garde',
    async () => {
      for (const [quand, attendu] of [['2026-10-20T10:00:00+02:00', 1],
                                      ['2026-11-01T09:00:00+01:00', 2]] as const) {
        await regleLHeure(quand)
        const f = await foyerSolo(`clo-retire-${attendu}`, { revenu: 300_000 })
        const thauba = await membre(f, 'Thauba', { revenu: 300_000 })
        const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 100_000, commun: true,
                                            participants: [f.userId, thauba.userId] })
        await ouvre(f, '2026-10-01')
        // Ce que fait « Changer qui participe » : retirer, puis refiger le mois COURANT.
        ou(await f.client.from('charge_participant').delete()
          .eq('charge_id', loyer).eq('user_profile_id', thauba.userId).select())
        ou(await f.client.rpc('refige_le_mois', { le_mois: `${quand.slice(0, 7)}-01` }))
        await regleLHeure('2026-11-02T10:00:00+01:00')
        ou(await clore(f, { mis: 0 }))
        expect((await ligne(loyer, '2026-10-01'))!.depense_part).toHaveLength(attendu)
      }
      await regleLHeure('2026-11-01T10:00:00+01:00')
    })
})
