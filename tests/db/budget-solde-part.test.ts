/**
 * Qui porte le solde d'une année ? La base répartit l'ajustement selon ce que CHACUN a porté
 * sur l'année (`porte_par`, `recale_l_annee`), pas selon les parts de la ligne du mois qu'on
 * clôture. `apercu_des_soldes` ne rend que le total du foyer : l'écran de clôture ne peut donc
 * pas annoncer « ta part » du solde à deux — au prorata des parts de décembre, il se trompait
 * dès que les parts avaient bougé dans l'année (une arrivée en septembre, par exemple).
 */
import { afterAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { clore, foyerSolo, ligne, membre, ou, ouvre, ouvreLAnnee, poseCharge, ajustements }
  from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

afterAll(remetLHeure)

const partsDe = async (depense: string) =>
  Object.fromEntries(ou(await admin().from('depense_part').select('user_profile_id, part_cents')
    .eq('depense_id', depense)).map(p => [p.user_profile_id, p.part_cents]))

describe('le solde d’une année à deux', () => {
  it('se répartit selon ce que chacun a porté sur l’année, pas selon les parts de décembre', async () => {
    await regleLHeure('2027-01-05T10:00:00+01:00')
    const f = await foyerSolo('solde-part', { revenu: 300_000 })
    const thauba = await membre(f, 'Thauba', { revenu: 300_000, arrivee: '2026-11-01', depuis: '2026-11-01' })
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
      mode: 'mis_de_cote', commun: true, participants: [f.userId, thauba.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    await ouvre(f, '2026-12-01')

    const decembre = await partsDe((await ligne(entretien, '2026-12-01'))!.id)
    const apercu = ou(await f.client.rpc('apercu_des_soldes', { le_mois: '2026-12-01' })) as
      { cents: number }[]
    expect(apercu).toHaveLength(1)
    const total = apercu[0].cents

    /* Ce que l'écran calculait : le prorata des parts de la ligne de décembre. */
    const sommeDec = decembre[f.userId] + decembre[thauba.userId]
    const prorataKamil = Math.round(total * decembre[f.userId] / sommeDec)

    ou(await clore(f, { mois: '2026-12-01', mis: 0 }))
    const [solde] = await ajustements(entretien)
    const posees = await partsDe(solde.id)
    expect(posees[f.userId] + posees[thauba.userId]).toBe(total)

    /* Thauba n'arrive qu'en novembre : Kamil a porté septembre et octobre seul, donc environ
       75 % de l'année. Sa part du solde dépasse de beaucoup les 50 % de décembre. */
    expect(Math.abs(decembre[f.userId] - decembre[thauba.userId]), 'décembre est partagé à parts égales')
      .toBeLessThanOrEqual(1)
    expect(Math.abs(posees[f.userId] - prorataKamil), 'l’écart entre la base et le prorata de décembre')
      .toBeGreaterThan(2_000)
  })
})
