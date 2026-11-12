/**
 * Les triggers `security definer` n'écrivent pas chez les autres.
 *
 * Trois failles de la MÊME famille ont été trouvées en une relecture : le
 * ticket qui remplissait la liste d'un autre foyer (0027), la case de repas qui
 * mangeait sa barquette, et le cochage qui réécrivait son ordre de rayons
 * (0028). Toutes les trois par le même chemin :
 *
 *   un trigger `security definer` se fiait à un identifiant fourni par le
 *   client sans vérifier à qui appartenait la ligne visée.
 *
 * La RLS protège la table qui DÉCLENCHE le trigger. Elle ne protège aucune des
 * tables que le trigger touche ensuite. Ces tests sont là pour que la
 * quatrième fois ne passe pas.
 *
 * Tous ont échoué avant leur correctif.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor
let cycleA: string
let cycleB: string
let magasinB: string

async function cycle(a: Actor, semaine: string) {
  const { data, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of: semaine }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!.id as string
}

beforeAll(async () => {
  alice = await makeActor('croise-alice')
  bob = await makeActor('croise-bob')
  cycleA = await cycle(alice, '2032-01-05')
  cycleB = await cycle(bob, '2032-01-12')
  const { data } = await admin().from('store')
    .insert({ household_id: bob.householdId, name: 'Chez Bob' }).select().single()
  magasinB = data!.id
})

describe('manger la barquette d’un autre foyer', () => {
  it('ne consomme pas une part qui n’est pas à soi', async () => {
    // La RLS accepte la case : elle ne regarde que le foyer de la CASE. C'est
    // au trigger de vérifier celui de la BARQUETTE.
    const { data: p } = await admin().from('portion').insert({
      household_id: bob.householdId, cycle_id: cycleB, label: 'Dahl de Bob',
      grams: 340, kcal: 600, protein_g: 30, fiber_g: 9, carb_g: 60, fat_g: 18,
    }).select().single()

    await alice.client.from('meal_slot').insert({
      household_id: alice.householdId, cycle_id: cycleA, user_profile_id: alice.userId,
      day: '2032-01-05', meal: 'diner', portion_id: p!.id,
      state: 'mange', eaten_at: new Date().toISOString(),
    })

    const { data } = await admin().from('portion').select('state').eq('id', p!.id).single()
    expect(data!.state, 'la barquette d’un autre foyer a été mangée').toBe('au_frais')
  })

  it('n’écrit rien dans le journal de l’autre foyer', async () => {
    // Le pire du cas : `tg_portion_journal` signait l'événement du compte
    // d'Alice, dans le journal de Bob, qui ne voit aucune case pour l'expliquer.
    const { data } = await admin().from('portion_event')
      .select('by_user_id').eq('household_id', bob.householdId)
      .eq('by_user_id', alice.userId)
    expect(data ?? [], 'un événement signé d’un autre foyer').toHaveLength(0)
  })
})

describe('l’ordre des rayons', () => {
  it('ne bouge pas chez le foyer propriétaire du magasin', async () => {
    // `aisle_order` est unique sur (store_id, aisle) et son trigger redérive le
    // foyer DEPUIS LE MAGASIN : écrire avec le magasin de Bob écrivait chez Bob.
    await admin().from('aisle_order').insert({
      household_id: bob.householdId, store_id: magasinB, aisle: 'Frais', position: 5,
    })

    // Depuis 0044, la ligne croisée ne se fabrique même plus depuis le client :
    // c'est la première barrière, et c'est la bonne.
    const { error: refus } = await alice.client.from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, store_id: magasinB,
      label: 'sonde', aisle: 'Frais',
    })
    expect(refus?.message, 'un article a désigné le magasin d’un autre foyer')
      .toMatch(/pas au foyer/)

    /*
     * ⚠️ On la pose ET on la coche par le rôle de service.
     *
     *    C'est tout l'objet du test : éprouver la SECONDE barrière, celle qui
     *    doit tenir seule le jour où la première céderait. Cocher depuis le
     *    client se ferait maintenant refuser par la première — le trigger
     *    d'apprentissage ne tournerait jamais, et l'assertion finale
     *    deviendrait vraie sans rien prouver. Un test vert qui n'exécute plus
     *    le code qu'il surveille est pire que pas de test.
     */
    const { data: a } = await admin().from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, store_id: magasinB,
      label: 'sonde', aisle: 'Frais',
    }).select().single()
    const { error: coche } = await admin().from('shopping_item')
      .update({ checked_at: new Date().toISOString() }).eq('id', a!.id)
    expect(coche, `le cochage d'amorce a échoué : ${coche?.message}`).toBeNull()

    // Et l'apprentissage a bien tourné — sinon la suite ne prouverait rien.
    const { data: stock } = await admin().from('stock_item')
      .select('id').eq('shopping_item_id', a!.id)
    expect(stock ?? [], 'le trigger d’apprentissage n’a pas tourné').toHaveLength(1)

    const { data } = await admin().from('aisle_order')
      .select('position').eq('store_id', magasinB).eq('aisle', 'Frais').single()
    expect(Number(data!.position), 'l’ordre des rayons d’un autre foyer a bougé').toBe(5)
  })

  it('apprend normalement dans son propre magasin', async () => {
    // Le correctif ne doit pas casser ce qu'il protège.
    const { data: m } = await admin().from('store')
      .insert({ household_id: alice.householdId, name: 'Chez Alice' }).select().single()
    const { data: a } = await alice.client.from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, store_id: m!.id,
      label: 'yaourt', aisle: 'Frais',
    }).select().single()
    await alice.client.from('shopping_item')
      .update({ checked_at: new Date().toISOString() }).eq('id', a!.id)

    const { data } = await admin().from('aisle_order')
      .select('position').eq('store_id', m!.id).eq('aisle', 'Frais').maybeSingle()
    expect(data, 'l’ordre des rayons ne s’apprend plus du tout').not.toBeNull()
  })
})

describe('un article créé DÉJÀ COCHÉ', () => {
  it('est accepté — c’est le cas « pris dans la foulée »', async () => {
    // Le trigger était `BEFORE INSERT` et insérait dans `stock_item` avec
    // `shopping_item_id = new.id` : la ligne n'existait pas encore, la clé
    // étrangère échouait. Le BEFORE pose désormais le rang, l'AFTER écrit.
    const { data: m } = await admin().from('store')
      .insert({ household_id: alice.householdId, name: 'Foulée' }).select().single()
    const { data, error } = await alice.client.from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, store_id: m!.id,
      label: 'pris dans la foulée', aisle: 'Épicerie',
      checked_at: new Date().toISOString(),
      checked_rank: 1,
    }).select().single()
    expect(error, `refusé : ${error?.message}`).toBeNull()

    // Et il entre bien à l'inventaire, ce qui était tout l'objet du trigger.
    const { data: stock } = await admin().from('stock_item')
      .select('label').eq('shopping_item_id', data!.id)
    expect(stock ?? [], 'l’article n’est pas entré à l’inventaire').toHaveLength(1)
  })
})

/**
 * Ce qu'une ligne DÉSIGNE est au même foyer qu'elle.
 *
 * Quinze colonnes de rattachement se repointaient librement vers le foyer d'à
 * côté. Aucune escalade n'en découlait, parce que chaque consommateur
 * revérifiait le foyer à l'arrivée — mais c'était une protection au point
 * d'usage, pas à la source : le premier consommateur écrit sans la clause
 * rouvrait tout le lot d'un coup.
 */
describe('désigner chez le voisin', () => {
  it('refuse de préempter l’article de courses d’un autre foyer', async () => {
    /*
     * `stock_item.shopping_item_id` porte un index unique GLOBAL, et
     * `tg_shopping_check_apres` insère en `on conflict do nothing`. Poser sa
     * propre ligne sur l'article d'autrui faisait donc taire le remplissage du
     * garde-manger de l'autre : il payait son pain et ne le voyait jamais
     * entrer, sans le moindre message.
     */
    const { data: sien } = await admin().from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, label: 'pain',
    }).select().single()

    const { error } = await bob.client.from('stock_item').insert({
      household_id: bob.householdId, shopping_item_id: sien!.id, label: 'SQUAT',
    })
    expect(error?.message, 'un foyer a préempté l’article d’un autre')
      .toMatch(/pas au foyer/)
  })

  it('refuse une arête de dépendance vers le geste d’un autre foyer', async () => {
    const gestes = await Promise.all([
      admin().from('session_task').insert({
        cycle_id: cycleA, household_id: alice.householdId, label: 'chez Alice',
        duration_min: 2, planned_start_min: 0,
      }).select().single(),
      admin().from('session_task').insert({
        cycle_id: cycleB, household_id: bob.householdId, label: 'chez Bob',
        duration_min: 2, planned_start_min: 0,
      }).select().single(),
    ])

    const { error } = await bob.client.from('session_task_dependency')
      .insert({ task_id: gestes[1].data!.id, depends_on_id: gestes[0].data!.id })
    expect(error?.message, 'une arête a traversé deux foyers').toMatch(/pas au foyer/)
  })

  it('laisse évidemment passer ce qui est à soi', async () => {
    // Le correctif ne doit pas casser ce qu'il protège.
    const { data: sien } = await admin().from('shopping_item').insert({
      cycle_id: cycleA, household_id: alice.householdId, label: 'lait',
    }).select().single()
    const { error } = await alice.client.from('stock_item').insert({
      household_id: alice.householdId, shopping_item_id: sien!.id, label: 'lait',
    })
    expect(error, `refusé à tort : ${error?.message}`).toBeNull()
  })
})
