/**
 * Le cycle : la machine à états, et ce qu'elle interdit.
 *
 * Tout le lot 1 pend à cet objet. Si un foyer peut se retrouver « en cuisine »
 * sans être passé par les courses, ou avec deux cycles vivants, l'accueil n'a
 * plus de réponse unique à donner — et c'est toute la promesse de l'app.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor

/** Semaines distinctes : `cycle_unique_week` interdit d'en réutiliser une. */
let semaine = 0
const prochaineSemaine = () => {
  const d = new Date(2027, 0, 4 + 7 * semaine++)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const SEQUENCE = ['vide', 'selection', 'courses', 'pret', 'en_cuisine', 'dressage', 'semaine', 'cloture']

/**
 * Crée un cycle et l'amène à l'état voulu EN SUIVANT la séquence — sauter
 * directement à « prêt » est précisément ce que la base refuse, et un test qui
 * l'ignorerait passerait à vide.
 */
async function cycleNeuf(a: Actor, etat: string = 'vide') {
  const { data, error } = await admin().from('cycle')
    .insert({ household_id: a.householdId, week_of: prochaineSemaine() })
    .select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()

  for (const pas of SEQUENCE.slice(1, SEQUENCE.indexOf(etat) + 1)) {
    const { error: e } = await admin().from('cycle')
      .update({ state: pas }).eq('id', data!.id)
    expect(e, `l'amorce n'a pas pu atteindre ${pas}`).toBeNull()
  }
  return data!
}

/** Ferme tout cycle vivant : l'index partiel n'en tolère qu'un. */
async function faisLePlace(a: Actor) {
  await admin().from('cycle').update({ state: 'interrompue' })
    .eq('household_id', a.householdId).not('state', 'in', '(cloture,interrompue)')
}

beforeAll(async () => {
  alice = await makeActor('cycle-alice')
  bob = await makeActor('cycle-bob')
})

describe('la séquence', () => {
  it('laisse passer le chemin normal, de bout en bout', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice)
    const suite = ['selection', 'courses', 'pret', 'en_cuisine', 'dressage', 'semaine', 'cloture']
    for (const etat of suite) {
      const { error } = await alice.client.from('cycle')
        .update({ state: etat }).eq('id', c.id)
      expect(error, `transition refusée vers ${etat}`).toBeNull()
    }
  })

  it('refuse de sauter les courses pour aller en cuisine', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice)
    const { error } = await alice.client.from('cycle')
      .update({ state: 'en_cuisine' }).eq('id', c.id)
    expect(error, 'un saut d’état a été accepté').not.toBeNull()
    expect(error!.message).toMatch(/transition/)
  })

  it('refuse de revenir en arrière depuis la clôture', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice, 'semaine')
    await alice.client.from('cycle').update({ state: 'cloture' }).eq('id', c.id)
    const { error } = await alice.client.from('cycle')
      .update({ state: 'semaine' }).eq('id', c.id)
    expect(error, 'un cycle clos a été rouvert').not.toBeNull()
  })

  it('permet d’interrompre puis de reprendre là où on s’était arrêté', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice, 'en_cuisine')
    const stop = await alice.client.from('cycle')
      .update({ state: 'interrompue' }).eq('id', c.id)
    expect(stop.error).toBeNull()
    const reprise = await alice.client.from('cycle')
      .update({ state: 'en_cuisine' }).eq('id', c.id)
    expect(reprise.error, 'une session interrompue doit pouvoir reprendre').toBeNull()
  })

  it('horodate l’entrée en cuisine et la clôture sans qu’on le lui demande', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice, 'pret')
    await alice.client.from('cycle').update({ state: 'en_cuisine' }).eq('id', c.id)
    const { data: enCours } = await alice.client.from('cycle')
      .select('started_at, closed_at').eq('id', c.id).single()
    expect(enCours!.started_at, 'started_at n’a pas été posé').not.toBeNull()
    expect(enCours!.closed_at).toBeNull()

    for (const e of ['dressage', 'semaine', 'cloture']) {
      await alice.client.from('cycle').update({ state: e }).eq('id', c.id)
    }
    const { data: clos } = await alice.client.from('cycle')
      .select('closed_at').eq('id', c.id).single()
    expect(clos!.closed_at, 'closed_at n’a pas été posé').not.toBeNull()
  })
})

describe('un seul cycle vivant', () => {
  it('interdit deux cycles ouverts pour le même foyer', async () => {
    await faisLePlace(alice)
    await cycleNeuf(alice)
    const { error } = await admin().from('cycle')
      .insert({ household_id: alice.householdId, week_of: prochaineSemaine() })
    expect(error, 'deux cycles vivants ont coexisté').not.toBeNull()
  })

  it('en laisse ouvrir un nouveau une fois le précédent clos', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice, 'semaine')
    await alice.client.from('cycle').update({ state: 'cloture' }).eq('id', c.id)
    const { error } = await admin().from('cycle')
      .insert({ household_id: alice.householdId, week_of: prochaineSemaine() })
    expect(error, 'impossible de repartir après une clôture').toBeNull()
  })

  it('n’empêche pas un AUTRE foyer d’avoir le sien', async () => {
    await faisLePlace(bob)
    const { error } = await admin().from('cycle')
      .insert({ household_id: bob.householdId, week_of: prochaineSemaine() })
    expect(error, 'l’unicité déborde sur les autres foyers').toBeNull()
  })
})

describe('open_cycle', () => {
  it('rend le cycle vivant plutôt que d’en créer un second', async () => {
    await faisLePlace(alice)
    const existant = await cycleNeuf(alice, 'selection')
    const { data, error } = await alice.client.rpc('open_cycle', {
      p_week_of: prochaineSemaine(), p_servings: 8,
    })
    expect(error).toBeNull()
    expect(data, 'un deuxième cycle a été ouvert').toBe(existant.id)
  })

  it('refuse de rouvrir une semaine déjà close plutôt que d’effacer son bilan', async () => {
    await faisLePlace(bob)
    const semaineClose = prochaineSemaine()
    const { data: id } = await bob.client.rpc('open_cycle', {
      p_week_of: semaineClose, p_servings: 6,
    })
    for (const e of ['selection', 'courses', 'pret', 'en_cuisine', 'dressage', 'semaine', 'cloture']) {
      await bob.client.from('cycle').update({ state: e }).eq('id', id!)
    }
    const { error } = await bob.client.rpc('open_cycle', {
      p_week_of: semaineClose, p_servings: 6,
    })
    expect(error, 'une semaine close a été rouverte').not.toBeNull()
  })
})

describe('isolation', () => {
  it('un foyer ne voit jamais le cycle d’un autre', async () => {
    await faisLePlace(bob)
    const sien = await cycleNeuf(bob)
    const { data } = await alice.client.from('cycle').select('id').eq('id', sien.id)
    expect(data ?? [], 'fuite de cycle entre foyers').toHaveLength(0)
  })

  it('un foyer ne peut pas déplacer son cycle chez un autre', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice)
    const { error } = await alice.client.from('cycle')
      .update({ household_id: bob.householdId }).eq('id', c.id)
    // `with check` refuse l'écriture ; à défaut, la ligne devient invisible et
    // l'update ne touche rien. Les deux sont acceptables, un transfert non.
    const { data: chezBob } = await admin().from('cycle')
      .select('household_id').eq('id', c.id).single()
    expect(chezBob!.household_id, 'un cycle a changé de foyer').toBe(alice.householdId)
    if (error) expect(error.message).toBeTruthy()
  })

  it('rattache une recette au foyer du cycle, pas à celui qu’on déclare', async () => {
    await faisLePlace(alice)
    const c = await cycleNeuf(alice)
    const { data: recette } = await admin().from('recipe')
      .insert({ title: 'Dahl de test', yield_servings: 4 }).select().single()

    // Bob tente d'accrocher une ligne au cycle d'Alice en se déclarant chez lui.
    const { error } = await bob.client.from('cycle_recipe').insert({
      cycle_id: c.id, household_id: bob.householdId,
      recipe_id: recette!.id, servings: 2,
    })
    const { data: posee } = await admin().from('cycle_recipe')
      .select('household_id').eq('cycle_id', c.id)
    // Soit RLS a refusé, soit le trigger a redérivé le foyer — jamais celui de Bob.
    for (const l of posee ?? []) {
      expect(l.household_id, 'une ligne s’est rattachée au mauvais foyer')
        .not.toBe(bob.householdId)
    }
    if (!error) {
      const { data: vuParBob } = await bob.client.from('cycle_recipe')
        .select('id').eq('cycle_id', c.id)
      expect(vuParBob ?? [], 'Bob voit ce qu’il a écrit chez Alice').toHaveLength(0)
    }
  })
})

describe('current_cycle', () => {
  it('rend le cycle vivant du foyer, et rien quand il n’y en a pas', async () => {
    await faisLePlace(alice)
    const vide = await alice.client.rpc('current_cycle')
    expect(vide.data).toBeNull()

    const c = await cycleNeuf(alice, 'courses')
    const { data } = await alice.client.rpc('current_cycle')
    expect(data).toBe(c.id)
  })
})
