/**
 * Le verrou du foyer.
 *
 * Il sérialise, dans un foyer, tout ce qui touche à une clôture : une saisie,
 * une facture, un revenu ou une ligne qui naît pendant une clôture attend sa
 * fin, puis la voit. On le prouve en le TENANT dans une transaction ouverte,
 * et en regardant l'écriture du client attendre.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { admin, makeActor, type Actor } from './helpers/db'
import { attends, connexion, suivie } from './helpers/pg'

let kamil: Actor
let voisin: Actor
const ouvertes: pg.Client[] = []

beforeAll(async () => {
  kamil = await makeActor('verrou')
  voisin = await makeActor('verrou-voisin')
  // Arrivé en janvier : sans cela, mars n'a aucun participant arrivé, et aucune ligne n'y naît.
  await admin().from('user_profile').update({ entre_le: '2026-01-01' }).eq('id', kamil.userId)
})
afterAll(async () => { for (const c of ouvertes) await c.end().catch(() => {}) })

/** Une transaction qui tient le verrou du foyer, comme une clôture en cours. */
async function tientLeVerrou(foyer: string) {
  const c = await connexion()
  ouvertes.push(c)
  await c.query('begin')
  await c.query('select public.verrou_du_foyer($1)', [foyer])
  return c
}

/** L'écriture ATTEND tant que le verrou est tenu, puis passe. */
async function attendLeVerrou(foyer: string,
  ecrit: () => PromiseLike<{ error: { message: string } | null }>) {
  const s1 = await tientLeVerrou(foyer)
  const e = suivie(ecrit())
  await attends(800)
  const attendait = !e.fini
  await s1.query('commit')
  const r = await e.p
  return { attendait, erreur: r.error?.message ?? null }
}

describe('le verrou du foyer', () => {
  it('une écriture du client attend qu’une fonction du foyer ait fini', async () => {
    const r = await attendLeVerrou(kamil.householdId, () =>
      kamil.client.from('user_profile').update({ display_name: 'Attend' })
        .eq('id', kamil.userId).select())
    expect(r.attendait, 'l’écriture n’a pas attendu le verrou').toBe(true)
    expect(r.erreur).toBeNull()
  })

  it('le foyer d’à côté n’attend pas', async () => {
    const s1 = await tientLeVerrou(kamil.householdId)
    try {
      const { error } = await voisin.client.from('user_profile')
        .update({ display_name: 'Libre' }).eq('id', voisin.userId).select()
      expect(error).toBeNull()
    } finally { await s1.query('rollback') }
  })

  it('chaque table que le client écrit prend le verrou', async () => {
    const { data: c } = await admin().from('charge').insert({
      household_id: kamil.householdId, libelle: 'Internet', montant_cents: 3_700,
      periodicite: 'mensuel', debut: '2026-01-01',
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: kamil.userId, household_id: kamil.householdId })
    await kamil.client.rpc('ouvre_le_mois', { le_mois: '2026-03-01' })
    const { data: l } = await admin().from('depense').select('id')
      .eq('charge_id', c!.id).eq('mois', '2026-03-01').single()

    const gestes: [string, () => PromiseLike<{ error: { message: string } | null }>][] = [
      ['charge', () => kamil.client.from('charge').insert({
        household_id: kamil.householdId, libelle: 'Gaz', montant_cents: 4_000,
        periodicite: 'mensuel', debut: '2026-01-01' }).select()],
      ['charge_participant', () => kamil.client.from('charge_participant')
        .delete().eq('charge_id', c!.id).select()],
      ['revenu', () => kamil.client.from('revenu').insert({
        household_id: kamil.householdId, user_profile_id: kamil.userId,
        net_mensuel_cents: 300_000, valid_from: '2026-03-01' }).select()],
      ['regle_partage', () => kamil.client.from('regle_partage').insert({
        household_id: kamil.householdId, cle: 'moitie', valid_from: '2026-03-01' }).select()],
      ['depense', () => kamil.client.from('depense')
        .update({ regle_le: '2026-03-31' }).eq('id', l!.id).select()],
      ['depense_part', () => kamil.client.from('depense_part')
        .update({ part_cents: 1 }).eq('depense_id', l!.id).select()],
    ]
    for (const [table, geste] of gestes) {
      const r = await attendLeVerrou(kamil.householdId, geste)
      expect(r.attendait, `${table} n’a pas attendu le verrou`).toBe(true)
    }
  })
})
