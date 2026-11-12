/**
 * Ce qu'on met au congélateur sans l'avoir cuisiné.
 *
 * Deux natures, et les confondre coûte cher :
 *
 *  · un PRODUIT sert aux courses — savoir qu'on l'a évite de le racheter ;
 *  · un PLAT est un REPAS — il se mange depuis la semaine et pèse dans les
 *    calories du jour. Rangé à l'inventaire, il disparaîtrait du plan et
 *    compterait pour zéro, ce que D33 interdit précisément.
 *
 * Et dans les deux cas une date de mise au froid, parce que c'est elle qui fait
 * courir les trois mois — pas le jour où l'on a pensé à le saisir.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let moi: Actor

const dans = (mois: number) => {
  const d = new Date()
  d.setMonth(d.getMonth() + mois)
  return d.toISOString()
}

beforeAll(async () => { moi = await makeActor('congelo') })

describe('un plat acheté', () => {
  it('entre en barquettes, une par part, sans session ni recette', async () => {
    const congeleLe = new Date('2026-08-21T12:00:00Z').toISOString()
    const { data, error } = await moi.client.from('portion').insert(
      Array.from({ length: 2 }, () => ({
        household_id: moi.householdId, label: 'PrepMyMeal — poulet curry',
        grams: 350, kcal: 406, protein_g: 32, carb_g: 40, fat_g: 11, fiber_g: 4,
        source: 'achete', location: 'congelateur',
        frozen_at: congeleLe, expires_at: dans(3),
      }))).select()
    expect(error, `refusé : ${error?.message}`).toBeNull()
    expect(data ?? [], 'une part, une ligne').toHaveLength(2)
    expect(data![0].cycle_id, 'une barquette achetée n’a pas de session').toBeNull()
    expect(data![0].recipe_id, 'ni de recette').toBeNull()
    expect(new Date(data![0].frozen_at!).getTime(),
      'la date de mise au froid a été réécrite').toBe(new Date(congeleLe).getTime())
  })

  it('se compte dans la semaine comme n’importe quelle barquette', async () => {
    // C'est tout l'enjeu du choix « plat » plutôt que « produit » : un
    // PrepMyMeal mangé mardi ne doit pas laisser mardi vide.
    const { data: part } = await admin().from('portion').insert({
      household_id: moi.householdId, label: 'Chili acheté', grams: 300, kcal: 520,
      protein_g: 28, carb_g: 50, fat_g: 12, fiber_g: 6,
      source: 'achete', location: 'congelateur',
      frozen_at: new Date().toISOString(), expires_at: dans(3),
    }).select().single()

    const { error } = await moi.client.from('meal_slot').insert({
      household_id: moi.householdId, user_profile_id: moi.userId,
      day: '2026-10-06', meal: 'diner', portion_id: part!.id, state: 'prevu',
    })
    expect(error, `la barquette achetée ne se planifie pas : ${error?.message}`).toBeNull()
  })

  it('ne se réécrit pas une provenance', async () => {
    // Sinon le bilan de la semaine mélangerait ce qu'on a cuisiné et ce qu'on a
    // acheté, sans qu'on puisse plus les distinguer.
    const { data: p } = await admin().from('portion').insert({
      household_id: moi.householdId, label: 'Acheté', grams: 200, kcal: 300,
      protein_g: 10, carb_g: 20, fat_g: 5, fiber_g: 2,
      source: 'achete', location: 'frigo', expires_at: dans(1),
    }).select().single()
    const { error } = await moi.client.from('portion')
      .update({ source: 'session' }).eq('id', p!.id)
    expect(error?.message, 'une barquette a changé de provenance')
      .toMatch(/ne change pas de provenance/)
  })

  it('garde la date imprimée sur l’emballage, et applique D29 sinon', async () => {
    /*
     * ⚠️ `tg_portion_peremption` recalculait `expires_at` à CHAQUE insertion au
     *    congélateur : la date lue sur le paquet était écrasée par « trois
     *    mois » sans un mot. Une règle générale ne doit s'appliquer que là où
     *    personne n'en sait plus qu'elle.
     */
    const dlc = new Date('2027-02-14T12:00:00Z')
    const { data: lue } = await moi.client.from('portion').insert({
      household_id: moi.householdId, label: 'Avec DLC', grams: 200, kcal: 300,
      protein_g: 10, carb_g: 20, fat_g: 5, fiber_g: 2,
      source: 'achete', location: 'congelateur',
      frozen_at: new Date().toISOString(), expires_at: dlc.toISOString(),
    }).select().single()
    expect(new Date(lue!.expires_at!).getTime(),
      'la date imprimée a été écrasée').toBe(dlc.getTime())

    // Sans date donnée, la règle reprend : trois mois après la mise au froid.
    const congeleLe = new Date('2026-07-01T12:00:00Z')
    const { data: sans } = await admin().from('portion').insert({
      household_id: moi.householdId, label: 'Sans DLC', grams: 200, kcal: 300,
      protein_g: 10, carb_g: 20, fat_g: 5, fiber_g: 2,
      source: 'achete', location: 'congelateur', frozen_at: congeleLe.toISOString(),
    }).select().single()
    const attendu = new Date(congeleLe); attendu.setDate(attendu.getDate() + 90)
    expect(new Date(sans!.expires_at!).getTime(),
      'les trois mois ne partent pas de la mise au froid').toBe(attendu.getTime())
  })
})

describe('un produit congelé', () => {
  it('porte sa date de mise au froid et sa péremption', async () => {
    const congeleLe = new Date('2026-09-01T12:00:00Z').toISOString()
    const { data, error } = await moi.client.from('stock_item').insert({
      household_id: moi.householdId, label: 'Petits pois', quantity: 750, unit: 'g',
      location: 'congelateur', frozen_at: congeleLe, expires_at: dans(3),
    }).select().single()
    expect(error, `refusé : ${error?.message}`).toBeNull()
    expect(new Date(data!.frozen_at!).getTime()).toBe(new Date(congeleLe).getTime())
  })

  it('ne porte pas de date de mise au froid ailleurs qu’au congélateur', async () => {
    // Une date de congélation sur une ligne du placard ne veut rien dire, et
    // elle ferait courir une péremption qui n'a pas lieu d'être.
    const { error } = await moi.client.from('stock_item').insert({
      household_id: moi.householdId, label: 'Riz', location: 'placard',
      frozen_at: new Date().toISOString(),
    })
    expect(error, 'un produit du placard a été « congelé »').not.toBeNull()
  })
})

/**
 * Les deux mensonges qu'un ajout manuel pouvait écrire.
 *
 * Ils se ressemblent : dans les deux cas une valeur inventée entre dans un
 * suivi qui, lui, est calculé. Et dans les deux cas rien ne le signale.
 */
describe('ce qu’on refuse d’écrire', () => {
  it('donne quatre jours à un plat mis au FRIGO, pas trois mois', async () => {
    // L'écran n'affiche la péremption qu'au congélateur, mais il l'envoyait
    // quand même — et depuis 0047 la base la respecte. Un plat au frigo héritait
    // des trois mois du congélateur, et Stock affichait « encore 91 jours ».
    const { data } = await moi.client.from('portion').insert({
      household_id: moi.householdId, label: 'Reste de lasagnes', grams: 300, kcal: 450,
      protein_g: 20, carb_g: 40, fat_g: 18, fiber_g: 3,
      source: 'manuel', location: 'frigo',
    }).select().single()
    const jours = (new Date(data!.expires_at!).getTime()
      - new Date(data!.prepared_at!).getTime()) / 864e5
    expect(jours, 'un plat au frigo a reçu autre chose que D29').toBeCloseTo(4, 1)
  })

  it('range un surgelé acheté avec sa date de mise au froid', async () => {
    /*
     * Le chemin PRINCIPAL du garde-manger, ce sont les courses : cocher un
     * article le range tout seul (D49). Le formulaire manuel avait ses dates,
     * ce chemin-là non — un surgelé entrait sans qu'on sache quand, donc sans
     * qu'on puisse jamais dire quand il en sort.
     */
    const { data: cycle } = await admin().from('cycle')
      .insert({ household_id: moi.householdId, week_of: '2030-05-06' }).select().single()
    const { data: article } = await admin().from('shopping_item').insert({
      cycle_id: cycle!.id, household_id: moi.householdId,
      label: 'Petits pois surgelés', aisle: 'Surgelés',
    }).select().single()

    await moi.client.from('shopping_item')
      .update({ checked_at: new Date().toISOString() }).eq('id', article!.id)

    const { data: range } = await admin().from('stock_item')
      .select('location, frozen_at, expires_at').eq('shopping_item_id', article!.id).single()
    expect(range!.location, 'le rayon des surgelés ne mène pas au congélateur')
      .toBe('congelateur')
    expect(range!.frozen_at, 'rangé au froid sans date de mise au froid').not.toBeNull()
    const jours = (new Date(range!.expires_at!).getTime()
      - new Date(range!.frozen_at!).getTime()) / 864e5
    expect(jours, 'trois mois à partir du rangement').toBeCloseTo(90, 1)
  })
})
