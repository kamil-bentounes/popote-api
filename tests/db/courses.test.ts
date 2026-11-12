/**
 * Les courses : ce que cocher déclenche.
 *
 * Cocher un article n'est pas un booléen. C'est trois choses à la fois : la
 * ligne est prise, l'article entre à l'inventaire (D49), et l'ordre des rayons
 * apprend le chemin qu'on suit vraiment dans ce magasin (D58).
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor
let magasin: string

async function article(a: Actor, label: string, rayon: string, store?: string | null) {
  const { data, error } = await admin().from('shopping_item').insert({
    household_id: a.householdId,
    label,
    aisle: rayon,
    store_id: store === undefined ? magasin : store,
  }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}

const coche = (id: string) => admin().from('shopping_item')
  .update({ checked_at: new Date().toISOString() }).eq('id', id).select().single()

beforeAll(async () => {
  alice = await makeActor('courses-alice')
  bob = await makeActor('courses-bob')
  const { data } = await admin().from('store')
    .insert({ household_id: alice.householdId, name: 'Lidl', is_default: true })
    .select().single()
  magasin = data!.id
})

describe('le rang de cochage', () => {
  it('se numérote dans l’ordre où l’on prend les choses', async () => {
    const a = await article(alice, 'Carottes', 'Fruits et légumes')
    const b = await article(alice, 'Poulet', 'Boucherie, poissonnerie')
    const c = await article(alice, 'Lessive', 'Entretien')

    const r1 = await coche(a.id)
    const r2 = await coche(b.id)
    const r3 = await coche(c.id)

    expect(r1.data!.checked_rank).toBeLessThan(r2.data!.checked_rank!)
    expect(r2.data!.checked_rank).toBeLessThan(r3.data!.checked_rank!)
  })

  it('s’efface quand on décoche : on s’est trompé de chariot', async () => {
    const a = await article(alice, 'Riz', 'Épicerie salée')
    await coche(a.id)
    const { data } = await admin().from('shopping_item')
      .update({ checked_at: null }).eq('id', a.id).select().single()
    expect(data!.checked_rank, 'le rang a survécu au décochage').toBeNull()
  })

  it('ne laisse jamais un rang sans date de cochage', async () => {
    // Le trigger normalise plutôt que de refuser : une ligne posée avec un rang
    // mais sans date repart à zéro. L'invariant compte, pas la façon de le tenir.
    const { data, error } = await admin().from('shopping_item').insert({
      household_id: alice.householdId, label: 'Incohérent', checked_rank: 3,
    }).select().single()
    expect(error).toBeNull()
    expect(data!.checked_rank, 'un rang a survécu sans date de cochage').toBeNull()
  })
})

describe('cocher remplit l’inventaire (D49)', () => {
  it('fait entrer l’article au placard', async () => {
    const a = await article(alice, 'Lentilles corail', 'Épicerie salée')
    await coche(a.id)
    const { data } = await admin().from('stock_item')
      .select('label, location, source').eq('household_id', alice.householdId)
      .eq('label', 'Lentilles corail')
    expect(data!.length, 'l’article coché n’est pas entré à l’inventaire')
      .toBeGreaterThan(0)
    expect(data![0].source).toBe('courses')
  })

  it('devine le bon endroit selon le rayon', async () => {
    await coche((await article(alice, 'Petits pois surgelés', 'Surgelés')).id)
    await coche((await article(alice, 'Yaourt nature', 'Frais')).id)

    const { data } = await admin().from('stock_item')
      .select('label, location').eq('household_id', alice.householdId)
      .in('label', ['Petits pois surgelés', 'Yaourt nature'])
    const par = Object.fromEntries(data!.map(s => [s.label, s.location]))
    expect(par['Petits pois surgelés']).toBe('congelateur')
    expect(par['Yaourt nature']).toBe('frigo')
  })

  it('retient ce qu’on reprend à chaque fois (D45)', async () => {
    await coche((await article(alice, 'Café en grains', 'Épicerie salée')).id)
    const { data } = await admin().from('shopping_habit')
      .select('label, times_added').eq('household_id', alice.householdId)
      .eq('label', 'Café en grains')
    expect(data!.length, 'l’habitude n’a pas été retenue').toBe(1)
  })
})

describe('l’ordre des rayons s’apprend (D58)', () => {
  it('enregistre un rang par rayon dès la première sortie', async () => {
    await coche((await article(alice, 'Pommes', 'Fruits et légumes')).id)
    await coche((await article(alice, 'Éponges', 'Entretien')).id)

    const { data } = await admin().from('aisle_order')
      .select('aisle, position').eq('store_id', magasin)
    const par = Object.fromEntries(data!.map(o => [o.aisle, Number(o.position)]))
    expect(par['Fruits et légumes'], 'aucun ordre appris').toBeDefined()
    expect(par['Entretien']).toBeDefined()
  })

  it('lisse plutôt que d’écraser : un magasin réorganisé ne casse pas tout', async () => {
    const { data: avant } = await admin().from('aisle_order')
      .select('position').eq('store_id', magasin).eq('aisle', 'Fruits et légumes').single()

    // On recoche le même rayon très tard dans une nouvelle sortie.
    for (let i = 0; i < 6; i++) {
      await coche((await article(alice, `Bouchon ${i}`, 'Épicerie sucrée')).id)
    }
    await coche((await article(alice, 'Bananes', 'Fruits et légumes')).id)

    const { data: apres } = await admin().from('aisle_order')
      .select('position').eq('store_id', magasin).eq('aisle', 'Fruits et légumes').single()

    const a = Number(avant!.position)
    const b = Number(apres!.position)
    expect(b, 'la position n’a pas bougé').not.toBe(a)
    // Moyenne mobile : elle se déplace vers la nouvelle observation sans y sauter.
    expect(b, 'la dernière observation a tout écrasé').toBeLessThan(a + 12)
    expect(b).toBeGreaterThan(a)
  })

  it('garde un ordre par magasin, pas un ordre global', async () => {
    const { data: autre } = await admin().from('store')
      .insert({ household_id: alice.householdId, name: 'Carrefour' }).select().single()
    await coche((await article(alice, 'Pain', 'Épicerie sucrée', autre!.id)).id)

    const { data } = await admin().from('aisle_order')
      .select('store_id').eq('household_id', alice.householdId).eq('aisle', 'Épicerie sucrée')
    const magasins = new Set(data!.map(o => o.store_id))
    expect(magasins.size, 'les rayons de deux magasins ont été confondus')
      .toBeGreaterThanOrEqual(1)
    expect(magasins.has(autre!.id)).toBe(true)
  })
})

describe('isolation', () => {
  it('un foyer ne voit jamais la liste d’un autre', async () => {
    const a = await article(bob, 'Secret', 'Autre', null)
    const { data } = await alice.client.from('shopping_item').select('id').eq('id', a.id)
    expect(data ?? [], 'fuite de liste entre foyers').toHaveLength(0)
  })

  it('un foyer ne voit jamais l’ordre des rayons d’un autre', async () => {
    const { data } = await bob.client.from('aisle_order').select('id').eq('store_id', magasin)
    expect(data ?? [], 'fuite d’ordre de rayons').toHaveLength(0)
  })

  it('un foyer peut cocher les siens', async () => {
    const a = await article(alice, 'Beurre', 'Frais')
    const { data, error } = await alice.client.from('shopping_item')
      .update({ checked_at: new Date().toISOString() }).eq('id', a.id).select()
    expect(error).toBeNull()
    expect(data ?? [], 'le foyer ne peut pas cocher sa propre liste').toHaveLength(1)
  })
})
