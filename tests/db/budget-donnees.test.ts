/**
 * La couche de données du budget, telle que l'application l'appelle : par le
 * client PARTAGÉ de `src/lib/supabase.ts`, connecté au compte du banc. Sans
 * session, la RLS répondrait « rien », et le test serait vert à vide.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { connecteLeClientPartage } from './helpers/db'
import { foyerDOctobre, ligne, poseCharge } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

let o: Awaited<ReturnType<typeof foyerDOctobre>>
let d: typeof import('./front-fige/lib/donnees/budget.ts')

beforeAll(async () => {
  await regleLHeure('2026-11-01T10:00:00+01:00')
  o = await foyerDOctobre('donnees')
  await connecteLeClientPartage(o.f)
  d = await import('./front-fige/lib/donnees/budget.ts')
})
afterAll(remetLHeure)

describe('la couche de données du budget', () => {
  it('lit le mois avec la façon de chaque ligne, et les points de base des parts', async () => {
    const lignes = await d.lisLeMois('2026-10-01')
    const courses = lignes.find(l => l.charge_id === o.id.courses)!
    expect(courses.facon).toBe('au_fil')
    expect(courses.parts[0].part_bps).toBe(10_000)
    expect(lignes.find(l => l.charge_id === o.id.entretien)?.facon).toBe('mis_de_cote')
  })

  it('une saisie renvoyée deux fois n’en fait qu’une, et le renvoi réussit', async () => {
    const courses = (await ligne(o.id.courses, '2026-10-01'))!.id
    const s = { id: randomUUID(), foyerId: o.f.householdId, depenseId: courses,
                faitLe: '2026-10-03', cents: 4_790, moi: o.f.userId }
    await d.ajouteSaisie(s)
    await d.ajouteSaisie(s)
    expect((await d.lisLesSaisies('2026-10-01')).filter(x => x.id === s.id)).toHaveLength(1)
  })

  it('poser son revenu deux fois le même mois : une seule écriture, la seconde', async () => {
    await d.poseRevenu({ foyerId: o.f.householdId, userId: o.f.userId, cents: 440_000 })
    await d.poseRevenu({ foyerId: o.f.householdId, userId: o.f.userId, cents: 445_000 })
    const ceMois = (await d.lisLesRevenus()).filter(r => r.valid_from === d.moisDe())
    expect(ceMois.map(r => r.net_mensuel_cents)).toEqual([445_000])
    expect((await d.lisLesRevenus()).length, 'l’historique est perdu').toBeGreaterThanOrEqual(2)
  })

  it('une facture mise de côté, l’état de son année, et son retrait', async () => {
    const id = randomUUID()
    await d.paieFacture({ id, chargeId: o.id.entretien, cents: 32_000, payeLe: '2026-10-20' })
    expect((await d.lisLesFactures(o.id.entretien, 2026)).map(f => f.montant_cents))
      .toEqual([32_000])
    expect((await d.lisEtatDeLAnnee(o.id.entretien, 2026)).b).toBe(32_000)
    await d.retireFacture(id)
    expect(await d.lisLesFactures(o.id.entretien, 2026)).toEqual([])
  })

  it('une charge mise de côté a une histoire dès sa première facture ; une neuve, non', async () => {
    /* C'est ce qui grise, dans « Mes charges », les trois façons mensuelles
       (§ 3.7) : la base refuserait (0110), l'écran le dit avant. */
    const neuve = await poseCharge(o.f, { libelle: 'Taxe d’habitation', cents: 60_000,
                                          mode: 'mis_de_cote' })
    expect(await d.aUneHistoire(neuve)).toBe(false)
    const id = randomUUID()
    await d.paieFacture({ id, chargeId: neuve, cents: 1_000, payeLe: '2026-10-21' })
    expect(await d.aUneHistoire(neuve)).toBe(true)
  })

  /* AVANT la clôture : clôturer confirme toutes les lignes d'octobre, et
     `retire_charge` ne compte que les saisies des lignes qui partiraient. */
  it('retirer une charge qui a des saisies demande d’abord, avec le total', async () => {
    expect(await d.retireCharge(o.id.courses)).toEqual({
      aConfirmer: { cents: 4_790, message: 'Courses a 47,90 € de dépenses déclarées en octobre.' } })
    expect(await d.retireCharge(o.id.courses, true)).toEqual({ sort: 'supprimee' })
  })

  it('clôture, puis revient dessus', async () => {
    const r = await d.clotureLeMois({ mois: '2026-10-01', factures: [], rien: [],
                                      misDeCote: 0, poche: null })
    expect(r.non_soldees).toEqual([])
    expect((await d.lisLesClotures()).map(k => k.mois)).toContain('2026-10-01')
    await d.rouvreLeMois('2026-10-01')
    expect((await d.lisLesClotures()).map(k => k.mois)).not.toContain('2026-10-01')
  })
})
