/**
 * À égalité de reste, l'écran départage comme la base.
 *
 * En 50/50 avec un montant IMPAIR en centimes, les deux restes sont toujours égaux : la base donne
 * le centime restant à celui dont `md5(uid::text || ligne::text)` est le plus petit
 * (`confirme_la_ligne`, 0104). `prorata` (`src/lib/budget/mois.ts`) départageait par identifiant :
 * pour la moitié des lignes, `maPart` d'une ligne dépassée et le récap de clôture donnaient le
 * centime à l'autre — un centime d'écart avec ce que la base écrit.
 *
 * On confirme seize factures (seize identifiants, donc seize départages) à un montant impair, et
 * on compare, personne par personne, la part que la base a écrite à celle que l'écran aurait
 * annoncée AVANT la confirmation, avec les parts de la ligne telles qu'elle les avait alors.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { foyerSolo, membre, ouvre, poseCharge, type Foyer } from './helpers/budget'
import type { Actor } from './helpers/db'
import { partSur, type Ligne } from './front-fige/lib/budget/mois'

let f: Foyer
let autre: Actor
const factures: { id: string; avant: Ligne }[] = []
const N = 16

beforeAll(async () => {
  f = await foyerSolo('egalite-md5', { revenu: 400_000 })
  autre = await membre(f, 'Autre', { revenu: 400_000 })
  const charges: string[] = []
  for (let i = 0; i < N; i++) {
    charges.push(await poseCharge(f, { libelle: `Facture ${i}`, cents: 5_000, mode: 'facture',
                                       commun: true, participants: [f.userId, autre.userId] }))
  }
  await ouvre(f, '2026-10-01')
  for (const charge of charges) {
    const { data } = await f.client.from('depense')
      .select('id, charge_id, libelle, montant_cents, montant_prevu_cents, facon, confirme_le, regularise_annee, depense_part(user_profile_id, part_cents, part_bps)')
      .eq('charge_id', charge).eq('mois', '2026-10-01').single()
    const { depense_part, ...reste } = data!
    factures.push({ id: data!.id, avant: { ...reste, parts: depense_part } as Ligne })
  }
}, 120_000)

describe('l’égalité de reste se départage comme la base', () => {
  it('les restes sont bien égaux (50/50, montant impair) : le test éprouve un départage', () => {
    for (const { avant } of factures) {
      expect(avant.parts.map(p => p.part_cents)).toEqual([2_500, 2_500])
    }
  })

  it('pour chaque ligne et chaque membre, `partSur` = la part que la base écrit à la confirmation', async () => {
    const REEL = 6_201
    let departages = 0
    for (const { id, avant } of factures) {
      const { error } = await f.client.rpc('confirme_la_depense', { la_depense: id, reel_cents: REEL })
      expect(error).toBeNull()
      const { data } = await f.client.from('depense_part').select('user_profile_id, part_cents')
        .eq('depense_id', id)
      expect(data!.reduce((s, p) => s + p.part_cents, 0)).toBe(REEL)
      for (const p of data!) {
        expect(partSur(avant, p.user_profile_id, REEL), `ligne ${id}, membre ${p.user_profile_id}`)
          .toBe(p.part_cents)
      }
      if (new Set(data!.map(p => p.part_cents)).size === 2) departages++
    }
    expect(departages, 'tous les départages auraient dû donner 3 100 / 3 101').toBe(N)
  })
})
