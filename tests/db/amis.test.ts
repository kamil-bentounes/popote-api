/**
 * Les amis entre foyers, et ce qu'une recette laisse voir d'elle.
 *
 * Trois principes, et chacun peut se perdre en silence :
 *
 *  · l'amitié est SYMÉTRIQUE et EXPLICITE — on ne suit personne à son insu, et
 *    le lien se rompt des deux côtés ;
 *  · le défaut est PRIVÉ — partager est un geste, pas un réglage oublié ;
 *  · on voit QUI — une recette venue d'ailleurs porte le prénom de qui l'a
 *    ajoutée, sans qu'on puisse pour autant lire la liste des membres d'un
 *    autre foyer.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let alice: Actor      // foyer A
let bob: Actor        // foyer B, deviendra ami de A
let carol: Actor      // foyer C, ami de personne

async function recette(a: Actor, titre: string, visibility: string) {
  const { data, error } = await a.client.from('recipe').insert({
    title: titre, origin: 'manuelle', owner_household_id: a.householdId,
    visibility, yield_servings: 2, plannable: true,
  }).select().single()
  expect(error, `l'amorce a échoué : ${error?.message}`).toBeNull()
  return data!.id as string
}

beforeAll(async () => {
  alice = await makeActor('ami-alice')
  bob = await makeActor('ami-bob')
  carol = await makeActor('ami-carol')
})

describe('devenir amis', () => {
  let jeton: string

  it('s’invite par un lien, et rien n’est ami avant acceptation', async () => {
    const { data, error } = await alice.client.from('foyer_ami')
      .insert({ invite_par: alice.householdId, cree_par: alice.userId })
      .select().single()
    expect(error).toBeNull()
    jeton = data!.jeton

    const { data: amis } = await alice.client.rpc('foyers_amis')
    expect(amis ?? [], 'une invitation en attente compte déjà comme une amitié')
      .toHaveLength(0)
  })

  it('ne se crée pas au nom d’un autre foyer', async () => {
    const { error } = await bob.client.from('foyer_ami')
      .insert({ invite_par: alice.householdId })
    expect(error, 'un foyer a invité au nom d’un autre').not.toBeNull()
  })

  it('ne s’accepte pas en écrivant la ligne soi-même', async () => {
    // Sans cette absence d'UPDATE, on s'ajoute n'importe quel foyer.
    const { data } = await bob.client.from('foyer_ami')
      .update({ accepte_par: bob.householdId, accepte_le: new Date().toISOString() })
      .eq('jeton', jeton).select()
    expect(data ?? [], 'une amitié s’est écrite sans le jeton').toHaveLength(0)
  })

  it('s’accepte avec le jeton, et devient SYMÉTRIQUE', async () => {
    const { error } = await bob.client.rpc('accepter_amitie', { p_jeton: jeton })
    expect(error, `refusé : ${error?.message}`).toBeNull()

    const { data: chezAlice } = await alice.client.rpc('foyers_amis')
    const { data: chezBob } = await bob.client.rpc('foyers_amis')
    expect(chezAlice, 'Alice ne voit pas Bob').toEqual([bob.householdId])
    expect(chezBob, 'la réciproque ne tient pas').toEqual([alice.householdId])
  })

  it('ne se consomme qu’une fois', async () => {
    const { error } = await carol.client.rpc('accepter_amitie', { p_jeton: jeton })
    expect(error, 'le jeton a resservi').not.toBeNull()
  })

  it('refuse un jeton expiré', async () => {
    const { data } = await alice.client.from('foyer_ami')
      .insert({ invite_par: alice.householdId }).select().single()
    await admin().from('foyer_ami')
      .update({ expire_le: new Date(Date.now() - 1000).toISOString() }).eq('id', data!.id)
    const { error } = await carol.client.rpc('accepter_amitie', { p_jeton: data!.jeton })
    expect(error?.message).toMatch(/expir/i)
  })

  it('refuse de s’ajouter soi-même', async () => {
    const { data } = await alice.client.from('foyer_ami')
      .insert({ invite_par: alice.householdId }).select().single()
    const { error } = await alice.client.rpc('accepter_amitie', { p_jeton: data!.jeton })
    expect(error?.message).toMatch(/soi-même/i)
  })
})

describe('ce qu’une recette laisse voir', () => {
  let privee: string
  let partagee: string
  let publique: string

  beforeAll(async () => {
    privee = await recette(alice, 'Privée d’Alice', 'privee')
    partagee = await recette(alice, 'Partagée d’Alice', 'partagee')
    publique = await recette(alice, 'Publique d’Alice', 'publique')
  })

  it('garde la privée pour son seul foyer', async () => {
    for (const [qui, nom] of [[bob, 'un ami'], [carol, 'un inconnu']] as const) {
      const { data } = await qui.client.from('recipe').select('id').eq('id', privee)
      expect(data ?? [], `la recette privée est visible par ${nom}`).toHaveLength(0)
    }
  })

  it('montre la partagée à un AMI, et à lui seul', async () => {
    const { data: chezBob } = await bob.client.from('recipe').select('title').eq('id', partagee)
    expect(chezBob ?? [], 'un ami ne voit pas ce qu’on partage').toHaveLength(1)

    const { data: chezCarol } = await carol.client.from('recipe').select('id').eq('id', partagee)
    expect(chezCarol ?? [], 'un inconnu voit ce qui est réservé aux amis').toHaveLength(0)
  })

  it('montre la publique à tout le monde', async () => {
    const { data } = await carol.client.from('recipe').select('title').eq('id', publique)
    expect(data ?? []).toHaveLength(1)
  })

  it('applique la même règle aux ingrédients, aux étapes et aux macros', async () => {
    await admin().from('recipe_ingredient')
      .insert({ recipe_id: privee, ordinal: 1, raw_text: 'secret' })
    await admin().from('recipe_step')
      .insert({ recipe_id: privee, ordinal: 1, text: 'geste secret' })

    for (const t of ['recipe_ingredient', 'recipe_step'] as const) {
      const { data } = await bob.client.from(t).select('recipe_id').eq('recipe_id', privee)
      expect(data ?? [], `${t} d’une recette privée a fuité`).toHaveLength(0)
    }
  })

  it('cesse de la montrer quand l’amitié est rompue', async () => {
    const { data: liens } = await alice.client.from('foyer_ami')
      .select('id').not('accepte_par', 'is', null)
    await alice.client.from('foyer_ami').delete().eq('id', liens![0].id)

    const { data } = await bob.client.from('recipe').select('id').eq('id', partagee)
    expect(data ?? [], 'l’ancien ami voit encore ce qu’on partage').toHaveLength(0)
  })
})

describe('le prénom de qui a ajouté', () => {
  it('se lit pour son foyer et pour ses amis, jamais au-delà', async () => {
    // On rétablit l'amitié, rompue par le test précédent.
    const { data: inv } = await alice.client.from('foyer_ami')
      .insert({ invite_par: alice.householdId }).select().single()
    await bob.client.rpc('accepter_amitie', { p_jeton: inv!.jeton })

    const { data: vus } = await bob.client.rpc('prenoms_visibles')
    const foyers = new Set((vus ?? []).map((p: { household_id: string }) => p.household_id))
    expect(foyers.has(bob.householdId), 'on ne voit pas les siens').toBe(true)
    expect(foyers.has(alice.householdId), 'on ne voit pas son ami').toBe(true)
    expect(foyers.has(carol.householdId), 'on voit un foyer inconnu').toBe(false)
  })

  it('n’expose que le prénom', async () => {
    const { data } = await bob.client.rpc('prenoms_visibles')
    expect(Object.keys((data ?? [])[0] ?? {}).sort())
      .toEqual(['display_name', 'household_id', 'id'])
  })

  it('ne donne toujours pas accès au profil complet d’un ami', async () => {
    // La table reste cadrée sur le foyer : la vue ne l'ouvre pas.
    const { data } = await bob.client.from('user_profile')
      .select('id').eq('household_id', alice.householdId)
    expect(data ?? [], 'le profil complet d’un ami est lisible').toHaveLength(0)
  })
})

/**
 * Partager n'est pas céder.
 *
 * La visibilité est devenue une colonne de DROITS le jour où les amis sont
 * arrivés — or la policy d'écriture des recettes, elle, datait d'avant et
 * disait `using (true)`. Celui à qui l'on partage pouvait donc publier pour
 * toute la terre ce qu'on lui avait montré à lui, et rompre l'amitié n'y
 * changeait plus rien.
 */
describe('qui a le droit de réécrire une recette', () => {
  let partagee: string

  beforeAll(async () => {
    partagee = await recette(alice, 'Le dahl d’Alice', 'partagee')
  })

  it('l’ami la lit, et ne la publie pas', async () => {
    const { data: lue } = await bob.client.from('recipe').select('id').eq('id', partagee)
    expect(lue ?? [], 'l’ami ne voit plus la recette partagée').toHaveLength(1)

    const { data, error } = await bob.client.from('recipe')
      .update({ visibility: 'publique' }).eq('id', partagee).select()
    expect(data ?? [], 'un ami a publié la recette d’un autre').toHaveLength(0)
    if (error) expect(error.message).toMatch(/visib|propriétaire|row-level/i)

    const { data: chezCarol } = await carol.client.from('recipe').select('id').eq('id', partagee)
    expect(chezCarol ?? [], 'un inconnu voit la recette').toHaveLength(0)
  })

  it('l’ami ne la renomme pas non plus, ni ne s’en déclare l’auteur', async () => {
    const { data: t } = await bob.client.from('recipe')
      .update({ title: 'Le dahl de Bob' }).eq('id', partagee).select()
    expect(t ?? [], 'un ami a renommé la recette d’un autre').toHaveLength(0)

    const { data: a } = await bob.client.from('recipe')
      .update({ created_by: bob.userId }).eq('id', partagee).select()
    expect(a ?? [], 'un ami s’est déclaré auteur').toHaveLength(0)

    const { data: apres } = await admin().from('recipe')
      .select('title, visibility, created_by').eq('id', partagee).single()
    expect(apres!.title).toBe('Le dahl d’Alice')
    expect(apres!.visibility).toBe('partagee')
  })

  it('ne réécrit pas non plus ses étapes ni ses ingrédients', async () => {
    // Cadrer `recipe` sans cadrer ses tables filles ne protège rien : ce qui
    // les tenait n'était que l'impossibilité de lire, et partager la lève.
    const { data: e } = await admin().from('recipe_step')
      .insert({ recipe_id: partagee, ordinal: 1, text: 'Faire revenir l’oignon.' })
      .select().single()
    const { data: ecrit } = await bob.client.from('recipe_step')
      .update({ text: 'AMI RÉÉCRIT' }).eq('id', e!.id).select()
    expect(ecrit ?? [], 'un ami a réécrit une étape').toHaveLength(0)

    const { data: i } = await admin().from('recipe_ingredient')
      .insert({ recipe_id: partagee, ordinal: 1, raw_text: '1 oignon' }).select().single()
    const { data: ing } = await bob.client.from('recipe_ingredient')
      .update({ raw_text: 'AMI RÉÉCRIT', qty: 9999 }).eq('id', i!.id).select()
    expect(ing ?? [], 'un ami a réécrit un ingrédient').toHaveLength(0)
  })

  it('le foyer propriétaire, lui, décide de tout', async () => {
    const { error } = await alice.client.from('recipe')
      .update({ visibility: 'publique', title: 'Dahl corail' }).eq('id', partagee)
    expect(error, `le propriétaire s’est vu refuser : ${error?.message}`).toBeNull()
    const { data } = await carol.client.from('recipe').select('title').eq('id', partagee)
    expect(data ?? [], 'publique, mais invisible').toHaveLength(1)
    // Et on remet comme avant, pour ne pas laisser traîner une publique.
    await alice.client.from('recipe').update({ visibility: 'partagee' }).eq('id', partagee)
  })

  it('corrige le catalogue mutualisé sans se l’attribuer', async () => {
    // La classe B reste corrigeable par tous, c'est tout son objet (D16). Mais
    // la visibilité et l'auteur ne sont pas des corrections.
    const { data: r } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}` })
      .select().single()

    const { error: correction } = await carol.client.from('recipe')
      .update({ title: 'Titre corrigé' }).eq('id', r!.id)
    expect(correction, `la correction a été refusée : ${correction?.message}`).toBeNull()

    for (const champ of [{ visibility: 'publique' }, { created_by: carol.userId }]) {
      const { error } = await carol.client.from('recipe').update(champ).eq('id', r!.id)
      expect(error, `le catalogue a accepté ${Object.keys(champ)[0]}`).not.toBeNull()
    }
  })
})

describe('le jeton d’invitation ne se dicte pas', () => {
  it('ignore le jeton et l’expiration venus du client', async () => {
    const devine = '00000000-0000-4000-8000-000000000042'
    const dans100ans = new Date(Date.now() + 100 * 365 * 864e5).toISOString()
    const { data, error } = await carol.client.from('foyer_ami')
      .insert({ invite_par: carol.householdId, jeton: devine, expire_le: dans100ans })
      .select().single()
    expect(error, `refusé : ${error?.message}`).toBeNull()
    expect(data!.jeton, 'le client a choisi le jeton').not.toBe(devine)
    expect(new Date(data!.expire_le).getTime(),
      'le client a choisi l’expiration').toBeLessThan(Date.now() + 8 * 864e5)
  })
})
