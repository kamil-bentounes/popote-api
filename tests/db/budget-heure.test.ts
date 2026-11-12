/**
 * L'heure du budget.
 *
 * Trois choses à tenir : elle avance pendant une transaction (une facture qui
 * attend le verrou passe minuit avec elle), elle est celle de Paris (entre
 * minuit et 2 h, la base en UTC vit encore la veille), et un banc la règle sans
 * attendre le mois qu'il veut jouer.
 */
import { afterAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { connexion } from './helpers/pg'
import { regleLHeure, remetLHeure } from './helpers/horloge'

afterAll(remetLHeure)

describe('l’heure du budget', () => {
  it('avance pendant une transaction, au contraire de now()', async () => {
    const c = await connexion()
    try {
      await c.query('begin')
      const { rows: [a] } = await c.query('select now() as debut')
      await c.query('select pg_sleep(1.2)')
      const { rows: [b] } = await c.query('select public.maintenant() as plus_tard')
      await c.query('rollback')
      expect(new Date(b.plus_tard).getTime() - new Date(a.debut).getTime())
        .toBeGreaterThan(1000)
    } finally { await c.end() }
  })

  it('se règle par une connexion directe, et PostgREST la voit', async () => {
    await regleLHeure('2026-11-10T12:00:00+01:00')
    const { data, error } = await admin().rpc('aujourdhui')
    expect(error).toBeNull()
    expect(data).toBe('2026-11-10')
    expect((await admin().rpc('mois_courant')).data).toBe('2026-11-01')
  })

  it('à 0 h 30 à Paris, c’est déjà le jour suivant de l’UTC', async () => {
    await regleLHeure('2026-10-31T23:30:00Z')
    expect((await admin().rpc('aujourdhui')).data).toBe('2026-11-01')
  })

  it('avance depuis l’heure réglée', async () => {
    await regleLHeure('2026-10-31T23:59:59+01:00')
    await new Promise(r => setTimeout(r, 1500))
    expect((await admin().rpc('mois_courant')).data).toBe('2026-11-01')
  })

  it('se remet, et revient au vrai jour', async () => {
    await remetLHeure()
    const { data } = await admin().rpc('maintenant')
    expect(Math.abs(new Date(data as string).getTime() - Date.now())).toBeLessThan(60_000)
  })
})
