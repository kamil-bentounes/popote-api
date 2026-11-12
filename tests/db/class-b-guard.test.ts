import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => { alice = await makeActor('alice-guard') })

async function seedStep(confidence: number) {
  const a = admin()
  const { data: r } = await a.from('recipe')
    .insert({ source_url: `https://x/${Date.now()}-${Math.random()}`, yield_servings: 4 })
    .select().single()
  const { data: s } = await a.from('recipe_step')
    .insert({ recipe_id: r!.id, ordinal: 1, text: 'Enfourner', duration_min: 25, confidence })
    .select().single()
  return s!
}

describe("garde d'écriture de la classe B", () => {
  it("autorise la correction d'un champ peu sûr ET la trace", async () => {
    const step = await seedStep(0.4)
    const { error } = await alice.client
      .from('recipe_step').update({ duration_min: 30 }).eq('id', step.id)
    expect(error).toBeNull()

    const { data } = await admin().from('recipe_step')
      .select('duration_min, edited_by_household_id, edited_at').eq('id', step.id).single()
    expect(Number(data!.duration_min)).toBe(30)
    expect(data!.edited_by_household_id, 'traçabilité non posée').toBe(alice.householdId)
    expect(data!.edited_at).not.toBeNull()
  })

  it("refuse la modification d'un champ à confiance élevée", async () => {
    const step = await seedStep(0.95)
    const { error } = await alice.client
      .from('recipe_step').update({ duration_min: 999 }).eq('id', step.id)
    expect(error, 'une ligne sûre est modifiable par un foyer').not.toBeNull()
  })

  it('laisse passer le rôle de service quelle que soit la confiance', async () => {
    const step = await seedStep(0.99)
    const { error } = await admin().from('recipe_step').update({ duration_min: 12 }).eq('id', step.id)
    expect(error).toBeNull()
  })

  it("fonctionne sur recipe, qui n'a PAS de colonne confidence", async () => {
    const { data: r } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}` }).select().single()
    const { error } = await alice.client.from('recipe').update({ title: 'corrigé' }).eq('id', r!.id)
    expect(error, 'la garde ne doit pas planter sur une table sans confidence').toBeNull()
    const { data } = await admin().from('recipe')
      .select('edited_by_household_id').eq('id', r!.id).single()
    expect(data!.edited_by_household_id).toBe(alice.householdId)
  })

  it('remplit household_id de nutrition_target automatiquement', async () => {
    const { data, error } = await alice.client.from('nutrition_target').insert({
      user_profile_id: alice.userId,
      kcal: 2000, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
    }).select().single()
    expect(error, 'household_id doit être posé par trigger, pas par le client').toBeNull()
    expect(data!.household_id).toBe(alice.householdId)
  })
})
