/**
 * Ce que l'ordonnanceur reçoit, et ce que le plan laisse en base.
 *
 * Deux défauts trouvés à la relecture, tous deux invisibles au typage et aux
 * tests d'exemple, et tous deux au cœur du produit :
 *
 *  · l'ORDRE des étapes d'une recette était perdu avant même d'arriver à
 *    l'ordonnanceur — qui planifiait donc « Enfournez » avant « Préparez la
 *    pâte » sans rien enfreindre ;
 *  · le plan reprenait l'identifiant de l'étape de recette comme clé primaire
 *    de la tâche, ce qui rendait impossible de refaire une recette.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, connecteLeClientPartage, makeActor, type Actor } from './helpers/db'
import { etapesDuCycle } from './front-fige/lib/donnees/session.ts'

let alice: Actor
let recettes: string[] = []

async function recette(titre: string, etapes: string[]) {
  const { data: r, error } = await admin().from('recipe')
    .insert({ title: titre, yield_servings: 4, plannable: true }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  await admin().from('recipe_step').insert(etapes.map((text, i) => ({
    recipe_id: r!.id, ordinal: i + 1, text,
    duration_min: 10, load_type: 'actif' as const,
  })))
  return r!.id as string
}

beforeAll(async () => {
  alice = await makeActor('plan-alice')
  // `etapesDuCycle` lit avec le client de l'application : sans session, la RLS
  // rendrait zéro ligne et le test passerait à vide.
  await connecteLeClientPartage(alice)
  recettes = [
    await recette('R1', ['R1 émince', 'R1 cuit', 'R1 sert']),
    await recette('R2', ['R2 émince', 'R2 cuit', 'R2 sert']),
  ]
})

describe('l’ordre des étapes d’une recette', () => {
  it('survit au trajet jusqu’à l’ordonnanceur', async () => {
    const { data: c } = await admin().from('cycle')
      .insert({ household_id: alice.householdId, week_of: '2033-02-07' }).select().single()
    for (const r of recettes) {
      await admin().from('cycle_recipe')
        .insert({ cycle_id: c!.id, recipe_id: r, servings: 4 })
    }

    const etapes = await etapesDuCycle(c!.id)
    expect(etapes.length).toBe(6)

    // Chaque étape sauf la première de sa recette doit garder un prédécesseur.
    // Sans le tri par recette, les lignes revenaient entrelacées et la boucle
    // qui déduit l'ordre repartait à zéro à chaque ligne : ZÉRO sur six.
    const avecPrecedent = etapes.filter(e => e.dependDe.length > 0).length
    expect(avecPrecedent, 'l’enchaînement des recettes a été perdu').toBe(4)

    // Et l'enchaînement doit être le bon : « cuit » après « émince ».
    for (const r of recettes) {
      const siennes = etapes.filter(e => e.recetteId === r)
        .sort((a, b) => a.ordinal - b.ordinal)
      expect(siennes.map(e => e.ordinal)).toEqual([1, 2, 3])
      expect(siennes[1].dependDe, 'la 2e étape ne suit pas la 1re')
        .toContain(siennes[0].id)
      expect(siennes[2].dependDe).toContain(siennes[1].id)
      // Et surtout PAS de dépendance croisée entre deux recettes.
      expect(siennes[0].dependDe, 'la 1re étape d’une recette dépend d’autre chose')
        .toEqual([])
    }
  })
})
