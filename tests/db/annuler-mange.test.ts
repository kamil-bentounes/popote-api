/**
 * Annuler « Je l'ai mangé » (migration 0129) : `annule_mange` remet MA case à « prévu », efface l'heure, et rend la part
 * là où elle était (frigo ou congélateur). Jamais la case de l'autre membre, jamais `meal_extra`, jamais deux fois.
 *
 * Ce fichier ne touche qu'à ses propres foyers : il ne remet jamais la base à zéro.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { readFileSync } from 'node:fs'
import pg from 'pg'
import { admin, makeActor, makeOrphan, type Actor } from './helpers/db'
import { bilanDuJour } from './front-fige/lib/semaine.ts'

let kamil: Actor
let autre: Actor
let lea: { client: ReturnType<typeof createClient>; userId: string }
const db = admin()

const parisAujourdhui = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Paris' })
const jourDans = (n: number) => new Date(Date.parse(`${parisAujourdhui()}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10)
const aujourdhui = () => jourDans(0)

let plat = 0
const nouveauPlat = () => `Annuler ${Date.now()}-${++plat}`

beforeAll(async () => {
  kamil = await makeActor('annule-kamil')
  autre = await makeActor('annule-autre')
  const email = `annule-lea-${Date.now()}@test.local`
  const { data: u, error } = await db.auth.admin.createUser({ email, password: 'test-password-12345', email_confirm: true })
  expect(error).toBeNull()
  expect((await db.from('user_profile').insert({ id: u!.user.id, household_id: kamil.householdId, display_name: 'Léa' })).error).toBeNull()
  const client = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
  expect((await client.auth.signInWithPassword({ email, password: 'test-password-12345' })).error).toBeNull()
  lea = { client, userId: u!.user.id }
})
beforeEach(async () => {
  expect((await db.from('meal_slot').delete().eq('household_id', kamil.householdId)).error).toBeNull()
})

async function parts(label: string, n: number, o: { lieu?: 'frigo' | 'congelateur'; etat?: string } = {}) {
  const froid = o.lieu === 'congelateur'
  const { data, error } = await db.from('portion').insert(Array.from({ length: n }, () => ({
    household_id: kamil.householdId, label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
    location: o.lieu ?? 'frigo', state: o.etat ?? 'au_frais',
    frozen_at: froid ? new Date().toISOString() : null,
    expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
  }))).select()
  expect(error).toBeNull()
  return data!
}
/** Une part DÉJÀ « mangee » à l'insertion : l'état d'avant n'est pas connu (c'est le cas des parts mangées avant 0129). */
async function partDejaMangee(label: string, o: { lieu?: 'frigo' | 'congelateur' } = {}) {
  const froid = o.lieu === 'congelateur'
  const { data, error } = await db.from('portion').insert({
    household_id: kamil.householdId, label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
    location: o.lieu ?? 'frigo', state: 'mangee', frozen_at: froid ? new Date().toISOString() : null,
    expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
  }).select().single()
  expect(error).toBeNull()
  return data!
}
const caseMangee = async (qui: string, jour: string, meal: string, portionId: string | null) => {
  const { data, error } = await db.from('meal_slot').insert({
    household_id: kamil.householdId, user_profile_id: qui, day: jour, meal, portion_id: portionId, state: 'mange', eaten_at: new Date().toISOString(),
  }).select().single()
  expect(error).toBeNull()
  return data!
}
const lePlat = (label: string, lieu = 'frigo', etat = 'au_frais') => ({ type: 'plat', recipe_id: null, label, location: lieu, state: etat })
const pose = (c: Actor, jour: string, meal: string, choix: object) =>
  c.client.rpc('choisir_un_repas', { p_day: jour, p_meal: meal, p_users: [c.userId], p_today: aujourdhui(), p_choix: choix })
/** « Je l'ai mangé » comme l'écran : `mange_une_part` pour un plat. */
const mange = (c: { rpc: Actor['client']['rpc'] }, label: string, jour: string, meal: string, lieu = 'frigo', etat = 'au_frais') =>
  c.rpc('mange_une_part', {
    p_recipe: null as unknown as string, p_label: label, p_location: lieu, p_state: etat,
    p_day: jour, p_meal: meal, p_eaten_at: new Date().toISOString(),
  })
const annule = (c: Actor['client'] | typeof lea.client, id: string) => c.rpc('annule_mange', { p_case: id })
const caseDe = async (qui: string, jour: string, meal: string) =>
  (await db.from('meal_slot').select('*').eq('user_profile_id', qui).eq('day', jour).eq('meal', meal).maybeSingle()).data
const part = async (id: string) => (await db.from('portion').select('*').eq('id', id).single()).data!
const auFrigo = async (label: string) =>
  (await db.from('portion').select('id', { count: 'exact', head: true }).eq('label', label).eq('location', 'frigo').in('state', ['au_frais', 'decongelee'])).count!

describe('annuler « mangé »', () => {
  it('ma case repasse à prévu, l’heure s’efface, la part revient au frigo (5 parts redeviennent 6)', async () => {
    const label = nouveauPlat()
    await parts(label, 6)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    expect(await auFrigo(label)).toBe(5)
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect(c.state).toBe('mange')
    const r = await annule(kamil.client, c.id)
    expect(r.error).toBeNull()
    expect(r.data).toMatchObject({ rendue: true, location: 'frigo', state: 'au_frais' })
    const apres = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect(apres.state).toBe('prevu')
    expect(apres.eaten_at).toBeNull()
    expect(apres.portion_id).toBe(c.portion_id)
    expect(await auFrigo(label)).toBe(6)
    const { data: journal } = await db.from('portion_event').select('kind').eq('portion_id', c.portion_id!).order('at')
    expect(journal!.map(e => e.kind).slice(-2)).toEqual(['mangee', 'remise'])
  })

  it('une part qui venait du congélateur y retourne, au même état', async () => {
    const label = nouveauPlat()
    const [p] = await parts(label, 1, { lieu: 'congelateur' })
    expect((await mange(kamil.client, label, aujourdhui(), 'diner', 'congelateur')).error).toBeNull()
    expect((await part(p.id)).state).toBe('mangee')
    const c = (await caseDe(kamil.userId, aujourdhui(), 'diner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    const apres = await part(p.id)
    expect(apres).toMatchObject({ state: 'au_frais', location: 'congelateur' })
    expect(apres.frozen_at).not.toBeNull()
    expect(apres.etat_avant_mangee).toBeNull()
  })

  it('une part décongelée revient décongelée, pas « au frais » ; et pour une part mangée avant 0129, on la déduit du journal', async () => {
    const label = nouveauPlat()
    const [p, q] = await parts(label, 2, { etat: 'decongelee' })
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner', 'frigo', 'decongelee')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect((await part(c.portion_id!)).state).toBe('decongelee')
    // Une part mangée « avant 0129 » : pas d'état d'avant. Congelée puis décongelée (événement au journal) : décongelée.
    const vieille = await partDejaMangee(label)
    await db.from('portion_event').insert({ portion_id: vieille.id, household_id: kamil.householdId, kind: 'decongelee' })
    expect(vieille.etat_avant_mangee).toBeNull()
    const s = await caseMangee(kamil.userId, jourDans(-2), 'diner', vieille.id)
    expect((await annule(kamil.client, s.id)).error).toBeNull()
    expect((await part(vieille.id)).state).toBe('decongelee')
    expect(p.id).not.toBe(q.id)
  })

  it('une part mangée au frigo, jamais congelée et sans état d’avant, revient « au frais »', async () => {
    const p = await partDejaMangee(nouveauPlat())
    const s = await caseMangee(kamil.userId, aujourdhui(), 'diner', p.id)
    expect((await annule(kamil.client, s.id)).error).toBeNull()
    expect((await part(p.id)).state).toBe('au_frais')
  })

  it('le double appui : la case déjà prévue ne rend pas deux fois la part', async () => {
    const label = nouveauPlat()
    await parts(label, 3)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect(await auFrigo(label)).toBe(3)
    // On remange une AUTRE case avec une autre part, puis un second appui sur l'ancienne annulation : rien ne bouge.
    expect((await mange(kamil.client, label, aujourdhui(), 'diner')).error).toBeNull()
    expect(await auFrigo(label)).toBe(2)
    const encore = await annule(kamil.client, c.id)
    expect(encore.error?.message).toMatch(/n’est pas noté mangé/)
    expect(await auFrigo(label)).toBe(2)
  })

  it('en parallèle : deux appuis simultanés, une seule part rendue', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const [a, b] = await Promise.all([annule(kamil.client, c.id), annule(kamil.client, c.id)])
    expect([a.error, b.error].filter(Boolean)).toHaveLength(1)
    expect(await auFrigo(label)).toBe(2)
  })

  it('une case pas mangée est refusée (prévue, sautée) ; une case inconnue aussi', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await pose(kamil, aujourdhui(), 'diner', lePlat(label))).error).toBeNull()
    const prevue = (await caseDe(kamil.userId, aujourdhui(), 'diner'))!
    expect((await annule(kamil.client, prevue.id)).error?.message).toMatch(/n’est pas noté mangé/)
    expect((await pose(kamil, aujourdhui(), 'collation', { type: 'saute' })).error).toBeNull()
    const sautee = (await caseDe(kamil.userId, aujourdhui(), 'collation'))!
    expect((await annule(kamil.client, sautee.id)).error?.message).toMatch(/n’est pas noté mangé/)
    expect((await annule(kamil.client, crypto.randomUUID())).error?.message).toMatch(/pas dans ton foyer/)
  })

  it('ma case seulement : l’autre membre ne peut pas annuler la mienne, et la sienne ne bouge pas quand j’annule la mienne', async () => {
    const label = nouveauPlat()
    await parts(label, 4)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    expect((await mange(lea.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    expect(await auFrigo(label)).toBe(2)
    const maCase = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const laSienne = (await caseDe(lea.userId, aujourdhui(), 'dejeuner'))!
    const refus = await annule(lea.client, maCase.id)
    expect(refus.error?.message).toMatch(/Ce n’est pas ton repas/)
    expect((await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!.state).toBe('mange')
    expect(await auFrigo(label)).toBe(2)
    expect((await annule(kamil.client, maCase.id)).error).toBeNull()
    const sienne = (await caseDe(lea.userId, aujourdhui(), 'dejeuner'))!
    expect(sienne.state).toBe('mange')
    expect(sienne.eaten_at).toBe(laSienne.eaten_at)
    expect((await part(laSienne.portion_id!)).state).toBe('mangee')
    expect(await auFrigo(label)).toBe(3)
  })

  it('un étranger au foyer est refusé, et rien ne bouge', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const r = await annule(autre.client, c.id)
    expect(r.error?.message).toMatch(/pas dans ton foyer/)
    expect((await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!.state).toBe('mange')
    expect(await auFrigo(label)).toBe(1)
  })

  it('un jour passé est accepté', async () => {
    const label = nouveauPlat()
    await parts(label, 3)
    expect((await pose(kamil, jourDans(-1), 'diner', lePlat(label))).error).toBeNull()
    const c = (await caseDe(kamil.userId, jourDans(-1), 'diner'))!
    expect(c.state).toBe('mange')
    expect(await auFrigo(label)).toBe(2)
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect(await auFrigo(label)).toBe(3)
    const apres = (await caseDe(kamil.userId, jourDans(-1), 'diner'))!
    expect(apres).toMatchObject({ state: 'prevu', eaten_at: null })
  })

  it('une part jetée depuis ne ressuscite pas', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    await db.from('portion').update({ state: 'jetee' }).eq('id', c.portion_id!)
    const r = await annule(kamil.client, c.id)
    expect(r.error).toBeNull()
    expect(r.data).toMatchObject({ rendue: false })
    expect((await part(c.portion_id!)).state).toBe('jetee')
    expect((await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!.state).toBe('prevu')
  })

  it('le meal_extra n’est pas touché', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const { data: e, error } = await db.from('meal_extra').insert({
      household_id: kamil.householdId, meal_slot_id: c.id, label: 'Chocolat', kcal: 55, protein_g: 1, planifie: false,
    }).select().single()
    expect(error).toBeNull()
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    const { data: apres } = await db.from('meal_extra').select('*').eq('meal_slot_id', c.id)
    expect(apres).toHaveLength(1)
    expect(apres![0]).toMatchObject({ id: e!.id, label: 'Chocolat', kcal: 55, planifie: false })
  })

  it('« autre chose » sans barquette : la case repasse seulement à prévu', async () => {
    const repere = { type: 'repere', label: 'Sandwich', kcal: 450, protein_g: 20, fiber_g: 3, carb_g: 50, fat_g: 15 }
    expect((await pose(kamil, aujourdhui(), 'dejeuner', repere)).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    await db.from('meal_slot').update({ state: 'mange', eaten_at: new Date().toISOString() }).eq('id', c.id)
    const r = await annule(kamil.client, c.id)
    expect(r.error).toBeNull()
    expect(r.data).toMatchObject({ portion_id: null, rendue: false })
    const apres = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect(apres).toMatchObject({ state: 'prevu', eaten_at: null, portion_id: null })
    // Les extras SONT le repas : la ligne, ses kcal et son libellé restent, mais elle redevient « planifiée ».
    const { data: extras } = await db.from('meal_extra').select('label, kcal, planifie').eq('meal_slot_id', c.id)
    expect(extras).toMatchObject([{ label: 'Sandwich', kcal: 450, planifie: true }])
  })

  it('le bilan ne compte plus le repas jusqu’à ce qu’il soit de nouveau noté', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const lire = async () => {
      const { data } = await db.from('meal_slot').select('*, portion:portion_id(kcal, protein_g), extras:meal_extra(kcal, protein_g, planifie)')
        .eq('user_profile_id', kamil.userId).eq('day', aujourdhui())
      return bilanDuJour(data as never, kamil.userId, aujourdhui())
    }
    expect(await lire()).toMatchObject({ kcal: 600, proteinG: 40, renseignes: 1 })
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect(await lire()).toMatchObject({ kcal: 0, proteinG: 0, renseignes: 0 })
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    expect(await lire()).toMatchObject({ kcal: 600, proteinG: 40, renseignes: 1 })
  })

  it('on peut le remanger après l’avoir annulé : la même part est reprise', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    const r = await mange(kamil.client, label, aujourdhui(), 'dejeuner')
    expect(r.error).toBeNull()
    expect(r.data.portion_id).toBe(c.portion_id)
    expect((await part(c.portion_id!)).state).toBe('mangee')
  })
})

describe('annuler « mangé » : ce que la base garde', () => {
  it('une part mangée par DEUX cases : annuler la mienne ne rend rien, annuler la seconde la rend', async () => {
    const label = nouveauPlat()
    const [p] = await parts(label, 1)
    const a = await caseMangee(kamil.userId, aujourdhui(), 'dejeuner', p.id)
    const b = await caseMangee(lea.userId, aujourdhui(), 'dejeuner', p.id)
    await db.from('portion').update({ state: 'mangee' }).eq('id', p.id)
    const r1 = await annule(kamil.client, a.id)
    expect(r1.error).toBeNull()
    expect(r1.data).toMatchObject({ rendue: false })
    expect((await part(p.id)).state, 'l’autre personne l’a notée : elle reste mangée').toBe('mangee')
    expect((await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!.state).toBe('prevu')
    expect((await caseDe(lea.userId, aujourdhui(), 'dejeuner'))!.state).toBe('mange')
    const r2 = await annule(lea.client, b.id)
    expect(r2.data).toMatchObject({ rendue: true, state: 'au_frais' })
    expect((await part(p.id)).state).toBe('au_frais')
  })

  it('une part déplacée entre-temps revient là où elle est maintenant, avec son état de ce lieu', async () => {
    const label = nouveauPlat()
    const [p] = await parts(label, 1, { etat: 'decongelee' })
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner', 'frigo', 'decongelee')).error).toBeNull()
    expect((await part(p.id)).etat_avant_mangee).toBe('decongelee')
    // Remise au congélateur depuis la fiche du frigo : une part du congélateur est toujours « au frais », jamais « décongelée ».
    const { error } = await db.from('portion').update({ location: 'congelateur', frozen_at: new Date().toISOString() }).eq('id', p.id)
    expect(error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const r = await annule(kamil.client, c.id)
    expect(r.error).toBeNull()
    expect(r.data).toMatchObject({ rendue: true, location: 'congelateur', state: 'au_frais' })
    expect(await part(p.id)).toMatchObject({ state: 'au_frais', location: 'congelateur' })
  })

  it('une part décongelée rendue garde sa date limite', async () => {
    const label = nouveauPlat()
    const [p] = await parts(label, 1, { etat: 'decongelee' })
    const limite = (await part(p.id)).expires_at
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner', 'frigo', 'decongelee')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    const apres = await part(p.id)
    expect(apres.state).toBe('decongelee')
    expect(new Date(apres.expires_at).getTime()).toBe(new Date(limite).getTime())
  })

  it('une part supprimée entre-temps : la case repasse à prévu, sans barquette, et rien n’est rendu', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    await db.from('portion').delete().eq('id', c.portion_id!)
    const r = await annule(kamil.client, c.id)
    expect(r.error).toBeNull()
    expect(r.data).toMatchObject({ portion_id: null, rendue: false })
    expect(await caseDe(kamil.userId, aujourdhui(), 'dejeuner')).toMatchObject({ state: 'prevu', eaten_at: null, portion_id: null })
  })

  it('sans session (anon) : refusé ; sans foyer : refusé', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    const anon = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    const r = await annule(anon, c.id)
    expect(r.error?.message).toMatch(/permission denied|not authorized|JWT/i)
    const orphelin = await makeOrphan()
    const r2 = await annule(orphelin.client as unknown as Actor['client'], c.id)
    expect(r2.error?.message).toMatch(/Aucun foyer/)
    expect((await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!.state).toBe('mange')
  })

  it('la colonne « état d’avant » n’est pas écrivable par un client : ni à l’insertion, ni à la mise à jour', async () => {
    const label = nouveauPlat()
    const base = {
      household_id: kamil.householdId, label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
      expires_at: new Date(Date.now() + 30 * 86_400_000).toISOString(),
    }
    const ins = await kamil.client.from('portion').insert({ ...base, etat_avant_mangee: 'decongelee' }).select().single()
    expect(ins.error).toBeNull()
    expect(ins.data!.etat_avant_mangee, 'à l’insertion').toBeNull()
    const maj = await kamil.client.from('portion').update({ etat_avant_mangee: 'decongelee' }).eq('id', ins.data!.id).select().single()
    expect(maj.error).toBeNull()
    expect(maj.data!.etat_avant_mangee, 'sur une part au frais').toBeNull()
    // Sur une part mangée : la valeur posée par le passage à « mangee » ne bouge pas, et la rendre ne dépend pas d'un client.
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await part(c.portion_id!)).etat_avant_mangee).toBe('au_frais')
    const maj2 = await kamil.client.from('portion').update({ etat_avant_mangee: 'decongelee' }).eq('id', c.portion_id!).select().single()
    expect(maj2.error).toBeNull()
    expect(maj2.data!.etat_avant_mangee).toBe('au_frais')
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect(await part(c.portion_id!)).toMatchObject({ state: 'au_frais', etat_avant_mangee: null })
  })

  it('la migration rejouée deux fois de suite ne produit aucune erreur', async () => {
    const sql = readFileSync('supabase/migrations/0129_annuler_mange.sql', 'utf8')
    const c = new pg.Client({
      connectionString: process.env.SUPABASE_ADMIN_DB_URL ?? 'postgresql://supabase_admin:postgres@127.0.0.1:54322/postgres',
    })
    await c.connect()
    try {
      await c.query(sql)
      await c.query(sql)
    } finally { await c.end() }
    // Et elle marche toujours.
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const cs = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await annule(kamil.client, cs.id)).error).toBeNull()
  })
})

describe('annuler « autre chose » : le bilan ne compte plus le repas, aujourd’hui, sur un jour passé, ni le lendemain', () => {
  const repere = { type: 'repere', label: 'Restaurant', kcal: 900, protein_g: 35, fiber_g: 3, carb_g: 90, fat_g: 40 }
  const bilan = async (jour: string) => {
    const { data } = await db.from('meal_slot').select('*, portion:portion_id(kcal, protein_g), extras:meal_extra(kcal, protein_g, planifie)')
      .eq('user_profile_id', kamil.userId).eq('day', jour)
    return bilanDuJour(data as never, kamil.userId, jour)
  }

  it('aujourd’hui : choisi (planifié), mangé, annulé : 0 ; de nouveau mangé : 900', async () => {
    expect((await pose(kamil, aujourdhui(), 'dejeuner', repere)).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    expect((await bilan(aujourdhui())).kcal, 'choisi, pas mangé').toBe(0)
    await db.from('meal_slot').update({ state: 'mange', eaten_at: new Date().toISOString() }).eq('id', c.id)
    expect((await bilan(aujourdhui())).kcal).toBe(900)
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect(await bilan(aujourdhui())).toMatchObject({ kcal: 0, proteinG: 0, renseignes: 0 })
    await db.from('meal_slot').update({ state: 'mange', eaten_at: new Date().toISOString() }).eq('id', c.id)
    expect((await bilan(aujourdhui())).kcal).toBe(900)
  })

  it('un jour passé : noté par la feuille (mangé, extra « noté après coup »), annulé : le repas ne compte plus', async () => {
    const hier = jourDans(-1)
    expect((await pose(kamil, hier, 'diner', repere)).error).toBeNull()
    const c = (await caseDe(kamil.userId, hier, 'diner'))!
    expect(c.state).toBe('mange')
    expect((await db.from('meal_extra').select('planifie').eq('meal_slot_id', c.id)).data).toEqual([{ planifie: false }])
    expect((await bilan(hier)).kcal).toBe(900)
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect((await db.from('meal_extra').select('planifie').eq('meal_slot_id', c.id)).data, 'redevenu planifié').toEqual([{ planifie: true }])
    expect(await bilan(hier)).toMatchObject({ kcal: 0, proteinG: 0, renseignes: 0, prevus: 1 })
    // « Je l'ai mangé » sur ce jour passé le compte de nouveau.
    await db.from('meal_slot').update({ state: 'mange', eaten_at: new Date().toISOString() }).eq('id', c.id)
    expect((await bilan(hier)).kcal).toBe(900)
  })

  it('le lendemain : une annulation d’hier ou d’aujourd’hui ne recompte pas, quel que soit le jour où on lit', async () => {
    const hier = jourDans(-1)
    expect((await pose(kamil, hier, 'dejeuner', repere)).error).toBeNull()
    const c = (await caseDe(kamil.userId, hier, 'dejeuner'))!
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    // Le bilan ne regarde plus l'heure qu'il est : la même case donne le même zéro, aujourd'hui comme dans une semaine.
    const { data } = await db.from('meal_slot').select('*, portion:portion_id(kcal, protein_g), extras:meal_extra(kcal, protein_g, planifie)').eq('id', c.id)
    for (const jourLu of [hier, aujourdhui(), jourDans(7)]) {
      expect(bilanDuJour(data as never, kamil.userId, hier), `lu le ${jourLu}`).toMatchObject({ kcal: 0, proteinG: 0 })
    }
  })

  it('un plat annulé garde ses « en plus » comptés : ce sont des notes après coup, pas le repas', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await mange(kamil.client, label, aujourdhui(), 'dejeuner')).error).toBeNull()
    const c = (await caseDe(kamil.userId, aujourdhui(), 'dejeuner'))!
    await db.from('meal_extra').insert({ household_id: kamil.householdId, meal_slot_id: c.id, label: 'Chocolat', kcal: 55, protein_g: 1, planifie: false })
    expect((await annule(kamil.client, c.id)).error).toBeNull()
    expect((await db.from('meal_extra').select('planifie').eq('meal_slot_id', c.id)).data).toEqual([{ planifie: false }])
    expect((await bilan(aujourdhui())).kcal).toBe(55)
  })
})
