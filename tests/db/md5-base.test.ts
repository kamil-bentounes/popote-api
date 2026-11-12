/**
 * Le `md5` de l'écran (`src/lib/md5.ts`) rend la même chaîne que `md5(text)` de la base.
 *
 * La base départage les restes égaux d'une répartition au centime par `md5(uid::text ||
 * ligne::text)` ; l'écran doit trancher pareil (`prorata`, `mois.ts`), sans quoi `maPart` et le
 * récap de clôture diffèrent d'un centime de ce que la base écrit.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { connexion } from './helpers/pg'
import { md5 } from './front-fige/lib/md5'

let c: pg.Client
beforeAll(async () => { c = await connexion() })
afterAll(async () => { await c.end() })

describe('md5 : l’écran et la base', () => {
  const chaines = [
    '', 'a', 'abc', 'é', 'Popote — 12,34 €', '🍳',
    'x'.repeat(55), 'x'.repeat(56), 'x'.repeat(63), 'x'.repeat(64), 'x'.repeat(65), 'x'.repeat(200),
    ...Array.from({ length: 20 }, () => randomUUID() + randomUUID()),
  ]

  it.each(chaines.map(s => [s.length > 40 ? `${s.slice(0, 12)}… (${s.length})` : s, s]))(
    '« %s »', async (_nom, s) => {
      const { rows: [r] } = await c.query('select md5($1::text) as h', [s])
      expect(md5(s)).toBe(r.h)
    })
})
