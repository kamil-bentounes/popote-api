/**
 * L'ancien paquet, servi une fois par le service worker après le déploiement.
 * Ses lectures tournent ; ses gestes devenus faux disent « Recharge la page »
 * au lieu d'écrire.
 */
import { describe, expect, it } from 'vitest'
import { foyerSolo, poseCharge } from './helpers/budget'

describe('l’ancien paquet', () => {
  it('regularise_annuel n’existe plus', async () => {
    const f = await foyerSolo('ancien-releve')
    const { error } = await f.client.rpc('regularise_annuel',
      { la_charge: '00000000-0000-0000-0000-000000000000', annee: 2026, reel_cents: 0 })
    /* PGRST202 : PostgREST ne trouve pas la fonction. */
    expect(error?.code).toBe('PGRST202')
  })

  it('ses lectures tournent encore', async () => {
    const f = await foyerSolo('ancien-lectures')
    const taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                                       mode: 'mis_de_cote' })
    for (const [fn, args] of [
      ['excedent_du_mois', { le_mois: '2026-10-01' }],
      ['reste_enveloppe', { le_mois: '2026-10-01' }],
      ['provisions_de', { la_charge: taxe, annee: 2026 }],
      ['provisions_a_venir', { la_charge: taxe, annee: 2026 }],
      ['rattrape_les_mois', {}],
      ['refige_le_mois', { le_mois: '2026-10-01' }],
    ] as const) {
      expect((await f.client.rpc(fn, args)).error, fn).toBeNull()
    }
  })
})
