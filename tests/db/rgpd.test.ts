import { describe, it, expect, beforeAll } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => {
  alice = await makeActor('alice-rgpd')
  const { error } = await alice.client.from('nutrition_target').insert({
    user_profile_id: alice.userId,
    kcal: 2000, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
  })
  expect(error).toBeNull()
})

describe('RGPD', () => {
  it("exporte les données du foyer, et rien d'autre", async () => {
    const { data, error } = await alice.client.rpc('export_my_data')
    expect(error).toBeNull()
    expect(data.household.id).toBe(alice.householdId)
    expect(data.nutrition_targets.length).toBeGreaterThanOrEqual(1)
    expect(data.profiles.every((p: any) => p.household_id === alice.householdId)).toBe(true)
  })

  it("n'oublie aucune table de données de foyer", async () => {
    // Ce test existe pour une raison précise : l'export a déjà pris du retard
    // sur le schéma une fois. Il doit échouer le jour où l'on ajoute une table
    // de classe C sans l'ajouter à `export_my_data`.
    const { data: tables } = await admin().rpc('tables_de_foyer')
    const { data: exporte } = await alice.client.rpc('export_my_data')
    const cles = new Set(Object.keys(exporte))

    // Correspondance table → clé de l'export. Le pluriel est celui du JSON.
    const attendu: Record<string, string> = {
      household: 'household', user_profile: 'profiles',
      nutrition_target: 'nutrition_targets', invitation: 'invitations',
      llm_usage: 'llm_usage', cycle: 'cycles', cycle_recipe: 'cycle_recipes',
      store: 'stores', aisle_order: 'aisle_order', shopping_item: 'shopping_items',
      shopping_trip: 'shopping_trips', shopping_habit: 'shopping_habits',
      session_task: 'session_tasks', session_appliance: 'session_appliances',
      duration_observation: 'duration_observations', portion: 'portions',
      portion_event: 'portion_events', meal_slot: 'meal_slots',
      meal_extra: 'meal_extras', frequent_food: 'frequent_foods',
      stock_item: 'stock_items', recipe: 'recipes',
      session_convive: 'session_convives',
      // Budget, lot 1
      compte: 'comptes', revenu: 'revenus', regle_partage: 'regles_partage',
      // Budget, lot 2
      charge: 'charges', charge_participant: 'charge_participants',
      depense: 'depenses', depense_part: 'depense_parts',
      // Budget, lot 3
      enveloppe: 'enveloppes', poche_epargne: 'poches_epargne',
      releve_annuel: 'releves_annuels',
      poche_poste: 'poche_postes', versement_epargne: 'versements_epargne',
      // Budget refait (0097)
      saisie: 'saisies', facture: 'factures', cloture: 'clotures',
      cloture_choix: 'cloture_choix',
      // L'aide intégrée (0118)
      aide_signalement: 'aide_signalements',
      // Nos aliments (0124)
      aliment: 'aliments',
    }

    const oubliees = (tables as { table_name: string }[])
      .map(t => t.table_name)
      // Ces deux-là n'ont pas de colonne household_id propre : elles suivent
      // leur parent, déjà exporté.
      .filter(t => !['session_task_recipe', 'session_task_dependency'].includes(t))
      .filter(t => !cles.has(attendu[t] ?? t))

    expect(oubliees, 'tables de foyer absentes de l’export').toEqual([])
  })

  it("exporte ses réglages de rappel et ses mails reçus, et SEULEMENT les siens (0127)", async () => {
    /* `rappel_reglage` et `rappel_envoye` portent `user_id`, pas `household_id` : `tables_de_foyer` ne les réclame pas,
       donc le test d'exhaustivité ci-dessus ne les verrait jamais manquer. Celui-ci les nomme. */
    const bob = await makeActor('bob-rgpd-rappels')
    const a = admin()
    /* Dans le MÊME foyer qu'Alice : c'est ce qui rend l'isolement utile à dire. */
    const { error: ep } = await a.from('user_profile').update({ household_id: alice.householdId }).eq('id', bob.userId)
    expect(ep).toBeNull()
    await alice.client.from('rappel_reglage').insert({ user_id: alice.userId, type: 'sortir_du_congelateur', actif: true })
    await bob.client.from('rappel_reglage').insert({ user_id: bob.userId, type: 'barquette_perime', actif: true })
    const envoyes = await a.from('rappel_envoye').insert([
      { user_id: alice.userId, type: 'sortir_du_congelateur', cle: '2026-10-28' },
      { user_id: bob.userId, type: 'barquette_perime', cle: '2026-10-28' },
    ])
    expect(envoyes.error).toBeNull()

    const { data, error } = await alice.client.rpc('export_my_data')
    expect(error).toBeNull()
    expect(data.rappel_reglages.map((r: any) => [r.user_id, r.type, r.actif]))
      .toEqual([[alice.userId, 'sortir_du_congelateur', true]])
    expect(data.rappels_envoyes.map((r: any) => [r.user_id, r.type, r.cle]))
      .toEqual([[alice.userId, 'sortir_du_congelateur', '2026-10-28']])

    /* Le journal des passages n'a rien de personnel : il n'est pas dans l'export. */
    expect(Object.keys(data)).not.toContain('rappel_passe')

    await a.from('rappel_envoye').delete().in('user_id', [alice.userId, bob.userId])
    await a.from('rappel_reglage').delete().in('user_id', [alice.userId, bob.userId])
  })

  it('supprime le compte et ses données en cascade', async () => {
    const victim = await makeActor('victime')
    await victim.client.from('nutrition_target').insert({
      user_profile_id: victim.userId,
      kcal: 1, protein_g: 1, fiber_g: 1, carb_g: 1, fat_g: 1,
    })
    const { error } = await victim.client.rpc('delete_my_account')
    expect(error).toBeNull()

    const a = admin()
    const { data: prof } = await a.from('user_profile').select('id').eq('id', victim.userId)
    expect(prof, 'le profil doit avoir disparu').toHaveLength(0)
    const { data: tg } = await a.from('nutrition_target')
      .select('id').eq('user_profile_id', victim.userId)
    expect(tg, 'les cibles doivent avoir disparu en cascade').toHaveLength(0)
    const { data: u } = await a.auth.admin.getUserById(victim.userId)
    expect(u.user, "le compte d'authentification doit avoir disparu").toBeNull()
  })

  it('supprime le compte MÊME avec des charges communes', async () => {
    /* La fixture ci-dessus n'a aucune charge : un trigger posé sur la
       suppression de `charge_participant` a tué la suppression de compte
       pendant une journée entière sans la faire rougir. La cascade
       `user_profile → charge_participant` retire la ligne du partant de
       chaque charge commune ; c'est le cas NORMAL, pas un cas limite. */
    const victim = await makeActor('victime-commune')
    const { data: c } = await admin().from('charge').insert({
      household_id: victim.householdId, libelle: 'Loyer', montant_cents: 90_000,
      periodicite: 'mensuel', debut: '2026-01-01', commun: true,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: victim.userId,
      household_id: victim.householdId,
    })

    const { error } = await victim.client.rpc('delete_my_account')
    expect(error, `suppression refusée : ${error?.message}`).toBeNull()

    const { data: prof } = await admin().from('user_profile')
      .select('id').eq('id', victim.userId)
    expect(prof, 'le profil doit avoir disparu').toHaveLength(0)
  })
})

describe('supprimer son compte quand on a un compte en banque perso', () => {
  /*
   * Trouvé le 01/10/2026 en relisant la spec du Budget, vrai en prod : un
   * compte `perso` exige un titulaire (`compte_titulaire_coherent`, 0051), et
   * supprimer le profil met `titulaire_id` à null (`on delete set null`). Le
   * droit à l'effacement échouait donc pour tout membre qui avait déclaré son
   * compte — Kamil en a deux, dont un archivé. Aucun test n'en créait.
   */
  it('passe, seul au foyer, avec un compte actif et un archivé', async () => {
    const victim = await makeActor('victime-comptes')
    const { error: ce } = await admin().from('compte').insert([
      { household_id: victim.householdId, nom: 'Mon CA', genre: 'perso', titulaire_id: victim.userId },
      { household_id: victim.householdId, nom: 'Ancien CA', genre: 'perso', titulaire_id: victim.userId,
        archive_le: new Date().toISOString() },
    ])
    expect(ce, `l'amorce a échoué : ${ce?.message}`).toBeNull()

    const { error } = await victim.client.rpc('delete_my_account')
    expect(error, `suppression refusée : ${error?.message}`).toBeNull()
    const { data: u } = await admin().auth.admin.getUserById(victim.userId)
    expect(u.user, 'le compte d’authentification a survécu').toBeNull()
  })

  it('à deux, son compte part et les charges qui y étaient payées restent', async () => {
    const hote = await makeActor('hote-comptes')
    const a = admin()
    const email = `partante-${Date.now()}@test.local`
    const { data: cree } = await a.auth.admin.createUser(
      { email, password: 'test-password-12345', email_confirm: true })
    const partante = cree.user!.id
    await a.from('user_profile').insert({ id: partante, household_id: hote.householdId,
                                          display_name: 'Partante' })
    const client = createClient(process.env.VITE_SUPABASE_URL!,
      process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    await client.auth.signInWithPassword({ email, password: 'test-password-12345' })

    const { data: sien } = await a.from('compte').insert({ household_id: hote.householdId,
      nom: 'Son CA', genre: 'perso', titulaire_id: partante }).select().single()
    const { data: celuiDeLHote } = await a.from('compte').insert({ household_id: hote.householdId,
      nom: 'CA hôte', genre: 'perso', titulaire_id: hote.userId }).select().single()
    const { data: charge } = await a.from('charge').insert({
      household_id: hote.householdId, libelle: 'Forfait', montant_cents: 1_000,
      periodicite: 'mensuel', debut: '2026-01-01', compte_id: sien!.id,
    }).select().single()

    const { error } = await client.rpc('delete_my_account')
    expect(error, `suppression refusée : ${error?.message}`).toBeNull()

    const { data: reste } = await a.from('compte').select('id').eq('household_id', hote.householdId)
    expect(reste!.map(c => c.id), 'le compte de l’hôte est parti avec elle')
      .toEqual([celuiDeLHote!.id])
    const { data: c } = await a.from('charge').select('compte_id').eq('id', charge!.id).single()
    expect(c, 'la charge est partie avec son compte').not.toBeNull()
    expect(c!.compte_id).toBeNull()
  })
})
