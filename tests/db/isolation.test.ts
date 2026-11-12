import { describe, it, expect, beforeAll, beforeEach } from 'vitest'
import { makeActor, makeOrphan, admin, type Actor } from './helpers/db'

let alice: Actor, bob: Actor
beforeAll(async () => { alice = await makeActor('alice'); bob = await makeActor('bob') })

describe('classe C — données de foyer', () => {
  it('un foyer ne voit que son propre household', async () => {
    const { data } = await alice.client.from('household').select('id')
    expect(data?.map(h => h.id)).toEqual([alice.householdId])
  })

  it("un foyer ne voit jamais les cibles d'un autre", async () => {
    // ⚠️ Assertion indispensable : sans elle, si l'amorce échoue, alice voit
    // 0 ligne et le test passe SANS RIEN AVOIR TESTÉ.
    const { error: seed } = await admin().from('nutrition_target').insert({
      user_profile_id: bob.userId,
      kcal: 2400, protein_g: 180, fiber_g: 30, carb_g: 250, fat_g: 70,
    })
    expect(seed, "l'amorce du test a échoué : le test serait vert à vide").toBeNull()

    const { data } = await alice.client
      .from('nutrition_target').select('*').eq('user_profile_id', bob.userId)
    expect(data ?? [], 'fuite entre foyers').toHaveLength(0)
  })

  it('les cibles sont historisées, pas écrasées', async () => {
    for (const kcal of [2000, 2100]) {
      const { error } = await alice.client.from('nutrition_target').insert({
        user_profile_id: alice.userId,
        kcal, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
      })
      expect(error).toBeNull()
    }
    const { data } = await alice.client
      .from('nutrition_target').select('kcal').eq('user_profile_id', alice.userId)
    expect(data!.length, 'une cible qui change ne doit pas effacer le passé')
      .toBeGreaterThanOrEqual(2)
  })

  it('un foyer ne peut pas écrire une cible chez un autre', async () => {
    const { error } = await alice.client.from('nutrition_target').insert({
      user_profile_id: bob.userId,
      kcal: 1, protein_g: 1, fiber_g: 1, carb_g: 1, fat_g: 1,
    })
    expect(error, 'écriture croisée acceptée').not.toBeNull()
  })

  // ↓↓↓ Les trois tests de SUPPRESSION. Sans eux, `for all` laissait un membre
  //     effacer son foyer entier, profils et cibles compris. ↓↓↓
  it('un membre ne peut PAS supprimer son foyer', async () => {
    await alice.client.from('household').delete().eq('id', alice.householdId)
    const { data } = await admin().from('household').select('id').eq('id', alice.householdId)
    expect(data, 'un membre a effacé son foyer et tout ce qui cascade derrière').toHaveLength(1)
  })

  it('un membre ne peut PAS supprimer un profil, pas même le sien', async () => {
    await alice.client.from('user_profile').delete().eq('id', alice.userId)
    const { data } = await admin().from('user_profile').select('id').eq('id', alice.userId)
    expect(data, "supprimer son profil permettrait de s'échapper du foyer").toHaveLength(1)
  })

  it('un membre ne peut PAS supprimer le profil de son colocataire', async () => {
    const a = admin()
    const u = await a.auth.admin.createUser({
      email: `colo-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true })
    const { data: colo } = await a.from('user_profile')
      .insert({ id: u.data.user!.id, household_id: alice.householdId, display_name: 'colo' })
      .select().single()
    await alice.client.from('user_profile').delete().eq('id', colo!.id)
    const { data } = await a.from('user_profile').select('id').eq('id', colo!.id)
    expect(data, "un membre a supprimé le profil d'un autre").toHaveLength(1)
  })

  // ↓↓↓ Portée PERSONNE : le foyer partage la lecture, pas l'écriture. ↓↓↓
  it("un membre ne peut PAS supprimer les cibles d'un autre membre", async () => {
    const a = admin()
    const u = await a.auth.admin.createUser({
      email: `colo2-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true })
    await a.from('user_profile').insert({
      id: u.data.user!.id, household_id: alice.householdId, display_name: 'colo2' })
    const { data: cible, error: seed } = await a.from('nutrition_target').insert({
      user_profile_id: u.data.user!.id,
      kcal: 2400, protein_g: 180, fiber_g: 30, carb_g: 250, fat_g: 70,
    }).select().single()
    expect(seed, "l'amorce a échoué : le test serait vert à vide").toBeNull()

    await alice.client.from('nutrition_target').delete().eq('id', cible!.id)
    const { data } = await a.from('nutrition_target').select('id').eq('id', cible!.id)
    expect(data, "un membre a effacé l'historique d'objectifs d'un autre").toHaveLength(1)
  })

  it('un membre ne peut PAS renommer un autre membre', async () => {
    const a = admin()
    const u = await a.auth.admin.createUser({
      email: `colo3-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true })
    await a.from('user_profile').insert({
      id: u.data.user!.id, household_id: alice.householdId, display_name: 'intact' })

    await alice.client.from('user_profile')
      .update({ display_name: 'renommé de force' }).eq('id', u.data.user!.id)
    const { data } = await a.from('user_profile')
      .select('display_name').eq('id', u.data.user!.id).single()
    expect(data!.display_name, 'un membre a renommé un autre').toBe('intact')
  })

  it('un authentifié SANS profil ne voit aucune donnée de foyer', async () => {
    const { client: orphan } = await makeOrphan()
    for (const t of ['household', 'user_profile', 'nutrition_target', 'invitation']) {
      const { data } = await orphan.from(t).select('*')
      expect(data ?? [], `${t} visible par un orphelin`).toHaveLength(0)
    }
  })
})

const TABLES_A = [
  'food', 'food_yield_factor', 'unit_weight', 'unit_conversion', 'density',
  'default_temperature', 'default_duration', 'typical_quantity',
  'appliance_catalog', 'ingestion_job', 'instance_setting', 'non_action_pattern',
] as const

// ⚠️ Lignes RÉELLEMENT valides. Avec un food_id inexistant, food_yield_factor et
// density échoueraient sur la clé étrangère même sans RLS : le test resterait
// vert alors qu'il ne teste rien.
let foodId: string
beforeAll(async () => {
  const { data } = await admin().from('food')
    .insert({ source: 'ciqual', source_code: `seed-${Date.now()}`, name: 'témoin' })
    .select().single()
  foodId = data!.id
})

const LIGNE_A = (): Record<string, Record<string, unknown>> => ({
  food: { source: 'ciqual', source_code: `pirate-${Date.now()}`, name: 'pirate' },
  food_yield_factor: { food_id: foodId, factor: 1 },
  unit_weight: { label: 'pirate', grams: 1 },
  unit_conversion: { unit_label: `pirate-${Date.now()}`, grams: 1 },
  density: { food_id: foodId, grams_per_ml: 1 },
  default_temperature: { preparation: `pirate-${Date.now()}`, temperature_c: 180 },
  default_duration: { verb: `pirate-${Date.now()}`, base_minutes: 1, load_type: 'actif' },
  typical_quantity: { ciqual_subgroup: `pirate-${Date.now()}`, grams: 1 },
  appliance_catalog: { code: `pirate-${Date.now()}`, label: 'Pirate' },
  ingestion_job: { url: `https://pirate.test/${Date.now()}` },
  instance_setting: { key: `pirate-${Date.now()}`, value: {} },
  non_action_pattern: { pattern: `pirate-${Date.now()}` },
})

describe('classe A — référentiel', () => {
  it('est lisible par tout utilisateur authentifié', async () => {
    for (const t of TABLES_A) {
      const { error } = await alice.client.from(t).select('*').limit(1)
      expect(error, `lecture de ${t}`).toBeNull()
    }
  })

  it("n'est inscriptible par AUCUN utilisateur authentifié, sur les 12 tables", async () => {
    const lignes = LIGNE_A()
    for (const t of TABLES_A) {
      const { error } = await alice.client.from(t).insert(lignes[t])
      expect(error, `${t} accepte une écriture authentifiée`).not.toBeNull()
    }
  })

  it('est inscriptible par le rôle de service', async () => {
    const code = `four-${Date.now()}`
    const { error } = await admin()
      .from('appliance_catalog').insert({ code, label: 'Four' })
    expect(error).toBeNull()
    // ⚠️ On NETTOIE. `appliance_catalog` est du référentiel, lu par l'écran
    //    Plan : sans cela, chaque exécution du test ajoutait un four à la liste
    //    des appareils du foyer. La base locale en comptait déjà quatre.
    await admin().from('appliance_catalog').delete().eq('code', code)
  })
})

describe('classe B — catalogue partagé', () => {
  const TABLES_B = ['recipe', 'recipe_ingredient', 'recipe_step', 'recipe_step_dependency'] as const

  const seedRecipe = async () => {
    const { data } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}`, yield_servings: 4 })
      .select().single()
    return data!
  }

  it('porte la traçabilité sur les quatre tables', async () => {
    for (const t of TABLES_B) {
      const { error } = await alice.client
        .from(t).select('edited_by_household_id, edited_at').limit(1)
      expect(error, `traçabilité manquante sur ${t}`).toBeNull()
    }
  })

  it('est lisible par les deux foyers', async () => {
    const r = await seedRecipe()
    for (const who of [alice, bob]) {
      const { data } = await who.client.from('recipe').select('id').eq('id', r.id)
      expect(data, 'le catalogue est partagé').toHaveLength(1)
    }
  })

  it("REFUSE l'insertion par un utilisateur authentifié", async () => {
    const { error } = await alice.client
      .from('recipe').insert({ source_url: `https://pirate/${Date.now()}` })
    expect(error, 'un foyer peut créer une recette dans le catalogue partagé').not.toBeNull()
  })

  it('REFUSE la suppression par un utilisateur authentifié', async () => {
    const r = await seedRecipe()
    // Sans policy DELETE, PostgREST ne renvoie PAS d'erreur : il supprime 0 ligne.
    await alice.client.from('recipe').delete().eq('id', r.id)
    const { data } = await admin().from('recipe').select('id').eq('id', r.id)
    expect(data, 'la ligne a été supprimée par un foyer').toHaveLength(1)
  })
})

describe('current_household()', () => {
  it('ne provoque pas de récursion de policy', async () => {
    const { data, error } = await alice.client.rpc('current_household')
    expect(error, 'code 42P17 = récursion de policy').toBeNull()
    expect(data).toBe(alice.householdId)
  })

  it('renvoie NULL pour un authentifié sans profil', async () => {
    const { client: orphan } = await makeOrphan()
    const { data } = await orphan.rpc('current_household')
    expect(data).toBeNull()
  })
})

describe('création du premier foyer', () => {
  // ⚠️ Indispensable : makeActor() a déjà créé des foyers dans le beforeAll global,
  // donc le repli `not exists (household)` vaut false et l'instance serait fermée.
  // Sans ce réglage, le test d'évasion passe À VIDE — il resterait vert même si
  // l'on remettait `for all` sur user_profile, soit la régression qu'il interdit.
  beforeAll(async () => {
    await admin().from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: true } })
  })

  /* 0070 REFERME la création dès qu'un foyer existe : c'est ce qui empêche
     quelqu'un arrivé sans son lien d'invitation de se fabriquer un second
     foyer, et donc un couple de finir avec deux budgets séparés. Ces tests-ci
     portent sur le garde « déjà rattaché », pas sur ce verrou-là : on rouvre
     donc avant chacun, sinon le premier d'entre eux referme pour les suivants
     et ils échoueraient tous sur le mauvais motif. */
  beforeEach(async () => {
    await admin().from('instance_setting')
      .update({ value: { enabled: true } }).eq('key', 'allow_household_creation')
  })

  it('un authentifié sans profil peut créer son foyer, une seule fois', async () => {
    const { client: solo } = await makeOrphan()
    const { data, error } = await solo.rpc('create_household', { p_name: 'Chez nous' })
    expect(error).toBeNull()
    expect(data).toBeTruthy()

    const { data: hh } = await solo.rpc('current_household')
    expect(hh).toBe(data)

    const { error: e2 } = await solo.rpc('create_household', { p_name: 'Évasion' })
    expect(e2, 'un utilisateur déjà rattaché ne doit pas pouvoir créer un foyer').not.toBeNull()
  })

  it('ne peut PAS être contournée en supprimant son propre profil', async () => {
    const { client: evade } = await makeOrphan()
    const { data: hh1, error: e1 } = await evade.rpc('create_household', { p_name: 'Premier' })
    expect(e1, "l'amorce a échoué : tout le test dégénérerait en expect(null).toBe(null)").toBeNull()
    expect(hh1).toBeTruthy()
    const { data: me } = await evade.auth.getUser()

    await evade.from('user_profile').delete().eq('id', me.user!.id)
    const { data: still } = await evade.rpc('current_household')
    expect(still, 'le profil a pu être supprimé : évasion possible').toBe(hh1)

    const { error } = await evade.rpc('create_household', { p_name: 'Évasion' })
    expect(error, 'évasion réussie vers un second foyer').not.toBeNull()
    // L'erreur doit venir du garde « déjà rattaché », pas du verrou d'instance :
    // sinon le test ne prouverait rien sur l'absence de policy DELETE.
    expect(String((error as any).message)).toContain('rattaché')
  })

  it("refuse la création quand l'instance est verrouillée", async () => {
    const a = admin()
    await a.from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: false } })
    const { client: tard } = await makeOrphan()
    const { error } = await tard.rpc('create_household', { p_name: 'Trop tard' })
    expect(error, "l'instance est sur invitation : la création doit être refusée").not.toBeNull()
    await a.from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: true } })
  })
})
