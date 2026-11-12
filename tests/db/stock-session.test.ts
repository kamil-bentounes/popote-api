/**
 * « On range » : ce que la session prend dans le stock, et le rangement d'un seul geste (migration 0120).
 *
 * Le 25/10/2026, 1 500 g de poireaux et 20 tortillas avaient servi aux recettes, et le frigo de
 * l'appli les montrait encore. `ce_que_la_session_prend` calcule ce qui part, `range_la_session`
 * l'applique — avec les barquettes et le passage à « semaine », en une transaction, une seule fois.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { admin, makeActor, type Actor } from './helpers/db'
import { attends, commeLui, connexion, suivie } from './helpers/pg'

let alice: Actor
let bob: Actor
/** Un aliment par test : deux tests ne se disputent jamais la même ligne de stock. */
let aliments: string[] = []
let semaine = 0
/** Les aliments d'au-dessus de l'indice 100 : chaque test en prend un neuf, jamais déjà au stock du foyer. */
let pris = 0
const neuf = () => aliments[100 + pris++]

beforeAll(async () => {
  alice = await makeActor('stock-session-alice')
  bob = await makeActor('stock-session-bob')
  const { data, error } = await admin().from('food').select('id').order('id').limit(200)
  expect(error).toBeNull()
  aliments = data!.map(f => f.id)
})

/** Un seul cycle vivant par foyer : les précédents sont clos (par la machine à états, comme en vrai). */
async function clos(a: Actor) {
  const { data } = await admin().from('cycle').select('id').eq('household_id', a.householdId)
    .not('state', 'in', '(cloture,interrompue)')
  for (const c of data ?? []) {
    const { error: e1 } = await admin().from('cycle').update({ state: 'interrompue' }).eq('id', c.id)
    expect(e1).toBeNull()
    const { error: e2 } = await admin().from('cycle').update({ state: 'cloture' }).eq('id', c.id)
    expect(e2).toBeNull()
  }
}

/** Un cycle au dressage (l'étape où l'on range) et ses recettes. */
async function session(a: Actor, recettes: {
  parts: number; rendement: number | null
  lignes: { food: string; qty?: number | null; unit?: string | null; grammes?: number | null }[]
}[], etat = 'dressage') {
  semaine += 1
  await clos(a)
  const jour = new Date(Date.UTC(2030, 0, 1 + 7 * semaine)).toISOString().slice(0, 10)
  const { data: cycle, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of: jour, state: etat }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  for (const [i, r] of recettes.entries()) {
    const { data: recette, error: e1 } = await admin().from('recipe').insert({
      title: `Recette ${semaine}.${i}`, yield_servings: r.rendement, origin: 'manuelle',
      owner_household_id: a.householdId,
    }).select().single()
    expect(e1).toBeNull()
    const { error: e2 } = await admin().from('recipe_ingredient').insert(r.lignes.map((l, k) => ({
      recipe_id: recette!.id, ordinal: k + 1, raw_text: `ligne ${k + 1}`, food_id: l.food,
      qty: l.qty ?? null, unit: l.unit ?? null, grams_reference: l.grammes ?? null,
    })))
    expect(e2).toBeNull()
    const { error: e3 } = await admin().from('cycle_recipe').insert({
      cycle_id: cycle!.id, household_id: a.householdId, recipe_id: recette!.id,
      servings: r.parts, position: i,
    })
    expect(e3).toBeNull()
  }
  return cycle!.id as string
}

async function range(a: Actor, o: {
  label: string; food?: string | null; quantite?: number | null; unite?: string | null
  lieu?: 'frigo' | 'congelateur' | 'placard'; perime?: string | null
}) {
  const lieu = o.lieu ?? 'frigo'
  const { data, error } = await admin().from('stock_item').insert({
    household_id: a.householdId, label: o.label, food_id: o.food ?? null,
    quantity: o.quantite ?? null, unit: o.unite ?? null, location: lieu,
    frozen_at: lieu === 'congelateur' ? new Date().toISOString() : null,
    expires_at: o.perime ?? null,
  }).select().single()
  expect(error, "l'amorce du stock a échoué").toBeNull()
  return data!.id as string
}

async function stock(id: string) {
  const { data, error } = await admin().from('stock_item').select('*').eq('id', id).maybeSingle()
  expect(error).toBeNull()
  return data
}

/** Une barquette par recette du cycle, au frigo : le minimum que `range_la_session` demande. */
async function lots(cycle: string, o: { lieu?: string; pour?: string | null } = {}) {
  const { data, error } = await admin().from('cycle_recipe').select('recipe_id').eq('cycle_id', cycle).order('position')
  expect(error).toBeNull()
  return data!.map(r => ({
    recipe_id: r.recipe_id, grams: 300, kcal: 500, protein_g: 30, fiber_g: 8, carb_g: 50, fat_g: 15,
    for_user_id: o.pour ?? null, location: o.lieu ?? 'frigo',
  }))
}

/** Range : les barquettes, le retrait du stock avec ces corrections, le passage à « semaine ». */
async function range_(a: Actor, cycle: string, o: {
  restes?: Record<string, unknown>; retirer?: boolean; le?: Date; lots?: unknown[]
} = {}) {
  return a.client.rpc('range_la_session', {
    p_cycle: cycle, p_lots: o.lots ?? await lots(cycle), p_range_le: (o.le ?? new Date()).toISOString(),
    p_restes: o.restes ?? {}, p_retirer: o.retirer ?? true,
  })
}

/** Range, et ne rend que le nombre de lignes de stock touchées (ou l'erreur). */
async function retire(a: Actor, cycle: string, restes: Record<string, unknown> = {}) {
  const { data, error } = await range_(a, cycle, { restes })
  return { data: data === null ? null : (data as { retirees: number }).retirees, error }
}

async function prend(a: Actor, cycle: string) {
  const { data, error } = await a.client.rpc('ce_que_la_session_prend', { p_cycle: cycle })
  expect(error).toBeNull()
  return data!
}

describe('le calcul', () => {
  it('le cas réel : 1 000 g de poireaux × 6 parts / 4 = 1 500 g, le stock tombe à zéro', async () => {
    const [poireau] = aliments
    const cycle = await session(alice, [{
      parts: 6, rendement: 4, lignes: [{ food: poireau, qty: 1000, unit: 'g', grammes: 1000 }],
    }])
    const ligne = await range(alice, { label: 'Poireaux', food: poireau, quantite: 1500, unite: 'g' })

    const [l] = await prend(alice, cycle)
    expect(l).toMatchObject({ stock_item_id: ligne, libelle: 'Poireaux', calculable: true })
    expect(Number(l.prise)).toBe(1500)
    expect(Number(l.reste)).toBe(0)

    const { data: n, error } = await retire(alice, cycle)
    expect(error).toBeNull()
    expect(n).toBe(1)
    expect(await stock(ligne), 'une ligne à zéro est supprimée').toBeNull()
  })

  it('les ml se prennent comme des grammes ; un rendement inconnu vaut FACTEUR 1, comme la liste de courses', async () => {
    const lait = aliments[1]
    const cycle = await session(alice, [{
      // 250 ml pour une recette sans rendement, cuisinée pour 2 parts : la liste de courses a acheté
      // 250 ml (facteur 1), pas 500. Multiplier par les parts viderait ce qu'on a acheté pour 1×.
      parts: 2, rendement: null, lignes: [{ food: lait, qty: 250, unit: 'ml', grammes: 250 }],
    }])
    const ligne = await range(alice, { label: 'Lait', food: lait, quantite: 1000, unite: 'ml' })
    const [l] = await prend(alice, cycle)
    expect(Number(l.prise)).toBe(250)
    expect(Number(l.reste)).toBe(750)

    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity)).toBe(750)
  })

  it('le cas de la revue : 1 000 g de farine, une recette sans rendement pour 2 parts, ne vide pas le sac', async () => {
    const farine = aliments[20]
    const cycle = await session(alice, [{
      parts: 2, rendement: null, lignes: [{ food: farine, qty: 500, unit: 'g', grammes: 500 }],
    }])
    const ligne = await range(alice, { label: 'Farine', food: farine, quantite: 1000, unite: 'g' })
    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity), 'la liste de courses compte 500 g, pas 1 000').toBe(500)
  })

  it('à l’unité : 20 tortillas comptées en qty, pas en grammes', async () => {
    const tortilla = aliments[2]
    const cycle = await session(alice, [{
      // 10 tortillas pour 2 parts, cuisinées pour 4 : 20. grams_reference est ignoré ici.
      parts: 4, rendement: 2, lignes: [{ food: tortilla, qty: 10, unit: null, grammes: 700 }],
    }])
    const ligne = await range(alice, { label: 'Tortillas', food: tortilla, quantite: 20 })
    const [l] = await prend(alice, cycle)
    expect(l.calculable).toBe(true)
    expect(Number(l.prise)).toBe(20)
    await retire(alice, cycle)
    expect(await stock(ligne)).toBeNull()
  })

  it('additionne les recettes du cycle qui partagent un aliment', async () => {
    const oeuf = aliments[3]
    const cycle = await session(alice, [
      { parts: 4, rendement: 4, lignes: [{ food: oeuf, qty: 6, unit: null }] },
      { parts: 2, rendement: 1, lignes: [{ food: oeuf, qty: 1, unit: 'u' }] },
    ])
    await range(alice, { label: 'Œufs', food: oeuf, quantite: 12 })
    const [l] = await prend(alice, cycle)
    expect(Number(l.prise)).toBe(8)
    expect(Number(l.reste)).toBe(4)
  })

  it('ne prend pas plus que le stock', async () => {
    const [, , , , beurre] = aliments
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: beurre, qty: 500, unit: 'g', grammes: 500 }],
    }])
    await range(alice, { label: 'Beurre', food: beurre, quantite: 250, unite: 'g' })
    const [l] = await prend(alice, cycle)
    expect(Number(l.prise)).toBe(250)
    expect(Number(l.reste)).toBe(0)
  })

  it('deux lignes du même aliment se partagent le besoin, la plus pressée d’abord', async () => {
    const farine = aliments[5]
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: farine, qty: 300, unit: 'g', grammes: 300 }],
    }])
    const tard = await range(alice, { label: 'Farine (placard)', food: farine, quantite: 200,
      unite: 'g', lieu: 'placard', perime: '2031-01-01T00:00:00Z' })
    const tot = await range(alice, { label: 'Farine (ouverte)', food: farine, quantite: 200,
      unite: 'g', lieu: 'placard', perime: '2030-06-01T00:00:00Z' })

    const lignes = await prend(alice, cycle)
    const parId = new Map(lignes.map(l => [l.stock_item_id, l]))
    expect(Number(parId.get(tot)!.prise), 'la plus pressée part en entier').toBe(200)
    expect(Number(parId.get(tard)!.prise), 'la seconde ne prend que le reste du besoin').toBe(100)

    await retire(alice, cycle)
    expect(await stock(tot)).toBeNull()
    expect(Number((await stock(tard))!.quantity)).toBe(100)
  })
})

describe('ce qu’elle ne touche pas', () => {
  it('une ligne sans quantité, un pot, ou un autre aliment : intacts', async () => {
    const [ail, pot, autre, sel] = [aliments[6], aliments[7], aliments[8], aliments[9]]
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [
        { food: ail, qty: 2, unit: null }, { food: pot, qty: 1, unit: 'pot', grammes: 125 },
        { food: sel, qty: null, unit: null },
      ],
    }])
    const sansQuantite = await range(alice, { label: 'Ail', food: ail, quantite: null })
    const enPot = await range(alice, { label: 'Yaourt', food: pot, quantite: 4, unite: 'pot' })
    const horsRecette = await range(alice, { label: 'Confiture', food: autre, quantite: 1, unite: 'u' })
    const sansAliment = await range(alice, { label: 'Yaourt dessert', food: null, quantite: 6, unite: 'u' })
    const sansLigne = await range(alice, { label: 'Sel', food: sel, quantite: 500, unite: 'g' })

    const lignes = await prend(alice, cycle)
    const ids = lignes.map(l => l.stock_item_id)
    expect(ids).toContain(sansQuantite)
    expect(lignes.find(l => l.stock_item_id === sansQuantite)!.calculable).toBe(false)
    expect(lignes.find(l => l.stock_item_id === enPot)!.calculable, 'un pot n’est pas calculable').toBe(false)
    expect(lignes.find(l => l.stock_item_id === sansLigne)!.calculable,
      'sans poids de recette, rien à calculer').toBe(false)
    expect(ids, 'ni hors recette').not.toContain(horsRecette)
    expect(ids, 'ni sans aliment').not.toContain(sansAliment)

    const { data: n } = await retire(alice, cycle)
    expect(n).toBe(0)
    for (const id of [sansQuantite, enPot, horsRecette, sansAliment, sansLigne]) {
      expect(await stock(id), 'la ligne a disparu').not.toBeNull()
    }
    expect(Number((await stock(enPot))!.quantity)).toBe(4)
    expect(Number((await stock(sansLigne))!.quantity)).toBe(500)
  })
})

describe('les corrections de l’écran', () => {
  async function cas() {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 1000, unit: 'g', grammes: 1000 }],
    }])
    const ligne = await range(alice, { label: 'Carottes', food: aliment, quantite: 1500, unite: 'g' })
    return { cycle, ligne }
  }

  it('« il en reste 800 » l’emporte sur le calcul (500)', async () => {
    const { cycle, ligne } = await cas()
    const { data: n, error } = await retire(alice, cycle, { [ligne]: 800 })
    expect(error).toBeNull()
    expect(n).toBe(1)
    expect(Number((await stock(ligne))!.quantity)).toBe(800)
  })

  it('« il en reste 0 » supprime la ligne', async () => {
    const { cycle, ligne } = await cas()
    await retire(alice, cycle, { [ligne]: 0 })
    expect(await stock(ligne)).toBeNull()
  })

  it('un reste plus grand que le stock laisse la ligne telle quelle ; un négatif la supprime', async () => {
    const a = await cas()
    const { data: n } = await retire(alice, a.cycle, { [a.ligne]: 99_999 })
    expect(n, 'rien n’a changé').toBe(0)
    expect(Number((await stock(a.ligne))!.quantity)).toBe(1500)

    const b = await cas()
    await retire(alice, b.cycle, { [b.ligne]: -5 })
    expect(await stock(b.ligne)).toBeNull()
  })

  it('une correction sur une ligne d’un autre foyer, ou inconnue, est ignorée', async () => {
    const { cycle, ligne } = await cas()
    const chezBob = await range(bob, { label: 'Carottes de Bob', quantite: 10, unite: 'g' })
    const { error } = await retire(alice, cycle,
      { [chezBob]: 0, '00000000-0000-0000-0000-000000000000': 3 })
    expect(error).toBeNull()
    expect(await stock(chezBob), 'le stock de Bob n’a pas bougé').not.toBeNull()
    expect(Number((await stock(ligne))!.quantity)).toBe(500)
  })

  it('refuse un reste qui n’est pas un nombre, sans rien retirer', async () => {
    const { cycle, ligne } = await cas()
    const { error } = await retire(alice, cycle, { [ligne]: 'beaucoup' })
    expect(error?.message).toMatch(/pas un nombre/)
    expect(Number((await stock(ligne))!.quantity)).toBe(1500)
    const { data } = await admin().from('cycle').select('stock_retire_le').eq('id', cycle).single()
    expect(data!.stock_retire_le, 'une écriture refusée ne marque pas la session').toBeNull()
  })
})

describe('l’idempotence', () => {
  it('ne retire jamais deux fois : le second appel ne fait rien', async () => {
    const aliment = aliments[30]
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 600, unit: 'g', grammes: 600 }],
    }])
    const ligne = await range(alice, { label: 'Riz', food: aliment, quantite: 1000, unite: 'g' })

    const premier = await retire(alice, cycle)
    expect(premier.data).toBe(1)
    expect(Number((await stock(ligne))!.quantity)).toBe(400)
    const { data: c } = await admin().from('cycle').select('stock_retire_le').eq('id', cycle).single()
    expect(c!.stock_retire_le).not.toBeNull()

    // Du riz racheté entre-temps : la session ne le reprend pas.
    await admin().from('stock_item').update({ quantity: 1400 }).eq('id', ligne)
    const second = await retire(alice, cycle)
    expect(second.error).toBeNull()
    expect(second.data).toBe(0)
    expect(Number((await stock(ligne))!.quantity)).toBe(1400)
  })
})

describe('l’isolation entre foyers', () => {
  it('un autre foyer ne lit rien et ne retire rien', async () => {
    const aliment = aliments[31]
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 100, unit: 'g', grammes: 100 }],
    }])
    const ligne = await range(alice, { label: 'Sucre', food: aliment, quantite: 500, unite: 'g' })

    expect(await prend(bob, cycle), 'Bob lit le stock d’Alice').toEqual([])
    const { error } = await retire(bob, cycle)
    expect(error?.message).toMatch(/introuvable/i)
    expect(Number((await stock(ligne))!.quantity)).toBe(500)
    const { data } = await admin().from('cycle').select('stock_retire_le').eq('id', cycle).single()
    expect(data!.stock_retire_le).toBeNull()
  })

  it('un cycle qui n’existe pas : rien à lire, une erreur claire à l’écriture', async () => {
    const inconnu = '00000000-0000-0000-0000-000000000000'
    expect(await prend(alice, inconnu)).toEqual([])
    const { error } = await retire(alice, inconnu)
    expect(error?.message).toMatch(/introuvable/i)
  })

  it('l’anonyme n’a aucune des fonctions', async () => {
    const { createClient } = await import('@supabase/supabase-js')
    const anonyme = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!,
      { auth: { persistSession: false } })
    const a = await anonyme.rpc('ce_que_la_session_prend',
      { p_cycle: '00000000-0000-0000-0000-000000000000' })
    const b = await anonyme.rpc('range_la_session', {
      p_cycle: '00000000-0000-0000-0000-000000000000', p_lots: [], p_range_le: new Date().toISOString(),
    })
    const c = await anonyme.rpc('retire_du_stock_interne',
      { p_cycle: '00000000-0000-0000-0000-000000000000', p_restes: {} })
    expect(a.error, 'lecture ouverte à l’anonyme').not.toBeNull()
    expect(b.error, 'écriture ouverte à l’anonyme').not.toBeNull()
    expect(c.error, 'retrait interne ouvert à l’anonyme').not.toBeNull()
  })
})

describe('le calcul, les cas que la revue a trouvés', () => {
  it('une ligne en g sans grams_reference se compte par sa qty', async () => {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 300, unit: 'g', grammes: null }],
    }])
    const ligne = await range(alice, { label: 'Riz', food: aliment, quantite: 1000, unite: 'g' })
    const [l] = await prend(alice, cycle)
    expect(l.calculable).toBe(true)
    expect(Number(l.prise)).toBe(300)
    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity)).toBe(700)
  })

  it('une ligne de recette qui ne se convertit pas rend la ligne de stock NON calculable, au lieu d’un retrait partiel', async () => {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [
        { food: aliment, qty: 300, unit: 'g', grammes: 300 },
        // « 2 bouquets » : ni poids, ni unité compatible. Retirer les 300 g seuls serait un retrait partiel.
        { food: aliment, qty: 2, unit: 'bouquet', grammes: null },
      ],
    }])
    const ligne = await range(alice, { label: 'Persil', food: aliment, quantite: 500, unite: 'g' })
    const [l] = await prend(alice, cycle)
    expect(l.calculable).toBe(false)
    expect(l.prise).toBeNull()
    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity), 'le stock n’a pas bougé').toBe(500)
  })

  it('un aliment en grammes ET à la pièce au stock : les deux sont non calculables, pas satisfaits deux fois', async () => {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 2, unit: null, grammes: 200 }],
    }])
    const enMasse = await range(alice, { label: 'Oignons (filet)', food: aliment, quantite: 500, unite: 'g' })
    const aLaPiece = await range(alice, { label: 'Oignons (vrac)', food: aliment, quantite: 5 })
    const lignes = await prend(alice, cycle)
    expect(lignes.find(l => l.stock_item_id === enMasse)!.calculable).toBe(false)
    expect(lignes.find(l => l.stock_item_id === aLaPiece)!.calculable).toBe(false)
    await retire(alice, cycle)
    expect(Number((await stock(enMasse))!.quantity)).toBe(500)
    expect(Number((await stock(aLaPiece))!.quantity)).toBe(5)
  })

  it('à l’unité : pas de 0,75 oignon — on arrondit vers le bas, le reste reste au stock', async () => {
    const aliment = neuf()
    // 3 oignons pour 4 parts, cuisinés pour 3 : 2,25 → 2 ; 5 au stock → 3.
    const cycle = await session(alice, [{
      parts: 3, rendement: 4, lignes: [{ food: aliment, qty: 3, unit: null }],
    }])
    const ligne = await range(alice, { label: 'Oignons', food: aliment, quantite: 5 })
    const [l] = await prend(alice, cycle)
    expect(Number(l.prise)).toBe(2)
    expect(Number(l.reste)).toBe(3)
    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity)).toBe(3)

    // Trois quarts d'oignon : rien ne sort.
    const aliment2 = neuf()
    const cycle2 = await session(alice, [{
      parts: 3, rendement: 4, lignes: [{ food: aliment2, qty: 1, unit: null }],
    }])
    const ligne2 = await range(alice, { label: 'Échalotes', food: aliment2, quantite: 4 })
    const [l2] = await prend(alice, cycle2)
    expect(Number(l2.prise)).toBe(0)
    await retire(alice, cycle2)
    expect(Number((await stock(ligne2))!.quantity)).toBe(4)
  })

  it('le poids appris par le foyer fait d’« 2 oignons » des grammes, comme la liste de courses', async () => {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 2, unit: null, grammes: null }],
    }])
    const ligne = await range(alice, { label: 'Oignons', food: aliment, quantite: 1000, unite: 'g' })
    const [sans] = await prend(alice, cycle)
    expect(sans.calculable, 'sans poids appris, deux oignons ne sont pas des grammes').toBe(false)

    const { error } = await admin().from('household_unit_weight').insert({
      household_id: alice.householdId, food_id: aliment, unit_label: 'oignon', grams: 118,
      observations: 3, seuil: 3, actif: true,
    })
    expect(error).toBeNull()
    const [avec] = await prend(alice, cycle)
    expect(avec.calculable).toBe(true)
    expect(Number(avec.prise)).toBe(236)
    await retire(alice, cycle)
    expect(Number((await stock(ligne))!.quantity)).toBe(764)
  })
})

describe('range_la_session : les barquettes, le stock et l’état, ensemble', () => {
  async function portions(cycle: string) {
    const { data, error } = await admin().from('portion').select('*').eq('cycle_id', cycle).order('created_at')
    expect(error).toBeNull()
    return data!
  }
  async function etat(cycle: string) {
    const { data } = await admin().from('cycle').select('state, stock_retire_le').eq('id', cycle).single()
    return data!
  }
  async function simple(extra: { etat?: string } = {}) {
    const aliment = neuf()
    const cycle = await session(alice, [
      { parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 200, unit: 'g', grammes: 200 }] },
      { parts: 2, rendement: 2, lignes: [] },
    ], extra.etat ?? 'dressage')
    const ligne = await range(alice, { label: 'Lentilles', food: aliment, quantite: 600, unite: 'g' })
    return { cycle, ligne }
  }

  it('crée les barquettes, retire le stock et passe à « semaine » en un appel', async () => {
    const { cycle, ligne } = await simple()
    const le = new Date(Date.now() - 2 * 86_400_000)
    le.setSeconds(0, 0)
    const l = await lots(cycle)
    l[1].location = 'congelateur'
    const { data, error } = await range_(alice, cycle, { le, lots: l })
    expect(error).toBeNull()
    expect(data).toMatchObject({ deja: false, cree: true, portions: 2, retirees: 1 })

    const ps = await portions(cycle)
    expect(ps).toHaveLength(2)
    const frigo = ps.find(p => p.location === 'frigo')!
    const froid = ps.find(p => p.location === 'congelateur')!
    expect(new Date(frigo.prepared_at).getTime()).toBe(le.getTime())
    expect(frigo.frozen_at).toBeNull()
    expect(new Date(froid.frozen_at!).getTime(), 'frozen_at = l’heure du rangement').toBe(le.getTime())
    // La péremption vient du trigger : 4 × 24 h et 90 × 24 h, exactement.
    expect(new Date(frigo.expires_at).getTime() - le.getTime()).toBe(4 * 86_400_000)
    expect(new Date(froid.expires_at).getTime() - le.getTime()).toBe(90 * 86_400_000)
    expect(Number((await stock(ligne))!.quantity)).toBe(400)
    const c = await etat(cycle)
    expect(c.state).toBe('semaine')
    expect(c.stock_retire_le).not.toBeNull()
  })

  it('le titre vient de la recette, pas du client', async () => {
    const { cycle } = await simple()
    const l = await lots(cycle)
    await range_(alice, cycle, { lots: [{ ...l[0], label: 'Un titre inventé' }] })
    const [p] = await portions(cycle)
    expect(p.label).toMatch(/^Recette /)
  })

  it('DOUBLE APPUI : deux appels en même temps créent les barquettes UNE fois, et retirent le stock une fois', async () => {
    const { cycle, ligne } = await simple()
    // Un second membre du foyer, sur son téléphone.
    const email = `stock-session-second-${Date.now()}@test.local`
    const { data: u, error: ue } = await admin().auth.admin.createUser({
      email, password: 'test-password-12345', email_confirm: true,
    })
    expect(ue).toBeNull()
    const { error: pe } = await admin().from('user_profile')
      .insert({ id: u!.user.id, household_id: alice.householdId, display_name: 'Second' })
    expect(pe).toBeNull()
    const second = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!,
      { auth: { persistSession: false } })
    expect((await second.auth.signInWithPassword({ email, password: 'test-password-12345' })).error).toBeNull()

    const l = await lots(cycle)
    const args = { p_cycle: cycle, p_lots: l, p_range_le: new Date().toISOString(), p_restes: {}, p_retirer: true }
    const reponses = await Promise.all([
      alice.client.rpc('range_la_session', args),
      second.rpc('range_la_session', args),
      alice.client.rpc('range_la_session', args),
    ])
    for (const r of reponses) expect(r.error).toBeNull()
    expect(reponses.filter(r => !(r.data as { deja: boolean }).deja), 'un seul appel a rangé').toHaveLength(1)
    expect((await portions(cycle)), 'les barquettes sont doublées').toHaveLength(l.length)
    expect(Number((await stock(ligne))!.quantity), 'le stock est retiré deux fois').toBe(400)
    expect((await etat(cycle)).state).toBe('semaine')
  })

  it('DOUBLE APPUI, au coude à coude : le second attend le premier, puis ne trouve plus rien à faire', async () => {
    const { cycle, ligne } = await simple()
    const l = await lots(cycle)
    const sql = `select public.range_la_session($1, $2::jsonb, $3, '{}'::jsonb, true) as r`
    const args = [cycle, JSON.stringify(l), new Date().toISOString()]
    const a = await connexion()
    const b = await connexion()
    try {
      // Le premier téléphone range, sa transaction reste ouverte…
      await commeLui(a, alice.userId)
      const premier = (await a.query(sql, args)).rows[0].r
      expect(premier).toMatchObject({ deja: false, cree: true })

      // … le second appuie PENDANT ce temps : il doit attendre, pas passer devant.
      await commeLui(b, alice.userId)
      const second = suivie(b.query(sql, args))
      await attends(500)
      expect(second.fini, 'le second appel n’a pas attendu le verrou du cycle').toBe(false)

      await a.query('commit')
      const r = (await second.p).rows[0].r
      await b.query('commit')
      expect(r, 'le second doit trouver le travail fait').toMatchObject({ deja: true, cree: false, retirees: 0 })
    } finally {
      await a.query('rollback').catch(() => {})
      await b.query('rollback').catch(() => {})
      await a.end()
      await b.end()
    }
    expect(await portions(cycle), 'les barquettes sont doublées').toHaveLength(l.length)
    expect(Number((await stock(ligne))!.quantity), 'le stock est retiré deux fois').toBe(400)
  })

  it('rejouée (la réponse s’est perdue) : « déjà rangé », rien n’est recréé ni retiré', async () => {
    const { cycle, ligne } = await simple()
    expect((await range_(alice, cycle)).error).toBeNull()
    await admin().from('stock_item').update({ quantity: 900 }).eq('id', ligne)
    const { data, error } = await range_(alice, cycle, { lots: [...await lots(cycle), ...await lots(cycle)] })
    expect(error).toBeNull()
    expect(data).toMatchObject({ deja: true, cree: false, portions: 2, retirees: 0 })
    expect(await portions(cycle)).toHaveLength(2)
    expect(Number((await stock(ligne))!.quantity)).toBe(900)
  })

  it('p_retirer faux : on range sans toucher au stock, et la date reste vide', async () => {
    const { cycle, ligne } = await simple()
    const { data, error } = await range_(alice, cycle, { retirer: false })
    expect(error).toBeNull()
    expect(data).toMatchObject({ cree: true, retirees: 0 })
    expect(Number((await stock(ligne))!.quantity)).toBe(600)
    const c = await etat(cycle)
    expect(c.state).toBe('semaine')
    expect(c.stock_retire_le).toBeNull()
  })

  it('refuse un cycle qui n’est pas au dressage, sans rien écrire', async () => {
    const { cycle, ligne } = await simple({ etat: 'en_cuisine' })
    const { error } = await range_(alice, cycle)
    expect(error?.message).toMatch(/pas au rangement/)
    expect(await portions(cycle)).toHaveLength(0)
    expect(Number((await stock(ligne))!.quantity)).toBe(600)
    expect((await etat(cycle)).state).toBe('en_cuisine')
  })

  it('un cycle à « semaine » sans barquette n’est pas rangeable non plus', async () => {
    const { cycle } = await simple({ etat: 'semaine' })
    const { error } = await range_(alice, cycle)
    expect(error?.message).toMatch(/pas au rangement/)
    expect(await portions(cycle)).toHaveLength(0)
  })

  it('des barquettes déjà là (dépannage) sont gardées telles quelles : on ne les double pas', async () => {
    const { cycle, ligne } = await simple()
    const [lot] = await lots(cycle)
    const { error: e0 } = await admin().from('portion').insert({
      household_id: alice.householdId, cycle_id: cycle, recipe_id: lot.recipe_id, label: 'Déjà là',
      grams: 250, kcal: 400, protein_g: 20, fiber_g: 5, carb_g: 40, fat_g: 10, location: 'frigo',
    })
    expect(e0).toBeNull()
    const { data, error } = await range_(alice, cycle)
    expect(error).toBeNull()
    expect(data).toMatchObject({ cree: false, portions: 1, retirees: 1 })
    expect(await portions(cycle)).toHaveLength(1)
    expect(Number((await stock(ligne))!.quantity)).toBe(400)
    expect((await etat(cycle)).state).toBe('semaine')
  })

  describe('ce qu’elle refuse, sans rien écrire', () => {
    async function refuse(
      o: (cycle: string) => Promise<NonNullable<Parameters<typeof range_>[2]>> | NonNullable<Parameters<typeof range_>[2]>,
      motif: RegExp,
    ) {
      const { cycle, ligne } = await simple()
      const { error } = await range_(alice, cycle, await o(cycle))
      expect(error?.message).toMatch(motif)
      expect(await portions(cycle), 'une écriture refusée a laissé des barquettes').toHaveLength(0)
      expect(Number((await stock(ligne))!.quantity)).toBe(600)
      const c = await etat(cycle)
      expect(c.state).toBe('dressage')
      expect(c.stock_retire_le).toBeNull()
      return { cycle }
    }

    it('une recette qui n’est pas de la session', async () => {
      const { data: autre } = await admin().from('recipe').insert({
        title: 'Hors session', origin: 'manuelle', owner_household_id: alice.householdId,
      }).select().single()
      const { cycle } = await simple()
      const l = await lots(cycle)
      const { error } = await range_(alice, cycle, { lots: [{ ...l[0], recipe_id: autre!.id }] })
      expect(error?.message).toMatch(/pas d’une recette de cette session/)
      expect(await portions(cycle)).toHaveLength(0)
    })

    it('un lieu inconnu', async () => {
      await refuse(async c => ({ lots: await lots(c, { lieu: 'placard' }) }), /frigo ou au congélateur/)
    })

    it('un poids ou des macros absurdes', async () => {
      const { cycle } = await simple()
      const l = await lots(cycle)
      for (const mauvais of [{ grams: 0 }, { grams: 50_000 }, { kcal: -1 }, { protein_g: 99_999 }, { fat_g: null }]) {
        const { error } = await range_(alice, cycle, { lots: [{ ...l[0], ...mauvais }] })
        expect(error?.message, JSON.stringify(mauvais)).toMatch(/plausibles/)
      }
      expect(await portions(cycle)).toHaveLength(0)
    })

    it('une barquette pour quelqu’un d’un autre foyer', async () => {
      const { cycle } = await simple()
      const l = await lots(cycle, { pour: bob.userId })
      const { error } = await range_(alice, cycle, { lots: l })
      expect(error?.message).toMatch(/pas du foyer/)
      expect(await portions(cycle)).toHaveLength(0)
    })

    it('une barquette pour un membre du foyer : acceptée', async () => {
      const { cycle } = await simple()
      const { error } = await range_(alice, cycle, { lots: await lots(cycle, { pour: alice.userId }) })
      expect(error).toBeNull()
      expect((await portions(cycle))[0].for_user_id).toBe(alice.userId)
    })

    it('aucun lot, ou des lots mal formés', async () => {
      await refuse(() => ({ lots: [] }), /Rien à dresser/)
      await refuse(() => ({ lots: [{ recipe_id: 'pas-un-uuid' }] }), /mal formées/)
      await refuse(() => ({ lots: [42] }), /mal formées/)
    })

    it('« rangé le » dans le futur, ou il y a plus de 4 jours', async () => {
      await refuse(() => ({ le: new Date(Date.now() + 3_600_000) }), /futur/)
      await refuse(() => ({ le: new Date(Date.now() - 5 * 86_400_000) }), /plus de 4 jours/)
    })

    it('un reste qui n’est pas un nombre', async () => {
      await refuse(() => ({ restes: { x: 'beaucoup' } }), /pas un nombre/)
    })

    it('« rangé le » il y a trois jours est accepté', async () => {
      const { cycle } = await simple()
      const { error } = await range_(alice, cycle, { le: new Date(Date.now() - 3 * 86_400_000) })
      expect(error).toBeNull()
    })
  })

  it('un autre foyer n’y range rien', async () => {
    const { cycle, ligne } = await simple()
    const { error } = await range_(bob, cycle)
    expect(error?.message).toMatch(/introuvable/i)
    expect(await portions(cycle)).toHaveLength(0)
    expect(Number((await stock(ligne))!.quantity)).toBe(600)
  })
})

describe('stock_retire_le n’est pas aux comptes', () => {
  it('un membre ne remet pas la date à zéro par PostgREST, ni ne la pose', async () => {
    const aliment = neuf()
    const cycle = await session(alice, [{
      parts: 4, rendement: 4, lignes: [{ food: aliment, qty: 100, unit: 'g', grammes: 100 }],
    }])
    await range(alice, { label: 'Semoule', food: aliment, quantite: 500, unite: 'g' })
    expect((await range_(alice, cycle)).error).toBeNull()

    const remet = await alice.client.from('cycle').update({ stock_retire_le: null }).eq('id', cycle).select()
    expect(remet.error?.message).toMatch(/posée par le rangement/)
    const pose = await alice.client.from('cycle').update({ stock_retire_le: new Date().toISOString() })
      .eq('id', cycle).select()
    expect(pose.error?.message).toMatch(/posée par le rangement/)
    const { data } = await admin().from('cycle').select('stock_retire_le').eq('id', cycle).single()
    expect(data!.stock_retire_le).not.toBeNull()

    // Les autres colonnes restent modifiables, et un envoi qui ne change rien à la date passe.
    const autre = await alice.client.from('cycle').update({ servings_target: 12, stock_retire_le: data!.stock_retire_le })
      .eq('id', cycle).select()
    expect(autre.error).toBeNull()
    expect(autre.data).toHaveLength(1)
  })

  it('une insertion par un compte ne porte pas la date non plus ; le rôle de service le peut', async () => {
    const semaineSuivante = new Date(Date.UTC(2031, 0, 6 + semaine)).toISOString().slice(0, 10)
    await clos(alice)
    const { error } = await alice.client.from('cycle').insert({
      household_id: alice.householdId, week_of: semaineSuivante, state: 'vide',
      stock_retire_le: new Date().toISOString(),
    })
    expect(error?.message).toMatch(/posée par le rangement/)
    const { data, error: e2 } = await admin().from('cycle').insert({
      household_id: alice.householdId, week_of: semaineSuivante, state: 'vide',
      stock_retire_le: new Date().toISOString(),
    }).select().single()
    expect(e2).toBeNull()
    expect(data!.stock_retire_le).not.toBeNull()
  })

  it('le retrait interne n’est appelable par aucun compte', async () => {
    const { error } = await alice.client.rpc('retire_du_stock_interne',
      { p_cycle: '00000000-0000-0000-0000-000000000000', p_restes: {} })
    expect(error).not.toBeNull()
  })
})
