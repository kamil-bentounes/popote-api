/**
 * Cuisiner à plusieurs, et ce qu'un convive n'a pas le droit de faire.
 *
 * Une session appartenait à un foyer et à lui seul. On peut désormais y convier
 * un foyer AMI : il suit l'avancement et prend des gestes. Tout l'enjeu tient
 * dans la frontière — il cuisine, il ne réécrit pas.
 *
 * Quatre choses peuvent se perdre en silence, et chacune a son test :
 *
 *  · convier quelqu'un qui n'est pas un ami, ou à la session d'un autre ;
 *  · entrer sans avoir dit oui ;
 *  · renommer, réordonner ou rallonger les gestes de son hôte ;
 *  · continuer à voir la session après avoir été retiré.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let hote: Actor      // celui qui cuisine
let ami: Actor       // son ami, convié
let etranger: Actor  // ami de personne
let cycle: string
let geste: string
let recette: string

async function amis(a: Actor, b: Actor) {
  const { data } = await a.client.from('foyer_ami')
    .insert({ invite_par: a.householdId }).select().single()
  const { error } = await b.client.rpc('accepter_amitie', { p_jeton: data!.jeton })
  expect(error, `l'amitié n'a pas pris : ${error?.message}`).toBeNull()
}

beforeAll(async () => {
  hote = await makeActor('ens-hote')
  ami = await makeActor('ens-ami')
  etranger = await makeActor('ens-etranger')
  await amis(hote, ami)

  const { data: c } = await admin().from('cycle')
    .insert({ household_id: hote.householdId, week_of: '2029-03-05', state: 'en_cuisine' })
    .select().single()
  cycle = c!.id

  // Une recette PRIVÉE : le convive doit pouvoir en lire le titre pendant la
  // session, et plus après.
  const { data: r } = await hote.client.from('recipe').insert({
    title: 'Le curry du dimanche', origin: 'manuelle', visibility: 'privee',
    owner_household_id: hote.householdId, yield_servings: 4, plannable: true,
  }).select().single()
  recette = r!.id
  await admin().from('cycle_recipe').insert({
    cycle_id: cycle, household_id: hote.householdId, recipe_id: recette, servings: 4,
  })

  const { data: t } = await admin().from('session_task').insert({
    cycle_id: cycle, household_id: hote.householdId, label: 'Émincer 500 g d’oignons',
    verb: 'emincer', quantity_g: 500, duration_min: 6, planned_start_min: 0,
  }).select().single()
  geste = t!.id
  await admin().from('session_task_recipe')
    .insert({ task_id: geste, recipe_id: recette, household_id: hote.householdId })
})

describe('convier à sa session', () => {
  it('ne convie qu’un ami', async () => {
    const { error } = await hote.client.from('session_convive')
      .insert({ cycle_id: cycle, invite_id: etranger.householdId, hote_id: hote.householdId })
    expect(error, 'un inconnu a été convié').not.toBeNull()
  })

  it('ne convie personne à la session d’un autre', async () => {
    const { error } = await ami.client.from('session_convive')
      .insert({ cycle_id: cycle, invite_id: etranger.householdId, hote_id: hote.householdId })
    expect(error, 'un ami a convié chez son hôte').not.toBeNull()
  })

  it('pose l’hôte d’après le cycle, quoi qu’en dise le client', async () => {
    const { data, error } = await hote.client.from('session_convive')
      .insert({ cycle_id: cycle, invite_id: ami.householdId, hote_id: ami.householdId })
      .select().single()
    expect(error, `refusé : ${error?.message}`).toBeNull()
    expect(data!.hote_id, 'le client a choisi l’hôte').toBe(hote.householdId)
    expect(data!.rejoint_le, 'l’hôte a fait entrer son ami de force').toBeNull()
  })
})

describe('tant qu’on n’a pas dit oui', () => {
  it('voit l’invitation, et rien de la session', async () => {
    const { data: invits } = await ami.client.from('session_convive').select('*')
    expect(invits ?? [], 'l’invitation ne se voit pas').toHaveLength(1)

    const { data: gestes } = await ami.client.from('session_task').select('id')
    expect(gestes ?? [], 'la session se voit sans avoir été rejointe').toHaveLength(0)
    const { data: cycles } = await ami.client.from('cycle').select('id').eq('id', cycle)
    expect(cycles ?? [], 'le cycle se voit sans avoir été rejoint').toHaveLength(0)
  })
})

describe('une fois entré', () => {
  beforeAll(async () => {
    const { error } = await ami.client.from('session_convive')
      .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cycle)
    expect(error, `n'a pas pu rejoindre : ${error?.message}`).toBeNull()
  })

  it('voit le plan, et le titre de ce qu’on cuisine', async () => {
    const { data: gestes } = await ami.client.from('session_task').select('id, label')
    expect(gestes ?? [], 'le convive ne voit pas le plan').toHaveLength(1)

    const { data: titres } = await ami.client.from('session_task_recipe')
      .select('recipe:recipe_id(title)')
    expect((titres ?? [])[0]?.recipe, 'le convive cuisine sans savoir quoi').not.toBeNull()
  })

  it('prend un geste et le termine', async () => {
    const debut = new Date().toISOString()
    const { error: e1 } = await ami.client.from('session_task')
      .update({ assignee_id: ami.userId, started_at: debut }).eq('id', geste)
    expect(e1, `n'a pas pu prendre : ${e1?.message}`).toBeNull()

    const { error: e2 } = await ami.client.from('session_task')
      .update({ done_at: new Date(Date.now() + 60_000).toISOString() }).eq('id', geste)
    expect(e2, `n'a pas pu terminer : ${e2?.message}`).toBeNull()

    const { data } = await admin().from('session_task')
      .select('actual_min, household_id').eq('id', geste).single()
    expect(Number(data!.actual_min), 'la durée ne s’est pas mesurée').toBeGreaterThan(0)
    expect(data!.household_id, 'le geste a changé de foyer').toBe(hote.householdId)
  })

  it('la mesure reste au foyer qui cuisine', async () => {
    // D48 : l'observation nourrit les durées par défaut de la cuisine où elle a
    // eu lieu, pas de celle du convive.
    const { data: chezLHote } = await admin().from('duration_observation')
      .select('id').eq('household_id', hote.householdId)
    const { data: chezLeConvive } = await admin().from('duration_observation')
      .select('id').eq('household_id', ami.householdId)
    expect(chezLHote ?? [], 'rien n’a été observé chez l’hôte').toHaveLength(1)
    expect(chezLeConvive ?? [], 'une observation est partie chez le convive').toHaveLength(0)
  })

  it('ne réécrit ni le libellé, ni la durée, ni l’ordre', async () => {
    for (const champ of [{ label: 'Autre chose' }, { duration_min: 99 },
                         { planned_start_min: 500 }, { is_active: false }]) {
      const { error } = await ami.client.from('session_task').update(champ).eq('id', geste)
      expect(error, `le convive a réécrit ${Object.keys(champ)[0]}`).not.toBeNull()
    }
    const { data } = await admin().from('session_task')
      .select('label, duration_min').eq('id', geste).single()
    expect(data!.label).toBe('Émincer 500 g d’oignons')
  })

  it('ne supprime rien et ne fait pas avancer le cycle de son hôte', async () => {
    const { data: sup } = await ami.client.from('session_task').delete().eq('id', geste).select()
    expect(sup ?? [], 'le convive a supprimé un geste').toHaveLength(0)
    const { data: maj } = await ami.client.from('cycle')
      .update({ state: 'dressage' }).eq('id', cycle).select()
    expect(maj ?? [], 'le convive a fait avancer le cycle de son hôte').toHaveLength(0)
  })

  it('n’ouvre pas le reste du foyer qui l’accueille', async () => {
    // La session est une fenêtre, pas une porte.
    for (const table of ['shopping_item', 'portion', 'stock_item', 'meal_slot']) {
      const { data } = await ami.client.from(table).select('household_id')
      expect((data ?? []).every((l: { household_id: string }) =>
        l.household_id === ami.householdId),
        `${table} du foyer hôte est lisible`).toBe(true)
    }
  })
})

/**
 * Les quatre façons de passer sous la frontière.
 *
 * Chacune a marché une fois. Ce qui les réunit : la frontière était annoncée
 * par un commentaire et tenue par un seul verrou, toujours placé un cran trop
 * loin — la ligne plutôt que la colonne, la recette plutôt que ses lignes,
 * l'instant de l'invitation plutôt que celui de la lecture.
 */
describe('ce que le convive ne peut PAS faire', () => {
  it('ne se fait pas passer pour l’hôte en envoyant son propre foyer', async () => {
    /*
     * ⚠️ `household_id` est envoyé par le CLIENT, et `tg_derive_household` ne
     *    le repose qu'APRÈS le contrôle (ordre alphabétique des triggers).
     *    Envoyer son propre foyer suffisait donc à passer pour l'hôte, puis la
     *    colonne était remise en place et rien n'y paraissait.
     */
    // ⚠️ `household_id` SEUL : envoyé avec le reste, le test resterait vert
    //    même si c'était le libellé qui déclenchait le refus.
    const { error: seul } = await ami.client.from('session_task')
      .update({ household_id: ami.householdId }).eq('id', geste)
    expect(seul, 'le foyer envoyé dans la charge a suffi').not.toBeNull()

    const { error } = await ami.client.from('session_task').update({
      household_id: ami.householdId, label: 'PIRATE', duration_min: 999,
      planned_start_min: 480, position: 99,
    }).eq('id', geste)
    expect(error, 'le foyer envoyé dans la charge a suffi').not.toBeNull()

    const { data } = await admin().from('session_task')
      .select('label, household_id').eq('id', geste).single()
    expect(data!.label).toBe('Émincer 500 g d’oignons')
    expect(data!.household_id).toBe(hote.householdId)
  })

  it('ne réécrit ni les étapes ni les ingrédients de la recette de son hôte', async () => {
    // 0036 avait cadré `recipe` et laissé ses tables filles en `using (true)` :
    // seule l'impossibilité de LIRE les protégeait, et la session l'a levée.
    const { data: e } = await admin().from('recipe_step')
      .insert({ recipe_id: recette, ordinal: 1, text: 'Émincer les oignons.' })
      .select().single()
    const { data: i } = await admin().from('recipe_ingredient')
      .insert({ recipe_id: recette, ordinal: 1, raw_text: '2 oignons' }).select().single()

    const { data: etapes } = await ami.client.from('recipe_step')
      .update({ text: 'RÉÉCRIT' }).eq('id', e!.id).select()
    expect(etapes ?? [], 'le convive a réécrit une étape').toHaveLength(0)
    const { data: ing } = await ami.client.from('recipe_ingredient')
      .update({ raw_text: 'RÉÉCRIT' }).eq('id', i!.id).select()
    expect(ing ?? [], 'le convive a réécrit un ingrédient').toHaveLength(0)

    const { data: apres } = await admin().from('recipe_step')
      .select('text').eq('id', e!.id).single()
    expect(apres!.text).toBe('Émincer les oignons.')
  })

  it('ne défait pas un geste, ne dicte pas la durée, ne prend pas celui d’un autre', async () => {
    // Le geste a été pris et terminé par le convive lui-même plus haut.
    for (const champ of [{ done_at: null }, { actual_min: 999 }, { started_at: null },
                         { created_at: new Date().toISOString() }]) {
      const { error } = await ami.client.from('session_task').update(champ).eq('id', geste)
      expect(error, `le convive a écrit ${Object.keys(champ)[0]}`).not.toBeNull()
    }

    // Et un geste déjà pris par l'hôte ne se reprend pas.
    const { data: autre } = await admin().from('session_task').insert({
      cycle_id: cycle, household_id: hote.householdId, label: 'Râper le gingembre',
      duration_min: 3, planned_start_min: 10,
    }).select().single()
    await hote.client.from('session_task')
      .update({ assignee_id: hote.userId, started_at: new Date().toISOString() })
      .eq('id', autre!.id)
    const { error } = await ami.client.from('session_task')
      .update({ assignee_id: ami.userId }).eq('id', autre!.id)
    expect(error, 'le convive a pris le geste de son hôte').not.toBeNull()
  })
})

/**
 * Ce que la mesure vaut, et à qui appartient un geste.
 *
 * Les horodatages ne sont pas des champs de formulaire : ils sont la MESURE
 * (D48), et elle nourrit les durées par défaut du foyer où l'on a cuisiné. Un
 * convive qui antidate son geste de cinq heures empoisonne le journal de son
 * hôte, qui ne peut même pas l'effacer.
 */
describe('la mesure ne se dicte pas', () => {
  let session: { hote: Actor; convive: Actor; cycle: string; geste: string }

  beforeAll(async () => {
    const h = await makeActor('mes-h')
    const c = await makeActor('mes-c')
    await amis(h, c)
    const { data: cy } = await admin().from('cycle')
      .insert({ household_id: h.householdId, week_of: '2029-09-03', state: 'en_cuisine' })
      .select().single()
    const { data: t } = await admin().from('session_task').insert({
      cycle_id: cy!.id, household_id: h.householdId, label: 'Éplucher les pommes de terre',
      verb: 'eplucher', quantity_g: 800, duration_min: 8, planned_start_min: 0,
    }).select().single()
    await h.client.from('session_convive')
      .insert({ cycle_id: cy!.id, hote_id: h.householdId, invite_id: c.householdId })
    await c.client.from('session_convive')
      .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cy!.id)
    session = { hote: h, convive: c, cycle: cy!.id, geste: t!.id }
  })

  it('repose l’heure de début, quoi qu’en dise le client', async () => {
    const ilYA5h = new Date(Date.now() - 5 * 3600_000).toISOString()
    const { error } = await session.convive.client.from('session_task')
      .update({ assignee_id: session.convive.userId, started_at: ilYA5h })
      .eq('id', session.geste)
    expect(error, `refusé : ${error?.message}`).toBeNull()

    const { data } = await admin().from('session_task')
      .select('started_at').eq('id', session.geste).single()
    const ecart = Math.abs(Date.now() - new Date(data!.started_at!).getTime())
    expect(ecart, 'le client a antidaté son geste').toBeLessThan(60_000)
  })

  it('l’observation qui part chez l’hôte est celle du temps réellement passé', async () => {
    /*
     * Le convive écrit BIEN une observation dans le journal de son hôte, et
     * c'est voulu : il a cuisiné dans cette cuisine-là. Ce qu'il ne peut pas,
     * c'est en choisir la valeur. Ici il a pris le geste il y a un instant :
     * la mesure vaut une fraction de minute, pas les cinq heures annoncées.
     *
     * ⚠️ On reprend le geste ici plutôt que de compter sur le test précédent :
     *    un test qui ne se rejoue pas seul ne prouve rien le jour où on le
     *    lance seul, c'est-à-dire le jour où il échoue.
     */
    await session.convive.client.from('session_task')
      .update({ assignee_id: session.convive.userId,
                started_at: new Date(Date.now() - 5 * 3600_000).toISOString() })
      .eq('id', session.geste)
    await session.convive.client.from('session_task')
      .update({ done_at: new Date().toISOString() }).eq('id', session.geste)
    const { data } = await admin().from('duration_observation')
      .select('actual_min').eq('household_id', session.hote.householdId)
    expect(data ?? [], 'rien n’a été observé').toHaveLength(1)
    expect(Number(data![0].actual_min), 'cinq heures pour éplucher des pommes de terre')
      .toBeLessThan(1)
  })

  it('ne change pas l’identifiant d’un geste', async () => {
    const { error } = await session.convive.client.from('session_task')
      .update({ id: crypto.randomUUID() }).eq('id', session.geste)
    expect(error, 'un geste a changé d’identifiant sous son hôte').not.toBeNull()
  })

  it('rend le geste qu’on a pris, et seulement celui-là', async () => {
    const { data: t } = await admin().from('session_task').insert({
      cycle_id: session.cycle, household_id: session.hote.householdId,
      label: 'Laver la salade', duration_min: 2, planned_start_min: 5,
    }).select().single()

    await session.convive.client.from('session_task')
      .update({ assignee_id: session.convive.userId, started_at: new Date().toISOString() })
      .eq('id', t!.id)
    const { error } = await session.convive.client.from('session_task')
      .update({ assignee_id: null, started_at: null }).eq('id', t!.id)
    expect(error, `on ne peut pas rendre son propre geste : ${error?.message}`).toBeNull()

    // Et celui d'un autre reste à lui.
    const { data: sien } = await admin().from('session_task').insert({
      cycle_id: session.cycle, household_id: session.hote.householdId,
      label: 'Sortir le plat', duration_min: 1, planned_start_min: 9,
    }).select().single()
    await session.hote.client.from('session_task')
      .update({ assignee_id: session.hote.userId, started_at: new Date().toISOString() })
      .eq('id', sien!.id)
    const { error: vol } = await session.convive.client.from('session_task')
      .update({ assignee_id: null }).eq('id', sien!.id)
    expect(vol, 'le convive a rendu le geste de son hôte').not.toBeNull()
  })

  it('laisse passer le rôle de service', async () => {
    // ⚠️ `security definer` fait de `current_user` le propriétaire de la
    //    fonction : `current_user = 'service_role'` était devenu du code mort,
    //    et le premier script de réparation s'y serait cassé les dents.
    const { error } = await admin().from('session_task')
      .update({ label: 'Corrigé par le service', planned_start_min: 42 })
      .eq('id', session.geste)
    expect(error, `le rôle de service a été refusé : ${error?.message}`).toBeNull()

    const { data: c } = await admin().from('cycle')
      .insert({ household_id: session.convive.householdId, week_of: '2029-10-01' })
      .select().single()
    const { error: inv } = await admin().from('session_convive').insert({
      cycle_id: c!.id, hote_id: session.convive.householdId,
      invite_id: session.hote.householdId,
    })
    expect(inv, `le service ne peut pas créer d’invitation : ${inv?.message}`).toBeNull()
  })
})

/**
 * L'amitié n'est pas transitive, et la session ne la rend pas transitive.
 *
 * Le convive lit les recettes de la session : c'est ce qu'il cuisine. Mais une
 * session contient aussi ce qu'un TROISIÈME foyer a prêté à l'hôte — et
 * celui-là n'a rien promis au convive. Sans distinction, cuisiner une fois chez
 * quelqu'un donnait accès à tout ce que ses autres amis lui avaient montré.
 */
async function sessionPartagee(nom: string, semaine: string) {
  const h = await makeActor(`${nom}-h`)
  const c = await makeActor(`${nom}-c`)
  await amis(h, c)
  const { data: cy } = await admin().from('cycle')
    .insert({ household_id: h.householdId, week_of: semaine, state: 'en_cuisine' })
    .select().single()
  await h.client.from('session_convive')
    .insert({ cycle_id: cy!.id, hote_id: h.householdId, invite_id: c.householdId })
  await c.client.from('session_convive')
    .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cy!.id)
  return { hote: h, convive: c, cycle: cy!.id }
}

/** Une session d'hôte qui contient AUSSI le plat d'un tiers, ami de lui seul. */
async function sessionAvecTiers(nom: string, semaine: string) {
  const hote = await makeActor(`${nom}-hote`)
  const convive = await makeActor(`${nom}-convive`)
  const tiers = await makeActor(`${nom}-tiers`)
  await amis(hote, convive)
  await amis(hote, tiers)   // ⚠️ le tiers n'est PAS ami du convive

  const { data: pretee } = await tiers.client.from('recipe').insert({
    title: 'La tarte du tiers', origin: 'manuelle', visibility: 'partagee',
    owner_household_id: tiers.householdId, yield_servings: 4, plannable: true,
  }).select().single()
  const { data: aMoi } = await hote.client.from('recipe').insert({
    title: 'Le plat de l’hôte', origin: 'manuelle', visibility: 'privee',
    owner_household_id: hote.householdId, yield_servings: 4, plannable: true,
  }).select().single()

  const { data: cy } = await admin().from('cycle')
    .insert({ household_id: hote.householdId, week_of: semaine, state: 'en_cuisine' })
    .select().single()
  for (const r of [pretee!.id, aMoi!.id]) {
    await admin().from('cycle_recipe').insert({
      cycle_id: cy!.id, household_id: hote.householdId, recipe_id: r, servings: 2,
    })
    const { data: t } = await admin().from('session_task').insert({
      cycle_id: cy!.id, household_id: hote.householdId, label: 'Un geste',
      duration_min: 3, planned_start_min: 0,
    }).select().single()
    await admin().from('session_task_recipe')
      .insert({ task_id: t!.id, recipe_id: r, household_id: hote.householdId })
  }
  await hote.client.from('session_convive')
    .insert({ cycle_id: cy!.id, hote_id: hote.householdId, invite_id: convive.householdId })
  await convive.client.from('session_convive')
    .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cy!.id)

  return { hote, convive, tiers, cycle: cy!.id,
           recetteDeLHote: aMoi!.id as string, recetteDuTiers: pretee!.id as string }
}

describe('ce que la session ne donne PAS à voir', () => {
  it('ne montre pas au convive ce qu’un autre ami a prêté à l’hôte', async () => {
    const s = await sessionAvecTiers('trans', '2029-11-05')

    // Ce que l'hôte cuisine et qui est à lui : oui, c'est l'objet de la session.
    const { data: sien } = await s.convive.client.from('recipe')
      .select('id').eq('id', s.recetteDeLHote)
    expect(sien ?? [], 'le convive ne voit pas ce qu’il cuisine').toHaveLength(1)

    // Ce qu'un tiers a prêté à l'hôte : non. Il n'a rien promis au convive.
    const { data: fuite } = await s.convive.client.from('recipe')
      .select('id').eq('id', s.recetteDuTiers)
    expect(fuite ?? [], 'la session rend l’amitié transitive').toHaveLength(0)
  })

  it('ne montre pas non plus QUEL geste sert QUEL plat du tiers', async () => {
    /*
     * La moitié qu'on oublie : fermer la recette et laisser le LIEN. Le contenu
     * restait clos, mais l'identifiant de la recette du tiers et le
     * regroupement des gestes par plat, non — et c'est déjà dire de qui l'hôte
     * est l'ami, et ce qu'il lui a emprunté.
     */
    const s = await sessionAvecTiers('lien', '2030-01-07')
    const { data: liens } = await s.convive.client.from('session_task_recipe')
      .select('recipe_id')
    const vus = new Set((liens ?? []).map(l => l.recipe_id))
    expect(vus.has(s.recetteDeLHote), 'le convive ne voit pas ce qu’il cuisine').toBe(true)
    expect(vus.has(s.recetteDuTiers), 'le lien vers le plat du tiers est visible').toBe(false)
  })

  it('ne laisse pas le convive pousser un geste à lui dans la session de son hôte', async () => {
    /*
     * ⚠️ Le sens SORTANT, celui qu'on ne regarde pas.
     *
     *    `tg_session_task_convive` s'ancrait sur `old.cycle_id` : si la ligne
     *    partait de mon cycle, il rendait la main sans rien vérifier.
     *    `tg_derive_household` reposait ensuite le foyer sur celui de l'hôte, et
     *    le `with check` passait par son disjoint de session. L'hôte héritait
     *    d'un geste au libellé arbitraire, dont il devenait propriétaire — et
     *    dont la complétion écrivait une observation fabriquée dans son journal
     *    de durées, qu'il ne peut pas effacer.
     */
    const s = await sessionPartagee('poussee', '2030-02-04')
    const { data: sien } = await admin().from('cycle')
      .insert({ household_id: s.convive.householdId, week_of: '2030-02-11' })
      .select().single()
    const { data: geste } = await admin().from('session_task').insert({
      cycle_id: sien!.id, household_id: s.convive.householdId,
      label: 'INJECTÉ PAR LE CONVIVE', verb: 'flamber', quantity_g: 9000,
      duration_min: 300, planned_start_min: 0,
    }).select().single()

    const { error } = await s.convive.client.from('session_task')
      .update({ cycle_id: s.cycle }).eq('id', geste!.id)
    expect(error?.message, 'un geste a été poussé chez l’hôte')
      .toMatch(/ne change pas de session/)

    // Et pas davantage en INSÉRANT directement : le `with check` de l'INSERT
    // ne porte pas le disjoint de session, à la différence de celui de
    // l'UPDATE. C'est la RLS qui refuse ici, pas le trigger — donc on le
    // vérifie plutôt que de le supposer.
    const { error: pose } = await s.convive.client.from('session_task').insert({
      cycle_id: s.cycle, household_id: s.convive.householdId,
      label: 'INSÉRÉ PAR LE CONVIVE', duration_min: 5, planned_start_min: 0,
    })
    expect(pose, 'le convive a inséré un geste chez son hôte').not.toBeNull()

    const { data: chezLHote } = await admin().from('session_task')
      .select('id').eq('cycle_id', s.cycle)
    expect(chezLHote ?? [], 'la session de l’hôte a gagné un geste').toHaveLength(0)
  })

  it('ne laisse pas le convive ajouter une recette à la session de son hôte', async () => {
    // Sinon il désignerait n'importe quel identifiant et se le ferait ouvrir.
    const s = await sessionPartagee('ajout', '2029-12-03')
    const { data: sienne } = await s.convive.client.from('recipe').insert({
      title: 'La mienne', origin: 'manuelle', owner_household_id: s.convive.householdId,
      yield_servings: 2,
    }).select().single()
    const { error } = await s.convive.client.from('cycle_recipe').insert({
      cycle_id: s.cycle, household_id: s.convive.householdId,
      recipe_id: sienne!.id, servings: 1,
    })
    expect(error, 'le convive a garni la session de son hôte').not.toBeNull()
  })
})

/**
 * Une invitation vaut pour UNE session, et tant qu'on est amis.
 *
 * `session_convive` n'a ni expiration ni lien avec l'état du cycle : la seule
 * façon honnête de refermer est de le demander à chaque lecture.
 */
describe('ce qui referme la session', () => {
  async function sessionAvecUnConvive(nom: string, semaine: string) {
    const h = await makeActor(`${nom}-h`)
    const c = await makeActor(`${nom}-c`)
    await amis(h, c)
    const { data: cy } = await admin().from('cycle')
      .insert({ household_id: h.householdId, week_of: semaine, state: 'en_cuisine' })
      .select().single()
    await admin().from('session_task').insert({
      cycle_id: cy!.id, household_id: h.householdId, label: 'Mélanger',
      duration_min: 2, planned_start_min: 0,
    })
    await h.client.from('session_convive')
      .insert({ cycle_id: cy!.id, hote_id: h.householdId, invite_id: c.householdId })
    await c.client.from('session_convive')
      .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cy!.id)
    const { data: vu } = await c.client.from('session_task').select('id')
    expect(vu ?? [], 'l’amorce a échoué : le convive ne voyait déjà rien').toHaveLength(1)
    return { hote: h, convive: c, cycle: cy!.id }
  }

  it('la fin de la session', async () => {
    const s = await sessionAvecUnConvive('fin', '2029-05-07')
    await s.hote.client.from('cycle').update({ state: 'interrompue' }).eq('id', s.cycle)
    const { data } = await s.convive.client.from('session_task').select('id')
    expect(data ?? [], 'la session close reste ouverte au convive').toHaveLength(0)
  })

  it('la rupture de l’amitié', async () => {
    const s = await sessionAvecUnConvive('rupture', '2029-06-04')
    const { data: liens } = await s.hote.client.from('foyer_ami').select('id')
    await s.hote.client.from('foyer_ami').delete().eq('id', liens![0].id)
    const { data } = await s.convive.client.from('session_task').select('id')
    expect(data ?? [], 'un ami d’un dimanche cuisine pour toujours').toHaveLength(0)
  })

  it('le retrait par l’hôte, et le départ du convive', async () => {
    const s = await sessionAvecUnConvive('retrait', '2029-07-02')
    const { data: parti } = await s.convive.client.from('session_convive')
      .delete().eq('cycle_id', s.cycle).select()
    expect(parti ?? [], 'le convive ne peut pas s’en aller').toHaveLength(1)
    const { data } = await s.convive.client.from('session_task').select('id')
    expect(data ?? [], 'la session suit celui qui l’a quittée').toHaveLength(0)
  })

  it('l’accueil ne propose que des sessions vivantes', async () => {
    const s = await sessionAvecUnConvive('accueil', '2029-08-06')
    const { data: avant } = await s.convive.client.rpc('invitations_de_session')
    expect(avant ?? [], 'la session vivante ne s’affiche pas').toHaveLength(1)

    await s.hote.client.from('cycle').update({ state: 'interrompue' }).eq('id', s.cycle)
    const { data: apres } = await s.convive.client.rpc('invitations_de_session')
    expect(apres ?? [], 'une session close reste affichée à l’accueil').toHaveLength(0)
  })
})

describe('quand l’invitation est retirée', () => {
  beforeAll(async () => {
    const { error } = await hote.client.from('session_convive').delete().eq('cycle_id', cycle)
    expect(error, `le retrait a échoué : ${error?.message}`).toBeNull()
  })

  it('la session disparaît, et la recette privée avec elle', async () => {
    const { data: gestes } = await ami.client.from('session_task').select('id')
    expect(gestes ?? [], 'la session se voit encore').toHaveLength(0)
    const { data: recettes } = await ami.client.from('recipe').select('id').eq('id', recette)
    expect(recettes ?? [], 'la recette privée se lit encore').toHaveLength(0)
    const { data: etapes } = await ami.client.from('recipe_step').select('id').eq('recipe_id', recette)
    expect(etapes ?? [], 'les étapes se lisent encore').toHaveLength(0)
  })
})

/**
 * Le temps réel, éprouvé pour de vrai.
 *
 * C'est le seul mécanisme de l'app qu'un test unitaire ne peut pas simuler : il
 * dépend d'une publication Postgres, d'un WebSocket et de la RLS appliquée au
 * flux. Trois choses qui se cassent en silence — et dont la panne ne se voit
 * qu'à deux, en cuisine, un dimanche.
 */
describe('être prévenu', () => {
  let cycleBis: string
  let gesteBis: string
  let hoteBis: Actor    // un foyer n'a qu'un cycle vivant : il en faut un autre
  let convive: Actor

  beforeAll(async () => {
    hoteBis = await makeActor('ens-tr-hote')
    convive = await makeActor('ens-tr')
    await amis(hoteBis, convive)

    const { data: c, error } = await admin().from('cycle')
      .insert({ household_id: hoteBis.householdId, week_of: '2029-04-02', state: 'en_cuisine' })
      .select().single()
    expect(error, `l'amorce a échoué : ${error?.message}`).toBeNull()
    cycleBis = c!.id
    const { data: t } = await admin().from('session_task').insert({
      cycle_id: cycleBis, household_id: hoteBis.householdId, label: 'Préchauffer le four',
      duration_min: 10, planned_start_min: 0,
    }).select().single()
    gesteBis = t!.id

    const { error: ei } = await hoteBis.client.from('session_convive')
      .insert({ cycle_id: cycleBis, hote_id: hoteBis.householdId, invite_id: convive.householdId })
    expect(ei, `l'invitation a échoué : ${ei?.message}`).toBeNull()
    const { error: er } = await convive.client.from('session_convive')
      .update({ rejoint_le: new Date().toISOString() }).eq('cycle_id', cycleBis)
    expect(er, `rejoindre a échoué : ${er?.message}`).toBeNull()
  })

  it('pousse au convive le geste que l’hôte vient de prendre', async () => {
    /*
     * ⚠️ Deux pièges, et chacun a fait passer ce test pour cassé ou pour vert.
     *
     *    · `SUBSCRIBED` dit que le canal est joint, pas que le serveur a fini
     *      de poser le filtre sur le flux. Une écriture unique juste après
     *      tombait parfois dans ce trou : on réécrit donc jusqu'à réception.
     *    · le flux rejoue les écritures récentes à l'abonnement. Avec
     *      `event: '*'`, le premier reçu était l'INSERT de l'amorce et le test
     *      concluait sur lui, sans rien prouver du geste.
     */
    let repete: ReturnType<typeof setInterval> | undefined
    let minuteur: ReturnType<typeof setTimeout> | undefined
    const canal = convive.client.channel(`test:${cycleBis}`)

    try {
      const charge = await new Promise<Record<string, unknown>>((resolve, rejeter) => {
        minuteur = setTimeout(() => rejeter(new Error('rien n’est arrivé en 10 s')), 10_000)
        canal
          .on('postgres_changes',
              { event: 'UPDATE', schema: 'public', table: 'session_task',
                filter: `cycle_id=eq.${cycleBis}` },
              charge => resolve(charge.new))
          .subscribe(statut => {
            if (statut !== 'SUBSCRIBED') return
            // ⚠️ `async` n'est pas décoratif : une requête PostgREST ne part
            //    qu'au premier `then`. Rendre le constructeur sans l'attendre
            //    n'envoyait rien du tout, et la relance ne relançait rien.
            const ecrit = async () => {
              await hoteBis.client.from('session_task')
                .update({ assignee_id: hoteBis.userId, started_at: new Date().toISOString() })
                .eq('id', gesteBis)
            }
            void ecrit()
            repete = setInterval(ecrit, 1_500)
          })
      })

      expect(charge.id, 'ce n’est pas le bon geste').toBe(gesteBis)
      expect(charge.started_at, 'le geste arrive sans avoir été pris').not.toBeNull()
    } finally {
      clearTimeout(minuteur); clearInterval(repete)
      await convive.client.removeChannel(canal)
    }
  }, 20_000)

  it('ne pousse rien à un foyer qui n’est pas convié', async () => {
    // La RLS s'applique au flux comme au reste : c'est ce qui empêche un canal
    // nommé au hasard de servir de fenêtre chez les autres.
    const rien = await new Promise<string>(resolve => {
      const minuteur = setTimeout(() => resolve('silence'), 4_000)
      etranger.client
        .channel(`intrus:${cycleBis}`)
        .on('postgres_changes',
            { event: '*', schema: 'public', table: 'session_task',
              filter: `cycle_id=eq.${cycleBis}` },
            () => { clearTimeout(minuteur); resolve('reçu') })
        .subscribe(async statut => {
          if (statut !== 'SUBSCRIBED') return
          await hoteBis.client.from('session_task')
            .update({ done_at: new Date().toISOString() }).eq('id', gesteBis)
        })
    })
    expect(rien, 'un étranger a reçu la session').toBe('silence')
  }, 20_000)
})
