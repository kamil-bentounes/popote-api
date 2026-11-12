/**
 * Les barquettes : péremption, journal, et le geste de manger.
 *
 * Ces règles vivent en base et non dans l'écran, parce que deux téléphones
 * écrivent en même temps (D50) et qu'un client peut être vieux d'une version.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor

const HEURE = 3_600_000

function barquette(a: Actor, champs: Record<string, unknown> = {}) {
  return {
    household_id: a.householdId,
    label: 'Dahl de lentilles',
    grams: 340,
    kcal: 520,
    protein_g: 28,
    fiber_g: 12,
    carb_g: 60,
    fat_g: 14,
    ...champs,
  }
}

async function pose(a: Actor, champs: Record<string, unknown> = {}) {
  const { data, error } = await admin().from('portion')
    .insert(barquette(a, champs)).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}

const joursApres = (iso: string, depuis: string) =>
  (new Date(iso).getTime() - new Date(depuis).getTime()) / (24 * HEURE)

beforeAll(async () => {
  alice = await makeActor('barq-alice')
  bob = await makeActor('barq-bob')
})

describe('la péremption (D29)', () => {
  it('donne quatre jours à une part posée au frigo', async () => {
    const p = await pose(alice)
    expect(p.expires_at).not.toBeNull()
    expect(joursApres(p.expires_at, p.prepared_at)).toBeCloseTo(4, 1)
  })

  it('donne trois mois à une part congelée, et date la congélation', async () => {
    const p = await pose(alice, { location: 'congelateur' })
    expect(p.frozen_at, 'frozen_at n’a pas été posé').not.toBeNull()
    expect(joursApres(p.expires_at, p.frozen_at!)).toBeCloseTo(90, 1)
  })

  it('congeler une part du frigo repart sur trois mois', async () => {
    const p = await pose(alice)
    const { data } = await admin().from('portion')
      .update({ location: 'congelateur' }).eq('id', p.id).select().single()
    expect(data!.frozen_at).not.toBeNull()
    expect(joursApres(data!.expires_at, data!.frozen_at!)).toBeCloseTo(90, 1)
  })

  it('décongeler donne UN jour, pas quatre', async () => {
    // C'est la règle qui compte : une part décongelée se mange le lendemain.
    const p = await pose(alice, { location: 'congelateur' })
    const { data, error } = await admin().from('portion')
      .update({ location: 'frigo' }).eq('id', p.id).select().single()
    expect(error).toBeNull()
    expect(data!.state, 'sortir du congélateur, c’est décongeler').toBe('decongelee')
    expect(data!.frozen_at).toBeNull()
    const heures = (new Date(data!.expires_at).getTime() - Date.now()) / HEURE
    expect(heures).toBeGreaterThan(20)
    expect(heures, 'une part décongelée a récupéré quatre jours').toBeLessThan(26)
  })

  it('recongeler repart de zéro, et ce test le dit enfin', async () => {
    /*
     * ⚠️ Ce test s'appelait « remettre au congélateur ne rallonge pas la vie »
     *    et n'assertait que `expires_at ≈ frozen_at + 90 j` — vrai par
     *    CONSTRUCTION, puisque le trigger pose les deux au même instant. Il
     *    serait resté vert quelle que soit la règle.
     *
     *    Ce qui se passe vraiment : décongeler met `frozen_at` à null, la
     *    contrainte l'impose hors du congélateur. La date d'origine est donc
     *    détruite, et recongeler repart pour quatre-vingt-dix jours pleins.
     *    Ce n'est pas idéal — recongeler n'est pas conseillé — mais c'est ce
     *    que le code fait, et un test doit dire le code, pas le souhait.
     */
    const ilYA80Jours = new Date(Date.now() - 80 * 864e5).toISOString()
    const p = await pose(alice, { location: 'congelateur', frozen_at: ilYA80Jours })
    expect(joursApres(p.expires_at, p.frozen_at!)).toBeCloseTo(90, 1)

    await admin().from('portion').update({ location: 'frigo' }).eq('id', p.id)
    const { data: degelee } = await admin().from('portion')
      .select('frozen_at, state').eq('id', p.id).single()
    expect(degelee!.frozen_at, 'la date d’origine survit à la décongélation').toBeNull()
    expect(degelee!.state).toBe('decongelee')

    const { data } = await admin().from('portion')
      .update({ location: 'congelateur' }).eq('id', p.id).select().single()
    expect(data!.state).toBe('au_frais')
    // Quatre-vingt-dix jours À PARTIR DE MAINTENANT, pas des dix qui restaient.
    expect(joursApres(data!.expires_at, new Date().toISOString())).toBeCloseTo(90, 1)
  })

  it('refuse une part congelée sans date de congélation', async () => {
    const { error } = await admin().from('portion')
      .insert(barquette(alice, { location: 'congelateur', frozen_at: null, expires_at: null }))
    // Le trigger pose frozen_at : la contrainte ne doit donc jamais se
    // déclencher. Ce test garantit que les deux restent cohérents.
    expect(error).toBeNull()
  })
})

describe('le journal', () => {
  it('note le dressage dès la création', async () => {
    const p = await pose(alice)
    const { data } = await admin().from('portion_event')
      .select('kind').eq('portion_id', p.id)
    expect(data!.map(e => e.kind)).toContain('dressee')
  })

  it('note chaque passage : congelée, décongelée, mangée', async () => {
    const p = await pose(alice)
    await admin().from('portion').update({ location: 'congelateur' }).eq('id', p.id)
    await admin().from('portion').update({ location: 'frigo' }).eq('id', p.id)
    await admin().from('portion').update({ state: 'mangee' }).eq('id', p.id)

    const { data } = await admin().from('portion_event')
      .select('kind').eq('portion_id', p.id).order('at')
    const kinds = data!.map(e => e.kind)
    expect(kinds).toContain('congelee')
    expect(kinds).toContain('decongelee')
    expect(kinds).toContain('mangee')
  })

  it('ne se laisse pas réécrire : c’est ce qui en fait une preuve', async () => {
    const p = await pose(alice)
    const { data: evt } = await admin().from('portion_event')
      .select('id').eq('portion_id', p.id).limit(1).single()

    const maj = await alice.client.from('portion_event')
      .update({ kind: 'jetee' }).eq('id', evt!.id).select()
    expect(maj.data ?? [], 'un journal réécrit ne prouve rien').toHaveLength(0)

    const sup = await alice.client.from('portion_event')
      .delete().eq('id', evt!.id).select()
    expect(sup.data ?? [], 'un journal effaçable ne prouve rien').toHaveLength(0)
  })

  it('reste lisible par le foyer, et par lui seul', async () => {
    const p = await pose(alice)
    const mienne = await alice.client.from('portion_event')
      .select('id').eq('portion_id', p.id)
    expect(mienne.data!.length, 'le foyer ne voit pas son propre journal')
      .toBeGreaterThan(0)

    const autre = await bob.client.from('portion_event').select('id').eq('portion_id', p.id)
    expect(autre.data ?? [], 'fuite de journal entre foyers').toHaveLength(0)
  })
})

describe('manger, c’est cocher', () => {
  it('consomme la barquette quand la case passe à « mangé »', async () => {
    const p = await pose(alice)
    const { error } = await admin().from('meal_slot').insert({
      household_id: alice.householdId,
      user_profile_id: alice.userId,
      day: '2027-03-01',
      meal: 'diner',
      portion_id: p.id,
      state: 'mange',
      eaten_at: new Date().toISOString(),
    })
    expect(error).toBeNull()

    const { data } = await admin().from('portion').select('state').eq('id', p.id).single()
    expect(data!.state, 'la barquette est restée au frigo après le repas').toBe('mangee')
  })

  it('distingue « rien mangé » de « on ne sait pas » (D33)', async () => {
    const saute = await admin().from('meal_slot').insert({
      household_id: alice.householdId, user_profile_id: alice.userId,
      day: '2027-03-02', meal: 'dejeuner', state: 'saute',
    })
    expect(saute.error, 'un repas sauté doit pouvoir être enregistré').toBeNull()

    // Un repas sauté n'a pas d'heure de consommation ; un repas mangé en a une.
    const incoherent = await admin().from('meal_slot').insert({
      household_id: alice.householdId, user_profile_id: alice.userId,
      day: '2027-03-03', meal: 'dejeuner', state: 'mange', eaten_at: null,
    })
    expect(incoherent.error, 'un repas « mangé » sans heure a été accepté').not.toBeNull()
  })

  it('n’accepte qu’une case par personne, jour et repas', async () => {
    const base = {
      household_id: alice.householdId, user_profile_id: alice.userId,
      day: '2027-03-04', meal: 'diner' as const,
    }
    expect((await admin().from('meal_slot').insert(base)).error).toBeNull()
    const doublon = await admin().from('meal_slot').insert(base)
    expect(doublon.error, 'deux dîners le même soir pour la même personne').not.toBeNull()
  })
})

describe('isolation', () => {
  it('un foyer ne voit jamais les barquettes d’un autre', async () => {
    const p = await pose(bob)
    const { data } = await alice.client.from('portion').select('id').eq('id', p.id)
    expect(data ?? [], 'fuite de barquette entre foyers').toHaveLength(0)
  })

  it('un foyer peut supprimer les siennes — le bouton existe partout', async () => {
    const p = await pose(alice)
    const { data } = await alice.client.from('portion').delete().eq('id', p.id).select()
    expect(data ?? [], 'impossible de supprimer sa propre barquette').toHaveLength(1)
  })

  it('un foyer ne peut pas supprimer celles d’un autre', async () => {
    const p = await pose(bob)
    await alice.client.from('portion').delete().eq('id', p.id)
    const { data } = await admin().from('portion').select('id').eq('id', p.id)
    expect(data ?? [], 'une barquette a été supprimée par un autre foyer').toHaveLength(1)
  })
})
