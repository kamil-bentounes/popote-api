/**
 * Les quatre défauts de base du grand test « cuisine » (migration 0117).
 *
 *  1. une session interrompue était invisible, et sa semaine ne se rouvrait pas ;
 *  2. supprimer une ligne de courses cochée ou payée répondait « 0 ligne » ;
 *  3. cocher du non-alimentaire (papier toilette) le rangeait au frigo ;
 *  4. `cycle_recipe.position` valait 0 partout.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'


let alice: Actor
let bob: Actor
let magasin: string

/** Lundi de la semaine qui contient `iso` (YYYY-MM-DD), décalé de `semaines`. */
function lundi(iso: string, semaines = 0): string {
  const [a, m, j] = iso.split('-').map(Number)
  const d = new Date(Date.UTC(a, m - 1, j))
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + 7 * semaines)
  return d.toISOString().slice(0, 10)
}

/** « Aujourd'hui » selon la base : c'est son horloge que la fonction lit, pas la nôtre. */
async function aujourdhui(): Promise<string> {
  const { data, error } = await admin().rpc('aujourdhui')
  expect(error).toBeNull()
  return data as string
}

async function cycleDe(a: Actor, week_of: string, state: string) {
  const { data, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of, state }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}

/** Ferme tout cycle vivant et libère les semaines : chaque test part d'un foyer sans cycle. */
async function videLesCycles(a: Actor) {
  await admin().from('cycle').delete().eq('household_id', a.householdId)
}

beforeAll(async () => {
  alice = await makeActor('cuisine-corr-alice')
  bob = await makeActor('cuisine-corr-bob')
  const { data } = await admin().from('store')
    .insert({ household_id: alice.householdId, name: 'Lidl', is_default: true })
    .select().single()
  magasin = data!.id
})

describe('1 · la session interrompue se retrouve', () => {
  it('cycle_a_reprendre rend la session interrompue de la semaine courante', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui()), 'interrompue')
    const { data, error } = await alice.client.rpc('cycle_a_reprendre')
    expect(error).toBeNull()
    expect(data).toBe(c.id)
  })

  it('… et celle de la semaine dernière, mais pas celle de septembre', async () => {
    await videLesCycles(alice)
    const auj = await aujourdhui()
    const vieille = await cycleDe(alice, lundi(auj, -4), 'interrompue')
    expect((await alice.client.rpc('cycle_a_reprendre')).data,
      'une session vieille d’un mois était proposée').toBeNull()
    const derniere = await cycleDe(alice, lundi(auj, -1), 'interrompue')
    expect((await alice.client.rpc('cycle_a_reprendre')).data).toBe(derniere.id)
    expect(derniere.id).not.toBe(vieille.id)
  })

  it('0119 · un plan de septembre COMMENCÉ cette semaine se reprend ; commencé il y a dix jours, non', async () => {
    await videLesCycles(alice)
    const auj = await aujourdhui()
    const ilYa = (jours: number) => new Date(Date.now() - jours * 86_400_000).toISOString()
    /* Le cas du 25/10 : ouvert le 18/09 pour la semaine du 21/09, cuisiné un mois plus tard. */
    const { data: vieux, error } = await admin().from('cycle')
      .insert({ household_id: alice.householdId, week_of: lundi(auj, -5), state: 'interrompue', started_at: ilYa(10) })
      .select().single()
    expect(error).toBeNull()
    expect((await alice.client.rpc('cycle_a_reprendre')).data, 'commencée il y a dix jours').toBeNull()
    await admin().from('cycle').update({ started_at: ilYa(0.1) }).eq('id', vieux!.id)
    expect((await alice.client.rpc('cycle_a_reprendre')).data, 'la session de ce dimanche était perdue')
      .toBe(vieux!.id)
  })

  it('prend la plus récente quand il y en a deux', async () => {
    await videLesCycles(alice)
    const auj = await aujourdhui()
    await cycleDe(alice, lundi(auj, -1), 'interrompue')
    const courante = await cycleDe(alice, lundi(auj), 'interrompue')
    expect((await alice.client.rpc('cycle_a_reprendre')).data).toBe(courante.id)
  })

  it('ne rend rien quand la session est close, et ne fuit pas chez le voisin', async () => {
    await videLesCycles(alice)
    await videLesCycles(bob)
    const auj = await aujourdhui()
    await cycleDe(alice, lundi(auj), 'cloture')
    expect((await alice.client.rpc('cycle_a_reprendre')).data).toBeNull()
    const chezAlice = await cycleDe(alice, lundi(auj, 1), 'interrompue')
    expect((await bob.client.rpc('cycle_a_reprendre')).data,
      'la session d’un autre foyer a fuité').toBeNull()
    expect((await alice.client.rpc('cycle_a_reprendre')).data).toBe(chezAlice.id)
  })

  it('est fermée à l’anonyme', async () => {
    const { createClient } = await import('@supabase/supabase-js')
    const anon = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!,
      { auth: { persistSession: false } })
    const { error } = await anon.rpc('cycle_a_reprendre')
    expect(error, 'l’anonyme a pu appeler la fonction').not.toBeNull()
  })

  it('open_cycle refuse une semaine interrompue en disant quoi faire', async () => {
    await videLesCycles(alice)
    const semaine = lundi(await aujourdhui(), 1)
    await cycleDe(alice, semaine, 'interrompue')
    const { error } = await alice.client.rpc('open_cycle', { p_week_of: semaine })
    expect(error).not.toBeNull()
    expect(error!.message).toMatch(/session interrompue/)
    expect(error!.message).toMatch(/reprends-la/)
  })

  it('open_cycle garde son message pour une semaine close', async () => {
    await videLesCycles(alice)
    const semaine = lundi(await aujourdhui(), 2)
    await cycleDe(alice, semaine, 'cloture')
    const { error } = await alice.client.rpc('open_cycle', { p_week_of: semaine })
    expect(error!.message).toMatch(/déjà son cycle, clos/)
  })
})

describe('2 · supprimer une ligne protégée le dit', () => {
  async function ligne(champs: Record<string, unknown>, cycle?: string) {
    const { data, error } = await admin().from('shopping_item').insert({
      household_id: alice.householdId, store_id: magasin, label: 'ligne de test',
      aisle: 'Frais', cycle_id: cycle ?? null, ...champs,
    }).select().single()
    expect(error, "l'amorce a échoué").toBeNull()
    return data!
  }
  const MESSAGE = 'Cette ligne est cochée ou payée : décoche-la et efface son prix pour la supprimer.'

  it('refuse par une exception lisible quand on supprime une ligne cochée', async () => {
    const l = await ligne({ checked_at: new Date().toISOString() })
    const { data, error } = await alice.client.from('shopping_item').delete().eq('id', l.id).select()
    expect(error, 'la base a répondu « 0 ligne » au lieu de refuser').not.toBeNull()
    expect(error!.code).toBe('23001')
    expect(error!.message).toBe(MESSAGE)
    expect(data ?? []).toHaveLength(0)
    const { data: reste } = await admin().from('shopping_item').select('id').eq('id', l.id)
    expect(reste).toHaveLength(1)
  })

  it('refuse aussi une ligne payée', async () => {
    const l = await ligne({ paid_price_eur: 2.5 })
    const { error } = await alice.client.from('shopping_item').delete().eq('id', l.id).select()
    expect(error?.message).toBe(MESSAGE)
  })

  it('laisse partir une ligne neuve', async () => {
    const l = await ligne({})
    const { error } = await alice.client.from('shopping_item').delete().eq('id', l.id)
    expect(error).toBeNull()
    expect((await admin().from('shopping_item').select('id').eq('id', l.id)).data).toHaveLength(0)
  })

  it('la régénération (lignes neuves seulement) passe sans lever, même au milieu de lignes cochées', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), 3), 'courses')
    const prise = await ligne({ source: 'recette', checked_at: new Date().toISOString() }, c.id)
    const neuve = await ligne({ source: 'recette' }, c.id)
    const { error } = await alice.client.from('shopping_item').delete()
      .eq('cycle_id', c.id).eq('source', 'recette')
      .is('checked_at', null).is('paid_price_eur', null)
    expect(error).toBeNull()
    expect((await admin().from('shopping_item').select('id').eq('id', neuve.id)).data).toHaveLength(0)
    expect((await admin().from('shopping_item').select('id').eq('id', prise.id)).data).toHaveLength(1)
  })

  it('ne casse pas la suppression d’un cycle : ses lignes cochées partent avec lui', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), 4), 'courses')
    const prise = await ligne({ checked_at: new Date().toISOString(), paid_price_eur: 1 }, c.id)
    const { error } = await admin().from('cycle').delete().eq('id', c.id)
    expect(error).toBeNull()
    const { data } = await admin().from('shopping_item').select('id, cycle_id').eq('id', prise.id)
    expect(data, 'la ligne cochée a survécu à son cycle, orpheline').toHaveLength(0)
  })

  it('ne casse pas la suppression d’un foyer', async () => {
    const jetable = await makeActor('cuisine-corr-jetable')
    await admin().from('shopping_item').insert({
      household_id: jetable.householdId, label: 'prise', checked_at: new Date().toISOString(),
    })
    const { error } = await admin().from('household').delete().eq('id', jetable.householdId)
    expect(error).toBeNull()
    const { data } = await admin().from('shopping_item').select('id')
      .eq('household_id', jetable.householdId)
    expect(data, 'des lignes de courses d’un foyer effacé ont survécu').toHaveLength(0)
  })

  it('ne casse pas delete_my_account', async () => {
    const partant = await makeActor('cuisine-corr-partant')
    await admin().from('shopping_item').insert({
      household_id: partant.householdId, label: 'prise', checked_at: new Date().toISOString(),
    })
    const { error } = await partant.client.rpc('delete_my_account')
    expect(error).toBeNull()
    const { data } = await admin().from('shopping_item').select('id')
      .eq('household_id', partant.householdId)
    expect(data, 'des lignes de courses d’un compte effacé ont survécu').toHaveLength(0)
  })
})

describe('3 · cocher ne range que de l’alimentaire', () => {
  let tomate: string
  beforeAll(async () => {
    const { data } = await admin().from('food').select('id').limit(1).single()
    tomate = data!.id
  })

  async function article(label: string, aisle: string | null, food_id: string | null = null) {
    const { data, error } = await admin().from('shopping_item').insert({
      household_id: alice.householdId, store_id: magasin, label, aisle, food_id,
    }).select().single()
    expect(error, "l'amorce a échoué").toBeNull()
    return data!
  }
  const coche = (id: string) => admin().from('shopping_item')
    .update({ checked_at: new Date().toISOString() }).eq('id', id).select().single()
  const decoche = (id: string) => admin().from('shopping_item')
    .update({ checked_at: null }).eq('id', id).select().single()
  const stockDe = async (id: string) =>
    (await admin().from('stock_item').select('id, location').eq('shopping_item_id', id)).data ?? []

  it('« Papier toilette » (Entretien) ne crée aucune ligne de stock', async () => {
    const a = await article('Papier toilette', 'Entretien')
    await coche(a.id)
    expect(await stockDe(a.id), 'du papier toilette est rangé au frigo').toHaveLength(0)
  })

  it('« Dentifrice » (Hygiène) non plus', async () => {
    const a = await article('Dentifrice', 'Hygiène')
    await coche(a.id)
    expect(await stockDe(a.id)).toHaveLength(0)
  })

  it('« Autre » se range : c’est le rayon par défaut d’un libellé inconnu (« Tofu » saisi à la main)', async () => {
    const tofu = await article('Tofu', 'Autre')
    await coche(tofu.id)
    expect(await stockDe(tofu.id), 'de la nourriture saisie à la main a disparu du stock').toHaveLength(1)
    const miel = await article('Miel', 'Autre', tomate)
    await coche(miel.id)
    expect(await stockDe(miel.id)).toHaveLength(1)
  })

  it('un article SANS rayon se range comme avant (NULL n’est pas « non alimentaire »)', async () => {
    const sans = await article('Farine', null, tomate)
    await coche(sans.id)
    expect(await stockDe(sans.id), 'un article sans rayon a disparu du stock').toHaveLength(1)
    const brut = await article('Truc sans rayon ni aliment', null)
    await coche(brut.id)
    expect(await stockDe(brut.id)).toHaveLength(1)
  })

  it('un article créé déjà coché suit la même règle', async () => {
    const { data } = await admin().from('shopping_item').insert({
      household_id: alice.householdId, store_id: magasin, label: 'Éponges',
      aisle: 'Entretien', checked_at: new Date().toISOString(),
    }).select().single()
    expect(await stockDe(data!.id)).toHaveLength(0)
  })

  it('une tomate se range ; décocher défait exactement ce que cocher a fait', async () => {
    const a = await article('Tomates', 'Fruits et légumes', tomate)
    await coche(a.id)
    expect(await stockDe(a.id)).toHaveLength(1)
    await decoche(a.id)
    expect(await stockDe(a.id)).toHaveLength(0)
  })

  it('le papier toilette garde le reste : rang, habitude, rayon appris', async () => {
    const a = await article('Mouchoirs', 'Entretien')
    const { data } = await coche(a.id)
    expect(data!.checked_rank).toBeGreaterThan(0)
    const { data: habitude } = await admin().from('shopping_habit').select('times_added')
      .eq('household_id', alice.householdId).ilike('label', 'Mouchoirs')
    expect(habitude).toHaveLength(1)
    await decoche(a.id)
    const { data: apres } = await admin().from('shopping_habit').select('times_added')
      .eq('household_id', alice.householdId).ilike('label', 'Mouchoirs')
    expect(apres, 'décocher n’a pas défait l’habitude').toHaveLength(0)
  })
})

describe('4 · la position des recettes du cycle', () => {
  async function recette(titre: string) {
    const { data } = await admin().from('recipe')
      .insert({ title: titre, yield_servings: 4 }).select().single()
    return data!.id as string
  }
  const retient = async (cycle: string, recipe: string) => {
    const { data, error } = await admin().from('cycle_recipe')
      .insert({ cycle_id: cycle, household_id: alice.householdId, recipe_id: recipe, servings: 4 })
      .select().single()
    expect(error).toBeNull()
    return data!
  }

  it('numérote 0, 1, 2 dans l’ordre où on retient', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), 5), 'selection')
    const a = await retient(c.id, await recette('Pos A'))
    const b = await retient(c.id, await recette('Pos B'))
    const d = await retient(c.id, await recette('Pos C'))
    expect([a.position, b.position, d.position]).toEqual([0, 1, 2])
  })

  it('après un retrait, la suivante passe après la dernière', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), 6), 'selection')
    await retient(c.id, await recette('Pos D'))
    const milieu = await retient(c.id, await recette('Pos E'))
    await retient(c.id, await recette('Pos E2'))
    await admin().from('cycle_recipe').delete().eq('id', milieu.id)
    const suivante = await retient(c.id, await recette('Pos F'))
    expect(suivante.position).toBe(3)
  })

  it('chaque cycle compte à part', async () => {
    await videLesCycles(alice)
    const c1 = await cycleDe(alice, lundi(await aujourdhui(), 7), 'cloture')
    const c2 = await cycleDe(alice, lundi(await aujourdhui(), 8), 'selection')
    await retient(c1.id, await recette('Pos G'))
    const premiere = await retient(c2.id, await recette('Pos H'))
    expect(premiere.position).toBe(0)
  })

  it('réécrire les parts ne déplace pas la recette', async () => {
    await videLesCycles(alice)
    const c = await cycleDe(alice, lundi(await aujourdhui(), 9), 'selection')
    const a = await retient(c.id, await recette('Pos I'))
    await retient(c.id, await recette('Pos J'))
    await admin().from('cycle_recipe').update({ servings: 6 }).eq('id', a.id)
    const { data } = await admin().from('cycle_recipe').select('position').eq('id', a.id).single()
    expect(data!.position).toBe(0)
  })
})
