/**
 * La règle d'apprentissage de la pesée (§5.2.1), là où elle fait autorité.
 *
 * Elle est en base et pas dans le client, pour la raison habituelle : deux
 * téléphones pèsent la même semaine, et un invariant du produit ne peut pas
 * dépendre de celui qui a saisi (D50).
 *
 * Quatre règles, et chacune peut casser en silence :
 *   1. le poids unitaire dérivé = grammes / quantité observée ;
 *   2. les aberrantes hors [0,4× ; 2,5×] la référence sont REJETÉES — et sans
 *      référence, rien n'est rejeté mais le seuil passe de 3 à 5 ;
 *   3. la valeur retenue est la MÉDIANE, pas la moyenne ;
 *   4. activation au seuil ; en dessous, la référence prime.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor
/** Un aliment AVEC référence (110 g), et un SANS. */
let oignon: string
let inconnu: string

async function pese(a: Actor, food: string, qte: number, grammes: number, unite = 'u') {
  const { data, error } = await admin().from('weighing').insert({
    household_id: a.householdId, food_id: food,
    qty_observed: qte, unit_observed: unite, grams: grammes,
  }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!.id as string
}

async function appris(a: Actor, food: string, unite = 'u') {
  const { data } = await admin().from('household_unit_weight')
    .select('grams, observations, seuil, actif')
    .eq('household_id', a.householdId).eq('food_id', food).eq('unit_label', unite).maybeSingle()
  return data
}

beforeAll(async () => {
  alice = await makeActor('pesee-alice')
  bob = await makeActor('pesee-bob')

  const { data: o } = await admin().from('food').insert({
    source: 'ciqual', source_code: `t-oignon-${Date.now()}`, name: 'Oignon de test',
  }).select().single()
  oignon = o!.id
  await admin().from('unit_weight')
    .insert({ food_id: oignon, label: 'oignon', grams: 110, confidence: 0.6 })

  const { data: i } = await admin().from('food').insert({
    source: 'ciqual', source_code: `t-inconnu-${Date.now()}`, name: 'Aliment sans référence',
  }).select().single()
  inconnu = i!.id
})

describe('le poids unitaire se dérive', () => {
  it('divise les grammes par la quantité observée', async () => {
    await pese(alice, oignon, 2, 240)
    expect(Number((await appris(alice, oignon))!.grams)).toBeCloseTo(120, 1)
  })

  it('n’active rien avec une seule pesée', async () => {
    // Une observation n'est pas une médiane : la référence doit primer.
    const a = await appris(alice, oignon)
    expect(a!.observations).toBe(1)
    expect(a!.actif, 'un poids a pris autorité sur une seule pesée').toBe(false)
    expect(a!.seuil).toBe(3)
  })

  it('s’active à la troisième, et prend la MÉDIANE', async () => {
    await pese(alice, oignon, 1, 100)   // 100
    await pese(alice, oignon, 1, 130)   // 130 · médiane de {100, 120, 130} = 120
    const a = await appris(alice, oignon)
    expect(a!.observations).toBe(3)
    expect(a!.actif, 'trois pesées n’ont pas suffi').toBe(true)
    expect(Number(a!.grams), 'la moyenne a été prise au lieu de la médiane')
      .toBeCloseTo(120, 1)
  })
})

describe('les aberrantes', () => {
  it('sont rejetées hors des bornes de la référence', async () => {
    // 1,2 kg pour un oignon : le doigt a glissé. La médiane ne doit pas bouger.
    const avant = await appris(alice, oignon)
    await pese(alice, oignon, 1, 1200)
    const apres = await appris(alice, oignon)
    expect(apres!.observations, 'une aberrante a été comptée').toBe(avant!.observations)
    expect(Number(apres!.grams)).toBeCloseTo(Number(avant!.grams), 1)
  })

  it('sont rejetées aussi par le bas', async () => {
    const avant = await appris(alice, oignon)
    await pese(alice, oignon, 1, 8)     // on a pesé la peau
    expect((await appris(alice, oignon))!.observations).toBe(avant!.observations)
  })

  it('ne sont pas filtrées quand aucune référence n’existe', async () => {
    // C'est le cas où l'apprentissage sert le plus : filtrer sur rien
    // reviendrait à filtrer sur la première observation, qui peut être fausse.
    await pese(bob, inconnu, 1, 40)
    await pese(bob, inconnu, 1, 900)
    const a = await appris(bob, inconnu)
    expect(a!.observations, 'une observation a été filtrée sans référence').toBe(2)
  })

  it('font passer le seuil à cinq quand il n’y a pas de référence', async () => {
    // Sans borne pour écarter les fautes, il en faut davantage pour conclure.
    const a = await appris(bob, inconnu)
    expect(a!.seuil).toBe(5)
    expect(a!.actif).toBe(false)

    await pese(bob, inconnu, 1, 50)
    await pese(bob, inconnu, 1, 60)
    expect((await appris(bob, inconnu))!.actif, 'quatre pesées ont suffi').toBe(false)
    await pese(bob, inconnu, 1, 55)
    expect((await appris(bob, inconnu))!.actif, 'cinq pesées n’ont pas suffi').toBe(true)
  })
})

describe('effacer une pesée', () => {
  it('recalcule la médiane, et désactive si le seuil n’est plus atteint', async () => {
    // Une faute de frappe se corrige en effaçant, pas en pesant trois fois de
    // plus pour la noyer dans la médiane.
    const jetable = await makeActor('pesee-efface')
    await pese(jetable, oignon, 1, 100)
    await pese(jetable, oignon, 1, 120)
    const dernier = await pese(jetable, oignon, 1, 140)
    expect((await appris(jetable, oignon))!.actif).toBe(true)

    await admin().from('weighing').delete().eq('id', dernier)
    const a = await appris(jetable, oignon)
    expect(a!.observations).toBe(2)
    expect(a!.actif, 'le poids est resté actif à deux observations').toBe(false)
    expect(Number(a!.grams)).toBeCloseTo(110, 1)
  })

  it('efface le poids appris quand il ne reste plus rien', async () => {
    const jetable = await makeActor('pesee-vide')
    const seul = await pese(jetable, oignon, 1, 115)
    await admin().from('weighing').delete().eq('id', seul)
    expect(await appris(jetable, oignon), 'un poids a survécu à ses observations').toBeNull()
  })
})

describe('le poids qui fait foi', () => {
  it('est celui du foyer dès qu’il est actif', async () => {
    const { data } = await alice.client.rpc('poids_unitaire', { p_food_id: oignon })
    expect(Number(data), 'la référence a primé sur le poids appris').toBeCloseTo(120, 1)
  })

  it('reste la référence pour un foyer qui n’a rien pesé', async () => {
    const neuf = await makeActor('pesee-neuf')
    const { data } = await neuf.client.rpc('poids_unitaire', { p_food_id: oignon })
    expect(Number(data)).toBeCloseTo(110, 1)
  })

  it('est null quand personne ne sait rien', async () => {
    const { data } = await alice.client.rpc('poids_unitaire', { p_food_id: inconnu })
    expect(data, 'un poids a été inventé').toBeNull()
  })
})

describe('l’isolation entre foyers', () => {
  it('ne laisse pas un foyer voir les pesées d’un autre', async () => {
    for (const table of ['weighing', 'household_unit_weight'] as const) {
      const { data } = await bob.client.from(table)
        .select('household_id').eq('household_id', alice.householdId)
      expect(data ?? [], `fuite de ${table} entre foyers`).toHaveLength(0)
    }
  })

  it('n’applique pas le poids d’un foyer chez un autre', async () => {
    // Bob n'a jamais pesé d'oignon : il doit rester sur la référence, pas
    // hériter des 120 g d'Alice.
    const { data } = await bob.client.rpc('poids_unitaire', { p_food_id: oignon })
    expect(Number(data), 'un poids appris a fuité entre foyers').toBeCloseTo(110, 1)
  })

  it('empêche d’écrire une pesée chez un autre foyer', async () => {
    const { error } = await bob.client.from('weighing').insert({
      household_id: alice.householdId, food_id: oignon,
      qty_observed: 1, unit_observed: 'u', grams: 999,
    })
    expect(error, 'une pesée a été écrite chez un autre foyer').not.toBeNull()
  })

  it('emporte les pesées avec le foyer', async () => {
    const jetable = await makeActor('pesee-jetable')
    await pese(jetable, oignon, 1, 105)
    await admin().from('household').delete().eq('id', jetable.householdId)
    const { data } = await admin().from('weighing')
      .select('id').eq('household_id', jetable.householdId)
    expect(data ?? [], 'des pesées ont survécu à leur foyer').toHaveLength(0)
  })
})

describe('la résolution par foyer', () => {
  it('se pose et ne fuit pas', async () => {
    const { data: r } = await admin().from('recipe')
      .insert({ title: 'Recette de pesée' }).select().single()
    const { data: ing } = await admin().from('recipe_ingredient')
      .insert({ recipe_id: r!.id, ordinal: 1, raw_text: '2 oignons' }).select().single()

    const { error } = await alice.client.from('household_ingredient_resolution').insert({
      household_id: alice.householdId, recipe_ingredient_id: ing!.id, food_id: oignon,
    })
    expect(error).toBeNull()

    const { data: chezBob } = await bob.client.from('household_ingredient_resolution')
      .select('recipe_ingredient_id').eq('recipe_ingredient_id', ing!.id)
    expect(chezBob ?? [], 'une correction de foyer a fuité').toHaveLength(0)
  })

  it('refuse une résolution qui ne dit rien', async () => {
    const { data: r } = await admin().from('recipe')
      .insert({ title: 'Vide' }).select().single()
    const { data: ing } = await admin().from('recipe_ingredient')
      .insert({ recipe_id: r!.id, ordinal: 1, raw_text: 'x' }).select().single()
    const { error } = await admin().from('household_ingredient_resolution').insert({
      household_id: alice.householdId, recipe_ingredient_id: ing!.id,
    })
    expect(error, 'une résolution sans aliment ni grammes a été acceptée').not.toBeNull()
  })
})
