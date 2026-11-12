/**
 * Le catalogue partagé, et ce qu'un foyer a le droit d'en faire.
 *
 * La migration 0033 a ouvert l'écriture sur la classe B pour qu'un foyer puisse
 * garder une recette collée. Deux trous s'en sont suivis, tous deux prouvés
 * avant correctif, et tous deux de la même nature : une porte ouverte pour un
 * usage légitime, empruntée pour autre chose.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor
let bob: Actor
let duCatalogue: string
/**
 * Un titre UNIQUE par exécution.
 *
 * La base locale n'est pas remise à zéro entre deux `npm test`, et le dernier
 * cas de ce fichier passe la recette en « partagée » : au second passage,
 * celle du premier était donc légitimement visible, et le test échouait sur
 * son propre résidu.
 */
const SECRET = `SECRET DU FOYER A ${Date.now()}`

beforeAll(async () => {
  alice = await makeActor('cat-alice')
  bob = await makeActor('cat-bob')
  const { data, error } = await admin().from('recipe').insert({
    title: 'Recette du catalogue mutualisé', origin: 'importee',
    owner_household_id: null, yield_servings: 4, plannable: true,
  }).select().single()
  expect(error, "l'amorce a échoué : le test serait vert à vide").toBeNull()
  duCatalogue = data!.id
})

describe('on ne s’approprie pas le catalogue', () => {
  it('refuse de changer le propriétaire d’une recette', async () => {
    // Le chemin de l'attaque : la policy d'UPDATE est `using (true)`, et celle
    // de DELETE ne regarde que le propriétaire. S'attribuer la recette suffisait
    // donc à pouvoir l'effacer — pour tous les foyers.
    await bob.client.from('recipe')
      .update({ owner_household_id: bob.householdId }).eq('id', duCatalogue)

    const { data } = await admin().from('recipe')
      .select('owner_household_id').eq('id', duCatalogue).single()
    expect(data!.owner_household_id, 'une recette du catalogue a changé de main')
      .toBeNull()
  })

  it('refuse d’en changer l’origine', async () => {
    await bob.client.from('recipe').update({ origin: 'manuelle' }).eq('id', duCatalogue)
    const { data } = await admin().from('recipe')
      .select('origin').eq('id', duCatalogue).single()
    expect(data!.origin).toBe('importee')
  })

  it('refuse de supprimer une recette du catalogue', async () => {
    const { data } = await bob.client.from('recipe')
      .delete().eq('id', duCatalogue).select()
    expect(data ?? [], 'une recette du catalogue a été supprimée').toHaveLength(0)

    const { data: encore } = await admin().from('recipe').select('id').eq('id', duCatalogue)
    expect(encore ?? []).toHaveLength(1)
  })

  it('laisse quand même chacun supprimer LA SIENNE', async () => {
    // Le correctif ne doit pas casser ce que 0033 est venu permettre.
    const { data: sienne } = await alice.client.from('recipe').insert({
      title: 'Collée par Alice', origin: 'manuelle',
      owner_household_id: alice.householdId, yield_servings: 2,
    }).select().single()
    expect(sienne, 'Alice ne peut plus garder sa recette').not.toBeNull()

    const { data } = await alice.client.from('recipe')
      .delete().eq('id', sienne!.id).select()
    expect(data ?? [], 'Alice ne peut plus supprimer la sienne').toHaveLength(1)
  })
})

describe('une recette privée reste privée', () => {
  let secrete: string

  it('ne se lit pas depuis un autre foyer', async () => {
    const { data } = await alice.client.from('recipe').insert({
      title: SECRET, origin: 'manuelle',
      owner_household_id: alice.householdId, visibility: 'privee',
      yield_servings: 4, plannable: true,
    }).select().single()
    secrete = data!.id

    const { data: chezBob } = await bob.client.from('recipe')
      .select('id, title').eq('id', secrete)
    expect(chezBob ?? [], 'la recette privée d’un foyer a fuité').toHaveLength(0)
  })

  it('n’apparaît pas dans le catalogue des autres', async () => {
    // C'est la requête que l'écran « Choisir » exécute : elle ne filtrait ni
    // `visibility` ni `owner_household_id`, et 0033 est précisément ce qui a
    // rempli la table de recettes privées.
    const { data } = await bob.client.from('recipe')
      .select('id, title').eq('plannable', true).limit(200)
    expect((data ?? []).map(r => r.title), 'la recette privée est au catalogue')
      .not.toContain(SECRET)
  })

  it('cache aussi ses ingrédients, ses étapes et ses macros', async () => {
    await admin().from('recipe_ingredient')
      .insert({ recipe_id: secrete, ordinal: 1, raw_text: 'ingrédient secret' })
    await admin().from('recipe_step')
      .insert({ recipe_id: secrete, ordinal: 1, text: 'étape secrète' })
    await admin().from('recipe_nutrition').insert({
      recipe_id: secrete, grams: 300, kcal: 500, protein_g: 20,
      fiber_g: 5, carb_g: 40, fat_g: 15, coverage: 1,
    })

    for (const t of ['recipe_ingredient', 'recipe_step', 'recipe_nutrition'] as const) {
      const { data } = await bob.client.from(t).select('recipe_id').eq('recipe_id', secrete)
      expect(data ?? [], `${t} d’une recette privée a fuité`).toHaveLength(0)
    }
  })

  it('reste visible pour son propre foyer', async () => {
    const { data } = await alice.client.from('recipe').select('title').eq('id', secrete)
    expect(data ?? [], 'Alice ne voit plus sa propre recette').toHaveLength(1)
  })

  it('reste cachée d’un foyer qui n’est PAS ami, même partagée', async () => {
    // « Partagée » veut dire « à nos amis », pas « à tout le monde » : c'est la
    // sémantique posée par la migration 0035. Bob n'est pas ami d'Alice ici.
    await alice.client.from('recipe').update({ visibility: 'partagee' }).eq('id', secrete)
    const { data } = await bob.client.from('recipe').select('title').eq('id', secrete)
    expect(data ?? [], 'un foyer non ami voit ce qui est réservé aux amis').toHaveLength(0)
  })

  it('devient visible de tous si on la rend PUBLIQUE', async () => {
    await alice.client.from('recipe').update({ visibility: 'publique' }).eq('id', secrete)
    const { data } = await bob.client.from('recipe').select('title').eq('id', secrete)
    expect(data ?? [], 'le partage public ne marche pas').toHaveLength(1)
  })
})

describe('les arcs de dépendance', () => {
  it('s’écrivent sous SA recette', async () => {
    // 0033 avait ouvert quatre tables et oublié celle-ci : l'import écrivait
    // son graphe et recevait un 42501, avalé en silence.
    const { data: r } = await alice.client.from('recipe').insert({
      title: 'Avec un graphe', origin: 'manuelle',
      owner_household_id: alice.householdId, yield_servings: 2,
    }).select().single()
    const { data: etapes } = await alice.client.from('recipe_step').insert([
      { recipe_id: r!.id, ordinal: 1, text: 'un' },
      { recipe_id: r!.id, ordinal: 2, text: 'deux' },
    ]).select()

    const { error } = await alice.client.from('recipe_step_dependency')
      .insert({ before_id: etapes![0].id, after_id: etapes![1].id })
    expect(error, `refusé : ${error?.message}`).toBeNull()
  })

  it('ne s’écrivent pas sous celle d’un autre', async () => {
    const { data: etapes } = await admin().from('recipe_step').insert([
      { recipe_id: duCatalogue, ordinal: 1, text: 'a' },
      { recipe_id: duCatalogue, ordinal: 2, text: 'b' },
    ]).select()
    const { error } = await bob.client.from('recipe_step_dependency')
      .insert({ before_id: etapes![0].id, after_id: etapes![1].id })
    expect(error, 'un arc a été écrit sous la recette d’un autre').not.toBeNull()
  })
})

/**
 * Les arcs d'une recette PRIVÉE.
 *
 * La classe B compte quatre tables, pas trois. `recipe_step_dependency` est
 * restée en `using (true)` deux migrations de trop : un compte qui ne voyait
 * pas une étape privée pouvait tout de même repointer l'arc qui la précède, et
 * le graphe qui ordonne la session s'en allait chez quelqu'un d'autre.
 */
describe('les arcs d’une recette qu’on ne voit pas', () => {
  let arc: { before_id: string; after_id: string }
  let etrangere: string

  beforeAll(async () => {
    const { data: r } = await alice.client.from('recipe').insert({
      title: 'Ordre secret', origin: 'manuelle', visibility: 'privee',
      owner_household_id: alice.householdId, yield_servings: 2,
    }).select().single()
    const { data: e } = await alice.client.from('recipe_step').insert([
      { recipe_id: r!.id, ordinal: 1, text: 'un' },
      { recipe_id: r!.id, ordinal: 2, text: 'deux' },
    ]).select()
    await alice.client.from('recipe_step_dependency')
      .insert({ before_id: e![0].id, after_id: e![1].id })
    arc = { before_id: e![0].id, after_id: e![1].id }

    const { data: c } = await admin().from('recipe_step')
      .insert({ recipe_id: duCatalogue, ordinal: 9, text: 'ailleurs' }).select().single()
    etrangere = c!.id
  })

  it('ne se lisent pas', async () => {
    const { data } = await bob.client.from('recipe_step_dependency')
      .select('before_id').eq('after_id', arc.after_id)
    expect(data ?? [], 'l’ordre d’une recette privée est lisible').toHaveLength(0)
  })

  it('ne se repointent pas vers une autre recette', async () => {
    const { data } = await bob.client.from('recipe_step_dependency')
      .update({ before_id: etrangere }).eq('after_id', arc.after_id).select()
    expect(data ?? [], 'un arc a été repointé').toHaveLength(0)

    const { data: apres } = await admin().from('recipe_step_dependency')
      .select('before_id').eq('after_id', arc.after_id).single()
    expect(apres!.before_id).toBe(arc.before_id)
  })

  it('mais le catalogue mutualisé reste corrigeable', async () => {
    // C'est tout l'objet de la classe B (D16) : resserrer ne doit pas fermer.
    const { data: e } = await admin().from('recipe_step').insert([
      { recipe_id: duCatalogue, ordinal: 20, text: 'x' },
      { recipe_id: duCatalogue, ordinal: 21, text: 'y' },
    ]).select()
    await admin().from('recipe_step_dependency')
      .insert({ before_id: e![0].id, after_id: e![1].id })
    // ⚠️ `.select()` et la LONGUEUR, pas seulement `error`. Un UPDATE
    //    entièrement refusé par la RLS rend `error: null` et zéro ligne : sans
    //    ça, ce test resterait vert le jour où l'on fermerait le catalogue par
    //    erreur — et c'est le seul garde-fou de D16 sur les arcs.
    const { data, error } = await bob.client.from('recipe_step_dependency')
      .update({ origin: 'confirme' }).eq('after_id', e![1].id).select()
    expect(error, `la correction du catalogue a été refusée : ${error?.message}`).toBeNull()
    expect(data ?? [], 'la correction n’a rien écrit').toHaveLength(1)
  })

  /**
   * Un arc relie deux étapes du MÊME plat.
   *
   * Vérifier chaque bout séparément ne dit pas cela : on pouvait repointer un
   * arc du catalogue vers une autre recette du catalogue — l'ordonnanceur lève
   * alors « dépendances circulaires » chez tout le monde — ou le tirer vers sa
   * propre recette privée, ce qui le rendait invisible pour tous. Une
   * contrainte d'ordre supprimée sans droit de suppression.
   */
  it('ne se repointent pas d’une recette du catalogue vers une autre', async () => {
    const { data: e } = await admin().from('recipe_step').insert([
      { recipe_id: duCatalogue, ordinal: 30, text: 'p' },
      { recipe_id: duCatalogue, ordinal: 31, text: 'q' },
    ]).select()
    await admin().from('recipe_step_dependency')
      .insert({ before_id: e![0].id, after_id: e![1].id })

    // Une SECONDE recette du catalogue, que bob a tout autant le droit de
    // corriger — mais pas de mélanger avec la première.
    const { data: autre } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}` }).select().single()
    const { data: ailleurs } = await admin().from('recipe_step')
      .insert({ recipe_id: autre!.id, ordinal: 1, text: 'ailleurs' }).select().single()

    // Un seul bout : l'arc enjamberait deux recettes. C'est le trigger qui
    // refuse, pas la policy — il passe avant le `with check`, donc on vérifie
    // le MESSAGE plutôt que de se contenter d'un refus quelconque.
    const { error: unBout } = await bob.client.from('recipe_step_dependency')
      .update({ before_id: ailleurs!.id }).eq('after_id', e![1].id)
    expect(unBout?.message, 'un arc relie deux recettes différentes')
      .toMatch(/du même plat/)

    /*
     * ⚠️ LES DEUX BOUTS D'UN COUP, et c'est là que tout se joue.
     *
     *    Une policy juge l'ANCIENNE paire dans son `using` et la NOUVELLE dans
     *    son `with check` — chacune cohérente de son côté, jamais comparée à
     *    l'autre. La RLS ne sait pas dire « la même recette qu'avant » : il
     *    faut un trigger. Trois migrations de suite ont échoué ici.
     */
    const { data: autreEtape } = await admin().from('recipe_step')
      .insert({ recipe_id: autre!.id, ordinal: 2, text: 'et sa suite' }).select().single()
    const { data: lesDeux, error } = await bob.client.from('recipe_step_dependency')
      .update({ before_id: ailleurs!.id, after_id: autreEtape!.id })
      .eq('after_id', e![1].id).select()
    expect(error?.message, 'un arc a changé de recette en déplaçant ses deux bouts')
      .toMatch(/ne change pas de recette/)
    expect(lesDeux ?? [], 'un arc a changé de recette').toHaveLength(0)

    const { data: apres } = await admin().from('recipe_step_dependency')
      .select('before_id').eq('after_id', e![1].id).single()
    expect(apres!.before_id).toBe(e![0].id)
  })

  it('ne se posent pas dans le catalogue par la bande', async () => {
    /*
     * Le geste le plus retors : l'INSERT direct dans le catalogue est refusé,
     * alors on pose l'arc chez soi — ce qui est permis — et on le déménage.
     * Sans l'interdiction de CHANGER de recette, on insérait dans le catalogue
     * sans jamais en avoir eu le droit, et dans le sens qu'on voulait.
     */
    const { data: mienne } = await bob.client.from('recipe').insert({
      title: 'Le cheval de Troie', origin: 'manuelle',
      owner_household_id: bob.householdId, yield_servings: 2,
    }).select().single()
    const { data: siennes } = await bob.client.from('recipe_step').insert([
      { recipe_id: mienne!.id, ordinal: 1, text: 'un' },
      { recipe_id: mienne!.id, ordinal: 2, text: 'deux' },
    ]).select()
    const { error: pose } = await bob.client.from('recipe_step_dependency')
      .insert({ before_id: siennes![0].id, after_id: siennes![1].id })
    expect(pose, `poser chez soi a été refusé : ${pose?.message}`).toBeNull()

    // Deux étapes du catalogue, dans l'ordre inverse : de quoi fabriquer une
    // boucle chez tous les foyers qui planifient cette recette.
    const { data: cat } = await admin().from('recipe_step').insert([
      { recipe_id: duCatalogue, ordinal: 40, text: 'd’abord' },
      { recipe_id: duCatalogue, ordinal: 41, text: 'ensuite' },
    ]).select()
    const { error } = await bob.client.from('recipe_step_dependency')
      .update({ before_id: cat![1].id, after_id: cat![0].id })
      .eq('after_id', siennes![1].id)
    expect(error?.message, 'un arc a été poussé dans le catalogue')
      .toMatch(/ne change pas de recette/)

    const { data: dansLeCatalogue } = await admin().from('recipe_step_dependency')
      .select('before_id').eq('after_id', cat![0].id)
    expect(dansLeCatalogue ?? [], 'le catalogue a gagné un arc').toHaveLength(0)
  })

  it('ne se déménagent pas en déménageant l’étape', async () => {
    /*
     * ⚠️ Le même invariant, une table plus loin.
     *
     *    Interdire à l'ARC de changer de recette ne sert à rien tant que
     *    l'ÉTAPE peut changer de recette : on réattache l'étape du catalogue à
     *    sa propre recette, et l'arc suit sans que le trigger soit consulté.
     *    La recette d'origine perd ses étapes, ses ingrédients et ses macros —
     *    pour tout le monde, et sans droit de suppression.
     */
    const { data: e } = await admin().from('recipe_step').insert([
      { recipe_id: duCatalogue, ordinal: 50, text: 'avant' },
      { recipe_id: duCatalogue, ordinal: 51, text: 'après' },
    ]).select()
    const { data: ing } = await admin().from('recipe_ingredient')
      .insert({ recipe_id: duCatalogue, ordinal: 50, raw_text: '1 carotte' })
      .select().single()

    const { data: mienne } = await bob.client.from('recipe').insert({
      title: 'Le déménagement', origin: 'manuelle',
      owner_household_id: bob.householdId, yield_servings: 2,
    }).select().single()

    for (const etape of e!) {
      const { error } = await bob.client.from('recipe_step')
        .update({ recipe_id: mienne!.id }).eq('id', etape.id)
      expect(error?.message, 'une étape du catalogue a changé de recette')
        .toMatch(/ne change pas de recette/)
    }
    const { error: eIng } = await bob.client.from('recipe_ingredient')
      .update({ recipe_id: mienne!.id }).eq('id', ing!.id)
    expect(eIng?.message, 'un ingrédient du catalogue a changé de recette')
      .toMatch(/ne change pas de recette/)

    const { data: restees } = await admin().from('recipe_step')
      .select('id').eq('recipe_id', duCatalogue).in('ordinal', [50, 51])
    expect(restees ?? [], 'le catalogue a été dépouillé de ses étapes').toHaveLength(2)
  })

  it('ne se posent pas depuis l’étape d’un autre', async () => {
    // L'INSERT ne regardait que `after_id` : on posait un arc dont l'origine
    // est l'étape privée de quelqu'un d'autre.
    const { data: privee } = await alice.client.from('recipe').insert({
      title: 'À moi seule', origin: 'manuelle', visibility: 'privee',
      owner_household_id: alice.householdId, yield_servings: 2,
    }).select().single()
    const { data: sienne } = await alice.client.from('recipe_step')
      .insert({ recipe_id: privee!.id, ordinal: 1, text: 'secret' }).select().single()

    const { data: aBob } = await bob.client.from('recipe').insert({
      title: 'À Bob', origin: 'manuelle', owner_household_id: bob.householdId,
      yield_servings: 2,
    }).select().single()
    const { data: etapeBob } = await bob.client.from('recipe_step')
      .insert({ recipe_id: aBob!.id, ordinal: 1, text: 'la sienne' }).select().single()

    const { error } = await bob.client.from('recipe_step_dependency')
      .insert({ before_id: sienne!.id, after_id: etapeBob!.id })
    expect(error, 'un arc est parti de l’étape privée d’un autre').not.toBeNull()
  })
})
