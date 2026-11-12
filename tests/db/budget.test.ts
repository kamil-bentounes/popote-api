/**
 * Le socle du budget : les comptes, les revenus, la clé de partage.
 *
 * Ce qui se joue ici n'est pas « la table existe » mais deux choses que le
 * reste du budget suppose vraies :
 *
 *  · la clé d'un mois donné ne bouge plus quand on saisit l'augmentation du
 *    mois suivant — sans ça, D62 (« la régularisation respecte l'histoire »)
 *    est une phrase sans mécanisme ;
 *  · la somme des parts fait EXACTEMENT 100 %. Un budget dont les parts ne
 *    recomposent pas le total est abandonné au troisième mois.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let moi: Actor
let voisin: Actor
/** Le deuxième membre du foyer, créé à la main : `makeActor` en fait un par foyer. */
let elle: string

beforeAll(async () => {
  moi = await makeActor('budget')
  voisin = await makeActor('budget-voisin')

  const { data } = await admin().auth.admin.createUser({
    email: `elle-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
  })
  elle = data.user!.id
  await admin().from('user_profile').insert({
    id: elle, household_id: moi.householdId, display_name: 'Elle',
  })

  /* `entre_le` vaut le jour de création du profil, ce qui est juste en usage
     réel — on accepte l'invitation le jour où l'on emménage. Les scénarios qui
     suivent se jouent sur des mois de 2026 : sans cette ligne, PERSONNE n'y est
     présent, et `parts_du_foyer` rend un ensemble vide à bon droit. */
  await admin().from('user_profile')
    .update({ entre_le: '2026-01-01' })
    .in('id', [moi.userId, elle])
  await admin().from('user_profile')
    .update({ entre_le: '2026-01-01' }).eq('id', voisin.userId)
})

/** La part de chacun, en points de base, pour le mois demandé. */
async function parts(a: Actor, mois: string): Promise<Record<string, number>> {
  const { data, error } = await a.client.rpc('parts_du_foyer', { le_mois: mois })
  expect(error, `parts_du_foyer a échoué : ${error?.message}`).toBeNull()
  return Object.fromEntries((data ?? []).map(
    (l: { user_profile_id: string; part_bps: number }) => [l.user_profile_id, l.part_bps]))
}

describe('la clé de partage', () => {
  it('suit les revenus, et la somme fait exactement 100 %', async () => {
    await admin().from('revenu').insert([
      { household_id: moi.householdId, user_profile_id: moi.userId,
        net_mensuel_cents: 370_000, valid_from: '2026-01-01' },
      { household_id: moi.householdId, user_profile_id: elle,
        net_mensuel_cents: 240_000, valid_from: '2026-01-01' },
    ])

    const p = await parts(moi, '2026-03-01')
    expect(p[moi.userId], 'le plus gros revenu doit porter la plus grosse part')
      .toBeGreaterThan(p[elle])
    // 370 000 / 610 000 = 60,65 %
    expect(p[moi.userId]).toBeGreaterThanOrEqual(6060)
    expect(p[moi.userId]).toBeLessThanOrEqual(6070)
    expect(Object.values(p).reduce((s, n) => s + n, 0),
      'la somme des parts ne recompose pas le total').toBe(10_000)
  })

  it('ne se recalcule PAS rétroactivement quand un revenu change', async () => {
    // Le cœur de D60/D62. On note l'augmentation de juin, puis on redemande
    // la clé de mars : elle doit être celle de mars.
    const mars = await parts(moi, '2026-03-01')

    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: elle,
      net_mensuel_cents: 320_000, valid_from: '2026-06-01',
    })

    expect(await parts(moi, '2026-03-01'),
      'une augmentation de juin a réécrit le partage de mars').toEqual(mars)

    const juin = await parts(moi, '2026-06-01')
    expect(juin[elle], 'juin n’a pas pris l’augmentation')
      .toBeGreaterThan(mars[elle])
    expect(Object.values(juin).reduce((s, n) => s + n, 0)).toBe(10_000)
  })

  it('n’inclut pas quelqu’un avant sa date d’entrée dans le foyer (D71)', async () => {
    await admin().from('user_profile').update({ entre_le: '2026-10-01' }).eq('id', elle)

    const avant = await parts(moi, '2026-03-01')
    expect(avant[elle], 'elle compte dans un mois où elle n’habitait pas là').toBeUndefined()
    expect(avant[moi.userId], 'seul présent, il porte tout').toBe(10_000)

    const apres = await parts(moi, '2026-11-01')
    expect(apres[elle], 'elle ne compte pas dans un mois où elle habite là').toBeGreaterThan(0)

    await admin().from('user_profile').update({ entre_le: '2020-01-01' }).eq('id', elle)
  })

  it('partage à parts égales quand la règle le dit, revenus ou pas', async () => {
    await admin().from('regle_partage').insert({
      household_id: moi.householdId, cle: 'moitie', valid_from: '2026-01-01',
    })
    const p = await parts(moi, '2026-03-01')
    expect(p[moi.userId], 'la moitié n’est pas la moitié').toBe(5000)
    expect(p[elle]).toBe(5000)

    await admin().from('regle_partage')
      .delete().eq('household_id', moi.householdId).eq('valid_from', '2026-01-01')
  })

  it('ne divise pas par zéro quand personne n’a saisi de revenu', async () => {
    // Un foyer qui vient d'ouvrir l'app doit voir un partage, pas une erreur.
    const p = await parts(voisin, '2026-03-01')
    expect(Object.values(p).reduce((s, n) => s + n, 0),
      'un foyer sans revenu ne rend pas 100 %').toBe(10_000)
  })
})

describe('les droits', () => {
  it('le foyer voit les revenus de ses membres, y compris ceux des autres', async () => {
    const { data } = await moi.client.from('revenu').select('user_profile_id')
    expect(new Set((data ?? []).map(r => r.user_profile_id)),
      'un membre ne voit pas le revenu de l’autre').toContain(elle)
  })

  it('le voisin ne voit rien, et n’écrit rien', async () => {
    const { data: vus } = await voisin.client.from('revenu')
      .select('id').eq('household_id', moi.householdId)
    expect(vus ?? [], 'le voisin lit les revenus du foyer d’à côté').toHaveLength(0)

    const { data: ecrit } = await voisin.client.from('compte').insert({
      household_id: moi.householdId, nom: 'Chez le voisin', genre: 'commun',
    }).select()
    // ⚠️ Une écriture refusée par RLS rend `error: null` et ZÉRO ligne : tester
    //    `error` seul laisserait passer une table grande ouverte.
    expect(ecrit ?? [], 'le voisin a écrit dans le foyer d’à côté').toHaveLength(0)
  })

  it('un compte ne peut pas désigner le titulaire du foyer d’à côté', async () => {
    const { error } = await moi.client.from('compte').insert({
      household_id: moi.householdId, nom: 'Compte mal rattaché',
      genre: 'perso', titulaire_id: voisin.userId,
    })
    expect(error, 'un compte désigne quelqu’un d’un autre foyer').not.toBeNull()
  })
})

describe('ce qui ne change pas', () => {
  it('la date d’effet d’un revenu ne se déplace pas', async () => {
    const { data: ligne } = await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: moi.userId,
      net_mensuel_cents: 100_000, valid_from: '2027-01-01',
    }).select().single()

    /* ⚠️ Une date LIBRE comme cible. La première version visait 2026-01-01, où
       cette personne a déjà un revenu : l'update échouait sur la contrainte
       d'unicité, pas sur le trigger, et le test serait resté vert même le
       trigger supprimé. Une relecture l'a montré en le retirant. */
    const { error } = await moi.client.from('revenu')
      .update({ valid_from: '2028-03-01' }).eq('id', ligne!.id)
    expect(error, 'on a déplacé un fait daté, donc réécrit le passé').not.toBeNull()

    const { data: apres } = await admin().from('revenu')
      .select('valid_from').eq('id', ligne!.id).single()
    expect(apres!.valid_from, 'la date a bougé quand même').toBe('2027-01-01')

    // Mais corriger le MONTANT reste permis : c'est une faute de frappe, pas
    // une réécriture de l'histoire.
    const { data: corrige } = await moi.client.from('revenu')
      .update({ net_mensuel_cents: 110_000 }).eq('id', ligne!.id).select()
    expect(corrige ?? [], 'on ne peut plus corriger une faute de frappe').toHaveLength(1)
  })

  it('un revenu ne change pas de personne', async () => {
    const { data: ligne } = await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: moi.userId,
      net_mensuel_cents: 90_000, valid_from: '2027-06-01',
    }).select().single()

    await moi.client.from('revenu')
      .update({ user_profile_id: elle }).eq('id', ligne!.id)

    /* On asserte l'ÉTAT, pas l'erreur. Une écriture entièrement refusée par
       RLS rend `error: null` et zéro ligne ; n'attendre qu'une erreur laisserait
       passer aussi bien une protection absente qu'une protection muette. */
    const { data: apres } = await admin().from('revenu')
      .select('user_profile_id').eq('id', ligne!.id).single()
    expect(apres!.user_profile_id, 'un revenu a été réattribué').toBe(moi.userId)
  })

  it('personne ne touche au revenu de l’autre, même dans son foyer', async () => {
    // D63 dit que le salaire est VISIBLE dans le foyer. Pas qu'il est écrivable
    // par l'autre — `nutrition_target` tranche déjà dans ce sens depuis 0005.
    const { data: sien } = await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: elle,
      net_mensuel_cents: 250_000, valid_from: '2029-01-01',
    }).select().single()

    await moi.client.from('revenu')
      .update({ net_mensuel_cents: 1 }).eq('id', sien!.id)
    await moi.client.from('revenu').delete().eq('id', sien!.id)

    const { data: apres } = await admin().from('revenu')
      .select('net_mensuel_cents').eq('id', sien!.id).maybeSingle()
    expect(apres, 'le revenu de l’autre a été supprimé').not.toBeNull()
    expect(apres!.net_mensuel_cents, 'le revenu de l’autre a été modifié').toBe(250_000)

    // Mais on voit toujours le sien : la lecture reste au foyer.
    const { data: vu } = await moi.client.from('revenu').select('id').eq('id', sien!.id)
    expect(vu ?? [], 'on ne voit plus le revenu de l’autre').toHaveLength(1)
  })

  it('un membre ne se fait pas disparaître des mois passés', async () => {
    // `entre_le` décide de ce qu'on paie : la porter à 2099 effaçait quelqu'un
    // de tous les mois, sans erreur et sans trace.
    const { error } = await moi.client.from('user_profile')
      .update({ entre_le: '2099-01-01' }).eq('id', moi.userId)
    expect(error, 'on peut encore se rendre absent de tous les mois').not.toBeNull()
  })
})

describe('l’export', () => {
  it('emporte les trois tables du lot', async () => {
    await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Commun', genre: 'commun', matelas_cents: 100_000,
    })
    const { data } = await moi.client.rpc('export_my_data')
    const j = data as Record<string, unknown[]>
    expect(j.comptes?.length, 'les comptes manquent à l’export').toBeGreaterThan(0)
    expect(j.revenus?.length, 'les revenus manquent à l’export').toBeGreaterThan(0)
    expect(j.regles_partage, 'les règles de partage manquent à l’export').toBeDefined()
    // Et l'export d'avant n'a pas été perdu en chemin.
    expect(j.household, 'le foyer a disparu de l’export').toBeDefined()
    expect(j.portions, 'les barquettes ont disparu de l’export').toBeDefined()
  })
})

describe('le catalogue des charges', () => {
  it('propose des sections à cocher, et se lit sans rien posséder', async () => {
    const { data, error } = await moi.client
      .from('catalogue_charge').select('section, libelle, periode, portee').order('ordre')
    expect(error, `le catalogue est illisible : ${error?.message}`).toBeNull()

    const sections = [...new Set((data ?? []).map(l => l.section))]
    expect(sections, 'les sections attendues manquent').toEqual(
      expect.arrayContaining(['Logement', 'Auto', 'Abonnements', 'Crédits']))

    // La périodicité proposée compte : une ligne annuelle saisie au mois fait
    // une erreur d'un facteur douze.
    const ct = (data ?? []).find(l => l.libelle === 'Contrôle technique')
    expect(ct?.periode, 'le contrôle technique n’est pas mensuel').toBe('annuel')
    const forfait = (data ?? []).find(l => l.libelle === 'Forfait mobile')
    expect(forfait?.portee, 'un forfait mobile n’est pas commun').toBe('perso')
  })

  it('ne se modifie pas depuis l’application', async () => {
    // Classe A : personne n'a besoin de renommer « Assurance auto ». Ce qui
    // appartient au foyer, c'est le montant, pas le libellé.
    const { data: ecrit } = await moi.client.from('catalogue_charge').insert({
      section: 'Pirate', libelle: 'À moi', periode: 'mensuel', portee: 'perso', ordre: 1,
    }).select()
    expect(ecrit ?? [], 'le référentiel est écrivable depuis l’app').toHaveLength(0)
  })
})
