/**
 * Les gestes du frigo (migration 0122) : manger SA part, jeter ou retirer sans laisser un repas pointé sur
 * une part disparue, et deux membres qui mangent la dernière part libre en même temps.
 *
 * Revue du frigo américain : « En manger une maintenant » ignorait `for_user_id` (la part de Thauba
 * pouvait être mangée avec les calories de Thauba), « Jeter » laissait la case du repas pointée sur la
 * part jetée — que « Je l'ai mangé » ressuscitait en « mangée » —, et le geste tenait en trois requêtes.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { admin, makeActor, type Actor } from './helpers/db'
import { attends, commeLui, connexion, suivie } from './helpers/pg'

let kamil: Actor
let thauba: { client: ReturnType<typeof createClient>; userId: string }
const db = admin()

/* « Aujourd'hui » du test : une case est unique par personne, jour et repas, donc chaque test vit un autre jour
   (loin devant : la péremption, elle, se joue sur l'heure vraie). */
let decalage = 0
beforeEach(() => { decalage += 10 })
const jourDans = (n: number) => new Date(Date.UTC(2040, 0, 1) + (decalage + n) * 86_400_000).toISOString().slice(0, 10)
const aujourdhui = () => jourDans(0)
let plat = 0
const nouveauPlat = () => `Plat ${Date.now()}-${++plat}`

beforeAll(async () => {
  kamil = await makeActor('frigo-kamil')
  const email = `frigo-thauba-${Date.now()}@test.local`
  const { data: u, error } = await db.auth.admin.createUser({ email, password: 'test-password-12345', email_confirm: true })
  expect(error).toBeNull()
  const { error: pe } = await db.from('user_profile')
    .insert({ id: u!.user.id, household_id: kamil.householdId, display_name: 'Thauba' })
  expect(pe).toBeNull()
  const client = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
  expect((await client.auth.signInWithPassword({ email, password: 'test-password-12345' })).error).toBeNull()
  thauba = { client, userId: u!.user.id }
})

async function parts(label: string, specs: { pour?: 'kamil' | 'thauba' | null; expire?: number }[]) {
  const { data, error } = await db.from('portion').insert(specs.map(s => ({
    household_id: kamil.householdId, label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
    location: 'frigo', for_user_id: s.pour === 'kamil' ? kamil.userId : s.pour === 'thauba' ? thauba.userId : null,
    expires_at: new Date(Date.now() + (s.expire ?? 2) * 86_400_000).toISOString(),
  }))).select()
  expect(error).toBeNull()
  return data!
}
async function pose(portionId: string, qui: string, jour: string, meal: string) {
  const { data, error } = await db.from('meal_slot').insert({
    household_id: kamil.householdId, user_profile_id: qui, day: jour, meal, portion_id: portionId, state: 'prevu',
  }).select().single()
  expect(error).toBeNull()
  return data!
}
const mange = (c: Actor['client'] | typeof thauba.client, label: string, meal: string, jour = aujourdhui()) =>
  c.rpc('mange_une_part', {
    p_recipe: null, p_label: label, p_location: 'frigo', p_state: 'au_frais',
    p_day: jour, p_meal: meal, p_eaten_at: new Date().toISOString(),
  })
const etatDe = async (id: string) => (await db.from('portion').select('state').eq('id', id).maybeSingle()).data?.state

describe('« En manger une maintenant » : la part de QUI la mange', () => {
  it('la mienne d’abord, puis celle de personne, celle d’un autre en dernier recours', async () => {
    const label = nouveauPlat()
    // Celle de Thauba est la plus pressée, puis celle de personne, puis la mienne : l'ordre de péremption ne décide pas.
    const [deThauba, deTous, demoi] = await parts(label, [{ pour: 'thauba', expire: 1 }, { pour: null, expire: 2 }, { pour: 'kamil', expire: 3 }])
    const a = await mange(kamil.client, label, 'petit_dejeuner')
    expect(a.error).toBeNull()
    expect(a.data.portion_id, 'Kamil a mangé la part d’un autre alors que la sienne était là').toBe(demoi.id)
    const b = await mange(kamil.client, label, 'dejeuner')
    expect(b.data.portion_id, 'puis celle qui est pour tout le monde').toBe(deTous.id)
    const c = await mange(kamil.client, label, 'diner')
    expect(c.data.portion_id, 'celle de Thauba en dernier recours').toBe(deThauba.id)
    for (const p of [demoi, deTous, deThauba]) expect(await etatDe(p.id)).toBe('mangee')
    expect((await mange(kamil.client, label, 'collation')).error?.message).toMatch(/plus de part/)
  })

  it('une part libre avant une réclamée ; la réclamée, le repas qui la réclamait la lâche et on le dit', async () => {
    const label = nouveauPlat()
    const [reclamee, libre] = await parts(label, [{ expire: 1 }, { expire: 3 }])
    const dinerDeThauba = await pose(reclamee.id, thauba.userId, jourDans(2), 'diner')

    const un = await mange(kamil.client, label, 'dejeuner')
    expect(un.data.portion_id, 'une part réclamée prise alors qu’une libre était là').toBe(libre.id)
    expect(un.data.libere).toEqual([])

    const deux = await mange(kamil.client, label, 'diner')
    expect(deux.error).toBeNull()
    expect(deux.data.portion_id).toBe(reclamee.id)
    expect(deux.data.libere).toEqual([{ day: jourDans(2), meal: 'diner', user_profile_id: thauba.userId }])
    const { data: lache } = await db.from('meal_slot').select('portion_id, state').eq('id', dinerDeThauba.id).single()
    expect(lache).toEqual({ portion_id: null, state: 'prevu' })
    const { data: ma } = await db.from('meal_slot').select('state, portion_id, eaten_at')
      .eq('user_profile_id', kamil.userId).eq('day', aujourdhui()).eq('meal', 'diner').single()
    expect(ma!.state).toBe('mange')
    expect(ma!.portion_id).toBe(reclamee.id)
    expect(ma!.eaten_at).not.toBeNull()
  })

  it('une réclamation d’un jour PASSÉ n’est pas une réservation', async () => {
    const label = nouveauPlat()
    const [vieille, neuve] = await parts(label, [{ expire: 1 }, { expire: 3 }])
    await pose(vieille.id, thauba.userId, jourDans(-3), 'diner')
    const r = await mange(kamil.client, label, 'dejeuner')
    expect(r.data.portion_id, 'la vieille réclamation compte encore comme réservée').toBe(vieille.id)
    expect(r.data.libere, 'un repas passé n’est pas « libéré »').toEqual([])
    expect(await etatDe(neuve.id)).toBe('au_frais')
  })

  it('ma case du repas porte déjà une part de ce plat : c’est celle-là', async () => {
    const label = nouveauPlat()
    const [a, b] = await parts(label, [{ expire: 1 }, { expire: 3 }])
    await pose(b.id, kamil.userId, aujourdhui(), 'diner')
    const r = await mange(kamil.client, label, 'diner')
    expect(r.data.portion_id).toBe(b.id)
    expect(await etatDe(a.id)).toBe('au_frais')
  })

  it('un repas déjà noté mangé n’est pas écrasé', async () => {
    const label = nouveauPlat()
    await parts(label, [{}, {}])
    expect((await mange(kamil.client, label, 'diner')).error).toBeNull()
    const encore = await mange(kamil.client, label, 'diner')
    expect(encore.error?.message).toMatch(/déjà noté mangé/)
  })

  it('un plat d’un autre foyer n’existe pas', async () => {
    const autre = await makeActor('frigo-autre')
    const label = nouveauPlat()
    await parts(label, [{}])
    expect((await mange(autre.client, label, 'diner')).error?.message).toMatch(/plus de part/)
  })

  it('DEUX membres, UNE part libre : la seconde est mangée une fois, le second attend puis la trouve prise', async () => {
    const label = nouveauPlat()
    const [seule] = await parts(label, [{}])
    const sql = `select public.mange_une_part(null, $1, 'frigo', 'au_frais', $2::date, 'diner', now()) as r`
    const a = await connexion()
    const b = await connexion()
    try {
      await commeLui(a, kamil.userId)
      const premier = (await a.query(sql, [label, aujourdhui()])).rows[0].r
      expect(premier.portion_id).toBe(seule.id)

      await commeLui(b, thauba.userId)
      const second = suivie(b.query(sql, [label, aujourdhui()]).catch(e => e as Error))
      await attends(500)
      expect(second.fini, 'le second n’a pas attendu le verrou de la part').toBe(false)
      await a.query('commit')
      const r = await second.p
      expect(r, 'la même part a été réservée deux fois').toBeInstanceOf(Error)
      expect((r as Error).message).toMatch(/plus de part/)
    } finally {
      await a.query('rollback').catch(() => {})
      await b.query('rollback').catch(() => {})
      await a.end(); await b.end()
    }
    const { data: cases } = await db.from('meal_slot').select('user_profile_id, state').eq('portion_id', seule.id)
    expect(cases).toEqual([{ user_profile_id: kamil.userId, state: 'mange' }])
  })

  it('DEUX membres, DEUX parts libres : chacun la sienne, jamais la même', async () => {
    const label = nouveauPlat()
    await parts(label, [{}, {}])
    const [x, y] = await Promise.all([mange(kamil.client, label, 'diner'), mange(thauba.client, label, 'diner')])
    expect(x.error).toBeNull()
    expect(y.error).toBeNull()
    expect(x.data.portion_id).not.toBe(y.data.portion_id)
  })
})

describe('jeter ou retirer : les repas lâchent leur part', () => {
  const ecarte = (c: Actor['client'], ids: string[], geste: 'jeter' | 'retirer') =>
    c.rpc('ecarte_des_parts', { p_ids: ids, p_geste: geste, p_day: aujourdhui() })

  it('jeter : la part passe à « jetée » et le repas qui la réclamait la lâche', async () => {
    const [p] = await parts(nouveauPlat(), [{}])
    const repas = await pose(p.id, thauba.userId, jourDans(1), 'diner')
    const r = await ecarte(kamil.client, [p.id], 'jeter')
    expect(r.error).toBeNull()
    expect(r.data).toEqual({ n: 1, libere: [{ day: jourDans(1), meal: 'diner', user_profile_id: thauba.userId }] })
    expect(await etatDe(p.id)).toBe('jetee')
    expect((await db.from('meal_slot').select('portion_id').eq('id', repas.id).single()).data!.portion_id).toBeNull()
  })

  it('une part jetée n’est JAMAIS ressuscitée en « mangée » par une case cochée', async () => {
    const [p] = await parts(nouveauPlat(), [{}])
    const repas = await pose(p.id, kamil.userId, aujourdhui(), 'diner')
    // Le défaut d'avant : la case restait pointée, on jette, puis « Je l'ai mangé ».
    await db.from('portion').update({ state: 'jetee' }).eq('id', p.id)
    const { error } = await db.from('meal_slot').update({ state: 'mange', eaten_at: new Date().toISOString() }).eq('id', repas.id)
    expect(error).toBeNull()
    expect(await etatDe(p.id), 'jetée → mangée : le gaspillage disparaît des comptes').toBe('jetee')
  })

  it('retirer : la part est supprimée (ni mangée, ni jetée) et le repas la lâche', async () => {
    const [a, b] = await parts(nouveauPlat(), [{}, {}])
    const repas = await pose(a.id, kamil.userId, jourDans(2), 'dejeuner')
    const r = await ecarte(kamil.client, [a.id, b.id], 'retirer')
    expect(r.error).toBeNull()
    expect(r.data.n).toBe(2)
    expect(r.data.libere).toHaveLength(1)
    expect(await etatDe(a.id), 'la part retirée existe encore').toBeUndefined()
    expect(await etatDe(b.id)).toBeUndefined()
    const { data: events } = await db.from('portion_event').select('kind').in('portion_id', [a.id, b.id])
    expect(events, 'retirer ne doit rien compter comme jeté').toEqual([])
    expect((await db.from('meal_slot').select('portion_id').eq('id', repas.id).single()).data!.portion_id).toBeNull()
  })

  it('une réclamation d’un jour passé lâche aussi, sans être annoncée', async () => {
    const [p] = await parts(nouveauPlat(), [{}])
    const vieux = await pose(p.id, thauba.userId, jourDans(-2), 'diner')
    const r = await ecarte(kamil.client, [p.id], 'jeter')
    expect(r.data.libere).toEqual([])
    expect((await db.from('meal_slot').select('portion_id').eq('id', vieux.id).single()).data!.portion_id).toBeNull()
  })

  it('refuse les parts d’un autre foyer, un geste inconnu, une liste vide', async () => {
    const autre = await makeActor('frigo-autre-2')
    const [p] = await parts(nouveauPlat(), [{}])
    expect((await ecarte(autre.client, [p.id], 'jeter')).error?.message).toMatch(/plus là/)
    expect(await etatDe(p.id)).toBe('au_frais')
    expect((await ecarte(kamil.client, [p.id], 'manger' as 'jeter')).error).not.toBeNull()
    expect((await ecarte(kamil.client, [], 'jeter')).error).not.toBeNull()
    expect((await ecarte(kamil.client, [p.id], 'jeter')).error).toBeNull()
    // Déjà jetée : plus candidate.
    expect((await ecarte(kamil.client, [p.id], 'retirer')).error?.message).toMatch(/plus là/)
  })
})
