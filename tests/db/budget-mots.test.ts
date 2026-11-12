/** Les mots que la base écrit dans ses refus : un mois, un montant, un prénom. */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { connexion } from './helpers/pg'

let c: pg.Client
beforeAll(async () => { c = await connexion() })
afterAll(async () => { await c.end() })

const un = async (sql: string) => (await c.query(sql)).rows[0]

describe('les mots de la base', () => {
  it('nomme le mois, et élide devant une voyelle', async () => {
    expect(await un(`select public.nom_du_mois('2026-10-15') as v`)).toEqual({ v: 'octobre' })
    expect(await un(`select public.de_mois('2026-08-01') as v`)).toEqual({ v: "d'août" })
    expect(await un(`select public.de_mois('2026-04-01') as v`)).toEqual({ v: "d'avril" })
    expect(await un(`select public.de_mois('2026-10-01') as v`)).toEqual({ v: "d'octobre" })
    expect(await un(`select public.de_mois('2026-03-01') as v`)).toEqual({ v: 'de mars' })
  })

  it('écrit un montant comme l’écran : espace fine, virgule, euros ronds sans « ,00 »', async () => {
    expect(await un(`select public.en_euros(43000) as v`)).toEqual({ v: '430 €' })
    expect(await un(`select public.en_euros(123456) as v`)).toEqual({ v: '1 234,56 €' })
    expect(await un(`select public.en_euros(-16668) as v`)).toEqual({ v: '−166,68 €' })
    expect(await un(`select public.en_euros(5) as v`)).toEqual({ v: '0,05 €' })
  })

  it('prend le prénom, et ne laisse jamais un trou', async () => {
    expect(await un(`select public.prenom_de('Thauba Benali') as v`)).toEqual({ v: 'Thauba' })
    expect(await un(`select public.prenom_de('  ') as v`)).toEqual({ v: "Quelqu'un" })
    expect(await un(`select public.prenom_de(null) as v`)).toEqual({ v: "Quelqu'un" })
  })
})
