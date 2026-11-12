/**
 * Ce qu'une année de charge mise de côté doit, et ce qu'elle a déjà posé (§ 4.4).
 *
 * B = Σ des factures ; Pl = les provisions faites et à venir, sur les mois
 * suivis seulement ; la cible ; le posé. `etat_de_l_annee` le rend tel que
 * `recale_l_annee` le calcule : l'écran ne recompte rien.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { ajustementEnAdmin, foyerSolo, ligne, ou, ouvreLAnnee, poseCharge, soldeEnAdmin,
         type Foyer } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

let f: Foyer
let entretien: string
let taxe: string

beforeAll(async () => {
  await regleLHeure('2026-10-15T12:00:00+02:00')
  f = await foyerSolo('annee')
  entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                    mode: 'mis_de_cote', categorie: 'auto' })
  taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                               mode: 'mis_de_cote', commun: true, categorie: 'maison' })
  // Les douze lignes 2026, comme le relevé annulé les a laissées en prod.
  await ouvreLAnnee(f, entretien, 2026)
  await ouvreLAnnee(f, taxe, 2026)
  await soldeEnAdmin(f, taxe, 2026, { reel: 145_000, prevu: 144_996 })
  await ajustementEnAdmin(f, taxe, '2026-09-01', 2026, 4, 'Taxe foncière — régularisation 2026')
})
afterAll(remetLHeure)

const etat = async (charge: string, annee = 2026) =>
  ou(await f.client.rpc('etat_de_l_annee', { la_charge: charge, annee })) as Record<string, unknown>

describe('l’état d’une année', () => {
  it('Entretien 2026 : Pl ne compte que les mois suivis, de septembre à décembre', async () => {
    expect(await etat(entretien)).toEqual({
      b: 0, pl: 16_668, pose: 0, soldee: false, premier_mois_suivi: '2026-09-01' })
  })

  it('les mois à venir sans ligne comptent aussi, s’ils sont suivis', async () => {
    const controle = await poseCharge(f, { libelle: 'Contrôle technique', cents: 12_000,
                                           mode: 'mis_de_cote' })
    expect((await etat(controle)).pl).toBe(3_000)   // octobre, novembre, décembre
  })

  it('Taxe foncière : une année soldée garde son prévu figé', async () => {
    expect(await etat(taxe)).toEqual({
      b: 145_000, pl: 144_996, pose: 4, soldee: true, premier_mois_suivi: '2026-09-01' })
  })

  it('une ligne fixe d’avant un passage en mise de côté ne compte pas, ni une ligne sans part',
    async () => {
      const assurance = await poseCharge(f, { libelle: 'Assurance', cents: 10_000 })
      for (const m of ['2026-09-01', '2026-10-01']) {
        ou(await f.client.rpc('ouvre_la_charge',
          { la_charge: assurance, foyer: f.householdId, le_mois: m }))
      }
      // Passée à 1 200 € par an : ses lignes de novembre et décembre seront mises de côté.
      ou(await admin().from('charge').update({ montant_cents: 120_000, periodicite: 'annuel' })
        .eq('id', assurance).select())
      for (const m of ['2026-11-01', '2026-12-01']) {
        ou(await f.client.rpc('ouvre_la_charge',
          { la_charge: assurance, foyer: f.householdId, le_mois: m }))
      }
      expect((await etat(assurance)).pl, 'les 200 € fixes déjà payés comptent').toBe(20_000)
      ou(await admin().from('depense_part').delete()
        .eq('depense_id', (await ligne(assurance, '2026-12-01'))!.id).select())
      expect((await etat(assurance)).pl, 'une ligne sans part compte').toBe(10_000)
    })

  it('le voisin ne lit pas l’état d’une charge qui n’est pas la sienne', async () => {
    const voisin = await foyerSolo('annee-voisin')
    expect((await voisin.client.rpc('etat_de_l_annee', { la_charge: entretien, annee: 2026 }))
      .error).not.toBeNull()
  })

  it('cible_de, recale_l_annee et pose_les_parts restent fermées au client', async () => {
    for (const [fn, args] of [
      ['cible_de', { la_charge: entretien, annee: 2026, comme_soldee: false }],
      ['recale_l_annee', { la_charge: entretien, annee: 2026 }],
    ] as const) {
      expect((await f.client.rpc(fn, args)).error, fn).not.toBeNull()
    }
  })
})
