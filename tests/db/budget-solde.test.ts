/**
 * Solder une année : ce qui n'a pas servi revient, ou le dépassement s'ajoute.
 *
 * `solde_l_annee` est interne : la clôture l'appelle. On l'appelle ici comme
 * elle, en propriétaire, avec `auth.uid()` posé.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { admin } from './helpers/db'
import { ajustements, clos, foyerSolo, ligne, membre, ou, ouvreLAnnee, poseCharge, type Foyer }
  from './helpers/budget'
import { connexion, enProprietaire } from './helpers/pg'
import { regleLHeure, remetLHeure } from './helpers/horloge'

let c: pg.Client
beforeAll(async () => {
  await regleLHeure('2027-01-05T10:00:00+01:00')
  c = await connexion()
})
afterAll(async () => { await c.end(); await remetLHeure() })

async function solde(f: Foyer, charge: string, annee: number, moisCible: string) {
  await enProprietaire(c, f.userId)
  try {
    await c.query('select public.solde_l_annee($1, $2, $3)', [charge, annee, moisCible])
    await c.query('commit')
  } catch (e) { await c.query('rollback'); throw e }
}

const releve = async (charge: string, annee = 2026) => ou(await admin().from('releve_annuel')
  .select('reel_cents, prevu_cents, ecart_cents').eq('charge_id', charge).eq('annee', annee)
  .maybeSingle())

describe('solder une année', () => {
  it('rend le non-dépensé dans le mois cible, et l’aperçu l’annonçait au centime', async () => {
    const f = await foyerSolo('solde-rend')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' }))
    expect(apercu).toEqual([{ charge: entretien, libelle: 'Entretien auto', annee: 2026,
                              cents: -16_668 }])
    expect(await ajustements(entretien), 'l’aperçu a écrit').toEqual([])

    await solde(f, entretien, 2026, '2026-12-01')
    expect(await releve(entretien)).toEqual({ reel_cents: 0, prevu_cents: 16_668,
                                              ecart_cents: -16_668 })
    expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents, l.libelle]))
      .toEqual([['2026-12-01', -16_668, 'Entretien auto — solde 2026']])

    // Idempotente : une seconde fois ne pose rien.
    await solde(f, entretien, 2026, '2026-12-01')
    expect(await ajustements(entretien)).toHaveLength(1)
  })

  it('matérialise les mois suivis sans ligne, et aucun mois clôturé', async () => {
    const f = await foyerSolo('solde-materialise')
    const ct = await poseCharge(f, { libelle: 'Contrôle technique', cents: 12_000,
                                     mode: 'mis_de_cote' })
    ou(await f.client.rpc('ouvre_la_charge',
      { la_charge: ct, foyer: f.householdId, le_mois: '2026-09-01' }))
    await clos(f, '2026-10-01')
    await solde(f, ct, 2026, '2026-12-01')
    expect(await ligne(ct, '2026-10-01'), 'un mois clôturé a gagné une ligne').toBeNull()
    expect(await ligne(ct, '2026-11-01')).not.toBeNull()
    expect(await ligne(ct, '2026-12-01')).not.toBeNull()
    expect(await releve(ct)).toEqual({ reel_cents: 0, prevu_cents: 3_000, ecart_cents: -3_000 })
  })

  it('une année sans mois suivi se solde à 0, sans ligne', async () => {
    const f = await foyerSolo('solde-sans-suivi', { revenu: null })
    const c2 = await poseCharge(f, { libelle: 'Assurance', cents: 24_000, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, c2, 2026)
    await solde(f, c2, 2026, '2026-12-01')
    expect(await releve(c2)).toEqual({ reel_cents: 0, prevu_cents: 0, ecart_cents: 0 })
    expect(await ajustements(c2)).toEqual([])
  })

  it('reste fermée au client', async () => {
    const f = await foyerSolo('solde-ferme')
    const { error } = await f.client.rpc('solde_l_annee',
      { la_charge: f.compte, annee: 2026, mois_cible: '2026-12-01' })
    expect(error?.message).toMatch(/permission denied/)
  })
})

/**
 * Ce que le solde pose, au centime, dans les cas où l'argent change de sens : le
 * dépassement déjà posé par les factures, le non-dépensé partiel, et un foyer à
 * deux dont chacun a porté une part différente (`pose_les_parts`, branche
 * `comme_soldee` de `cible_de`).
 */
describe('ce que le solde pose', () => {
  const parts = async (ligneId: string) =>
    ou(await admin().from('depense_part').select('user_profile_id, part_cents, part_bps')
      .eq('depense_id', ligneId)) as { user_profile_id: string; part_cents: number; part_bps: number }[]

  it('un solde partiel : 100 € payés sur 166,68 € mis de côté rendent 66,68 €', async () => {
    const f = await foyerSolo('solde-partiel')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 10_000, paye_le: '2026-12-20' }))
    expect(await ajustements(entretien), 'sous le prévu, la facture ne pose rien').toEqual([])
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' })) as
      { cents: number }[]
    expect(apercu.map(a => a.cents)).toEqual([-6_668])

    await solde(f, entretien, 2026, '2026-12-01')
    expect(await releve(entretien)).toEqual({ reel_cents: 10_000, prevu_cents: 16_668,
                                              ecart_cents: -6_668 })
    const [aj] = await ajustements(entretien)
    expect([aj.mois, aj.montant_cents]).toEqual(['2026-12-01', -6_668])
    expect(aj.depense_part.map(p => p.part_cents)).toEqual([-6_668])
  })

  it('l’aperçu compte les mois que le solde va matérialiser, et le solde pose le même chiffre', async () => {
    const f = await foyerSolo('solde-apercu-avant')
    const ct = await poseCharge(f, { libelle: 'Contrôle technique', cents: 12_000,
                                     mode: 'mis_de_cote' })
    // Seul septembre a sa ligne : octobre à décembre naissent au solde.
    ou(await f.client.rpc('ouvre_la_charge',
      { la_charge: ct, foyer: f.householdId, le_mois: '2026-09-01' }))
    expect(await ligne(ct, '2026-11-01')).toBeNull()
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' })) as
      { cents: number }[]
    expect(apercu.map(a => a.cents), 'sans les provisions à venir, l’aperçu dirait −10 €')
      .toEqual([-4_000])
    await solde(f, ct, 2026, '2026-12-01')
    expect((await ajustements(ct)).map(l => l.montant_cents)).toEqual([-4_000])
    expect(await releve(ct)).toEqual({ reel_cents: 0, prevu_cents: 4_000, ecart_cents: -4_000 })
  })

  it('un dépassement déjà posé par les factures : le solde n’ajoute rien', async () => {
    const f = await foyerSolo('solde-depasse')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 60_000, paye_le: '2026-12-20' }))
    expect((await ajustements(entretien)).map(l => l.montant_cents)).toEqual([43_332])
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' }))
    expect(apercu, 'rien à poser : l’aperçu est vide').toEqual([])
    await solde(f, entretien, 2026, '2026-12-01')
    expect((await ajustements(entretien)).map(l => l.montant_cents)).toEqual([43_332])
    expect(await releve(entretien)).toEqual({ reel_cents: 60_000, prevu_cents: 16_668,
                                              ecart_cents: 43_332 })
  })

  it('à deux : le non-dépensé se partage selon ce que chacun a porté, au centime', async () => {
    const f = await foyerSolo('solde-duo', { revenu: 300_000 })
    const g = await membre(f, 'solde-duo-g', { revenu: 150_000, arrivee: '2026-09-01' })
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
      mode: 'mis_de_cote', commun: true, participants: [f.userId, g.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    const lignes = ou(await admin().from('depense')
      .select('mois, depense_part(user_profile_id, part_cents)')
      .eq('charge_id', entretien).eq('source', 'modele')) as
      { mois: string; depense_part: { user_profile_id: string; part_cents: number }[] }[]
    const porte = new Map<string, number>()
    // Les mois suivis seuls : les revenus datent de septembre.
    for (const l of lignes.filter(l => l.mois >= '2026-09-01')) for (const p of l.depense_part)
      porte.set(p.user_profile_id, (porte.get(p.user_profile_id) ?? 0) + p.part_cents)
    expect(new Set(porte.values()).size, 'deux portées différentes').toBe(2)

    await solde(f, entretien, 2026, '2026-12-01')
    const [aj] = await ajustements(entretien)
    expect(aj.montant_cents).toBe(-16_668)
    const ps = await parts(aj.id)
    expect(ps).toHaveLength(2)
    expect(ps.reduce((t, p) => t + p.part_cents, 0)).toBe(-16_668)
    expect(ps.reduce((t, p) => t + p.part_bps, 0)).toBe(10_000)
    // Chacun récupère ce qu'il avait mis de côté, à un centime près.
    for (const p of ps)
      expect(Math.abs(p.part_cents + porte.get(p.user_profile_id)!)).toBeLessThan(1)
  })

  it('le mois cible est clôturé : tout est refusé, le relevé aussi', async () => {
    const f = await foyerSolo('solde-cible-clos')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    await clos(f, '2026-12-01')
    await expect(solde(f, entretien, 2026, '2026-12-01')).rejects.toThrow(/déjà clôturé/)
    expect(await releve(entretien), 'le relevé est resté dans la transaction annulée').toBeNull()
    expect(await ajustements(entretien)).toEqual([])
  })
})

/** Le critère de l'étape 1 de la clôture, lu par l'aperçu (`annees_a_solder` est interne). */
describe('les années que la clôture solderait', () => {
  const apercu = async (f: Foyer, mois: string) =>
    ou(await f.client.rpc('apercu_des_soldes', { le_mois: mois })) as
      { charge: string; annee: number; cents: number }[]

  it('une charge archivée compte encore ; une fixe, jamais', async () => {
    const f = await foyerSolo('solde-criteres')
    const ancienne = await poseCharge(f, { libelle: 'Vidange', cents: 24_000, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, ancienne, 2026)
    ou(await admin().from('charge').update({ archive_le: '2026-10-15' }).eq('id', ancienne).select())
    await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
    ou(await f.client.rpc('ouvre_le_mois', { le_mois: '2026-11-01' }))
    expect((await apercu(f, '2027-01-01')).map(a => [a.charge, a.annee, a.cents]))
      .toEqual([[ancienne, 2026, -8_000]])
  })

  it('en novembre, l’année en cours ne se solde pas ; en décembre, si', async () => {
    const f = await foyerSolo('solde-decembre')
    const c3 = await poseCharge(f, { libelle: 'Assurance', cents: 24_000, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, c3, 2026)
    expect(await apercu(f, '2026-11-01')).toEqual([])
    expect((await apercu(f, '2026-12-01')).map(a => a.cents)).toEqual([-8_000])
  })

  it('une année déjà soldée ne revient pas', async () => {
    const f = await foyerSolo('solde-deja')
    const c4 = await poseCharge(f, { libelle: 'Assurance', cents: 24_000, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, c4, 2026)
    await solde(f, c4, 2026, '2026-12-01')
    expect(await apercu(f, '2027-01-01')).toEqual([])
  })
})

/**
 * Une charge posée APRÈS la clôture de septembre et d'octobre n'a pas de ligne
 * dans ces mois (le gel : on n'ajoute rien à un mois clôturé). On vérifie que
 * l'année n'en est pas sous-comptée : ce que le foyer a payé de plus que ce qu'il
 * a mis de côté (novembre et décembre seuls) se pose en entier, et ce qu'il n'a
 * pas dépensé se rend en entier, au centime.
 */
describe('une charge posée après la clôture de septembre et d’octobre', () => {
  async function posee(nom: string) {
    await regleLHeure('2026-11-10T12:00:00+01:00')
    const f = await foyerSolo(nom)
    await clos(f, '2026-09-01')
    await clos(f, '2026-10-01')
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                            mode: 'mis_de_cote', debut: '2026-01-01' })
    await ouvreLAnnee(f, entretien, 2026)
    return { f, entretien }
  }
  /** Ce que l'année a porté : les lignes des mois suivis, plus les ajustements. */
  const portee = async (charge: string) => {
    const lignes = ou(await admin().from('depense').select('mois, montant_cents')
      .eq('charge_id', charge)) as { mois: string; montant_cents: number }[]
    return lignes.filter(l => l.mois >= '2026-09-01').reduce((s, l) => s + l.montant_cents, 0)
  }
  afterAll(() => regleLHeure('2027-01-05T10:00:00+01:00'))

  it('les mois clôturés n’ont pas de ligne, novembre et décembre portent 83,34 €', async () => {
    const { entretien } = await posee('solde-posee-apres')
    expect(await ligne(entretien, '2026-09-01')).toBeNull()
    expect(await ligne(entretien, '2026-10-01')).toBeNull()
    expect(await portee(entretien)).toBe(8_334)
  })

  it('une facture de 300,01 € : l’année porte exactement 300,01 €', async () => {
    const { f, entretien } = await posee('solde-posee-facture')
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 30_001, paye_le: '2026-11-10' }))
    expect(await portee(entretien)).toBe(30_001)
    await solde(f, entretien, 2026, '2026-12-01')
    expect(await portee(entretien), 'le solde a déplacé le total').toBe(30_001)
    expect(await releve(entretien)).toEqual({ reel_cents: 30_001, prevu_cents: 8_334,
                                              ecart_cents: 21_667 })
  })

  it('sans facture : le solde rend les 83,34 € mis de côté, l’année porte 0', async () => {
    const { f, entretien } = await posee('solde-posee-rien')
    await solde(f, entretien, 2026, '2026-12-01')
    expect(await portee(entretien)).toBe(0)
    expect(await releve(entretien)).toEqual({ reel_cents: 0, prevu_cents: 8_334,
                                              ecart_cents: -8_334 })
  })
})
