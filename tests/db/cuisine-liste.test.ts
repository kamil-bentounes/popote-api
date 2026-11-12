/**
 * La liste de courses GÉNÉRÉE (src/lib/donnees/courses.ts), contre la vraie base :
 * noms courts, regroupement par aliment, rayons, régénération au milieu de lignes prises.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { admin, connecteLeClientPartage, makeActor, type Actor } from './helpers/db'

/* `useGenereListe` est un hook : on lui retire React Query pour appeler sa fonction telle quelle,
   avec le client de l'application (celui de `src/lib/supabase.ts`, connecté à Alice). */
vi.mock('@tanstack/react-query', async importOriginal => ({
  ...await importOriginal<typeof import('@tanstack/react-query')>(),
  useMutation: (o: unknown) => o,
  useQueryClient: () => ({ invalidateQueries: () => undefined }),
}))

let alice: Actor

const lundi = (iso: string, semaines = 0): string => {
  const [a, m, j] = iso.split('-').map(Number)
  const d = new Date(Date.UTC(a, m - 1, j))
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + 7 * semaines)
  return d.toISOString().slice(0, 10)
}
async function aujourdhui(): Promise<string> {
  const { data } = await admin().rpc('aujourdhui')
  return data as string
}
async function cycleDe(a: Actor, week_of: string, state: string) {
  const { data, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of, state }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}
const videLesCycles = (a: Actor) => admin().from('cycle').delete().eq('household_id', a.householdId)

beforeAll(async () => {
  alice = await makeActor('cuisine-liste-alice')
})

describe('la liste générée : noms courts, rayons, régénération', () => {
  /* Les aliments se retrouvent par leur code CIQUAL : les identifiants sont tirés au hasard à chaque base. */
  const ID = {} as Record<'tomateCrue' | 'carotteCrue' | 'carotteSurgelee' | 'lentille' | 'oeuf', string>
  beforeAll(async () => {
    const codes = { tomateCrue: '20047', carotteCrue: '20009', carotteSurgelee: '20208', lentille: '20535', oeuf: '22000' }
    const { data } = await admin().from('food').select('id, source_code').eq('source', 'ciqual')
      .in('source_code', Object.values(codes))
    for (const [cle, code] of Object.entries(codes)) {
      const id = data?.find(f => f.source_code === code)?.id
      expect(id, `l'aliment CIQUAL ${code} manque : la base est-elle semée ?`).toBeTruthy()
      ID[cle as keyof typeof ID] = id!
    }
  })

  async function recetteAvec(titre: string,
    lignes: { food_id: string | null; raw_text: string; qty?: number; unit?: string; g?: number }[]) {
    const { data: r } = await admin().from('recipe')
      .insert({ title: titre, yield_servings: 4 }).select().single()
    const { error } = await admin().from('recipe_ingredient').insert(lignes.map((l, i) => ({
      recipe_id: r!.id, ordinal: i + 1, raw_text: l.raw_text, food_id: l.food_id,
      qty: l.qty ?? null, unit: l.unit ?? null, grams_reference: l.g ?? null,
    })))
    expect(error, "l'amorce a échoué").toBeNull()
    return r!.id as string
  }

  async function cycleAvec(semaines: number, recettes: string[]) {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), semaines), 'selection')
    for (const recipe_id of recettes) {
      const { error } = await admin().from('cycle_recipe')
        .insert({ cycle_id: c.id, recipe_id, servings: 4 })
      expect(error).toBeNull()
    }
    return c.id as string
  }

  async function genere(cycleId: string) {
    await connecteLeClientPartage(alice)
    /* Le hook sous un autre nom : on l'appelle hors de tout composant, avec `useMutation` réduit à ses options. */
    const { useGenereListe: genereLaListe } = await import('./front-fige/lib/donnees/courses.ts')
    const m = genereLaListe() as unknown as { mutationFn: (id: string) => Promise<unknown> }
    return m.mutationFn(cycleId)
  }
  const lignesDe = async (cycleId: string) =>
    (await admin().from('shopping_item').select('*').eq('cycle_id', cycleId)).data ?? []

  it('un même aliment dans deux recettes fait UNE ligne, quantités additionnées', async () => {
    const r1 = await recetteAvec('Salade', [{ food_id: ID.tomateCrue, raw_text: '200 g de tomates', qty: 200, unit: 'g', g: 200 }])
    const r2 = await recetteAvec('Four', [{ food_id: ID.tomateCrue, raw_text: '100 g de tomates', qty: 100, unit: 'g', g: 100 }])
    const c = await cycleAvec(10, [r1, r2])
    await genere(c)
    const lignes = await lignesDe(c)
    expect(lignes.map(l => l.label)).toEqual(['Tomate'])
    expect(Number(lignes[0].quantity)).toBe(300)
    expect(lignes[0].unit).toBe('g')
  })

  it('deux aliments au même nom court restent deux lignes, et leur nom entier les distingue (frais / surgelé)', async () => {
    const r1 = await recetteAvec('Poêlée', [{ food_id: ID.carotteCrue, raw_text: '200 g de carottes', qty: 200, unit: 'g', g: 200 }])
    const r2 = await recetteAvec('Wok', [{ food_id: ID.carotteSurgelee, raw_text: '300 g de carottes surgelées', qty: 300, unit: 'g', g: 300 }])
    const c = await cycleAvec(14, [r1, r2])
    await genere(c)
    const parLabel = Object.fromEntries((await lignesDe(c)).map(l => [l.label, { rayon: l.aisle, g: Number(l.quantity) }]))
    expect(parLabel, 'le frais et le surgelé ont été fusionnés : un rayon et un lieu de stock pris au hasard').toEqual({
      'Carotte, crue': { rayon: 'Fruits et légumes', g: 200 },
      'Carotte, surgelée, crue': { rayon: 'Surgelés', g: 300 },
    })
  })

  it('ne perd aucune quantité quand les unités diffèrent', async () => {
    const r1 = await recetteAvec('Salade 2', [{ food_id: ID.tomateCrue, raw_text: '200 g de tomates', qty: 200, unit: 'g', g: 200 }])
    const r2 = await recetteAvec('Farcies', [{ food_id: ID.tomateCrue, raw_text: '2 tomates', qty: 2, unit: 'u' }])
    const c = await cycleAvec(11, [r1, r2])
    await genere(c)
    const lignes = await lignesDe(c)
    expect(lignes).toHaveLength(1)
    expect(Number(lignes[0].quantity)).toBe(200)
    expect(lignes[0].note, 'les deux tomates ont disparu').toMatch(/2 u/)
  })

  it('range les lentilles à l’épicerie et les œufs au frais, sous leur nom court', async () => {
    const r = await recetteAvec('Dahl', [
      { food_id: ID.lentille, raw_text: '300 g de lentilles corail', qty: 300, unit: 'g', g: 300 },
      { food_id: ID.oeuf, raw_text: '4 œufs', qty: 4, unit: 'u', g: 240 },
    ])
    const c = await cycleAvec(12, [r])
    await genere(c)
    const parLabel = Object.fromEntries((await lignesDe(c)).map(l => [l.label, l.aisle]))
    expect(parLabel).toEqual({ 'Lentille corail': 'Épicerie salée', 'Oeuf': 'Frais' })
  })

  it('régénérer au milieu de lignes cochées ou payées ne lève pas, et les garde', async () => {
    const r = await recetteAvec('Salade 3', [{ food_id: ID.tomateCrue, raw_text: '200 g de tomates', qty: 200, unit: 'g', g: 200 }])
    const c = await cycleAvec(13, [r])
    await genere(c)
    const [prise] = await lignesDe(c)
    await admin().from('shopping_item').update({ checked_at: new Date().toISOString() }).eq('id', prise.id)
    await admin().from('shopping_item').insert({
      cycle_id: c, household_id: alice.householdId, label: 'Payée', source: 'recette', paid_price_eur: 2,
    })
    await expect(genere(c)).resolves.toBeDefined()
    const labels = (await lignesDe(c)).map(l => l.label).sort()
    expect(labels, 'la tomate cochée a été doublée ou perdue').toEqual(['Payée', 'Tomate'])
  })
})
