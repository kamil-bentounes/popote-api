import { describe, it, expect } from 'vitest'
import { admin } from './helpers/db'

describe('référentiels (lot 0a-2)', () => {
  it('CIQUAL est chargé avec ses groupes', async () => {
    const a = admin()
    const { count } = await a.from('food').select('*', { count: 'exact', head: true }).eq('source', 'ciqual')
    expect(count, 'CIQUAL doit compter ~3185 aliments').toBeGreaterThan(3000)
    const { data } = await a.from('food')
      .select('name, ciqual_subgroup, nutrients').ilike('name', 'Lentille verte, bouillie%').limit(1)
    expect(data![0].ciqual_subgroup).toBeTruthy()
    expect(Number((data![0].nutrients as any).proteines_g)).toBeGreaterThan(5)
  })

  it('les tables de conversion sont peuplées', async () => {
    const a = admin()
    for (const [t, min] of [['default_duration', 50], ['unit_conversion', 25],
                            ['non_action_pattern', 10], ['appliance_catalog', 8]] as const) {
      const { count } = await a.from(t).select('*', { count: 'exact', head: true })
      expect(count, `${t} est vide ou incomplète`).toBeGreaterThanOrEqual(min)
    }
  })

  // ⚠️ Régression réelle : `unique (verb, appliance_type)` ne contraint pas les lignes
  // où appliance_type est NULL — Postgres traite chaque NULL comme distinct. La
  // production est montée à 74 verbes au lieu de 55 avant que `nulls not distinct`
  // soit posé. Ce test garantit qu'un second chargement ne duplique plus rien.
  it('un upsert répété ne duplique pas les lignes sans appareil', async () => {
    const a = admin()
    const avant = (await a.from('default_duration').select('*', { count: 'exact', head: true })).count!

    const ligne = { verb: 'témoin-unicité', appliance_type: null,
                    base_minutes: 3, load_type: 'actif', scaling: 'constant' }
    for (let i = 0; i < 2; i++) {
      const { error } = await a.from('default_duration')
        .upsert(ligne, { onConflict: 'verb,appliance_type' })
      expect(error, `insertion ${i + 1}`).toBeNull()
    }
    const apres = (await a.from('default_duration').select('*', { count: 'exact', head: true })).count!
    expect(apres - avant, 'la ligne sans appareil a été insérée deux fois').toBe(1)

    await a.from('default_duration').delete().eq('verb', 'témoin-unicité')
  })

  it('les phrases sans geste sont bien répertoriées', async () => {
    const { data } = await admin().from('non_action_pattern').select('pattern')
    const motifs = (data ?? []).map(r => r.pattern)
    // « Bon appétit. » ne doit jamais recevoir de durée : ce serait une minute fantôme.
    expect(motifs.some(m => new RegExp(m, 'i').test('Bon appétit.'))).toBe(true)
    expect(motifs.some(m => new RegExp(m, 'i').test('Et voilà, vos cailles sont prêtes !'))).toBe(true)
    expect(motifs.some(m => new RegExp(m, 'i').test('Émincez les oignons.')),
      'une vraie action ne doit pas être écartée').toBe(false)
  })
})
