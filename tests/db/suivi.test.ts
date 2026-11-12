/**
 * Le suivi, lu depuis la base telle que l'écran la lit (lot 6).
 *
 * Les règles de calcul sont éprouvées sans base dans `src/lib/suivi.test.ts` —
 * un jour non renseigné n'est pas un jour à zéro, le payé ne se mélange pas à
 * l'estimé. Ce qui se vérifie ICI est ce que la base doit garantir :
 *
 *  · le budget du foyer est un budget DE FOYER — personne d'autre ne le lit ;
 *  · les données que le bilan agrège ne fuient pas d'un foyer à l'autre ;
 *  · et le bilan se remplit VRAIMENT tout seul : dresser, cocher, photographier
 *    un ticket suffit à ce que les trois chiffres tombent juste.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'
import { budget, serie } from './front-fige/lib/suivi.ts'
import type { Repas } from './front-fige/lib/suivi.ts'

let alice: Actor
let bob: Actor
let cycle: string
let magasin: string

beforeAll(async () => {
  alice = await makeActor('suivi-alice')
  bob = await makeActor('suivi-bob')
  const { data: c } = await admin().from('cycle')
    .insert({ household_id: alice.householdId, week_of: '2030-03-04' }).select().single()
  cycle = c!.id
  const { data: m } = await admin().from('store')
    .insert({ household_id: alice.householdId, name: 'Suivi', is_default: true })
    .select().single()
  magasin = m!.id
})

describe('le budget des courses', () => {
  it('se pose et se relit', async () => {
    const { error } = await alice.client.from('household')
      .update({ food_budget_eur: 320 }).eq('id', alice.householdId)
    expect(error).toBeNull()
    const { data } = await alice.client.from('household')
      .select('food_budget_eur').eq('id', alice.householdId).single()
    expect(Number(data!.food_budget_eur)).toBe(320)
  })

  it('accepte d’être retiré : ne pas s’en fixer est un choix', async () => {
    const { error } = await alice.client.from('household')
      .update({ food_budget_eur: null }).eq('id', alice.householdId)
    expect(error).toBeNull()
    await alice.client.from('household')
      .update({ food_budget_eur: 320 }).eq('id', alice.householdId)
  })

  it('refuse un budget nul ou négatif', async () => {
    for (const v of [0, -50]) {
      const { error } = await admin().from('household')
        .update({ food_budget_eur: v }).eq('id', alice.householdId)
      expect(error, `un budget de ${v} € a été accepté`).not.toBeNull()
    }
  })

  it('ne se lit pas depuis un autre foyer', async () => {
    const { data } = await bob.client.from('household')
      .select('food_budget_eur').eq('id', alice.householdId)
    expect(data ?? [], 'le budget d’un foyer a fuité').toHaveLength(0)
  })
})

describe('le bilan se remplit tout seul', () => {
  it('dresser, cocher, photographier suffit', async () => {
    // ── Le dimanche : deux barquettes dressées ────────────────────────────
    const parts = []
    for (const [label, kcal, prot] of [['Dahl', 620, 34], ['Poulet rôti', 540, 46]] as const) {
      const { data } = await admin().from('portion').insert({
        household_id: alice.householdId, cycle_id: cycle, label,
        grams: 340, kcal, protein_g: prot, fiber_g: 9, carb_g: 60, fat_g: 18,
      }).select().single()
      parts.push(data!)
    }

    // ── Le lundi : on en mange une ────────────────────────────────────────
    const { error: e1 } = await admin().from('meal_slot').insert({
      household_id: alice.householdId, cycle_id: cycle,
      user_profile_id: alice.userId, day: '2030-03-04', meal: 'diner',
      portion_id: parts[0].id, state: 'mange', eaten_at: new Date().toISOString(),
    })
    expect(e1, "l'amorce a échoué : le test serait vert à vide").toBeNull()

    // ── Le samedi précédent : la liste, puis le ticket ────────────────────
    const { data: article } = await admin().from('shopping_item').insert({
      cycle_id: cycle, household_id: alice.householdId, store_id: magasin,
      label: 'poulet', est_price_eur: 7,
    }).select().single()
    const { data: ticket } = await admin().from('receipt').insert({
      household_id: alice.householdId, store_id: magasin, bought_at: '2030-03-03',
    }).select().single()
    await admin().from('receipt_line').insert({
      receipt_id: ticket!.id, household_id: alice.householdId,
      label: 'FIL PLT', price_eur: 6.49, shopping_item_id: article!.id,
    })

    // ── Ce que l'écran lit ────────────────────────────────────────────────
    const { data: cases } = await alice.client.from('meal_slot')
      .select('day, user_profile_id, state, portion:portion_id(kcal, protein_g)')
      .gte('day', '2030-03-01').lte('day', '2030-03-10')
    const repas: Repas[] = (cases as unknown as {
      day: string; user_profile_id: string; state: Repas['state']
      portion: { kcal: number; protein_g: number } | null
    }[]).map(x => ({
      day: x.day, user_profile_id: x.user_profile_id, state: x.state,
      kcal: Number(x.portion?.kcal ?? 0), protein_g: Number(x.portion?.protein_g ?? 0),
      kcalExtra: 0, proteinExtra: 0,
    }))

    const s = serie(
      ['2030-03-04', '2030-03-05', '2030-03-06'], repas, alice.userId,
      { kcal: 2000, protein: 150 })
    expect(s.jours[0].kcal, 'le repas coché n’est pas remonté').toBe(620)
    expect(s.renseignes, 'un jour vide a été compté comme renseigné').toBe(1)
    expect(s.kcalMoyen, 'les jours vides ont tiré la moyenne vers le bas').toBe(620)
    expect(s.joursKcalTenue).toBe(1)
    expect(s.joursProteineTenue, '34 g ne tiennent pas une cible de 150').toBe(0)

    // Le prix payé est remonté tout seul du ticket sur l'article (lot 5).
    const { data: liste } = await alice.client.from('shopping_item')
      .select('est_price_eur, paid_price_eur').eq('cycle_id', cycle)
    const { data: dressees } = await alice.client.from('portion')
      .select('id').eq('cycle_id', cycle)

    // Le payé vient du TICKET, pas de la somme des articles rapprochés : sinon
    // les lignes qui ne sont sur aucune liste disparaissent du budget.
    const { data: tickets } = await alice.client.from('receipt')
      .select('id, total_eur').eq('id', ticket!.id)
    const { data: lignesTicket } = await alice.client.from('receipt_line')
      .select('price_eur').eq('receipt_id', ticket!.id)
    const payeTicket = tickets![0].total_eur !== null
      ? Number(tickets![0].total_eur)
      : lignesTicket!.reduce((s2, l) => s2 + Number(l.price_eur), 0)

    const b = budget(liste!, payeTicket, dressees!.length, 320)
    expect(b.paye, 'le ticket n’a pas rempli le prix payé').toBe(6.49)
    expect(b.estimeRestant, 'un article payé est resté compté comme estimé').toBe(0)
    expect(b.parPortion).toBe(3.25)
    expect(b.part).toBeCloseTo(6.49 / 320, 4)
  })
})

describe('l’isolation de ce que le bilan agrège', () => {
  it('ne laisse voir ni les repas, ni les barquettes, ni les achats d’un autre', async () => {
    for (const table of ['portion', 'meal_slot', 'shopping_item'] as const) {
      const { data } = await bob.client.from(table)
        .select('household_id').eq('household_id', alice.householdId)
      expect(data ?? [], `fuite de ${table} entre foyers`).toHaveLength(0)
    }
  })

  it('rend un bilan VIDE à un foyer neuf, pas celui du voisin', async () => {
    // Le pire bug possible ici serait silencieux : des chiffres plausibles,
    // mais ceux de quelqu'un d'autre.
    const { data: repas } = await bob.client.from('meal_slot').select('day')
    const { data: parts } = await bob.client.from('portion').select('id')
    expect([...(repas ?? []), ...(parts ?? [])]).toHaveLength(0)
  })
})
