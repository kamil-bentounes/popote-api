import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor, bob: Actor
beforeAll(async () => { alice = await makeActor('alice-llm'); bob = await makeActor('bob-llm') })

// Premier jour du mois courant, en UTC. NE PAS utiliser new Date(y, m, 1) :
// en Europe/Paris, toISOString() renverrait le mois précédent.
const month = () => new Date().toISOString().slice(0, 8) + '01'

describe('budget LLM', () => {
  it('décompte la consommation du foyer de son plafond', async () => {
    const a = admin()
    await a.from('household').update({ llm_monthly_cap_eur: 5 }).eq('id', alice.householdId)
    await a.from('llm_usage').insert({
      household_id: alice.householdId, month: month(), kind: 'vision', calls: 10, cost_eur: 1.5,
    })
    const { data, error } = await alice.client.rpc('llm_budget_remaining')
    expect(error).toBeNull()
    expect(Number(data)).toBeCloseTo(3.5, 2)
  })

  it("un foyer ne voit pas la consommation d'un autre", async () => {
    const { data } = await bob.client.from('llm_usage').select('*')
    expect((data ?? []).some(r => r.household_id === alice.householdId)).toBe(false)
  })

  it("la ligne système n'est visible d'aucun foyer", async () => {
    await admin().from('llm_usage').insert({
      household_id: null, month: month(), kind: 'extraction', calls: 5000, cost_eur: 4,
    })
    for (const who of [alice, bob]) {
      const { data } = await who.client.from('llm_usage').select('*').is('household_id', null)
      expect(data ?? [], 'la consommation système ne regarde pas les foyers').toHaveLength(0)
    }
  })

  it('le plafond global décompte exactement la consommation système', async () => {
    const a = admin()
    await a.from('instance_setting')
      .upsert({ key: 'llm_global_monthly_cap_eur', value: { amount: 50 } })
    const { data: before, error: e1 } = await a.rpc('llm_global_budget_remaining')
    expect(e1, 'service_role doit pouvoir appeler cette fonction').toBeNull()

    // ⚠️ Le test doit être idempotent : rejoué sans db:reset, un upsert laisserait
    // la ligne inchangée et l'écart mesuré vaudrait 0. On purge d'abord.
    await a.from('llm_usage').delete()
      .is('household_id', null).eq('month', month()).eq('kind', 'generation')
    const { data: base } = await a.rpc('llm_global_budget_remaining')

    await a.from('llm_usage').insert({
      household_id: null, month: month(), kind: 'generation', calls: 1, cost_eur: 7,
    })
    const { data: after } = await a.rpc('llm_global_budget_remaining')
    expect(Number(base) - Number(after), 'la consommation système doit se décompter du plafond')
      .toBeCloseTo(7, 2)
  })

  it('un foyer ne peut PAS appeler la fonction de budget global', async () => {
    const { error } = await alice.client.rpc('llm_global_budget_remaining')
    expect(error, 'le budget global ne regarde pas les foyers').not.toBeNull()
  })
})
