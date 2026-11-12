/**
 * Ce que la migration 0092 doit tenir : la photo, les gestes, « avec ce que j'ai ».
 *
 * Trois règles, et chacune a un défaut symétrique qu'il faut aussi attraper : la
 * photo fermée aux foyers ne doit pas fermer la correction du titre ; les gestes
 * ajoutés ne doivent rien changer aux recettes sans gestes mesurés ; le placard
 * d'un foyer ne doit pas rendre faisable la recette d'un autre.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createClient } from '@supabase/supabase-js'
import { admin, makeActor, type Actor } from './helpers/db'
import { tempsActif } from './front-fige/lib/recettes/temps.ts'

let alice: Actor
let bob: Actor
const unique = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`

/** Une recette du catalogue, propre au banc (`surcharge` : de quoi la faire autre). */
async function recette(surcharge: Record<string, unknown> = {}) {
  const { data, error } = await admin().from('recipe').insert({
    title: `Banc 0092 ${unique()}`, origin: 'importee', yield_servings: 4,
    plannable: true, source_url: `https://exemple.test/${unique()}`, ...surcharge,
  }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  return data!
}

async function actif(id: string) {
  const { data } = await admin().from('recipe').select('active_time_min').eq('id', id).single()
  return Number(data!.active_time_min)
}

beforeAll(async () => {
  alice = await makeActor('recettes-0092-alice')
  bob = await makeActor('recettes-0092-bob')
})

/** Le banc partage la base locale : il rend TOUT ce qu'il a semé. Étapes et lignes
    partent avec leur recette (cascade) ; le placard a son foyer, pas la recette ;
    le compte emporte son profil, et le foyer ne se supprime qu'une fois vidé de
    ses recettes et de son placard. Une erreur ici fait échouer le banc : un
    nettoyage qui se tait laisse huit foyers par passage. */
afterAll(async () => {
  const foyers = [alice.householdId, bob.householdId]
  const rendre = (quoi: string, error: { message: string } | null) => {
    if (error) throw new Error(`le banc n’a pas rendu ${quoi} : ${error.message}`)
  }
  rendre('le placard', (await admin().from('stock_item').delete().in('household_id', foyers)).error)
  rendre('les recettes', (await admin().from('recipe').delete().like('title', 'Banc 0092 %')).error)
  for (const a of [alice, bob])
    rendre(`le compte ${a.email}`, (await admin().auth.admin.deleteUser(a.userId)).error)
  rendre('les foyers', (await admin().from('household').delete().in('id', foyers)).error)
})

describe('la photo (R3)', () => {
  it('s’écrit par le rôle de service, en https', async () => {
    const r = await recette()
    const { error } = await admin().from('recipe')
      .update({ image_url: 'https://img.exemple.test/p.jpg' }).eq('id', r.id)
    expect(error).toBeNull()
  })

  it('refuse une adresse qui n’est pas en https', async () => {
    const r = await recette()
    for (const adresse of ['http://img.exemple.test/p.jpg', 'javascript:alert(1)',
      'data:image/png;base64,AAAA']) {
      const { error } = await admin().from('recipe').update({ image_url: adresse }).eq('id', r.id)
      expect(error, `${adresse} a été acceptée`).not.toBeNull()
    }
  })

  it('ne se pose pas par un foyer sur le catalogue, qui reste corrigeable', async () => {
    const r = await recette()
    const { error } = await alice.client.from('recipe')
      .update({ image_url: 'https://pistage.test/pixel.gif' }).eq('id', r.id)
    expect(error, 'un foyer a posé la photo du catalogue').not.toBeNull()

    const { data: corrigee, error: e2 } = await alice.client.from('recipe')
      .update({ title: 'Banc 0092 corrigé' }).eq('id', r.id).select('title').single()
    expect(e2, 'la garde de la photo a fermé la correction du titre').toBeNull()
    expect(corrigee?.title, 'la correction n’a rien écrit').toBe('Banc 0092 corrigé')
  })

  it('ne se pose pas non plus à la création d’une recette de foyer', async () => {
    const { error } = await alice.client.from('recipe').insert({
      title: 'Collée avec une photo', origin: 'manuelle',
      owner_household_id: alice.householdId, image_url: 'https://pistage.test/pixel.gif',
    })
    expect(error, 'une recette collée a posé sa propre photo').not.toBeNull()
  })

  it('laisse un foyer créer sa recette sans photo', async () => {
    const { data, error } = await alice.client.from('recipe').insert({
      title: 'Collée sans photo', origin: 'manuelle', owner_household_id: alice.householdId,
    }).select('id').single()
    expect(error).toBeNull()
    await admin().from('recipe').delete().eq('id', data!.id)
  })
})

describe('la source du catalogue, qui garde la photo (R3)', () => {
  it('ne se réécrit pas par un foyer, ni l’adresse ni le nom', async () => {
    const r = await recette({ source_name: 'Exemple' })
    for (const champs of [
      { source_url: 'http://169.254.169.254/latest/meta-data/' },
      { source_name: 'Un autre site' },
    ]) {
      const { data, error } = await alice.client.from('recipe')
        .update(champs).eq('id', r.id).select('id')
      expect(error, `un foyer a réécrit la source du catalogue : ${JSON.stringify(champs)}`)
        .not.toBeNull()
      expect(error?.code).toBe('23514')
      expect(data ?? []).toHaveLength(0)
    }
    const { data: relue } = await admin().from('recipe')
      .select('source_url, source_name').eq('id', r.id).single()
    expect(relue, 'la source du catalogue a bougé malgré le refus')
      .toEqual({ source_url: r.source_url, source_name: 'Exemple' })
  })

  it('laisse un foyer corriger le titre, et le rôle de service la source', async () => {
    const r = await recette({ source_name: 'Exemple' })
    const { error: e1 } = await alice.client.from('recipe')
      .update({ title: 'Banc 0092 retitré' }).eq('id', r.id)
    expect(e1, 'la garde de la source a fermé la correction du titre').toBeNull()

    const nouvelle = `https://exemple.test/${unique()}`
    const { error: e2 } = await admin().from('recipe')
      .update({ title: 'Banc 0092 par le service', source_url: nouvelle, source_name: 'Autre' })
      .eq('id', r.id)
    expect(e2, 'le rôle de service ne peut plus écrire la source').toBeNull()
    const { data: relue } = await admin().from('recipe')
      .select('title, source_url, source_name').eq('id', r.id).single()
    expect(relue).toEqual({
      title: 'Banc 0092 par le service', source_url: nouvelle, source_name: 'Autre',
    })
  })

  it('laisse un foyer corriger la source de SA recette', async () => {
    const { data, error } = await alice.client.from('recipe').insert({
      title: 'Banc 0092 sienne', origin: 'manuelle', owner_household_id: alice.householdId,
      source_url: `https://exemple.test/${unique()}`, source_name: 'Avant',
    }).select('id').single()
    expect(error).toBeNull()
    const nouvelle = `https://exemple.test/${unique()}`
    const { error: e2 } = await alice.client.from('recipe')
      .update({ source_url: nouvelle, source_name: 'Après' }).eq('id', data!.id)
    expect(e2, 'la garde du catalogue a fermé la source d’une recette de foyer').toBeNull()
    const { data: relue } = await admin().from('recipe')
      .select('source_url, source_name').eq('id', data!.id).single()
    expect(relue).toEqual({ source_url: nouvelle, source_name: 'Après' })
  })
})

describe('le temps actif compte au moins les gestes (R6)', () => {
  async function etapes(id: string, lignes: Record<string, unknown>[]) {
    const { error } = await admin().from('recipe_step').insert(lignes.map((l, i) => ({
      recipe_id: id, ordinal: i + 1, text: `étape ${i + 1}`, ...l,
    })))
    expect(error).toBeNull()
  }

  it('une étape passive compte ses gestes', async () => {
    const r = await recette()
    await etapes(r.id, [{ duration_min: 2, load_type: 'passif', appliance_type: 'blender',
      gesture_min: 1 }])
    expect(await actif(r.id), 'le smoothie compte encore zéro').toBe(1)
  })

  it('une étape active compte ses gestes quand ils dépassent sa durée', async () => {
    const r = await recette()
    await etapes(r.id, [{ duration_min: 4, load_type: 'actif', gesture_min: 7 }])
    expect(await actif(r.id)).toBe(7)
  })

  it('une étape active garde sa durée quand elle dépasse ses gestes', async () => {
    const r = await recette()
    await etapes(r.id, [{ duration_min: 10, load_type: 'actif', gesture_min: 3 }])
    expect(await actif(r.id)).toBe(10)
  })

  it('sans gestes mesurés, rien ne change', async () => {
    const r = await recette()
    await etapes(r.id, [
      { duration_min: 6, load_type: 'actif' },
      { duration_min: 40, load_type: 'passif', appliance_type: 'four' },
      { duration_min: 4, load_type: 'bloquant', appliance_type: 'plaques' },
    ])
    expect(await actif(r.id), 'les recettes non recalculées ont bougé').toBe(10)
  })

  it('dit la même chose que tempsActif(), côté client', async () => {
    const r = await recette()
    const lignes = [
      { load_type: 'actif', duration_min: 4, gesture_min: 7 },
      { load_type: 'bloquant', duration_min: 6, gesture_min: 2 },
      { load_type: 'passif', duration_min: 30, gesture_min: 1.5 },
      { load_type: 'passif', duration_min: 12, gesture_min: null },
      { load_type: 'actif', duration_min: 2.5, gesture_min: null },
    ]
    await etapes(r.id, lignes)
    expect(await actif(r.id)).toBe(tempsActif(lignes))
  })

  it('refuse des gestes négatifs', async () => {
    const r = await recette()
    const { error } = await admin().from('recipe_step').insert({
      recipe_id: r.id, ordinal: 1, text: 'x', duration_min: 1, load_type: 'actif', gesture_min: -1,
    })
    expect(error).not.toBeNull()
  })
})

describe('« avec ce que j’ai » (recettes_faisables)', () => {
  let a1: string
  let a2: string

  beforeAll(async () => {
    const { data } = await admin().from('food').select('id').eq('source', 'ciqual')
      .order('id').limit(2)
    expect(data, 'CIQUAL est vide : lancer `npm run seed`').toHaveLength(2)
    ;[a1, a2] = data!.map(f => f.id)
  })

  async function avecIngredients(aliments: (string | null)[]) {
    const r = await recette()
    const { error } = await admin().from('recipe_ingredient').insert(aliments.map((food_id, i) => ({
      recipe_id: r.id, ordinal: i + 1, raw_text: `ingrédient ${i + 1}`, food_id,
    })))
    expect(error).toBeNull()
    return r.id
  }

  async function auPlacard(qui: Actor, food_id: string) {
    const { error } = await admin().from('stock_item')
      .insert({ household_id: qui.householdId, label: 'banc', food_id })
    expect(error).toBeNull()
  }

  async function faisables(qui: Actor) {
    const { data, error } = await qui.client.rpc('recettes_faisables')
    expect(error).toBeNull()
    return new Set(data as string[])
  }

  it('rend une recette dont chaque ingrédient reconnu est au placard', async () => {
    const id = await avecIngredients([a1, null])
    await auPlacard(alice, a1)
    expect((await faisables(alice)).has(id)).toBe(true)
  })

  it('écarte une recette à qui il manque un aliment', async () => {
    const id = await avecIngredients([a1, a2])
    expect((await faisables(alice)).has(id)).toBe(false)
  })

  it('ne promet rien d’une recette dont aucun ingrédient n’est reconnu', async () => {
    const id = await avecIngredients([null, null])
    expect((await faisables(alice)).has(id)).toBe(false)
  })

  it('ne compte pas le placard d’un autre foyer', async () => {
    const id = await avecIngredients([a2])
    await auPlacard(bob, a2)
    expect((await faisables(bob)).has(id)).toBe(true)
    expect((await faisables(alice)).has(id), 'le placard de Bob a servi à Alice').toBe(false)
  })

  // Ce test ne protège rien tout seul : le plan par défaut rend déjà les
  // identifiants triés, avec ou sans `order by`. Seul un plan forcé (jointures par
  // fusion/boucle, balayages d'index coupés) les désordonne, et PostgREST ne laisse
  // pas poser ces options depuis un client. La garde est le test de la source, plus bas.
  it('rend ses identifiants triés, que le client lit par tranches', async () => {
    await auPlacard(alice, a1)
    for (let i = 0; i < 3; i++) await avecIngredients([a1])
    const { data, error } = await alice.client.rpc('recettes_faisables')
    expect(error).toBeNull()
    const ids = data as string[]
    expect(ids.length).toBeGreaterThan(1)
    expect(ids, 'les tranches du client se chevaucheraient').toEqual([...ids].sort())
  })

  it('trie sa réponse par une clause, pas par la chance du plan (source de la fonction)', () => {
    // La définition en vigueur : la dernière migration qui (re)crée la fonction.
    const dossier = fileURLToPath(new URL('../../supabase/migrations/', import.meta.url))
    const definitions = readdirSync(dossier).filter(f => f.endsWith('.sql')).sort()
      .map(f => readFileSync(dossier + f, 'utf8'))
      .flatMap(sql => [...sql.matchAll(
        /create\s+(?:or\s+replace\s+)?function\s+public\.recettes_faisables\s*\(\)[^$]*\$\$([\s\S]*?)\$\$/gi)])
    expect(definitions.length, 'la définition de la fonction est introuvable').toBeGreaterThan(0)
    const corps = definitions.at(-1)![1].replace(/--.*$/gm, '').trim()
    expect(corps, 'sans `order by` en queue, les tranches du client se chevauchent selon le plan')
      .toMatch(/order\s+by\s+r\.id$/i)
  })

  it('ne rend pas une recette non planifiable, même si tout est au placard', async () => {
    const r = await recette({ plannable: false })
    const { error } = await admin().from('recipe_ingredient').insert(
      { recipe_id: r.id, ordinal: 1, raw_text: 'ingrédient', food_id: a1 })
    expect(error).toBeNull()
    await auPlacard(alice, a1)
    expect((await faisables(alice)).has(r.id), 'une recette hors planning a été promise').toBe(false)
  })

  it('ne montre à un foyer que ce que sa RLS lui laisse lire (security invoker)', async () => {
    const privee = (foyer: Actor) => recette({
      owner_household_id: foyer.householdId, visibility: 'privee', origin: 'manuelle', source_url: null,
    })
    const [chezBob, chezAlice, catalogue] = [await privee(bob), await privee(alice), await recette()]
    const { error } = await admin().from('recipe_ingredient').insert(
      [chezBob, chezAlice, catalogue].map(r => ({ recipe_id: r.id, ordinal: 1, raw_text: 'x', food_id: a1 })))
    expect(error).toBeNull()
    await auPlacard(alice, a1)
    await auPlacard(bob, a1)

    const vuesParAlice = await faisables(alice)
    expect(vuesParAlice.has(chezAlice.id), 'Alice ne voit plus sa propre recette').toBe(true)
    expect(vuesParAlice.has(catalogue.id), 'Alice ne voit plus le catalogue').toBe(true)
    expect(vuesParAlice.has(chezBob.id), 'la recette privée de Bob est sortie chez Alice').toBe(false)
    expect((await faisables(bob)).has(chezBob.id), 'Bob ne voit plus sa propre recette').toBe(true)
  })

  it('est fermée aux visiteurs anonymes', async () => {
    const anonyme = createClient(process.env.VITE_SUPABASE_URL!,
      process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    const { error } = await anonyme.rpc('recettes_faisables')
    expect(error, 'un visiteur anonyme interroge le catalogue').not.toBeNull()
  })
})
