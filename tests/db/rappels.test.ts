/**
 * Les rappels par mail (migration 0126), côté base : qui règle quoi, qui peut appeler, ce qui est DÛ et quand
 * (à l'heure de Paris, changements d'heure compris), et jamais deux fois.
 *
 * Tout se joue en 2030 : la base borne les mois du budget à cinq ans, et 2030 donne deux dimanches de
 * changement d'heure (31 mars, 27 octobre). Chaque test a son foyer, et `rappels_a_envoyer` prend l'instant en
 * paramètre : rien ne dépend de l'horloge de la machine.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { randomUUID } from 'node:crypto'
import { admin, type Actor } from './helpers/db'
import { clos, foyerSolo, membre, ou, poseCharge, type Foyer } from './helpers/budget'
import { connexion, URL_PG_ADMIN } from './helpers/pg'
import { readFileSync } from 'node:fs'

const db = admin()

type Due = {
  user_id: string; email: string; prenom: string; type: string; cle: string; cles: string[]
  donnees: Record<string, any>
}
const TYPES = [
  'sortir_du_congelateur', 'barquette_perime', 'choisir_les_repas', 'noter_les_depenses',
  'confirmer_les_charges', 'cloturer_le_mois', 'facture_annuelle',
]

/** Ce qui est dû à cet instant, pour ces personnes seulement (la base de test est partagée). */
async function du(iso: string, qui: string[], type?: string): Promise<Due[]> {
  const r = await db.rpc('rappels_a_envoyer', { p_maintenant: iso })
  expect(r.error, r.error?.message).toBeNull()
  return (r.data as Due[]).filter(x => qui.includes(x.user_id) && (!type || x.type === type))
}

async function active(userId: string, type: string, actif = true) {
  ou(await db.from('rappel_reglage').upsert({ user_id: userId, type, actif }).select())
}

type Duo = { k: Foyer; t: Actor }
/** Un foyer de deux : Kamil (revenu posé) et Léa (sans revenu, sauf demande). */
async function duo(o: { revenuLea?: number } = {}): Promise<Duo> {
  const k = await foyerSolo('Kamil', { revenu: 310_000 })
  const t = await membre(k, 'Léa', o.revenuLea ? { revenu: o.revenuLea } : {})
  return { k, t }
}

let n = 0
async function portion(foyer: string, o: {
  label: string; lieu?: 'frigo' | 'congelateur'; etat?: string; expire?: string; pour?: string | null
}) {
  const congelee = o.lieu === 'congelateur'
  return ou(await db.from('portion').insert({
    household_id: foyer, label: o.label, grams: 500, kcal: 600, protein_g: 40, fiber_g: 5, carb_g: 60, fat_g: 20,
    location: o.lieu ?? 'frigo', state: o.etat ?? 'au_frais',
    frozen_at: congelee ? '2030-05-01T10:00:00Z' : null,
    expires_at: o.expire ?? (congelee ? '2030-08-01T10:00:00Z' : '2030-06-20T10:00:00Z'),
    for_user_id: o.pour ?? null,
  }).select().single()) as { id: string }
}
async function repas(foyer: string, qui: string, jour: string, meal: string, portionId: string | null, etat = 'prevu') {
  return ou(await db.from('meal_slot').insert({
    household_id: foyer, user_profile_id: qui, day: jour, meal, portion_id: portionId, state: etat,
    eaten_at: etat === 'mange' ? '2030-06-01T12:00:00Z' : null,
  }).select().single()) as { id: string }
}

/* Des instants précis. Paris est à UTC+2 l'été, UTC+1 l'hiver. */
const MARDI_19H = '2030-06-11T17:00:00Z'       // mardi 11 juin, 19 h 00 à Paris (heure d'été)
const MARDI_18H59 = '2030-06-11T16:59:00Z'

describe('les réglages : chacun les siens', () => {
  let d: Duo
  beforeAll(async () => { d = await duo() })

  it('un membre règle et relit ses rappels ; il ne voit pas ceux de l’autre', async () => {
    ou(await d.k.client.from('rappel_reglage').insert({ user_id: d.k.userId, type: 'sortir_du_congelateur', actif: true }).select())
    ou(await d.t.client.from('rappel_reglage').insert({ user_id: d.t.userId, type: 'choisir_les_repas', actif: true }).select())

    const kamil = ou(await d.k.client.from('rappel_reglage').select('user_id, type, actif'))
    expect(kamil).toEqual([{ user_id: d.k.userId, type: 'sortir_du_congelateur', actif: true }])
    const lea = ou(await d.t.client.from('rappel_reglage').select('user_id, type, actif'))
    expect(lea).toEqual([{ user_id: d.t.userId, type: 'choisir_les_repas', actif: true }])
  })

  it('un membre n’écrit pas pour l’autre (même foyer)', async () => {
    const r = await d.k.client.from('rappel_reglage').insert({ user_id: d.t.userId, type: 'noter_les_depenses', actif: true })
    expect(r.error, 'Kamil a écrit un réglage pour Léa').not.toBeNull()

    /* Mettre à jour ou supprimer la ligne de l'autre : la RLS la lui cache, rien n'est touché. */
    const maj = ou(await d.k.client.from('rappel_reglage').update({ actif: false })
      .eq('user_id', d.t.userId).select())
    expect(maj).toEqual([])
    const supp = ou(await d.k.client.from('rappel_reglage').delete().eq('user_id', d.t.userId).select())
    expect(supp).toEqual([])
    const chez = ou(await db.from('rappel_reglage').select('actif').eq('user_id', d.t.userId).eq('type', 'choisir_les_repas'))
    expect(chez).toEqual([{ actif: true }])
  })

  it('le membre et le type d’une ligne ne se déplacent pas', async () => {
    const vers = await d.k.client.from('rappel_reglage').update({ user_id: d.t.userId })
      .eq('user_id', d.k.userId).eq('type', 'sortir_du_congelateur').select()
    expect(vers.error, 'la ligne a changé de membre').not.toBeNull()
    const type = await d.k.client.from('rappel_reglage').update({ type: 'barquette_perime' })
      .eq('user_id', d.k.userId).eq('type', 'sortir_du_congelateur').select()
    expect(type.error, 'la ligne a changé de type').not.toBeNull()
  })

  it('un type inconnu est refusé', async () => {
    const r = await d.k.client.from('rappel_reglage').insert({ user_id: d.k.userId, type: 'spam', actif: true })
    expect(r.error).not.toBeNull()
  })

  it('un anonyme ne lit rien', async () => {
    const anon = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    const r = await anon.from('rappel_reglage').select('*')
    expect(r.error || r.data!.length === 0, 'un anonyme lit des réglages').toBeTruthy()
  })

  it('« envoyé » n’est ni lisible ni écrivable côté client', async () => {
    ou(await db.from('rappel_envoye').insert({ user_id: d.k.userId, type: 'sortir_du_congelateur', cle: '2030-06-12' }).select())
    const lu = await d.k.client.from('rappel_envoye').select('*')
    expect(lu.error || lu.data!.length === 0, 'le client lit rappel_envoye').toBeTruthy()
    const ecrit = await d.k.client.from('rappel_envoye').insert({ user_id: d.k.userId, type: 'barquette_perime', cle: 'x' })
    expect(ecrit.error, 'le client écrit rappel_envoye').not.toBeNull()
  })
})

describe('qui peut appeler', () => {
  let d: Duo
  beforeAll(async () => { d = await duo() })

  it('rappels_a_envoyer, reserve_rappel et libere_rappel sont refusés au client et à l’anonyme', async () => {
    const anon = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    for (const c of [d.k.client, anon]) {
      expect((await c.rpc('rappels_a_envoyer', { p_maintenant: MARDI_19H })).error, 'rappels_a_envoyer').not.toBeNull()
      expect((await c.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'choisir_les_repas', p_cles: ['x'] })).error, 'reserve_rappel').not.toBeNull()
      expect((await c.rpc('libere_rappel', { p_user: d.k.userId, p_type: 'choisir_les_repas', p_cles: ['x'] })).error, 'libere_rappel').not.toBeNull()
      expect((await c.rpc('rappel_actifs', { p_type: 'choisir_les_repas' })).error, 'rappel_actifs').not.toBeNull()
      expect((await c.rpc('appelle_les_rappels')).error, 'appelle_les_rappels').not.toBeNull()
    }
  })

  it('le rôle de service y accède', async () => {
    expect((await db.rpc('rappels_a_envoyer', { p_maintenant: MARDI_19H })).error).toBeNull()
  })

  it('coupé entre la lecture et l’envoi : la réservation refuse, donc rien ne part ; un exemple se réserve coupé', async () => {
    const reserve = async (cles: string[]) =>
      (await db.rpc('reserve_rappel', { p_user: d.t.userId, p_type: 'noter_les_depenses', p_cles: cles })).data
    await active(d.t.userId, 'noter_les_depenses', true)
    expect(await reserve(['2030-06-11']), 'activé : réservé').toBe(true)
    await active(d.t.userId, 'noter_les_depenses', false)
    expect(await reserve(['2030-06-12']), 'coupé : rien').toBe(false)
    expect(await reserve(['essai:noter_les_depenses:2030-06-12T08']), 'un exemple, coupé : réservé').toBe(true)
  })
})

describe('coupé par défaut', () => {
  it('rien n’est dû à qui n’a rien activé, même quand tout est dû', async () => {
    const d = await duo()
    const wrap = await portion(d.k.householdId, { label: 'Wraps', lieu: 'congelateur' })
    await repas(d.k.householdId, d.k.userId, '2030-06-12', 'diner', wrap.id)
    expect(await du(MARDI_19H, [d.k.userId, d.t.userId])).toEqual([])
  })

  it('seul celui qui a activé reçoit ; couper arrête tout', async () => {
    const d = await duo()
    const wrap = await portion(d.k.householdId, { label: 'Wraps', lieu: 'congelateur' })
    await repas(d.k.householdId, d.k.userId, '2030-06-12', 'diner', wrap.id)

    await active(d.k.userId, 'sortir_du_congelateur')
    const dus = await du(MARDI_19H, [d.k.userId, d.t.userId])
    expect(dus.map(x => x.user_id)).toEqual([d.k.userId])
    expect(dus[0].email).toBe(d.k.email.toLowerCase())
    expect(dus[0].prenom).toBe('Kamil')

    await active(d.k.userId, 'sortir_du_congelateur', false)
    expect(await du(MARDI_19H, [d.k.userId, d.t.userId])).toEqual([])
  })
})

describe('sortir_du_congelateur : la veille à 19 h', () => {
  it('regroupe par plat, dit pour qui et combien il en reste, à partir de 19 h et jusqu’à minuit', async () => {
    const d = await duo()
    const f = d.k.householdId
    // Quatre wraps pour demain (midi et soir, pour deux), trois autres restent au congélateur.
    const wraps = await Promise.all([0, 1, 2, 3, 4, 5, 6].map(() => portion(f, { label: 'Wraps poulet', lieu: 'congelateur' })))
    await repas(f, d.k.userId, '2030-06-12', 'dejeuner', wraps[0].id)
    await repas(f, d.t.userId, '2030-06-12', 'dejeuner', wraps[1].id)
    await repas(f, d.k.userId, '2030-06-12', 'diner', wraps[2].id)
    await repas(f, d.t.userId, '2030-06-12', 'diner', wraps[3].id)
    // Ce qui NE compte PAS : le frigo, un autre jour, un repas déjà mangé.
    const frigo = await portion(f, { label: 'Soupe', lieu: 'frigo' })
    await repas(f, d.k.userId, '2030-06-12', 'petit_dejeuner', frigo.id)
    await repas(f, d.k.userId, '2030-06-13', 'dejeuner', (await portion(f, { label: 'Autre jour', lieu: 'congelateur' })).id)
    await repas(f, d.k.userId, '2030-06-12', 'collation', (await portion(f, { label: 'Mangé', lieu: 'congelateur' })).id, 'mange')
    // Une barquette jetée que la case pointe encore : il n'y a plus rien à sortir.
    await repas(f, d.t.userId, '2030-06-12', 'collation', (await portion(f, { label: 'Jetée', lieu: 'congelateur', etat: 'jetee' })).id)

    await active(d.k.userId, 'sortir_du_congelateur')
    await active(d.t.userId, 'sortir_du_congelateur')
    const ids = [d.k.userId, d.t.userId]

    expect(await du(MARDI_18H59, ids), 'avant 19 h').toEqual([])
    const dus = await du(MARDI_19H, ids)
    expect(dus.map(x => x.user_id).sort()).toEqual([...ids].sort())
    for (const x of dus) {
      expect(x.type).toBe('sortir_du_congelateur')
      expect(x.cle).toBe('2030-06-12')
      expect(x.cles).toEqual(['2030-06-12'])
      expect(x.donnees.jour).toBe('2030-06-12')
      const plats = x.donnees.plats as any[]
      expect(plats.map(p => p.label)).toEqual(['Wraps poulet'])
      const w = plats[0]
      expect(w.n, 'quatre wraps, regroupés en un plat').toBe(4)
      expect([...w.portion_ids].sort()).toEqual([wraps[0].id, wraps[1].id, wraps[2].id, wraps[3].id].sort())
      expect(w.repas).toEqual([
        { meal: 'dejeuner', pour: ['Kamil', 'Léa'] },
        { meal: 'diner', pour: ['Kamil', 'Léa'] },
      ])
      expect(w.restant, 'il en restera trois au congélateur').toBe(3)
    }
    expect(await du('2030-06-11T21:59:00Z', ids), '23 h 59 : le passage manqué se rattrape').toHaveLength(2)
    expect(await du('2030-06-11T22:00:00Z', ids), 'minuit passé : c’est un autre jour').toEqual([])
  })

  it('deux plats pour demain : deux entrées, dans l’ordre des repas', async () => {
    const d = await duo()
    const f = d.k.householdId
    const a = await portion(f, { label: 'Pizza', lieu: 'congelateur' })
    const b = await portion(f, { label: 'Burger', lieu: 'congelateur' })
    await repas(f, d.k.userId, '2030-06-12', 'diner', a.id)
    await repas(f, d.k.userId, '2030-06-12', 'dejeuner', b.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    const [x] = await du(MARDI_19H, [d.k.userId])
    expect((x.donnees.plats as any[]).map(p => p.label)).toEqual(['Burger', 'Pizza'])
  })

  it('une barquette déjà sortie n’est plus à sortir ; une barquette de plus change le mail', async () => {
    const d = await duo()
    const f = d.k.householdId
    const a = await portion(f, { label: 'Wraps', lieu: 'congelateur' })
    await repas(f, d.k.userId, '2030-06-12', 'dejeuner', a.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    expect(await du(MARDI_19H, [d.k.userId])).toHaveLength(1)
    ou(await db.from('portion').update({ location: 'frigo' }).eq('id', a.id).select())
    expect(await du(MARDI_19H, [d.k.userId]), 'elle est au frigo : rien à sortir').toEqual([])
  })

  it('à l’heure de Paris : 19 h d’hiver est 18 h UTC, 19 h d’été est 17 h UTC', async () => {
    const d = await duo()
    const f = d.k.householdId
    await repas(f, d.k.userId, '2030-01-16', 'dejeuner', (await portion(f, { label: 'Wraps', lieu: 'congelateur' })).id)
    await repas(f, d.k.userId, '2030-06-12', 'dejeuner', (await portion(f, { label: 'Wraps', lieu: 'congelateur' })).id)
    await active(d.k.userId, 'sortir_du_congelateur')
    expect(await du('2030-01-15T17:59:00Z', [d.k.userId]), '18 h 59 à Paris, en hiver').toEqual([])
    expect(await du('2030-01-15T18:00:00Z', [d.k.userId]), '19 h pile, en hiver').toHaveLength(1)
    expect(await du('2030-06-11T16:59:00Z', [d.k.userId]), '18 h 59 à Paris, en été').toEqual([])
    expect(await du('2030-06-11T17:00:00Z', [d.k.userId]), '19 h pile, en été').toHaveLength(1)
  })

  it('autour du changement d’heure d’octobre (le dimanche 27, 3 h devient 2 h)', async () => {
    const d = await duo()
    const f = d.k.householdId
    // Samedi 26 octobre, 19 h (heure d’été) → le repas de dimanche.
    await repas(f, d.k.userId, '2030-10-27', 'dejeuner', (await portion(f, { label: 'Wraps', lieu: 'congelateur' })).id)
    // Dimanche 27 octobre, 19 h (heure d’hiver) → le repas de lundi.
    await repas(f, d.k.userId, '2030-10-28', 'dejeuner', (await portion(f, { label: 'Pizza', lieu: 'congelateur' })).id)
    await active(d.k.userId, 'sortir_du_congelateur')
    const ids = [d.k.userId]
    expect(await du('2030-10-26T16:59:00Z', ids)).toEqual([])
    expect((await du('2030-10-26T17:00:00Z', ids)).map(x => x.cle)).toEqual(['2030-10-27'])
    expect((await du('2030-10-27T17:59:00Z', ids)).map(x => x.cle), '19 h d’hiver n’est pas encore là').toEqual([])
    expect((await du('2030-10-27T18:00:00Z', ids)).map(x => x.cle)).toEqual(['2030-10-28'])
  })

  it('autour du changement d’heure de mars (le dimanche 31, 2 h devient 3 h)', async () => {
    const d = await duo()
    const f = d.k.householdId
    await repas(f, d.k.userId, '2030-04-01', 'dejeuner', (await portion(f, { label: 'Wraps', lieu: 'congelateur' })).id)
    await active(d.k.userId, 'sortir_du_congelateur')
    expect(await du('2030-03-31T16:59:00Z', [d.k.userId]), '18 h 59 d’été').toEqual([])
    expect(await du('2030-03-31T17:00:00Z', [d.k.userId]), '19 h d’été').toHaveLength(1)
  })
})

describe('barquette_perime : à 8 h, UN mail par membre et par jour pour ce qui périme et n’est prévu nulle part', () => {
  const MARDI_8H = '2030-06-11T06:00:00Z'
  it('regroupe tout dans un seul mail, par plat ; la clé est la date, chaque barquette est réservée avec', async () => {
    const d = await duo()
    const f = d.k.householdId
    // Trois lasagnes qui périment demain 21 h (Paris), non prévues.
    const trois = await Promise.all([1, 2, 3].map(() => portion(f, { label: 'Lasagnes saumon', expire: '2030-06-12T19:00:00Z' })))
    await active(d.k.userId, 'barquette_perime')
    const ids = [d.k.userId]

    expect(await du('2030-06-11T05:59:00Z', ids), '7 h 59').toEqual([])
    const dus = await du(MARDI_8H, ids)
    expect(dus).toHaveLength(1)
    const x = dus[0]
    expect(x.type).toBe('barquette_perime')
    expect(x.cle, 'la clé est la date du jour').toBe('2030-06-11')
    expect(x.cles[0]).toBe('2030-06-11')
    expect([...x.cles.slice(1)].sort()).toEqual(trois.map(t => t.id).sort())
    expect(x.donnees.n).toBe(3)
    const plats = x.donnees.plats as any[]
    expect(plats).toHaveLength(1)
    expect(plats[0].label).toBe('Lasagnes saumon')
    expect(plats[0].n).toBe(3)
    expect([...plats[0].portion_ids].sort()).toEqual(trois.map(t => t.id).sort())
    expect(new Date(plats[0].expire).toISOString()).toBe('2030-06-12T19:00:00.000Z')
    expect(plats[0].tardives).toEqual([])
    expect(await du('2030-06-11T21:59:00Z', ids), '23 h 59 : encore dû').toHaveLength(1)

    // Réservé (la date et les trois barquettes), il ne revient pas ; une quatrième barquette attend le lendemain.
    expect((await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'barquette_perime', p_cles: x.cles })).data).toBe(true)
    expect(await du(MARDI_8H, ids)).toEqual([])
    await portion(f, { label: 'Lasagnes saumon', expire: '2030-06-12T19:00:00Z' })
    expect(await du(MARDI_8H, ids), 'un mail par jour : la quatrième barquette attend demain').toEqual([])
    const demain = await du('2030-06-12T06:00:00Z', ids)
    expect(demain).toHaveLength(1)
    expect(demain[0].cle).toBe('2030-06-12')
    expect(demain[0].donnees.n, 'les trois déjà annoncées ne le sont pas deux fois').toBe(1)
  })

  it('quatre plats, un seul rang : UN mail, les quatre plats dedans', async () => {
    const d = await duo()
    const f = d.k.householdId
    await portion(f, { label: 'Lasagnes', expire: '2030-06-12T19:00:00Z' })
    await portion(f, { label: 'Lasagnes', expire: '2030-06-12T19:00:00Z' })
    await portion(f, { label: 'Soupe', expire: '2030-06-12T07:00:00Z' })
    await portion(f, { label: 'Pizza', expire: '2030-06-12T10:00:00Z' })
    await portion(f, { label: 'Wrap', expire: '2030-06-11T20:00:00Z' })
    await active(d.k.userId, 'barquette_perime')
    await active(d.t.userId, 'barquette_perime')
    const dus = await du(MARDI_8H, [d.k.userId, d.t.userId])
    // Un mail par MEMBRE (deux ont activé), un seul chacun, pas un par plat.
    expect(dus.map(x => x.user_id).sort()).toEqual([d.k.userId, d.t.userId].sort())
    for (const x of dus) {
      expect(x.donnees.n).toBe(5)
      expect((x.donnees.plats as any[]).map(p => p.label)).toEqual(['Wrap', 'Soupe', 'Pizza', 'Lasagnes'])   // du plus pressé au moins pressé
    }
    const seul = await du(MARDI_8H, [d.k.userId])
    expect(seul, '4 plats : 1 ligne').toHaveLength(1)
  })

  it('ne compte pas ce qui est prévu à temps, ce qui périme plus tard, ce qui a péri il y a plus de 24 h, ni le congélateur', async () => {
    const d = await duo()
    const f = d.k.householdId
    const prevue = await portion(f, { label: 'Prévue', expire: '2030-06-12T19:00:00Z' })
    await repas(f, d.k.userId, '2030-06-12', 'diner', prevue.id)
    await portion(f, { label: 'Plus tard', expire: '2030-06-12T22:30:00Z' }) // 00 h 30 le 13 : après demain soir
    await portion(f, { label: 'Périmée depuis longtemps', expire: '2030-06-10T05:00:00Z' }) // il y a 25 h
    await portion(f, { label: 'Congelée', lieu: 'congelateur', expire: '2030-06-12T19:00:00Z' })
    await portion(f, { label: 'Mangée', etat: 'mangee', expire: '2030-06-12T19:00:00Z' })
    await active(d.k.userId, 'barquette_perime')
    expect(await du(MARDI_8H, [d.k.userId])).toEqual([])
  })

  it('une barquette périmée depuis moins de 24 h est dans le mail (il dira « à jeter »)', async () => {
    const d = await duo()
    await portion(d.k.householdId, { label: 'Soupe', expire: '2030-06-10T07:00:00Z' })   // il y a 23 h
    await active(d.k.userId, 'barquette_perime')
    const [x] = await du(MARDI_8H, [d.k.userId])
    expect(new Date((x.donnees.plats as any[])[0].expire).getTime()).toBeLessThan(new Date(MARDI_8H).getTime())
  })

  it('une réclamation d’un jour passé ne la retient pas ; avant demain soir, jusqu’à 23 h 59 demain', async () => {
    const d = await duo()
    const f = d.k.householdId
    const vieille = await portion(f, { label: 'Soupe', expire: '2030-06-12T21:59:00Z' }) // 23 h 59 demain : dedans
    await repas(f, d.k.userId, '2030-06-09', 'diner', vieille.id) // un repas passé, jamais noté
    await active(d.k.userId, 'barquette_perime')
    expect(await du(MARDI_8H, [d.k.userId])).toHaveLength(1)
  })

  it('prévue pour un repas APRÈS sa péremption : elle compte comme non prévue, avec le jour du repas', async () => {
    const d = await duo()
    const f = d.k.householdId
    const tard = await portion(f, { label: 'Soupe', expire: '2030-06-12T19:00:00Z' })           // périme mercredi 12, 21 h
    await repas(f, d.k.userId, '2030-06-15', 'dejeuner', tard.id)                                // prévue samedi 15
    const aTemps = await portion(f, { label: 'Riz', expire: '2030-06-12T19:00:00Z' })
    await repas(f, d.k.userId, '2030-06-12', 'diner', aTemps.id)                                 // prévue mercredi soir : à temps
    const memeJour = await portion(f, { label: 'Pâtes', expire: '2030-06-12T19:00:00Z' })
    await repas(f, d.k.userId, '2030-06-12', 'dejeuner', memeJour.id)                            // le jour même : à temps
    await active(d.k.userId, 'barquette_perime')
    const [x] = await du(MARDI_8H, [d.k.userId])
    const plats = x.donnees.plats as any[]
    expect(plats.map(p => p.label), 'seule la soupe : le riz et les pâtes sont prévus à temps').toEqual(['Soupe'])
    expect(plats[0].tardives).toEqual(['2030-06-15'])
  })

  it('à l’heure de Paris, 8 h d’hiver est 7 h UTC', async () => {
    const d = await duo()
    await portion(d.k.householdId, { label: 'Soupe', expire: '2030-01-16T19:00:00Z' })
    await active(d.k.userId, 'barquette_perime')
    expect(await du('2030-01-15T06:59:00Z', [d.k.userId])).toEqual([])
    expect(await du('2030-01-15T07:00:00Z', [d.k.userId])).toHaveLength(1)
  })
})

describe('choisir_les_repas : le dimanche à 18 h, s’il reste des dîners vides', () => {
  const DIM_18H = '2030-06-09T16:00:00Z'
  const jours = ['2030-06-10', '2030-06-11', '2030-06-12', '2030-06-13', '2030-06-14', '2030-06-15', '2030-06-16']

  it('dû tant qu’un dîner est vide ; « sauté » et « autre chose » sont des réponses, « prévu sans rien » est vide', async () => {
    const d = await duo()
    const f = d.k.householdId
    const plat = await portion(f, { label: 'Pizza', lieu: 'frigo' })
    const wrap = await portion(f, { label: 'Wraps', lieu: 'congelateur' })
    await repas(f, d.k.userId, jours[0], 'diner', plat.id)
    await repas(f, d.k.userId, jours[1], 'diner', wrap.id)
    await repas(f, d.k.userId, jours[2], 'diner', null, 'saute')
    const autre = await repas(f, d.k.userId, jours[3], 'diner', null)
    ou(await db.from('meal_extra').insert({ household_id: f, meal_slot_id: autre.id, label: 'Restaurant', kcal: 800 }).select())
    await repas(f, d.k.userId, jours[4], 'diner', null) // « prévu » sans barquette ni extra : vide
    await active(d.k.userId, 'choisir_les_repas')
    const ids = [d.k.userId]

    expect(await du('2030-06-09T15:59:00Z', ids), '17 h 59').toEqual([])
    const [x] = await du(DIM_18H, ids)
    expect(x.cle).toBe('2030-W23')
    expect(x.donnees.vides, 'jours 5 et 6 (et 7), le « prévu sans rien » et les deux sans ligne').toBe(3)
    expect((x.donnees.jours as any[]).map(j => j.jour)).toEqual(jours)
    expect((x.donnees.jours as any[]).map(j => j.soir)).toEqual(['frigo', 'congelateur', 'autre', 'autre', 'vide', 'vide', 'vide'])
    expect(x.donnees.congelateur).toBe(1)
    expect(x.donnees.frigo).toBe(1)

    // Tout est choisi : plus rien d'à rappeler.
    await repas(f, d.k.userId, jours[4], 'diner', null, 'saute').catch(() => null)
    ou(await db.from('meal_slot').update({ state: 'saute' }).eq('user_profile_id', d.k.userId).eq('day', jours[4]).eq('meal', 'diner').select())
    await repas(f, d.k.userId, jours[5], 'diner', null, 'saute')
    await repas(f, d.k.userId, jours[6], 'diner', null, 'saute')
    expect(await du(DIM_18H, ids), 'tous les dîners ont une réponse').toEqual([])
  })

  it('ni le samedi, ni le lundi ; chacun pour ses propres dîners', async () => {
    const d = await duo()
    const f = d.k.householdId
    await active(d.k.userId, 'choisir_les_repas')
    await active(d.t.userId, 'choisir_les_repas')
    const plat = await portion(f, { label: 'Pizza' })
    for (const j of jours) await repas(f, d.k.userId, j, 'diner', null, 'saute')
    void plat
    // Kamil a tout répondu, Léa rien : seule Léa est relancée.
    const dus = await du(DIM_18H, [d.k.userId, d.t.userId])
    expect(dus.map(x => x.user_id)).toEqual([d.t.userId])
    expect(dus[0].donnees.vides).toBe(7)
    expect(await du('2030-06-08T16:00:00Z', [d.t.userId]), 'samedi').toEqual([])
    expect(await du('2030-06-10T16:00:00Z', [d.t.userId]), 'lundi').toEqual([])
  })

  it('à l’heure de Paris, y compris les dimanches de changement d’heure', async () => {
    const d = await duo()
    await active(d.k.userId, 'choisir_les_repas')
    const ids = [d.k.userId]
    // 27 octobre : 18 h est 17 h UTC (heure d'hiver) ; avant la bascule, 18 h aurait été 16 h UTC.
    expect(await du('2030-10-27T16:30:00Z', ids), '17 h 30 à Paris : pas encore').toEqual([])
    expect(await du('2030-10-27T17:00:00Z', ids), '18 h à Paris').toHaveLength(1)
    // 31 mars : 18 h est 16 h UTC (heure d'été).
    expect(await du('2030-03-31T15:59:00Z', ids)).toEqual([])
    expect(await du('2030-03-31T16:00:00Z', ids)).toHaveLength(1)
  })
})

/** Une charge « au fil du mois » (ou autre) et sa ligne de mois, avec les parts. */
async function ligneDuMois(d: Duo, o: {
  libelle: string; mois: string; facon: 'fixe' | 'facture' | 'au_fil'; parts: Actor[]; confirme?: boolean
}) {
  const charge = await poseCharge(d.k, {
    libelle: `${o.libelle} ${++n}`, cents: 10_000, mode: o.facon, participants: o.parts.map(p => p.userId),
  })
  const ligne = ou(await db.from('depense').insert({
    household_id: d.k.householdId, charge_id: charge, mois: o.mois, libelle: o.libelle, montant_cents: 10_000,
    montant_prevu_cents: 10_000, nature: 'estimee', source: 'modele', facon: o.facon,
    confirme_le: o.confirme ? '2030-06-20T10:00:00Z' : null,
  }).select().single()) as { id: string }
  ou(await db.from('depense_part').insert(o.parts.map(p => ({
    depense_id: ligne.id, user_profile_id: p.userId, household_id: d.k.householdId,
    part_cents: 10_000 / o.parts.length, part_bps: 10_000 / o.parts.length,
  }))).select())
  return { charge, ligne: ligne.id }
}
async function saisie(d: Duo, ligneId: string, faitLe: string) {
  ou(await db.from('saisie').insert({
    id: randomUUID(), household_id: d.k.householdId, depense_id: ligneId, fait_le: faitLe, montant_cents: 500,
    saisi_par: d.k.userId,
  }).select())
}

describe('noter_les_depenses : le dimanche à 20 h, si rien n’est noté depuis 7 jours', () => {
  const DIM_20H = '2030-06-09T18:00:00Z'
  it('dû quand une ligne « au fil » existe et que rien n’a été noté depuis une semaine', async () => {
    const d = await duo()
    const { ligne } = await ligneDuMois(d, { libelle: 'Courses', mois: '2030-06-01', facon: 'au_fil', parts: [d.k, d.t] })
    await active(d.k.userId, 'noter_les_depenses')
    await active(d.t.userId, 'noter_les_depenses')
    const ids = [d.k.userId, d.t.userId]

    expect(await du('2030-06-09T17:59:00Z', ids), '19 h 59').toEqual([])
    const dus = await du(DIM_20H, ids)
    expect(dus.map(x => x.user_id).sort()).toEqual([...ids].sort())
    expect(dus[0].cle).toBe('2030-W23')
    expect(dus[0].donnees.depuis_jours).toBeNull()
    expect(dus[0].donnees.lignes).toBe(1)

    // Une dépense notée il y a 8 jours : toujours dû, et le mail dit depuis combien de temps.
    await saisie(d, ligne, '2030-06-01')
    expect((await du(DIM_20H, ids))[0].donnees.depuis_jours).toBe(8)
    // Une dépense notée mercredi : rien à rappeler.
    await saisie(d, ligne, '2030-06-05')
    expect(await du(DIM_20H, ids)).toEqual([])
  })

  it('rien à noter sans ligne « au fil » à son nom ; pas le samedi', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2030-06-01', facon: 'fixe', parts: [d.k] })
    await ligneDuMois(d, { libelle: 'Courses', mois: '2030-06-01', facon: 'au_fil', parts: [d.k] })
    await active(d.k.userId, 'noter_les_depenses')
    await active(d.t.userId, 'noter_les_depenses')
    const dus = await du(DIM_20H, [d.k.userId, d.t.userId])
    expect(dus.map(x => x.user_id), 'Léa ne porte aucune ligne « au fil »').toEqual([d.k.userId])
    expect(await du('2030-06-08T18:00:00Z', [d.k.userId]), 'samedi').toEqual([])
  })

  it('à l’heure de Paris le dimanche du changement d’heure', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Courses', mois: '2030-10-01', facon: 'au_fil', parts: [d.k] })
    await active(d.k.userId, 'noter_les_depenses')
    expect(await du('2030-10-27T18:59:00Z', [d.k.userId]), '19 h 59 à Paris').toEqual([])
    expect(await du('2030-10-27T19:00:00Z', [d.k.userId]), '20 h à Paris').toHaveLength(1)
  })
})

describe('confirmer_les_charges : le 1er à 9 h, les lignes du mois fini à confirmer', () => {
  const PREMIER_9H = '2030-07-01T07:00:00Z'
  it('dû pour qui porte une facture non confirmée du mois fini', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Électricité', mois: '2030-06-01', facon: 'facture', parts: [d.k] })
    await ligneDuMois(d, { libelle: 'Internet', mois: '2030-06-01', facon: 'facture', parts: [d.k, d.t] })
    await ligneDuMois(d, { libelle: 'Déjà confirmée', mois: '2030-06-01', facon: 'facture', parts: [d.k], confirme: true })
    await ligneDuMois(d, { libelle: 'Un loyer fixe', mois: '2030-06-01', facon: 'fixe', parts: [d.k] })
    await ligneDuMois(d, { libelle: 'Mois en cours', mois: '2030-07-01', facon: 'facture', parts: [d.k] })
    await active(d.k.userId, 'confirmer_les_charges')
    await active(d.t.userId, 'confirmer_les_charges')
    const ids = [d.k.userId, d.t.userId]

    expect(await du('2030-07-01T06:59:00Z', ids), '8 h 59').toEqual([])
    const dus = await du(PREMIER_9H, ids)
    expect(dus.map(x => x.user_id).sort()).toEqual([...ids].sort())
    const kamil = dus.find(x => x.user_id === d.k.userId)!
    const lea = dus.find(x => x.user_id === d.t.userId)!
    expect(kamil.cle).toBe('2030-06')
    expect(kamil.donnees.n).toBe(2)
    expect((kamil.donnees.lignes as any[]).map(l => l.libelle)).toEqual(['Électricité', 'Internet'])
    expect(lea.donnees.n, 'Léa ne porte que la moitié d’Internet').toBe(1)
    expect(await du('2030-07-02T07:00:00Z', ids), 'le 2, ce n’est plus le jour').toEqual([])
  })

  it('rien si le mois est déjà clôturé', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Électricité', mois: '2030-06-01', facon: 'facture', parts: [d.k] })
    await active(d.k.userId, 'confirmer_les_charges')
    expect(await du(PREMIER_9H, [d.k.userId])).toHaveLength(1)
    ou(await db.from('cloture').insert({ household_id: d.k.householdId, mois: '2030-06-01', cloture_le: '2030-07-01T08:00:00Z' }).select())
    expect(await du(PREMIER_9H, [d.k.userId])).toEqual([])
  })

  it('à l’heure de Paris : 9 h d’hiver est 8 h UTC', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Électricité', mois: '2030-11-01', facon: 'facture', parts: [d.k] })
    await active(d.k.userId, 'confirmer_les_charges')
    expect(await du('2030-12-01T07:59:00Z', [d.k.userId])).toEqual([])
    expect(await du('2030-12-01T08:00:00Z', [d.k.userId])).toHaveLength(1)
  })
})

describe('cloturer_le_mois : le dernier jour à 19 h, si le mois n’est pas clos', () => {
  const FIN_19H = '2030-06-30T17:00:00Z'
  it('dû pour qui a un revenu, une part et un mois ouvert', async () => {
    const d = await duo()          // Léa n'a pas de revenu
    await ligneDuMois(d, { libelle: 'Électricité', mois: '2030-06-01', facon: 'facture', parts: [d.k, d.t] })
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2030-06-01', facon: 'fixe', parts: [d.k, d.t] })
    await active(d.k.userId, 'cloturer_le_mois')
    await active(d.t.userId, 'cloturer_le_mois')
    const ids = [d.k.userId, d.t.userId]

    expect(await du('2030-06-30T16:59:00Z', ids), '18 h 59').toEqual([])
    const dus = await du(FIN_19H, ids)
    expect(dus.map(x => x.user_id), 'Léa n’a pas posé de revenu : on ne lui parle pas de clôture').toEqual([d.k.userId])
    expect(dus[0].cle).toBe('2030-06')
    expect(dus[0].donnees.lignes).toBe(2)
    expect(dus[0].donnees.a_confirmer).toBe(1)
    expect(await du('2030-06-29T17:00:00Z', ids), 'l’avant-dernier jour').toEqual([])
  })

  it('rien si le mois est clos, ou s’il n’a aucune ligne', async () => {
    const d = await duo()
    await active(d.k.userId, 'cloturer_le_mois')
    expect(await du(FIN_19H, [d.k.userId]), 'aucune ligne').toEqual([])
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2030-06-01', facon: 'fixe', parts: [d.k] })
    expect(await du(FIN_19H, [d.k.userId])).toHaveLength(1)
    ou(await db.from('cloture').insert({ household_id: d.k.householdId, mois: '2030-06-01', cloture_le: '2030-06-30T10:00:00Z' }).select())
    expect(await du(FIN_19H, [d.k.userId])).toEqual([])
  })

  it('février, le 28 : le dernier jour change avec le mois', async () => {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2030-02-01', facon: 'fixe', parts: [d.k] })
    await active(d.k.userId, 'cloturer_le_mois')
    expect(await du('2030-02-28T18:00:00Z', [d.k.userId])).toHaveLength(1)   // 19 h CET
    expect(await du('2030-02-27T18:00:00Z', [d.k.userId])).toEqual([])
  })
})

describe('facture_annuelle : 15 jours avant le mois où la charge se paie', () => {
  async function chargeAnnuelle(d: Duo, payeLe: string, o: { parts?: Actor[] } = {}) {
    const charge = await poseCharge(d.k, {
      libelle: `Taxe foncière ${++n}`, cents: 145_000, mode: 'mis_de_cote', periodicite: 'annuel',
      participants: (o.parts ?? [d.k]).map(p => p.userId),
    })
    ou(await db.from('facture').insert({
      id: randomUUID(), household_id: d.k.householdId, charge_id: charge, annee: Number(payeLe.slice(0, 4)),
      paye_le: payeLe, montant_cents: 142_000, origine: 'saisie', saisi_par: d.k.userId,
    }).select())
    return charge
  }

  it('dû le 17 août pour une facture payée en septembre l’an dernier', async () => {
    const d = await duo()
    const charge = await chargeAnnuelle(d, '2029-09-14')
    await active(d.k.userId, 'facture_annuelle')
    await active(d.t.userId, 'facture_annuelle')
    const ids = [d.k.userId, d.t.userId]

    expect(await du('2030-08-17T06:59:00Z', ids), '8 h 59').toEqual([])
    const dus = await du('2030-08-17T07:00:00Z', ids)
    expect(dus.map(x => x.user_id), 'seuls les participants de la charge').toEqual([d.k.userId])
    expect(dus[0].cle, 'la clé est la date').toBe('2030-08-17')
    expect(dus[0].cles).toEqual(['2030-08-17', `${charge}:2030`])
    expect(dus[0].donnees.n).toBe(1)
    const c = (dus[0].donnees.charges as any[])[0]
    expect(c.mois).toBe('2030-09-01')
    expect(c.derniere_montant_cents).toBe(142_000)
    expect(await du('2030-08-16T07:00:00Z', ids), 'la veille').toEqual([])
    expect(await du('2030-08-18T07:00:00Z', ids), 'le lendemain').toEqual([])
  })

  it('rien si la facture de l’année est déjà saisie, ni sans facture passée', async () => {
    const d = await duo()
    const charge = await chargeAnnuelle(d, '2029-09-14')
    await active(d.k.userId, 'facture_annuelle')
    expect(await du('2030-08-17T07:00:00Z', [d.k.userId])).toHaveLength(1)
    ou(await db.from('facture').insert({
      id: randomUUID(), household_id: d.k.householdId, charge_id: charge, annee: 2030,
      paye_le: '2030-08-01', montant_cents: 150_000, origine: 'saisie', saisi_par: d.k.userId,
    }).select())
    expect(await du('2030-08-17T07:00:00Z', [d.k.userId]), 'déjà payée cette année').toEqual([])

    const e = await duo()
    await poseCharge(e.k, { libelle: 'Sans histoire', cents: 100_000, mode: 'mis_de_cote', periodicite: 'annuel' })
    await active(e.k.userId, 'facture_annuelle')
    expect(await du('2030-08-17T07:00:00Z', [e.k.userId]), 'aucune facture passée : pas de mois connu').toEqual([])
  })

  it('un mois de janvier se prévient en décembre, sous la clé de l’année suivante', async () => {
    const d = await duo()
    const charge = await chargeAnnuelle(d, '2029-01-20')
    await active(d.k.userId, 'facture_annuelle')
    const dus = await du('2030-12-17T08:00:00Z', [d.k.userId])   // 9 h CET
    expect(dus).toHaveLength(1)
    expect(dus[0].cles).toEqual(['2030-12-17', `${charge}:2031`])
    expect((dus[0].donnees.charges as any[])[0].mois).toBe('2031-01-01')
  })

  it('deux charges le même jour : UN mail par membre, les deux listées, les deux réservées avec la date', async () => {
    const d = await duo()
    const a = await chargeAnnuelle(d, '2029-09-14')
    const b = await chargeAnnuelle(d, '2029-09-20')
    await chargeAnnuelle(d, '2029-10-02')   // un autre mois : pas ce jour-là
    await active(d.k.userId, 'facture_annuelle')
    const dus = await du('2030-08-17T07:00:00Z', [d.k.userId])
    expect(dus).toHaveLength(1)
    expect(dus[0].donnees.n).toBe(2)
    expect((dus[0].donnees.charges as any[]).map(c => c.charge_id).sort()).toEqual([a, b].sort())
    expect(dus[0].cles).toHaveLength(3)
    expect((await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'facture_annuelle', p_cles: dus[0].cles })).data).toBe(true)
    expect(await du('2030-08-17T07:00:00Z', [d.k.userId]), 'réservé : plus rien').toEqual([])
  })

  it('une charge retirée n’est plus annoncée', async () => {
    const d = await duo()
    const charge = await chargeAnnuelle(d, '2029-09-14')
    await active(d.k.userId, 'facture_annuelle')
    ou(await db.from('charge').update({ archive_le: '2030-01-01T00:00:00Z' }).eq('id', charge).select())
    expect(await du('2030-08-17T07:00:00Z', [d.k.userId])).toEqual([])
  })
})

describe('jamais deux fois', () => {
  async function unDu() {
    const d = await duo()
    const wrap = await portion(d.k.householdId, { label: 'Wraps', lieu: 'congelateur' })
    await repas(d.k.householdId, d.k.userId, '2030-06-12', 'diner', wrap.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    return d
  }

  it('réservé, un rappel n’est plus dû ; libéré après un échec d’envoi, il l’est de nouveau', async () => {
    const d = await unDu()
    const [x] = await du(MARDI_19H, [d.k.userId])
    const r = await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: x.type, p_cles: x.cles })
    expect(r.data).toBe(true)
    expect(await du(MARDI_19H, [d.k.userId]), 'déjà parti').toEqual([])
    expect((await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: x.type, p_cles: x.cles })).data, 'une seconde réservation').toBe(false)

    expect((await db.rpc('libere_rappel', { p_user: d.k.userId, p_type: x.type, p_cles: x.cles })).error).toBeNull()
    expect(await du(MARDI_19H, [d.k.userId]), 'l’heure suivante réessaie').toHaveLength(1)
  })

  it('sept passages en même temps : un seul gagne', async () => {
    const d = await unDu()
    const essais = await Promise.all(Array.from({ length: 7 }, () =>
      db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'sortir_du_congelateur', p_cles: ['2030-06-12'] })))
    expect(essais.every(e => e.error === null)).toBe(true)
    expect(essais.filter(e => e.data === true)).toHaveLength(1)
    const lignes = ou(await db.from('rappel_envoye').select('cle').eq('user_id', d.k.userId))
    expect(lignes).toHaveLength(1)
  })

  it('une clé déjà prise : aucune des autres n’est posée', async () => {
    const d = await unDu()
    ou(await db.from('rappel_envoye').insert({ user_id: d.k.userId, type: 'barquette_perime', cle: 'b' }).select())
    const r = await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'barquette_perime', p_cles: ['a', 'b', 'c'] })
    expect(r.data).toBe(false)
    const lignes = ou(await db.from('rappel_envoye').select('cle').eq('user_id', d.k.userId).eq('type', 'barquette_perime'))
    expect(lignes.map((l: any) => l.cle)).toEqual(['b'])
  })

  it('la réservation est celle du membre : l’autre membre reçoit son propre mail', async () => {
    const d = await duo()
    const wrap = await portion(d.k.householdId, { label: 'Wraps', lieu: 'congelateur' })
    await repas(d.k.householdId, d.k.userId, '2030-06-12', 'diner', wrap.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    await active(d.t.userId, 'sortir_du_congelateur')
    expect((await db.rpc('reserve_rappel', { p_user: d.k.userId, p_type: 'sortir_du_congelateur', p_cles: ['2030-06-12'] })).data).toBe(true)
    expect((await du(MARDI_19H, [d.k.userId, d.t.userId])).map(x => x.user_id)).toEqual([d.t.userId])
  })

  it('les types du schéma sont ceux de l’écran', async () => {
    const d = await duo()
    for (const t of TYPES) await active(d.k.userId, t)
    const lus = ou(await d.k.client.from('rappel_reglage').select('type').order('type')) as { type: string }[]
    expect(lus.map(l => l.type).sort()).toEqual([...TYPES].sort())
  })
})


// ═══ La revue du chantier 5 ═══════════════════════════════════════════════════════════════════════════════

/** Les lignes de budget d'un foyer, tous mois confondus. */
async function lignesDuFoyer(foyer: string, mois?: string) {
  let q = db.from('depense').select('id, mois, libelle, facon').eq('household_id', foyer)
  if (mois) q = q.eq('mois', mois)
  return ou(await q) as { id: string; mois: string; libelle: string; facon: string }[]
}
async function prepare(iso: string) {
  const r = await db.rpc('prepare_les_rappels', { p_maintenant: iso })
  expect(r.error, r.error?.message).toBeNull()
  return r.data as { purges: number; foyers: number; lignes_nees: number; erreurs: number }
}

describe('M1 : les rappels du budget voient un mois que personne n’a ouvert', () => {
  const PREMIER_9H = '2030-07-01T07:00:00Z'
  const DIM_20H = '2030-06-09T18:00:00Z'
  const FIN_19H = '2030-06-30T17:00:00Z'

  it('confirmer_les_charges : sans préparation rien ; après, la facture du mois fini est là (lignes NON posées à la main)', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Électricité', cents: 10_000, mode: 'facture', participants: [d.k.userId] })
    await poseCharge(d.k, { libelle: 'Loyer', cents: 90_000, mode: 'fixe', participants: [d.k.userId] })
    await active(d.k.userId, 'confirmer_les_charges')
    expect(await lignesDuFoyer(d.k.householdId), 'aucune ligne : personne n’a ouvert le mois').toEqual([])
    expect(await du(PREMIER_9H, [d.k.userId]), 'le mois n’est pas ouvert : le rappel ne voit rien').toEqual([])

    const r = await prepare(PREMIER_9H)
    expect(r.foyers).toBeGreaterThan(0)
    expect(r.erreurs).toBe(0)
    expect((await lignesDuFoyer(d.k.householdId, '2030-06-01')).map(l => l.libelle).sort()).toEqual(['Loyer', 'Électricité'].sort())
    expect((await lignesDuFoyer(d.k.householdId, '2030-07-01')).length, 'le mois en cours aussi').toBe(2)

    const [x] = await du(PREMIER_9H, [d.k.userId])
    expect(x.type).toBe('confirmer_les_charges')
    expect(x.donnees.n).toBe(1)
    expect((x.donnees.lignes as any[]).map(l => l.libelle)).toEqual(['Électricité'])
  })

  it('l’ouverture est idempotente : une seconde passe ne crée rien', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Électricité', cents: 10_000, mode: 'facture' })
    await active(d.k.userId, 'confirmer_les_charges')
    await prepare(PREMIER_9H)
    const avant = await lignesDuFoyer(d.k.householdId)
    await prepare(PREMIER_9H)
    expect((await lignesDuFoyer(d.k.householdId)).map(l => l.id).sort()).toEqual(avant.map(l => l.id).sort())
  })

  it('noter_les_depenses : la ligne « au fil » du mois en cours naît, le dimanche à 20 h', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Courses', cents: 50_000, mode: 'au_fil', participants: [d.k.userId] })
    await active(d.k.userId, 'noter_les_depenses')
    expect(await du(DIM_20H, [d.k.userId])).toEqual([])
    await prepare(DIM_20H)
    const [x] = await du(DIM_20H, [d.k.userId])
    expect(x.type).toBe('noter_les_depenses')
    expect(x.donnees.lignes).toBe(1)
  })

  it('cloturer_le_mois : le dernier jour, le mois jamais ouvert est ouvert, puis annoncé', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Loyer', cents: 90_000, mode: 'fixe', participants: [d.k.userId] })
    await active(d.k.userId, 'cloturer_le_mois')
    expect(await du(FIN_19H, [d.k.userId])).toEqual([])
    await prepare(FIN_19H)
    const [x] = await du(FIN_19H, [d.k.userId])
    expect(x.cle).toBe('2030-06')
    expect(x.donnees.lignes).toBe(1)
  })

  it('un foyer où personne n’a activé de rappel du budget n’est PAS touché', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Électricité', cents: 10_000, mode: 'facture' })
    await active(d.k.userId, 'sortir_du_congelateur')   // un rappel de cuisine : ne justifie pas d'ouvrir un mois
    await prepare(PREMIER_9H)
    expect(await lignesDuFoyer(d.k.householdId)).toEqual([])
  })

  it('un mois clôturé ne gagne aucune ligne', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Électricité', cents: 10_000, mode: 'facture' })
    await clos(d.k, '2030-06-01')
    await active(d.k.userId, 'confirmer_les_charges')
    await prepare(PREMIER_9H)
    expect(await lignesDuFoyer(d.k.householdId, '2030-06-01')).toEqual([])
    expect((await lignesDuFoyer(d.k.householdId, '2030-07-01')).length).toBe(1)
  })

  it('un membre sans adresse confirmée n’ouvre rien (il n’est pas joignable)', async () => {
    const d = await duo()
    await poseCharge(d.k, { libelle: 'Électricité', cents: 10_000, mode: 'facture' })
    await active(d.k.userId, 'confirmer_les_charges')
    const c = await connexion(URL_PG_ADMIN)
    try { await c.query('update auth.users set email_confirmed_at = null where id = $1', [d.k.userId]) } finally { await c.end() }
    await prepare(PREMIER_9H)
    expect(await lignesDuFoyer(d.k.householdId)).toEqual([])
  })

  it('réservée au rôle de service', async () => {
    const d = await duo()
    expect((await d.k.client.rpc('prepare_les_rappels', { p_maintenant: PREMIER_9H })).error).not.toBeNull()
    expect((await d.k.client.rpc('note_la_passe', { p_statut: 'ok', p_dus: 0, p_envoyes: 0, p_echecs: 0 })).error).not.toBeNull()
    expect((await d.k.client.rpc('rappel_prenom', { p_nom: 'x', p_repli: 'y' })).error).not.toBeNull()
  })
})

describe('M4 : une panne se voit', () => {
  it('note_la_passe écrit une ligne sans adresse ni contenu ; le statut est contrôlé ; le client ne la lit pas', async () => {
    const d = await duo()
    const avant = ou(await db.from('rappel_passe').select('id').eq('origine', 'fonction')).length
    ou(await db.rpc('note_la_passe', { p_statut: 'echecs', p_dus: 3, p_envoyes: 2, p_echecs: 1 }))
    const lues = ou(await db.from('rappel_passe').select('*').eq('origine', 'fonction').order('id', { ascending: false }).limit(1)) as any[]
    expect(ou(await db.from('rappel_passe').select('id').eq('origine', 'fonction')).length).toBe(avant + 1)
    expect(lues[0]).toMatchObject({ origine: 'fonction', statut: 'echecs', dus: 3, envoyes: 2, echecs: 1 })
    expect(Object.keys(lues[0]).sort()).toEqual(['dus', 'echecs', 'envoyes', 'id', 'le', 'origine', 'statut'])
    expect((await db.rpc('note_la_passe', { p_statut: 'n’importe quoi', p_dus: 0, p_envoyes: 0, p_echecs: 0 })).error).not.toBeNull()
    const lu = await d.k.client.from('rappel_passe').select('*')
    expect(lu.error || lu.data!.length === 0, 'un membre lit le journal').toBeTruthy()
  })

  it('appelle_les_rappels laisse une ligne : sans secret, « sans_secret » ; avec, « appelee », délai de 60 s', async () => {
    const c = await connexion()
    try {
      await c.query('begin')
      await c.query('delete from public.rappel_passe where origine = $1', ['cron'])
      await c.query('select public.appelle_les_rappels()')
      let l = (await c.query(`select statut, dus from public.rappel_passe where origine = 'cron' order by id desc limit 1`)).rows[0]
      expect(l.statut).toBe('sans_secret')
      expect(l.dus).toBeNull()

      await c.query(`select vault.create_secret('http://127.0.0.1:9/rappels', 'rappels_url')`)
      await c.query(`select vault.create_secret('un-secret-de-test', 'rappels_secret')`)
      await c.query('select public.appelle_les_rappels()')
      l = (await c.query(`select statut from public.rappel_passe where origine = 'cron' order by id desc limit 1`)).rows[0]
      expect(l.statut).toBe('appelee')
      const file = (await c.query(`select timeout_milliseconds from net.http_request_queue order by id desc limit 1`)).rows[0]
      expect(file.timeout_milliseconds, 'le délai de pg_net est de 60 s').toBe(60_000)
      // Aucune adresse ni secret dans le journal.
      const colonnes = (await c.query(`select * from public.rappel_passe where origine = 'cron' limit 1`)).rows[0]
      expect(JSON.stringify(colonnes)).not.toMatch(/127\.0\.0\.1|un-secret/)
    } finally {
      await c.query('rollback').catch(() => {})
      await c.end()
    }
  })

  it('le job existe dans cron.job ; la migration le contrôle en fin de fichier (avertissement explicite s’il manque)', async () => {
    const c = await connexion()
    try {
      const r = await c.query(`select schedule from cron.job where jobname = 'rappels-par-mail'`)
      expect(r.rows).toEqual([{ schedule: '5 * * * *' }])
    } finally { await c.end() }
    const sql = readFileSync(new URL('../../supabase/migrations/0126_rappels.sql', import.meta.url), 'utf8')
    expect(sql).toMatch(/raise warning\s+'LES RAPPELS NE SONT PAS PLANIFIÉS/)
    expect(sql).toContain("jobname = 'rappels-par-mail'")
  })

  it('la passe purge ce qui a plus de 120 jours (et rien de plus récent)', async () => {
    const d = await duo()
    ou(await db.from('rappel_envoye').insert([
      { user_id: d.k.userId, type: 'sortir_du_congelateur', cle: 'vieux', envoye_le: '2030-01-01T10:00:00Z' },
      { user_id: d.k.userId, type: 'sortir_du_congelateur', cle: 'recent', envoye_le: '2030-06-01T10:00:00Z' },
    ]).select())
    ou(await db.from('rappel_passe').insert([
      { origine: 'cron', statut: 'appelee', le: '2030-01-01T10:00:00Z' }, { origine: 'cron', statut: 'appelee', le: '2030-06-10T10:00:00Z' },
    ]).select())
    const r = await prepare('2030-06-11T06:00:00Z')
    expect(r.purges).toBeGreaterThanOrEqual(1)
    const reste = (ou(await db.from('rappel_envoye').select('cle').eq('user_id', d.k.userId)) as { cle: string }[]).map(x => x.cle)
    expect(reste).toEqual(['recent'])
    const passes = ou(await db.from('rappel_passe').select('le').lt('le', '2030-06-11T00:00:00Z').gt('le', '2029-12-31T00:00:00Z')) as { le: string }[]
    expect(passes.map(x => x.le.slice(0, 10)), 'les vieilles lignes du journal sont parties').not.toContain('2030-01-01')
    expect(passes.map(x => x.le.slice(0, 10))).toContain('2030-06-10')
  })
})

describe('L6 : les droits de table', () => {
  it('ni truncate, ni references, ni trigger pour anon et authenticated sur les trois tables', async () => {
    const c = await connexion()
    try {
      for (const t of ['rappel_reglage', 'rappel_envoye', 'rappel_passe']) {
        for (const role of ['anon', 'authenticated']) {
          for (const droit of ['TRUNCATE', 'REFERENCES', 'TRIGGER']) {
            const r = await c.query('select has_table_privilege($1, $2, $3) as ok', [role, `public.${t}`, droit])
            expect(r.rows[0].ok, `${role} ${droit} ${t}`).toBe(false)
          }
        }
      }
      // Ce que la RLS borne reste permis à authenticated sur les réglages ; rien sur le reste.
      for (const droit of ['SELECT', 'INSERT', 'UPDATE', 'DELETE']) {
        expect((await c.query(`select has_table_privilege('authenticated', 'public.rappel_reglage', $1) as ok`, [droit])).rows[0].ok, droit).toBe(true)
        expect((await c.query(`select has_table_privilege('authenticated', 'public.rappel_envoye', $1) as ok`, [droit])).rows[0].ok, droit).toBe(false)
        expect((await c.query(`select has_table_privilege('authenticated', 'public.rappel_passe', $1) as ok`, [droit])).rows[0].ok, droit).toBe(false)
      }
    } finally { await c.end() }
  })
})

describe('L7 : les prénoms, normalisés partout', () => {
  async function demain() {
    const d = await duo()
    const f = d.k.householdId
    const w1 = await portion(f, { label: 'Wrap', lieu: 'congelateur' })
    const w2 = await portion(f, { label: 'Wrap', lieu: 'congelateur' })
    await repas(f, d.k.userId, '2030-06-12', 'diner', w1.id)
    await repas(f, d.t.userId, '2030-06-12', 'diner', w2.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    return d
  }
  const nom = async (id: string, display_name: string) => ou(await db.from('user_profile').update({ display_name }).eq('id', id).select())

  it('le destinataire : premier mot, blancs retirés ; vide → « toi »', async () => {
    const d = await demain()
    await nom(d.k.userId, '  Kamil   Bentounes ')
    expect((await du(MARDI_19H, [d.k.userId]))[0].prenom).toBe('Kamil')
    await nom(d.k.userId, '   ')
    const [x] = await du(MARDI_19H, [d.k.userId])
    expect(x.prenom).toBe('toi')
    // Lui-même, dans « pour qui », porte le prénom que le mail lui donne.
    const pour = ((x.donnees.plats as any[])[0].repas as any[])[0].pour as string[]
    expect(pour.sort()).toEqual(['Léa', 'toi'].sort())
  })

  it('l’AUTRE membre : un nom piégé arrive tel quel (premier mot), vide → « Quelqu’un » — l’échappement est celui du gabarit', async () => {
    const d = await demain()
    await nom(d.t.userId, '<img src=x onerror=alert(1)> Dupont')
    let [x] = await du(MARDI_19H, [d.k.userId])
    let pour = ((x.donnees.plats as any[])[0].repas as any[])[0].pour as string[]
    expect(pour.sort()).toEqual(['<img', 'Kamil'].sort())
    await nom(d.t.userId, '  ')
    ;[x] = await du(MARDI_19H, [d.k.userId])
    pour = ((x.donnees.plats as any[])[0].repas as any[])[0].pour as string[]
    expect(pour.sort()).toEqual(['Kamil', 'Quelqu’un'].sort())
    // Et le mail, bâti avec ces données EXACTES, échappe le nom de l'autre.
    await nom(d.t.userId, '<img src=x onerror=alert(1)> Dupont')
    ;[x] = await du(MARDI_19H, [d.k.userId])
    const { construis } = await import('../../supabase/functions/_shared/rappels/mails.ts')
    const m = construis(x.type, x.donnees, { base: 'https://exemple.test/app', maintenant: new Date(MARDI_19H), prenom: 'Léa' })
    expect(m.html).not.toContain('<img src=x')
    expect(m.html).toContain('&lt;img')
  })
})

describe('L8 : clôturer — le revenu d’un autre membre', () => {
  const FIN_19H = '2030-06-30T17:00:00Z'
  async function leMois(o: { revenuLea?: boolean; arriveeLea?: string } = {}) {
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2030-06-01', facon: 'fixe', parts: [d.k, d.t] })
    await active(d.k.userId, 'cloturer_le_mois')
    if (o.revenuLea) {
      ou(await db.from('revenu').insert({
        household_id: d.k.householdId, user_profile_id: d.t.userId, net_mensuel_cents: 250_000, valid_from: '2030-01-01',
      }).select())
    }
    if (o.arriveeLea) ou(await db.from('user_profile').update({ entre_le: o.arriveeLea }).eq('id', d.t.userId).select())
    return d
  }

  it('Léa n’a pas posé son revenu : le mail le sait (« absent »), comme la clôture le refusera', async () => {
    const d = await leMois()
    const [x] = await du(FIN_19H, [d.k.userId])
    expect(x.donnees.absent).toBe('Léa')
    // C'est la garde de `cloture_le_mois` (0108) : « Léa n'a pas encore posé son revenu : juin attend. »
    const garde = readFileSync(new URL('../../supabase/migrations/0108_budget_cloture.sql', import.meta.url), 'utf8')
    expect(garde).toContain("n''a pas encore posé son revenu")
  })

  it('son revenu posé, plus d’absent', async () => {
    const d = await leMois({ revenuLea: true })
    const [x] = await du(FIN_19H, [d.k.userId])
    expect(x.donnees.absent).toBeNull()
  })

  it('arrivée après la fin du mois : elle ne compte pas', async () => {
    // Un mois fini avant l'arrivée de Léa (la base borne les arrivées à l'avenir proche : on joue en septembre 2026).
    const d = await duo()
    await ligneDuMois(d, { libelle: 'Loyer', mois: '2026-09-01', facon: 'fixe', parts: [d.k] })
    await active(d.k.userId, 'cloturer_le_mois')
    const fin = '2026-09-30T17:00:00Z'
    expect((await du(fin, [d.k.userId]))[0].donnees.absent, 'elle est là en septembre').toBe('Léa')
    ou(await db.from('user_profile').update({ entre_le: '2026-10-15' }).eq('id', d.t.userId).select())
    expect((await du(fin, [d.k.userId]))[0].donnees.absent, 'elle arrive en octobre').toBeNull()
  })
})

describe('L9 : qui est joignable', () => {
  async function unDu() {
    const d = await duo()
    const wrap = await portion(d.k.householdId, { label: 'Wraps', lieu: 'congelateur' })
    await repas(d.k.householdId, d.k.userId, '2030-06-12', 'diner', wrap.id)
    await active(d.k.userId, 'sortir_du_congelateur')
    expect(await du(MARDI_19H, [d.k.userId])).toHaveLength(1)
    return d
  }
  const sql = async (requete: string, params: unknown[]) => {
    const c = await connexion(URL_PG_ADMIN)
    try { await c.query(requete, params) } finally { await c.end() }
  }

  it('un compte banni (dans le futur) ne reçoit rien ; un ban échu, si', async () => {
    const d = await unDu()
    await sql(`update auth.users set banned_until = now() + interval '1 day' where id = $1`, [d.k.userId])
    expect(await du(MARDI_19H, [d.k.userId])).toEqual([])
    await sql(`update auth.users set banned_until = now() - interval '1 day' where id = $1`, [d.k.userId])
    expect(await du(MARDI_19H, [d.k.userId])).toHaveLength(1)
  })

  it('un compte supprimé ne reçoit rien', async () => {
    const d = await unDu()
    await sql('update auth.users set deleted_at = now() where id = $1', [d.k.userId])
    expect(await du(MARDI_19H, [d.k.userId])).toEqual([])
  })

  it('une adresse non confirmée ne reçoit rien', async () => {
    const d = await unDu()
    await sql('update auth.users set email_confirmed_at = null where id = $1', [d.k.userId])
    expect(await du(MARDI_19H, [d.k.userId])).toEqual([])
  })
})
