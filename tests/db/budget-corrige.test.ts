/**
 * Corriger une charge : les factures décident, les saisies suivent la ligne.
 *
 * Elle supprimait les ajustements et les relevés des années qu'elle refaisait :
 * un dépassement déjà posé disparaissait, et le relevé d'une année close avec.
 * Elle ne refait plus que les lignes `modele` non confirmées, hors mois
 * clôturés et années soldées, puis recale.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin, type Actor } from './helpers/db'
import { ajustementEnAdmin, ajustements, clore, clos, declare, foyerDOctobre, foyerSolo, ligne,
         membre, ou, ouvre, ouvreLAnnee, poseCharge, soldeEnAdmin } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-10T12:00:00+01:00'))
afterAll(remetLHeure)

const corrige = (a: Actor, charge: string, o: {
  libelle: string; cents: number; periodicite: string; debut?: string; mode?: string
}) => a.client.rpc('corrige_la_charge', {
  la_charge: charge, nouveau_libelle: o.libelle, nouveau_montant: o.cents,
  nouvelle_periodicite: o.periodicite, nouveau_debut: o.debut ?? null,
  ...(o.mode ? { nouveau_mode: o.mode } : {}),
})

async function avecEntretien(nom: string) {
  const f = await foyerSolo(nom)
  const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                          mode: 'mis_de_cote', categorie: 'auto' })
  await ouvreLAnnee(f, entretien, 2026)
  return { f, entretien }
}
const poses = async (charge: string) => (await ajustements(charge)).map(l => l.montant_cents)

describe('une charge mise de côté', () => {
  it('renommée, garde ses factures, ses ajustements, son relevé, et les libellés de l’année soldée',
    async () => {
      const f = await foyerSolo('corr-renomme')
      const taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                                         mode: 'mis_de_cote', commun: true })
      await ouvreLAnnee(f, taxe, 2026)
      await soldeEnAdmin(f, taxe, 2026, { reel: 145_000, prevu: 144_996 })
      await ajustementEnAdmin(f, taxe, '2026-09-01', 2026, 4)
      ou(await corrige(f, taxe, { libelle: 'Taxe foncière — résidence', cents: 150_000,
                                  periodicite: 'annuel', mode: 'mis_de_cote' }))
      expect((await admin().from('facture').select('id').eq('charge_id', taxe)).data).toHaveLength(1)
      expect(await poses(taxe), 'un ajustement est parti, ou un nouveau est né').toEqual([4])
      const { data } = await admin().from('releve_annuel').select('prevu_cents')
        .eq('charge_id', taxe).single()
      expect(data!.prevu_cents).toBe(144_996)
      expect((await ligne(taxe, '2026-10-01'))!.libelle).toBe('Taxe foncière')
    })

  it('son montant change : l’année ouverte se recale par un contre-ajustement', async () => {
    const { f, entretien } = await avecEntretien('corr-montant')
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 32_000, paye_le: '2026-11-10' }))
    expect(await poses(entretien)).toEqual([15_332])
    ou(await corrige(f, entretien, { libelle: 'Entretien auto', cents: 60_000,
                                     periodicite: 'annuel', mode: 'mis_de_cote' }))
    // Septembre à décembre refaits à 50 € : Pl = 200 €, cible 120 €, déjà posé 153,32 €.
    expect(await poses(entretien)).toEqual([15_332, -3_332])
  })

  it('ne devient pas mensuelle avec des factures ; sans histoire, si', async () => {
    const { f, entretien } = await avecEntretien('corr-mensuelle')
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 10_000, paye_le: '2026-11-10' }))
    expect((await corrige(f, entretien, { libelle: 'Entretien auto', cents: 4_167,
      periodicite: 'mensuel', mode: 'fixe' })).error?.message)
      .toMatch(/retire-la et ajoute la nouvelle/)

    const vierge = await poseCharge(f, { libelle: 'Contrôle technique', cents: 12_000,
                                         mode: 'mis_de_cote' })
    await ouvre(f, '2026-11-01')
    ou(await corrige(f, vierge, { libelle: 'Contrôle technique', cents: 1_000,
                                  periodicite: 'mensuel', mode: 'fixe' }))
    expect((await ligne(vierge, '2026-11-01'))).toMatchObject({ facon: 'fixe', montant_cents: 1_000 })
  })

  it('« Fixe » est refusé pour l’Entretien d’octobre clôturé puis rouvert', async () => {
    const { f, entretien } = await avecEntretien('corr-rouvert')
    ou(await clore(f, { mis: 0 }))
    ou(await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
    expect((await corrige(f, entretien, { libelle: 'Entretien auto', cents: 4_167,
      periodicite: 'mensuel', mode: 'fixe' })).error?.message)
      .toMatch(/retire-la et ajoute la nouvelle/)
  })
})

describe('les mois', () => {
  it('l’ancien paquet l’appelle encore avec cinq arguments', async () => {
    const f = await foyerSolo('corr-ancien')
    const c = await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
    const { data, error } = await corrige(f, c, { libelle: 'Internet', cents: 3_900,
                                                  periodicite: 'mensuel' })
    expect(error).toBeNull()
    expect(typeof data).toBe('number')
  })

  it('reculer la date de départ ne fait naître aucune ligne dans un mois clôturé', async () => {
    const f = await foyerSolo('corr-recule')
    const c = await poseCharge(f, { libelle: 'Assurance', cents: 3_000, debut: '2026-06-01' })
    await clos(f, '2026-03-01')
    ou(await corrige(f, c, { libelle: 'Assurance', cents: 3_000, periodicite: 'mensuel',
                             debut: '2026-02-01' }))
    expect(await ligne(c, '2026-03-01')).toBeNull()
    expect(await ligne(c, '2026-02-01')).not.toBeNull()
    expect(await ligne(c, '2026-04-01')).not.toBeNull()
  })
})

describe('les saisies suivent la ligne refaite', () => {
  let f: Actor
  let thauba: Actor
  let courses: string
  beforeAll(async () => {
    f = await foyerSolo('corr-saisies', { revenu: 370_000 })
    thauba = await membre(f, 'Thauba', { revenu: 240_000 })
    courses = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil',
                                    commun: true, participants: [f.userId, thauba.userId] })
    await ouvre(f, '2026-09-01')
    await ouvre(f, '2026-10-01')
    ou(await declare(thauba, (await ligne(courses, '2026-10-01'))!.id, '2026-10-04', 30_000))
    ou(await declare(f, (await ligne(courses, '2026-10-01'))!.id, '2026-10-09', 13_000))
  })

  const lues = async () => ou(await admin().from('saisie')
    .select('id, saisi_par, created_at, montant_cents, depense_id')
    .eq('household_id', f.householdId).order('id')) as
    { id: string; saisi_par: string; created_at: string; montant_cents: number; depense_id: string }[]

  it('renommer Courses ou changer son prévu : les 430 € restent, avec leur auteur', async () => {
    const avant = await lues()
    ou(await corrige(f, courses, { libelle: 'Courses et marché', cents: 85_000,
                                   periodicite: 'mensuel', mode: 'au_fil' }))
    const apres = await lues()
    const octobre = (await ligne(courses, '2026-10-01'))!
    expect(octobre.montant_cents).toBe(85_000)
    expect(apres.map(s => ({ ...s, depense_id: undefined })))
      .toEqual(avant.map(s => ({ ...s, depense_id: undefined })))
    expect(apres.every(s => s.depense_id === octobre.id)).toBe(true)
    expect(apres.reduce((t, s) => t + s.montant_cents, 0)).toBe(43_000)
  })

  it('avancer la date de départ au-delà d’un mois qui a des saisies : refusé', async () => {
    ou(await declare(f, (await ligne(courses, '2026-09-01'))!.id, '2026-09-20', 5_000))
    expect((await corrige(f, courses, { libelle: 'Courses', cents: 85_000,
      periodicite: 'mensuel', debut: '2026-10-01', mode: 'au_fil' })).error?.message)
      .toMatch(/Des dépenses sont déclarées en septembre sur cette charge/)
  })

  it('la passer en fixe : refusé', async () => {
    expect((await corrige(f, courses, { libelle: 'Courses', cents: 85_000,
      periodicite: 'mensuel', mode: 'fixe' })).error?.message)
      .toMatch(/Des dépenses sont déclarées en septembre/)
  })
})

describe('la façon de la ligne', () => {
  it('une ligne confirmée d’un mois ouvert garde sa façon, et la clôture la traite ainsi', async () => {
    const { f, id } = await foyerDOctobre('corr-facon')
    const el = (await ligne(id.electricite, '2026-10-01'))!.id
    ou(await f.client.rpc('confirme_la_depense', { la_depense: el, reel_cents: 6_200 }))
    // Septembre, confirmé avant la refonte, avec 820 € déclarés.
    await ouvre(f, '2026-09-01')
    const sept = (await ligne(id.courses, '2026-09-01'))!.id
    ou(await declare(f, sept, '2026-09-30', 82_000))
    ou(await admin().from('depense').update({ confirme_le: '2026-09-30T20:00:00Z' })
      .eq('id', sept).select())

    ou(await corrige(f, id.electricite, { libelle: 'Électricité', cents: 5_000,
                                          periodicite: 'mensuel', mode: 'fixe' }))
    ou(await corrige(f, id.courses, { libelle: 'Courses', cents: 80_000,
                                      periodicite: 'mensuel', mode: 'fixe' }))
    expect((await ligne(id.electricite, '2026-10-01'))).toMatchObject({ facon: 'facture',
                                                                         montant_cents: 6_200 })
    const { data: c } = await admin().from('charge').select('mode, variable, enveloppe_id')
      .eq('id', id.courses).single()
    expect(c).toEqual({ mode: 'fixe', variable: false, enveloppe_id: null })

    ou(await clore(f, { mis: 0 }))
    ou(await clore(f, { mois: '2026-09-01', mis: 0 }))
    expect((await ligne(id.electricite, '2026-10-01'))!.montant_cents).toBe(6_200)
    expect((await ligne(id.courses, '2026-09-01'))!.montant_cents,
      'les Courses de septembre se sont clôturées comme une ligne fixe').toBe(82_000)
  })
})
