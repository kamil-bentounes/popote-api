/**
 * Les mois que Popote a suivis (D77), et les parts d'un foyer qu'on nomme.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { type Actor } from './helpers/db'
import { clos, foyerSolo, membre, type Foyer } from './helpers/budget'
import { connexion } from './helpers/pg'

let c: pg.Client
let f: Foyer
let deux: Foyer
let elle: Actor
beforeAll(async () => {
  c = await connexion()
  f = await foyerSolo('suivis')
  deux = await foyerSolo('suivis-deux', { revenu: 370_000, depuis: '2026-01-01' })
  elle = await membre(deux, 'Elle', { revenu: 240_000, depuis: '2026-01-01' })
})
afterAll(async () => { await c.end() })

const suivi = async (foyer: string, mois: string) =>
  (await c.query('select public.mois_suivi($1, $2) as v', [foyer, mois])).rows[0].v

describe('les mois suivis', () => {
  it('un revenu en vigueur suit le mois, et tous les suivants', async () => {
    expect(await suivi(f.householdId, '2026-08-01')).toBe(false)
    expect(await suivi(f.householdId, '2026-09-01')).toBe(true)
    expect(await suivi(f.householdId, '2027-03-01')).toBe(true)
  })
  it('un mois clôturé est suivi, revenu ou pas', async () => {
    await clos(f, '2026-06-01')
    expect(await suivi(f.householdId, '2026-06-01')).toBe(true)
    expect(await suivi(f.householdId, '2026-07-01')).toBe(false)
  })
  it('le premier mois suivi', async () => {
    /* `::text` : `pg` rend une date en `Date` à minuit LOCAL, et `toISOString()` la
       ramène au 31 mai sur une machine à l'heure de Paris. */
    const { rows } = await c.query('select public.premier_mois_suivi($1)::text as v',
      [f.householdId])
    expect(rows[0].v).toBe('2026-06-01')
  })
  it('le client n’y a pas accès', async () => {
    const { error } = await f.client.rpc('mois_suivi', { foyer: f.householdId, le_mois: '2026-09-01' })
    /* 42501, pas « fonction inconnue » (42883 / PGRST202) : un nom de paramètre
       faux ferait « passer » ce test sans rien prouver. */
    expect(error?.code).toBe('42501')
  })
})

describe('les parts d’un foyer donné', () => {
  it('rendent ce que parts_du_foyer rend au client', async () => {
    const { data } = await deux.client.rpc('parts_du_foyer', { le_mois: '2026-10-01' })
    const { rows } = await c.query(
      'select user_profile_id, part_bps from public.parts_du_mois($1, $2, null)',
      [deux.householdId, '2026-10-01'])
    const tri = (l: { user_profile_id: string; part_bps: number }[]) =>
      l.map(x => `${x.user_profile_id}:${x.part_bps}`).sort()
    expect(tri(rows)).toEqual(tri(data!))
    expect(tri(rows).length).toBe(2)
  })
  it('et répondent sans foyer courant', async () => {
    const { rows } = await c.query(
      'select count(*)::int as n from public.parts_du_mois($1, $2, null)',
      [deux.householdId, '2026-10-01'])
    expect(rows[0].n).toBe(2)
    expect(elle.userId).toBeTruthy()
  })
})
