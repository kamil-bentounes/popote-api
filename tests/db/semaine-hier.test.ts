/**
 * La semaine remonte (migration 0128) : on note hier. `choisir_un_repas` accepte un jour PASSÉ, jusqu'à sept jours en
 * arrière : ce qu'on y choisit est MANGÉ (la barquette sort du stock), un extra n'y est pas « planifié », « sauter »
 * reste « sauté ». Et `meal_extra.aliment_id` : l'aliment à nous dont l'extra est une copie (jamais celui d'un autre
 * foyer, et retirer l'aliment laisse la ligne).
 *
 * Ce fichier ne touche qu'à ses propres foyers : il ne remet jamais la base à zéro.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let kamil: Actor
let autre: Actor
const db = admin()

const parisAujourdhui = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Paris' })
const jourDans = (n: number) => new Date(Date.parse(`${parisAujourdhui()}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10)
const aujourdhui = () => jourDans(0)
const HIER = () => jourDans(-1)

let plat = 0
const nouveauPlat = () => `Hier ${Date.now()}-${++plat}`

beforeAll(async () => {
  kamil = await makeActor('hier-kamil')
  autre = await makeActor('hier-autre')
})
beforeEach(async () => {
  expect((await db.from('meal_slot').delete().eq('household_id', kamil.householdId)).error).toBeNull()
})

async function parts(label: string, n: number, o: { lieu?: 'frigo' | 'congelateur'; expire?: number } = {}, foyer = kamil.householdId) {
  const froid = o.lieu === 'congelateur'
  const { data, error } = await db.from('portion').insert(Array.from({ length: n }, () => ({
    household_id: foyer, label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
    location: o.lieu ?? 'frigo', state: 'au_frais',
    frozen_at: froid ? new Date().toISOString() : null,
    expires_at: new Date(Date.now() + (o.expire ?? 30) * 86_400_000).toISOString(),
  }))).select()
  expect(error).toBeNull()
  return data!
}
const lePlat = (label: string, lieu = 'frigo') => ({ type: 'plat', recipe_id: null, label, location: lieu, state: 'au_frais' })
const choisit = (jour: string, meal: string, choix: object, c: Actor = kamil) =>
  c.client.rpc('choisir_un_repas', { p_day: jour, p_meal: meal, p_users: [c.userId], p_today: aujourdhui(), p_choix: choix })
const caseDe = async (jour: string, meal: string) =>
  (await db.from('meal_slot').select('*').eq('user_profile_id', kamil.userId).eq('day', jour).eq('meal', meal).maybeSingle()).data
const extrasDe = async (slotId: string) => (await db.from('meal_extra').select('*').eq('meal_slot_id', slotId)).data!
const etat = async (id: string) => (await db.from('portion').select('state').eq('id', id).single()).data!.state
async function unAliment(foyer = kamil.householdId, label = `Skyr ${Date.now()}-${++plat}`) {
  const { data, error } = await db.from('aliment').insert({
    household_id: foyer, label, kcal_100g: 64, protein_100g: 9.5, carb_100g: 6.1, fat_100g: 0.2, unite: 'pot', unite_g: 150,
  }).select().single()
  expect(error).toBeNull()
  return data!
}

describe('hier : ce qu’on choisit est mangé', () => {
  it('un plat choisi pour hier : la case est mangée à l’heure du repas, la barquette sort du stock', async () => {
    const label = nouveauPlat()
    const [a, b] = await parts(label, 2)
    const r = await choisit(HIER(), 'diner', lePlat(label))
    expect(r.error).toBeNull()
    const c = (await caseDe(HIER(), 'diner'))!
    expect(c.state).toBe('mange')
    expect(c.portion_id).toBe(r.data.poses[kamil.userId])
    expect([a.id, b.id]).toContain(c.portion_id)
    /* 19 h à Paris, hier : jamais dans le futur, et pas « maintenant ». */
    const mange = new Date(c.eaten_at!)
    expect(mange.getTime()).toBeLessThanOrEqual(Date.now())
    expect(mange.toLocaleString('sv-SE', { timeZone: 'Europe/Paris' })).toBe(`${HIER()} 19:00:00`)
    expect(await etat(c.portion_id!)).toBe('mangee')
    const reste = [a, b].find(p => p.id !== c.portion_id)!
    expect(await etat(reste.id), 'l’autre barquette reste au frigo').toBe('au_frais')
  })

  it('le midi est à 12 h, le petit déjeuner à 8 h, la collation à 16 h', async () => {
    const heures: Record<string, string> = { dejeuner: '12:00:00', petit_dejeuner: '08:00:00', collation: '16:00:00' }
    for (const [meal, h] of Object.entries(heures)) {
      const r = await choisit(HIER(), meal, { type: 'repere', label: 'Yaourt', kcal: 95, protein_g: 12 })
      expect(r.error, meal).toBeNull()
      const c = (await caseDe(HIER(), meal))!
      expect(new Date(c.eaten_at!).toLocaleString('sv-SE', { timeZone: 'Europe/Paris' }), meal).toBe(`${HIER()} ${h}`)
    }
  })

  it('autre chose pour hier : case mangée, extra NOTÉ (pas planifié), avec son aliment', async () => {
    const al = await unAliment()
    const r = await choisit(HIER(), 'dejeuner', {
      type: 'repere', label: 'Skyr × 2 pots', grams: 300, kcal: 192, protein_g: 28.5, carb_g: 18.3, fat_g: 0.6, fiber_g: 0, aliment_id: al.id,
    })
    expect(r.error).toBeNull()
    const c = (await caseDe(HIER(), 'dejeuner'))!
    expect(c.state).toBe('mange')
    expect(c.portion_id).toBeNull()
    const [e] = await extrasDe(c.id)
    expect(e).toMatchObject({ label: 'Skyr × 2 pots', aliment_id: al.id, planifie: false })
    expect(Number(e.grams)).toBe(300)
    expect(Number(e.kcal)).toBe(192)
  })

  it('« On saute ce repas » reste sauté, sans heure', async () => {
    const r = await choisit(HIER(), 'diner', { type: 'saute' })
    expect(r.error).toBeNull()
    const c = (await caseDe(HIER(), 'diner'))!
    expect(c.state).toBe('saute')
    expect(c.eaten_at).toBeNull()
  })

  it('un repas d’aujourd’hui ou à venir se comporte comme avant : prévu, extra planifié', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    expect((await choisit(aujourdhui(), 'diner', lePlat(label))).error).toBeNull()
    const auj = (await caseDe(aujourdhui(), 'diner'))!
    expect(auj.state).toBe('prevu')
    expect(auj.eaten_at).toBeNull()
    expect((await choisit(jourDans(2), 'dejeuner', { type: 'repere', label: 'Restaurant', kcal: 800, protein_g: 30 })).error).toBeNull()
    const futur = (await caseDe(jourDans(2), 'dejeuner'))!
    expect(futur.state).toBe('prevu')
    expect((await extrasDe(futur.id))[0].planifie).toBe(true)
  })

  it('sept jours en arrière passent, huit sont refusés sans rien écrire', async () => {
    const ok = await choisit(jourDans(-7), 'diner', { type: 'repere', label: 'Pizza', kcal: 800, protein_g: 30 })
    expect(ok.error).toBeNull()
    expect((await caseDe(jourDans(-7), 'diner'))!.state).toBe('mange')
    const trop = await choisit(jourDans(-8), 'diner', { type: 'repere', label: 'Pizza', kcal: 800, protein_g: 30 })
    expect(trop.error?.message).toMatch(/trop ancien/)
    expect(await caseDe(jourDans(-8), 'diner')).toBeNull()
  })

  it('on peut CHANGER un repas passé pas encore noté : l’ancienne barquette est lâchée, la nouvelle mangée', async () => {
    const vieux = nouveauPlat()
    const neuf = nouveauPlat()
    const [v] = await parts(vieux, 1)
    const [n] = await parts(neuf, 1)
    const { error } = await db.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: HIER(), meal: 'diner', state: 'prevu', portion_id: v.id,
    })
    expect(error).toBeNull()
    const r = await choisit(HIER(), 'diner', lePlat(neuf))
    expect(r.error).toBeNull()
    expect(r.data.liberees.map((x: { portion_id: string }) => x.portion_id)).toEqual([v.id])
    const c = (await caseDe(HIER(), 'diner'))!
    expect(c.portion_id).toBe(n.id)
    expect(c.state).toBe('mange')
    expect(await etat(v.id), 'l’ancienne reste au frigo').toBe('au_frais')
    expect(await etat(n.id)).toBe('mangee')
  })

  it('un repas passé déjà noté mangé ne se change plus', async () => {
    const label = nouveauPlat()
    await parts(label, 2)
    expect((await choisit(HIER(), 'diner', lePlat(label))).error).toBeNull()
    const encore = await choisit(HIER(), 'diner', { type: 'saute' })
    expect(encore.error?.message).toMatch(/déjà mangé/)
    expect((await caseDe(HIER(), 'diner'))!.state).toBe('mange')
  })

  it('une barquette réclamée par un repas à venir n’est pas libre pour hier : refusé, rien n’est écrit', async () => {
    const label = nouveauPlat()
    const [a] = await parts(label, 1)
    expect((await db.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: jourDans(3), meal: 'diner', state: 'prevu', portion_id: a.id,
    })).error).toBeNull()
    const r = await choisit(HIER(), 'diner', lePlat(label))
    expect(r.error?.message).toMatch(/pas assez de parts libres/)
    expect(await caseDe(HIER(), 'diner')).toBeNull()
    expect(await etat(a.id)).toBe('au_frais')
  })

  it('un plat du congélateur coché hier sort du congélateur, comme aujourd’hui', async () => {
    const label = nouveauPlat()
    const [a] = await parts(label, 1, { lieu: 'congelateur' })
    expect((await choisit(HIER(), 'diner', lePlat(label, 'congelateur'))).error).toBeNull()
    expect(await etat(a.id)).toBe('mangee')
  })
})

describe('hier : la RLS et les autres gestes acceptent un jour passé', () => {
  it('« Je l’ai mangé » sur une case d’hier (mange_une_part) : la case est mangée, la barquette consommée', async () => {
    const label = nouveauPlat()
    const [a] = await parts(label, 1)
    expect((await db.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: HIER(), meal: 'diner', state: 'prevu', portion_id: a.id,
    })).error).toBeNull()
    const r = await kamil.client.rpc('mange_une_part', {
      p_recipe: null, p_label: label, p_location: 'frigo', p_state: 'au_frais', p_day: HIER(), p_meal: 'diner', p_eaten_at: new Date().toISOString(),
    })
    expect(r.error).toBeNull()
    expect((await caseDe(HIER(), 'diner'))!.state).toBe('mange')
    expect(await etat(a.id)).toBe('mangee')
  })

  it('un extra « en plus » d’hier s’écrit comme celui d’aujourd’hui (RLS du foyer), et compte', async () => {
    const { data: s, error } = await kamil.client.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: HIER(), meal: 'petit_dejeuner', state: 'prevu',
    }).select().single()
    expect(error).toBeNull()
    const e = await kamil.client.from('meal_extra').insert({
      household_id: kamil.householdId, meal_slot_id: s!.id, label: 'Céréales, 30 g', grams: 30, kcal: 114, protein_g: 3,
    }).select().single()
    expect(e.error).toBeNull()
    expect(e.data!.planifie).toBe(false)
  })

  it('un autre foyer ne voit pas hier', async () => {
    expect((await choisit(HIER(), 'diner', { type: 'saute' })).error).toBeNull()
    const vu = await autre.client.from('meal_slot').select('id').eq('day', HIER())
    expect(vu.data).toEqual([])
  })
})

describe('meal_extra.aliment_id : une copie, jamais une référence de valeurs', () => {
  it('l’aliment retiré laisse la ligne et vide le lien : le bilan d’hier ne bouge pas', async () => {
    const al = await unAliment()
    expect((await choisit(HIER(), 'diner', {
      type: 'repere', label: 'Skyr × 1 pot', grams: 150, kcal: 96, protein_g: 14.3, aliment_id: al.id,
    })).error).toBeNull()
    const c = (await caseDe(HIER(), 'diner'))!
    expect((await extrasDe(c.id))[0].aliment_id).toBe(al.id)
    expect((await db.from('aliment').delete().eq('id', al.id)).error).toBeNull()
    const [e] = await extrasDe(c.id)
    expect(e.aliment_id).toBeNull()
    expect(Number(e.kcal)).toBe(96)
  })

  it('corriger l’aliment demain ne réécrit pas l’extra', async () => {
    const al = await unAliment()
    expect((await choisit(HIER(), 'diner', {
      type: 'repere', label: 'Skyr', grams: 150, kcal: 96, protein_g: 14.3, aliment_id: al.id,
    })).error).toBeNull()
    expect((await db.from('aliment').update({ kcal_100g: 500 }).eq('id', al.id)).error).toBeNull()
    const [e] = await extrasDe((await caseDe(HIER(), 'diner'))!.id)
    expect(Number(e.kcal)).toBe(96)
  })

  it('l’aliment d’un autre foyer est refusé (par la fonction comme en écriture directe), rien n’est écrit', async () => {
    const chezLautre = await unAliment(autre.householdId)
    const r = await choisit(HIER(), 'diner', { type: 'repere', label: 'Skyr', kcal: 96, protein_g: 14, aliment_id: chezLautre.id })
    expect(r.error?.message).toMatch(/aliment_id désigne quelque chose qui n.est pas au foyer/)
    expect(await caseDe(HIER(), 'diner'), 'la case a été écrite malgré le refus').toBeNull()

    const { data: s } = await kamil.client.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: HIER(), meal: 'collation', state: 'prevu',
    }).select().single()
    const direct = await kamil.client.from('meal_extra').insert({
      household_id: kamil.householdId, meal_slot_id: s!.id, label: 'Skyr', kcal: 96, protein_g: 14, aliment_id: chezLautre.id,
    })
    expect(direct.error?.message).toMatch(/aliment_id désigne quelque chose qui n.est pas au foyer/)
  })

  it('les quantités récentes se lisent par aliment, pour la personne', async () => {
    const al = await unAliment()
    /* 30, 60, 45 : trois valeurs DIFFÉRENTES, pour que l'ordre se voie (un palindrome passerait à l'envers). */
    for (const [jour, g] of [[jourDans(-3), 30], [jourDans(-2), 60], [HIER(), 45]] as const) {
      expect((await choisit(jour, 'collation', {
        type: 'repere', label: `Céréales, ${g} g`, grams: g, kcal: g * 3.8, protein_g: g * 0.1, aliment_id: al.id,
      })).error).toBeNull()
    }
    const lu = await kamil.client.from('meal_extra')
      .select('grams, created_at, meal_slot!inner(user_profile_id)')
      .eq('aliment_id', al.id).eq('meal_slot.user_profile_id', kamil.userId)
      .not('grams', 'is', null).order('created_at', { ascending: false }).limit(20)
    expect(lu.error).toBeNull()
    expect(lu.data!.map(x => Number(x.grams))).toEqual([45, 60, 30])
    const autrui = await autre.client.from('meal_extra').select('id').eq('aliment_id', al.id)
    expect(autrui.data).toEqual([])
  })
})

describe('un jour est « passé » pour la base aussi, pas seulement pour le client (p_today)', () => {
  const dateDeLAppareil = (jour: string, meal: string, choix: object, today: string) =>
    kamil.client.rpc('choisir_un_repas', { p_day: jour, p_meal: meal, p_users: [kamil.userId], p_today: today, p_choix: choix })

  it('un p_today en avance d’un jour ne fait pas noter mangé le repas d’aujourd’hui : il reste prévu, planifié', async () => {
    const label = nouveauPlat()
    const [a] = await parts(label, 1)
    const r = await dateDeLAppareil(aujourdhui(), 'diner', lePlat(label), jourDans(1))
    expect(r.error).toBeNull()
    const c = (await caseDe(aujourdhui(), 'diner'))!
    expect(c.state).toBe('prevu')
    expect(c.eaten_at).toBeNull()
    expect(await etat(a.id), 'la barquette n’est pas consommée').toBe('au_frais')
    const e = await dateDeLAppareil(aujourdhui(), 'collation', { type: 'repere', label: 'Yaourt', kcal: 95, protein_g: 12 }, jourDans(1))
    expect(e.error).toBeNull()
    const cc = (await caseDe(aujourdhui(), 'collation'))!
    expect(cc.state).toBe('prevu')
    expect((await extrasDe(cc.id))[0].planifie).toBe(true)
  })

  it('un p_today en retard d’un jour ne rend pas « passé » un repas qui ne l’est pas : le repas d’hier reste noté mangé avec le bon p_today', async () => {
    const label = nouveauPlat()
    await parts(label, 1)
    /* p_today = hier (appareil en retard d'un jour) : hier n'est pas avant « aujourd'hui » selon lui, donc pas mangé. */
    expect((await dateDeLAppareil(HIER(), 'diner', lePlat(label), HIER())).error).toBeNull()
    expect((await caseDe(HIER(), 'diner'))!.state).toBe('prevu')
  })
})

describe('re-choisir le même plat sur un repas passé', () => {
  it('encore « prévu » : une seule barquette est consommée, celle de la case (pas deux)', async () => {
    const label = nouveauPlat()
    const [a, b] = await parts(label, 2)
    expect((await db.from('meal_slot').insert({
      household_id: kamil.householdId, user_profile_id: kamil.userId, day: HIER(), meal: 'diner', state: 'prevu', portion_id: a.id,
    })).error).toBeNull()
    const r = await choisit(HIER(), 'diner', lePlat(label))
    expect(r.error).toBeNull()
    const c = (await caseDe(HIER(), 'diner'))!
    expect(c.state).toBe('mange')
    expect(c.portion_id, 'changer pour le même plat reprend la barquette de la case').toBe(a.id)
    expect(await etat(a.id)).toBe('mangee')
    expect(await etat(b.id), 'l’autre barquette n’est pas touchée').toBe('au_frais')
    expect(r.data.liberees, 'rien n’est lâché').toEqual([])
    const { data: mangees } = await db.from('portion').select('id').eq('household_id', kamil.householdId).eq('label', label).eq('state', 'mangee')
    expect(mangees).toHaveLength(1)
  })
})
