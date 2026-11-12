/**
 * Les charges, et les dépenses qu'elles engendrent.
 *
 * Deux inventions à vérifier plutôt qu'à croire :
 *
 *  · l'ouverture d'un mois est IDEMPOTENTE. Il n'y a pas de `pg_cron` ici, donc
 *    elle est paresseuse : le premier qui ouvre l'app le 1er la déclenche. Si
 *    elle n'était pas idempotente, chaque visite ajouterait un jeu de dépenses.
 *  · la somme des parts figées recompose EXACTEMENT le montant. C'est tout
 *    l'intérêt des centimes entiers ; un budget dont les parts ne se
 *    recomposent pas est abandonné au troisième mois.
 *
 * ⚠️ Les `debut: '2026-01-01'` écrits en dur passent jusqu'au 31/12/2027 : le
 *    trigger de `charge` (0096) refuse un départ antérieur au 1er janvier de
 *    l'année précédente. Au 1er janvier 2028, il faudra les avancer.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'
import { ajustementEnAdmin } from './helpers/budget'

let moi: Actor
let elle: string
let voisin: Actor
let compteCommun: string

/** Le total des parts d'une dépense, en centimes. */
/** Le premier du mois courant, en heure locale. */
function moisCourant(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

async function sommeDesParts(depenseId: string): Promise<number> {
  const { data } = await admin().from('depense_part')
    .select('part_cents').eq('depense_id', depenseId)
  return (data ?? []).reduce((s, p) => s + p.part_cents, 0)
}

async function poseCharge(o: {
  libelle: string; cents: number; periodicite: string; participants: string[]
  cle?: string | null
}): Promise<string> {
  const { data: c, error } = await admin().from('charge').insert({
    household_id: moi.householdId, libelle: o.libelle, montant_cents: o.cents,
    periodicite: o.periodicite, cle: o.cle ?? null, compte_id: compteCommun,
    debut: '2026-01-01',
  }).select().single()
  expect(error, `charge refusée : ${error?.message}`).toBeNull()
  /* L'erreur était AVALÉE : un seul participant en échec fait échouer l'insert
     entier, la charge se retrouve sans personne, et le générateur l'ignore en
     silence. Le test échouait alors dix lignes plus loin, sur un message qui
     ne parlait que de provisions manquantes. */
  const { error: eP } = await admin().from('charge_participant').insert(
    o.participants.map(u => ({
      charge_id: c!.id, user_profile_id: u, household_id: moi.householdId,
    })))
  expect(eP, `participants refusés : ${eP?.message}`).toBeNull()
  return c!.id
}

/**
 * Une année soldée, comme la base la laisse désormais : `regularise_annuel` ne
 * fait plus que refuser (0113). On ouvre les mois d'abord — une fois l'année
 * soldée, plus aucun n'y naît —, puis le relevé, avec le prévu figé : la somme
 * des lignes de l'année.
 */
async function soldeAdmin(charge: string, annee: number, reelCents: number, a: Actor = moi) {
  const { data: lignes } = await admin().from('depense').select('montant_cents')
    .eq('charge_id', charge).eq('source', 'modele')
    .gte('mois', `${annee}-01-01`).lte('mois', `${annee}-12-01`)
  const prevu = (lignes ?? []).reduce((s, l) => s + l.montant_cents, 0)
  const { error } = await admin().from('releve_annuel').insert({
    household_id: a.householdId, charge_id: charge, annee,
    reel_cents: reelCents, prevu_cents: prevu, ecart_cents: reelCents - prevu,
  })
  expect(error, `relevé refusé : ${error?.message}`).toBeNull()
}

/** Ouvre les douze mois d'une charge, comme `regularise_annuel` le faisait. */
async function ouvreLAnnee(charge: string, annee: number, a: Actor = moi) {
  for (let m = 1; m <= 12; m++) {
    await a.client.rpc('ouvre_la_charge', { la_charge: charge, foyer: a.householdId,
      le_mois: `${annee}-${String(m).padStart(2, '0')}-01` })
  }
}

beforeAll(async () => {
  moi = await makeActor('charges')
  voisin = await makeActor('charges-voisin')
  const { data } = await admin().auth.admin.createUser({
    email: `elle-ch-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
  })
  elle = data.user!.id
  await admin().from('user_profile').insert({
    id: elle, household_id: moi.householdId, display_name: 'Elle',
  })
  await admin().from('user_profile')
    .update({ entre_le: '2026-01-01' }).in('id', [moi.userId, elle])

  // 3 700 / 2 400 → 60,65 / 39,34, soit 6066 / 3934 points de base.
  await admin().from('revenu').insert([
    { household_id: moi.householdId, user_profile_id: moi.userId,
      net_mensuel_cents: 370_000, valid_from: '2026-01-01' },
    { household_id: moi.householdId, user_profile_id: elle,
      net_mensuel_cents: 240_000, valid_from: '2026-01-01' },
  ])

  const { data: cpt } = await admin().from('compte').insert({
    household_id: moi.householdId, nom: 'Commun', genre: 'commun', matelas_cents: 100_000,
  }).select().single()
  compteCommun = cpt!.id
})

describe('l’ouverture d’un mois', () => {
  it('engendre une dépense par charge active, et fige les parts au centime', async () => {
    await poseCharge({ libelle: 'Internet', cents: 3_700, periodicite: 'mensuel',
                       participants: [moi.userId, elle] })

    const { data: nees, error } = await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-03-01' })
    expect(error, `ouverture refusée : ${error?.message}`).toBeNull()
    expect(nees, 'aucune dépense engendrée').toBeGreaterThan(0)

    const { data: d } = await admin().from('depense')
      .select('id, montant_cents, mois, nature, source')
      .eq('household_id', moi.householdId).eq('mois', '2026-03-01').single()
    expect(d!.montant_cents, 'une charge mensuelle vaut son montant').toBe(3_700)
    expect(d!.source).toBe('modele')

    expect(await sommeDesParts(d!.id),
      'la somme des parts ne recompose pas le montant').toBe(3_700)

    const { data: parts } = await admin().from('depense_part')
      .select('user_profile_id, part_cents, part_bps').eq('depense_id', d!.id)
    const mienne = parts!.find(p => p.user_profile_id === moi.userId)!
    expect(mienne.part_cents, 'le plus gros revenu porte la plus grosse part')
      .toBeGreaterThan(parts!.find(p => p.user_profile_id === elle)!.part_cents)
    expect(mienne.part_bps).toBeGreaterThanOrEqual(6060)
  })

  it('ne double rien quand on la relance — l’ouverture est paresseuse', async () => {
    const avant = await admin().from('depense')
      .select('id', { count: 'exact', head: true })
      .eq('household_id', moi.householdId).eq('mois', '2026-03-01')

    for (let i = 0; i < 3; i++) {
      await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-03-01' })
    }

    const apres = await admin().from('depense')
      .select('id', { count: 'exact', head: true })
      .eq('household_id', moi.householdId).eq('mois', '2026-03-01')
    expect(apres.count, 'rouvrir le mois a dupliqué les dépenses').toBe(avant.count)
  })

  it('donne tout à celui qui paie seul, pas sa part de foyer', async () => {
    // Le piège : les participants d'une charge ne sont pas tout le foyer, donc
    // leurs parts ne font pas 10 000 à elles seules. Sans renormalisation, un
    // payeur unique ne se verrait attribuer que 60 % de ce qu'il paie en entier.
    await poseCharge({ libelle: 'Crédit auto', cents: 25_000, periodicite: 'mensuel',
                       participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-04-01' })

    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2026-04-01')
      .eq('libelle', 'Crédit auto').single()
    const { data: parts } = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)

    expect(parts, 'une charge à un seul participant en a produit plusieurs').toHaveLength(1)
    expect(parts![0].part_cents, 'il ne porte pas la totalité de ce qu’il paie seul')
      .toBe(25_000)
  })

  it('ramène une charge annuelle au douzième (D61)', async () => {
    // 1450 € de taxe foncière, ce n'est pas « une dépense en octobre ».
    await poseCharge({ libelle: 'Taxe foncière', cents: 145_000, periodicite: 'annuel',
                       participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-05-01' })

    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2026-05-01')
      .eq('libelle', 'Taxe foncière').single()
    expect(d!.montant_cents, '1450 € par an font 120,83 € par mois').toBe(12_083)
    expect(await sommeDesParts(d!.id), 'les parts ne recomposent pas le douzième')
      .toBe(12_083)
  })

  it('ignore quelqu’un qui n’était pas encore là (D71)', async () => {
    await admin().from('user_profile').update({ entre_le: '2026-10-01' }).eq('id', elle)
    await poseCharge({ libelle: 'Électricité', cents: 5_000, periodicite: 'mensuel',
                       participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-06-01' })

    const { data: d } = await admin().from('depense').select('id')
      .eq('household_id', moi.householdId).eq('mois', '2026-06-01')
      .eq('libelle', 'Électricité').single()
    const { data: parts } = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)

    expect(parts, 'elle paie un mois où elle n’habitait pas là').toHaveLength(1)
    expect(parts![0].user_profile_id).toBe(moi.userId)
    expect(parts![0].part_cents).toBe(5_000)

    await admin().from('user_profile').update({ entre_le: '2026-01-01' }).eq('id', elle)
  })

  it('un montant impair se partage sans perdre le centime', async () => {
    // 10,25 € en 50/50 : 5,125 chacun. Deux parts arrondies feraient 10,26.
    await admin().from('regle_partage').insert({
      household_id: moi.householdId, cle: 'moitie', valid_from: '2026-01-01',
    })
    await poseCharge({ libelle: 'Impair', cents: 1_025, periodicite: 'mensuel',
                       participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-07-01' })

    const { data: d } = await admin().from('depense').select('id')
      .eq('household_id', moi.householdId).eq('mois', '2026-07-01')
      .eq('libelle', 'Impair').single()
    expect(await sommeDesParts(d!.id), 'le centime s’est perdu ou dupliqué').toBe(1_025)

    await admin().from('regle_partage')
      .delete().eq('household_id', moi.householdId).eq('cle', 'moitie')
  })
})

describe('ce qui ne change pas', () => {
  it('une dépense ne change ni de mois ni de charge', async () => {
    const { data: d } = await admin().from('depense').select('id, mois, charge_id')
      .eq('household_id', moi.householdId).eq('mois', '2026-03-01').limit(1).single()

    const { error: e1 } = await moi.client.from('depense')
      .update({ mois: '2026-02-01' }).eq('id', d!.id)
    expect(e1, 'une dépense a changé de mois').not.toBeNull()

    /* Dénouer le lien est permis — une régularisation manuelle le fait. Le
       DÉPLACER vers une autre charge, non : c'est ça, l'ancrage. */
    const autre = await poseCharge({ libelle: 'Ailleurs', cents: 100,
                                     periodicite: 'mensuel', participants: [moi.userId] })
    const { error: e2 } = await moi.client.from('depense')
      .update({ charge_id: autre }).eq('id', d!.id)
    expect(e2, 'une dépense a été déplacée vers une autre charge').not.toBeNull()
  })

  it('une part figée ne se retouche pas', async () => {
    /* ⚠️ Cadré sur MON foyer. Sans `.eq('household_id', …)`, ce select prenait
       une part au hasard dans toute la base — parfois celle d'un autre foyer,
       où la RLS refuse en silence (`error: null`, zéro ligne). Le test passait
       seul et échouait dans la suite, ce qui est la pire des deux façons. */
    const { data: p } = await admin().from('depense_part')
      .select('depense_id, user_profile_id, part_cents')
      .eq('household_id', moi.householdId).limit(1).single()
    const { error } = await moi.client.from('depense_part')
      .update({ part_cents: 1 })
      .eq('depense_id', p!.depense_id).eq('user_profile_id', p!.user_profile_id)
    expect(error, 'une part figée a été retouchée').not.toBeNull()
  })

  it('une charge qui a une histoire ne se supprime pas : elle s’archive', async () => {
    /* `on delete set null` avait deux défauts. Il émettait un UPDATE que
       `tg_depense_ancree` refusait — un membre ne pouvait pas supprimer sa
       propre charge, et le test d'origine ne le voyait pas parce qu'il
       supprimait en rôle de service. Et l'unicité étant `nulls distinct`,
       supprimer puis recréer une charge facturait le mois deux fois. */
    const id = await poseCharge({ libelle: 'Éphémère', cents: 1_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-08-01' })

    const { error } = await moi.client.from('charge').delete().eq('id', id)
    expect(error, 'une charge avec des dépenses a été supprimée').not.toBeNull()

    /* On l'archive : elle cesse d'engendrer, son histoire reste. Depuis 0096 le
       client n'archive plus en direct (`tg_charge_garde`) : seul « Retirer » le
       fait, et une charge dont la seule ligne est ouverte et non confirmée
       partirait entièrement. On confirme donc la ligne d'août : c'est elle,
       l'histoire. */
    const { error: confirme } = await admin().from('depense')
      .update({ confirme_le: '2026-08-31T20:00:00Z' })
      .eq('household_id', moi.householdId).eq('libelle', 'Éphémère').eq('mois', '2026-08-01')
    expect(confirme, 'la préparation a échoué').toBeNull()
    const direct = await moi.client.from('charge')
      .update({ archive_le: '2026-08-31' }).eq('id', id).select()
    expect(direct.error?.message, 'le client a archivé la charge sans passer par « Retirer »')
      .toMatch(/Retirer/)
    const retrait = await moi.client.rpc('retire_charge', { p_charge: id })
    expect(retrait.error, `retrait refusé : ${retrait.error?.message}`).toBeNull()
    expect(retrait.data, 'la charge à histoire devait s’archiver').toBe('archivee')
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-09-01' })

    const { data: apres } = await admin().from('depense').select('mois')
      .eq('household_id', moi.householdId).eq('libelle', 'Éphémère')
    expect(apres!.map(d => d.mois), 'une charge archivée engendre encore')
      .toEqual(['2026-08-01'])
  })

  it('une charge vierge, elle, se supprime sans façon', async () => {
    const id = await poseCharge({ libelle: 'Jamais ouverte', cents: 100,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    const { error } = await moi.client.from('charge').delete().eq('id', id)
    expect(error, 'une charge sans histoire refuse de partir').toBeNull()
  })
})

describe('retirer une charge', () => {
  /*
   * « Retirer » veut dire une seule chose : la charge disparaît, et on ne la
   * revoit plus. Elle s'archivait dès qu'elle avait une ligne, et les mois
   * déjà ouverts la GARDAIENT — le 25/09, un doublon retiré sur la foi de la
   * revue comptait encore 580 € en septembre.
   *
   * Seules restent les lignes que la base protège déjà : celles qu'on a
   * confirmées, et celles d'un mois marqué réglé. C'est de l'argent dont on a
   * dit qu'il était sorti ; la charge s'archive alors pour les garder.
   */
  async function lignes(libelle: string) {
    const { data } = await admin().from('depense').select('id, mois')
      .eq('household_id', moi.householdId).eq('libelle', libelle).order('mois')
    return data ?? []
  }

  it('la retire de TOUS les mois, et la charge avec', async () => {
    const id = await poseCharge({ libelle: 'Doublon du prêt', cents: 58_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-08-01' })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-09-01' })
    expect((await lignes('Doublon du prêt')).length).toBe(2)

    const { data, error } = await moi.client.rpc('retire_charge', { p_charge: id })
    expect(error, `retrait refusé : ${error?.message}`).toBeNull()
    expect(data).toBe('supprimee')
    expect(await lignes('Doublon du prêt'), 'un mois ouvert garde la charge retirée')
      .toEqual([])
    const { data: reste } = await admin().from('charge').select('id').eq('id', id)
    expect(reste, 'la charge retirée existe encore').toEqual([])
  })

  it('garde le mois marqué réglé et la ligne confirmée, et archive la charge', async () => {
    const id = await poseCharge({ libelle: 'Netflix arrêté', cents: 1_400,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    for (const m of ['2026-06-01', '2026-07-01', '2026-08-01']) {
      await moi.client.rpc('ouvre_le_mois', { le_mois: m })
    }
    const avant = await lignes('Netflix arrêté')
    await admin().from('depense').update({ regle_le: new Date().toISOString() })
      .eq('id', avant[0].id)
    await admin().from('depense').update({ confirme_le: new Date().toISOString() })
      .eq('id', avant[1].id)

    const { data, error } = await moi.client.rpc('retire_charge', { p_charge: id })
    expect(error, `retrait refusé : ${error?.message}`).toBeNull()
    expect(data).toBe('archivee')
    expect((await lignes('Netflix arrêté')).map(l => l.mois),
      'le réglé et le confirmé devaient rester, le reste partir')
      .toEqual(['2026-06-01', '2026-07-01'])
    const { data: c } = await admin().from('charge').select('archive_le').eq('id', id).single()
    expect(c!.archive_le, 'la charge qui garde des lignes n’est pas archivée').not.toBeNull()
  })

  it('ne retire rien chez un autre foyer', async () => {
    const id = await poseCharge({ libelle: 'Pas à toi', cents: 3_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-08-01' })
    const { error } = await voisin.client.rpc('retire_charge', { p_charge: id })
    expect(error, 'un voisin a retiré une charge qui n’est pas la sienne').not.toBeNull()
    expect((await lignes('Pas à toi')).length).toBe(1)
    const { data: c } = await admin().from('charge').select('archive_le').eq('id', id).single()
    expect(c!.archive_le).toBeNull()
  })
})

describe('la clé propre à une charge', () => {
  it('l’emporte sur celle du foyer (« Netflix à 50/50 »)', async () => {
    /* ⚠️ Ce test n'existait pas, et la colonne `charge.cle` n'était JAMAIS lue :
       `ouvre_le_mois` ne consultait que la règle du foyer. Deux charges
       identiques, l'une `moitie` et l'autre non, donnaient exactement le même
       partage — la seule fonctionnalité explicitement demandée était morte. */
    await poseCharge({ libelle: 'Au prorata', cents: 10_000, periodicite: 'mensuel',
                       participants: [moi.userId, elle] })
    await poseCharge({ libelle: 'À la moitié', cents: 10_000, periodicite: 'mensuel',
                       cle: 'moitie', participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-11-01' })

    const part = async (libelle: string) => {
      const { data: d } = await admin().from('depense').select('id')
        .eq('household_id', moi.householdId).eq('mois', '2026-11-01')
        .eq('libelle', libelle).single()
      const { data: p } = await admin().from('depense_part')
        .select('part_cents').eq('depense_id', d!.id).eq('user_profile_id', moi.userId).single()
      return p!.part_cents
    }

    expect(await part('À la moitié'), 'la clé de la charge est ignorée').toBe(5_000)
    expect(await part('Au prorata'), 'le prorata ne s’applique plus').toBeGreaterThan(5_500)
  })

  it('renormalise vraiment sur les participants, à trois dans le foyer', async () => {
    /* L'ancien test de renormalisation était tautologique : un seul
       participant, donc le centime résiduel lui reversait tout l'écart. En
       remplaçant la renormalisation par une division par 10000, il restait
       vert. À trois membres et deux participants, la faute se voit. */
    const { data: u } = await admin().auth.admin.createUser({
      email: `tiers-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const tiers = u.user!.id
    await admin().from('user_profile').insert({
      id: tiers, household_id: moi.householdId, display_name: 'Tiers', entre_le: '2026-01-01',
    })
    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: tiers,
      net_mensuel_cents: 390_000, valid_from: '2026-01-01',
    })

    await poseCharge({ libelle: 'À deux sur trois', cents: 10_000, periodicite: 'mensuel',
                       participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-12-01' })

    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2026-12-01')
      .eq('libelle', 'À deux sur trois').single()
    const { data: parts } = await admin().from('depense_part')
      .select('user_profile_id, part_cents, part_bps').eq('depense_id', d!.id)

    expect(parts, 'le tiers paie une charge à laquelle il ne participe pas').toHaveLength(2)
    expect(await sommeDesParts(d!.id), 'les deux parts ne font pas le montant').toBe(10_000)

    /* AU CENTIME, et pas « supérieur à ». Une première version bornait par le
       bas : en remplaçant la renormalisation par une division par 10 000, le
       reliquat reversait tout l'écart au plus gros contributeur et le test
       restait vert — 76,00 € au lieu de 60,66 € passaient tous les deux.
       Les valeurs exactes : 3700 et 2400 points de base sur 6100 de total,
       donc 6065 et 3934 centimes, plus le centime résiduel au premier. */
    const mienne = parts!.find(p => p.user_profile_id === moi.userId)!
    const sienne = parts!.find(p => p.user_profile_id === elle)!
    expect(mienne.part_cents, 'la renormalisation ne se fait pas sur les participants')
      .toBe(6_066)
    expect(sienne.part_cents, 'sa part n’est pas celle de leur duo').toBe(3_934)
    /* 6066, et non plus 6065 : les points de base sont eux aussi répartis aux
       plus forts restes, donc ils somment à 10 000 exactement. La version
       tronquée en perdait un et la trace d'audit ne recomposait pas le tout. */
    expect(mienne.part_bps, 'le bps figé n’explique pas la part en centimes').toBe(6_066)
    const { data: tousBps } = await admin().from('depense_part')
      .select('part_bps').eq('depense_id', d!.id)
    expect(tousBps!.reduce((s, p) => s + p.part_bps, 0),
      'les points de base ne recomposent pas 100 %').toBe(10_000)

    await admin().from('revenu').delete().eq('user_profile_id', tiers)
    await admin().from('user_profile').delete().eq('id', tiers)
  })
})

describe('la somme des parts ne peut pas mentir', () => {
  it('ni en reposant des parts fausses', async () => {
    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2026-03-01').limit(1).single()

    await moi.client.from('depense_part').delete().eq('depense_id', d!.id)
    const { error } = await moi.client.from('depense_part').insert({
      depense_id: d!.id, user_profile_id: moi.userId,
      household_id: moi.householdId, part_cents: 1, part_bps: 10_000,
    })
    expect(error, 'on a reposé des parts qui ne font pas le montant').not.toBeNull()
  })

  it('ni en changeant le montant sans reposer les parts', async () => {
    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2026-04-01')
      .eq('libelle', 'Crédit auto').single()
    const { error } = await moi.client.from('depense')
      .update({ montant_cents: 1 }).eq('id', d!.id)
    expect(error, 'le montant a changé en laissant les parts d’avant').not.toBeNull()
  })
})

describe('la régularisation de D62', () => {
  it('peut poser une seconde ligne sur la même charge et le même mois', async () => {
    /* L'unicité `(charge_id, mois)` interdisait toute ligne d'ajustement — la
       régularisation annoncée par D62 était impossible. Elle ne porte plus que
       sur ce que le générateur produit. Depuis 0101 le client n'écrit plus de
       ligne de charge : l'ajustement s'insère par la clé de service, comme la
       base le pose. */
    const { data: d } = await admin().from('depense').select('id, charge_id, mois')
      .eq('household_id', moi.householdId).eq('mois', '2026-05-01')
      .eq('libelle', 'Taxe foncière').single()

    const { data: ajout, error } = await admin().from('depense').insert({
      household_id: moi.householdId, charge_id: d!.charge_id, mois: d!.mois,
      libelle: 'Taxe foncière — régularisation', montant_cents: 2_000,
      nature: 'connue', source: 'manuel', regularise_annee: 2026,
    }).select()
    expect(error, `la régularisation est refusée : ${error?.message}`).toBeNull()
    expect(ajout ?? [], 'aucune ligne de régularisation créée').toHaveLength(1)
  })
})

describe('ce que la relecture finale a trouvé', () => {
  it('ramène une charge trimestrielle au tiers, pas au mois', async () => {
    /* ⚠️ `provision_mensuelle('trimestriel')` n'était couvert par AUCUN test :
       en remplaçant `round(montant/3.0)` par le montant entier, les 728 tests
       restaient verts. La copro à 300 € le trimestre — le cas réel de ce
       foyer — pouvait être facturée 300 € par mois sans que rien ne rougisse. */
    await poseCharge({ libelle: 'Copropriété', cents: 30_000, periodicite: 'trimestriel',
                       participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-02-01' })

    const { data: d } = await admin().from('depense').select('id, montant_cents')
      .eq('household_id', moi.householdId).eq('mois', '2027-02-01')
      .eq('libelle', 'Copropriété').single()
    expect(d!.montant_cents, '300 € par trimestre font 100 € par mois').toBe(10_000)
    expect(await sommeDesParts(d!.id)).toBe(10_000)
  })

  it('n’engendre rien pour quelqu’un qui n’est pas encore là', async () => {
    /* Le générateur ne vérifiait que l'EXISTENCE d'un participant, pas sa
       PRÉSENCE : une charge dont l'unique participant arrive le mois suivant
       produisait une dépense SANS AUCUNE PART. Elle pesait dans l'enveloppe et
       dans « à confirmer », et personne ne la devait. */
    const { data: u } = await admin().auth.admin.createUser({
      email: `futur-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const futur = u.user!.id
    await admin().from('user_profile').insert({
      id: futur, household_id: moi.householdId, display_name: 'Futur', entre_le: '2027-10-01',
    })

    await poseCharge({ libelle: 'Pas encore là', cents: 5_000, periodicite: 'mensuel',
                       participants: [futur] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-03-01' })

    const { data: d } = await admin().from('depense').select('id')
      .eq('household_id', moi.householdId).eq('mois', '2027-03-01')
      .eq('libelle', 'Pas encore là').maybeSingle()
    expect(d, 'une dépense est née sans personne pour la payer').toBeNull()

    await admin().from('user_profile').delete().eq('id', futur)
  })

  it('un compte perso exige un titulaire, un compte commun n’en a pas', async () => {
    const { error: e1 } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Perso sans nom', genre: 'perso',
    })
    expect(e1, 'un compte perso sans titulaire est accepté').not.toBeNull()

    const { error: e2 } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Commun avec titulaire', genre: 'commun',
      titulaire_id: moi.userId,
    })
    expect(e2, 'un compte commun avec titulaire est accepté').not.toBeNull()
  })

  it('un nom de compte se réutilise une fois le compte archivé', async () => {
    const { data: c } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Livret', genre: 'epargne',
    }).select().single()
    await admin().from('compte')
      .update({ archive_le: new Date().toISOString() }).eq('id', c!.id)

    const { error } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Livret', genre: 'epargne',
    })
    expect(error, 'un compte archivé confisque son nom pour toujours').toBeNull()
  })
})

describe('la régularisation annuelle (D62)', () => {
  it('un mois révolu JAMAIS ouvert ne compte pas comme « à venir »', async () => {
    /*
     * Le pendule de l'autre côté. 0073 mesure l'écart sur l'année entière —
     * juste — mais `provisions_a_venir` comptait « tout mois sans dépense »,
     * donc AUSSI les mois révolus que personne n'a ouverts. Le cas est le plus
     * ordinaire qui soit : on installe l'app en septembre et on pose la taxe
     * foncière avec « depuis janvier », ce que l'écran encourage. Un seul mois
     * ouvert, et l'app facturait 120,87 € pour une facture de 1 450 €.
     */
    const id = await poseCharge({ libelle: 'Foncier tardif ouvert', cents: 120_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    /* UN SEUL mois ouvert : le mois COURANT.
       ⚠️ Il était écrit en dur, « 2026-09-01 », alors que l'assertion compte
          les mois restants depuis la date du jour : le 1er octobre, octobre
          n'était pas ouvert et comptait comme « à venir ». */
    await moi.client.rpc('ouvre_le_mois', { le_mois: moisCourant() })

    const { data: aVenir } = await moi.client.rpc('provisions_a_venir',
      { la_charge: id, annee: new Date().getFullYear() })
    /* Ce qui reste à provisionner, ce sont les mois À VENIR de l'année — pas
       les huit mois révolus que personne n'ouvrira jamais. */
    /* ⚠️ Une ÉGALITÉ, pas un « au plus » : une fonction qui rendrait zéro
       passait l'ancienne assertion. Il reste exactement les mois d'octobre à
       décembre — le mois courant est déjà ouvert. */
    const moisRestants = 12 - (new Date().getMonth() + 1)
    expect(Number(aVenir),
      'les mois révolus jamais ouverts sont comptés comme à venir')
      .toBe(moisRestants * 10_000)
  })

  it('ne promet pas des provisions que personne ne fera', async () => {
    /* `ouvre_le_mois` exige un participant déjà arrivé. `provisions_a_venir`
       n'avait pas ce prédicat : il promettait des mois qui ne s'ouvriront
       jamais — mesuré à 724,98 € d'écart pour quelqu'un arrivé en juillet. */
    const tard = (await admin().auth.admin.createUser({
      email: `tard-av-${Date.now()}@fumee.test`, password: 'x'.repeat(12),
      email_confirm: true,
    })).data.user!.id
    await admin().from('user_profile').insert({
      id: tard, household_id: moi.householdId, display_name: 'Tard',
      entre_le: '2027-07-01',
    })
    const { data: c } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Que pour lui', montant_cents: 120_000,
      periodicite: 'annuel', debut: '2027-01-01', compte_id: compteCommun,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: tard, household_id: moi.householdId,
    })

    /* Il arrive en juillet : six mois, pas douze. Sans le prédicat de
       participant, la fonction en promettait douze. */
    const { data: aVenir } = await moi.client.rpc('provisions_a_venir',
      { la_charge: c!.id, annee: 2027 })
    expect(Number(aVenir),
      'on promet des provisions pour des mois sans personne au foyer')
      .toBe(6 * 10_000)

    await admin().from('user_profile').delete().eq('id', tard)
  })

  it('ne laisse pas lire les provisions d’une charge d’un autre foyer', async () => {
    /* `provisions_a_venir` est `security definer` et accordée à
       `authenticated` : sans filtre de foyer, un identifiant deviné rendait le
       montant exact de la charge du voisin. `provisions_de` filtrait déjà. */
    /* ⚠️ AVEC un participant, sinon le test est vide : le prédicat de
       participant ajouté par la même migration rend déjà zéro, et il passerait
       que le filtre de foyer soit là ou non. Toute charge réelle en a un. */
    const { data: sienne } = await admin().from('charge').insert({
      household_id: voisin.householdId, libelle: 'Secrète', montant_cents: 987_660,
      periodicite: 'annuel', debut: '2030-01-01',
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: sienne!.id, user_profile_id: voisin.userId,
      household_id: voisin.householdId,
    })

    const { data: fuite } = await moi.client.rpc('provisions_a_venir',
      { la_charge: sienne!.id, annee: 2030 })
    expect(Number(fuite ?? 0), 'le montant du voisin a fuité').toBe(0)
  })

  it('corriger une charge n’efface pas le relevé d’une année CLOSE', async () => {
    /*
     * `corrige_la_charge` supprimait les régularisations de TOUTES les années.
     * Renommer une charge un an plus tard évaporait 150,04 € d'une année close
     * et payée, en silence. Le test d'avant n'utilisait qu'UNE année : il ne
     * pouvait structurellement pas distinguer « toutes » de « celles qu'on
     * refait ».
     */
    const id = await poseCharge({ libelle: 'Deux années', cents: 120_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    for (const annee of [2029, 2030]) {
      for (let m = 1; m <= 12; m++) {
        await moi.client.rpc('ouvre_le_mois',
          { le_mois: `${annee}-${String(m).padStart(2, '0')}-01` })
      }
    }
    /* 2029 est SOLDÉE, comme la base la laisse : le relevé, et la ligne
       d'ajustement que le solde a posée (1 350 € payés pour 1 200 € prévus). */
    await soldeAdmin(id, 2029, 135_000)
    await ajustementEnAdmin(moi, id, '2029-12-01', 2029, 15_000)

    /* On renomme la charge — le geste le plus anodin qui soit. */
    await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Deux années, renommée',
      nouveau_montant: 120_000, nouvelle_periodicite: 'annuel',
    })

    const { data: trace } = await moi.client.from('releve_annuel')
      .select('annee').eq('charge_id', id)
    expect((trace ?? []).map(t => t.annee),
      'le relevé d’une année close a été effacé').toContain(2029)

    const { data: reg } = await admin().from('depense')
      .select('montant_cents').eq('charge_id', id).eq('regularise_annee', 2029)
    expect(reg ?? [], 'la régularisation d’une année close a été effacée')
      .toHaveLength(1)
  })
})

describe('le relevé du mois et l’excédent', () => {
  it('garde ce qui avait été prévu quand on saisit le réel', async () => {
    /* Sans mémoire du prévu, la comparaison disparaît au moment même où elle
       devient possible : confirmer écrase `montant_cents`. */
    const id = await poseCharge({ libelle: 'Énergie relevé', cents: 5_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-01-01' })

    const { data: d } = await admin().from('depense')
      .select('id, montant_cents, montant_prevu_cents')
      .eq('charge_id', id).eq('mois', '2029-01-01').single()
    expect(d!.montant_prevu_cents, 'le prévu n’a pas été gelé').toBe(5_000)

    /* On confirme un réel plus bas : 38 € au lieu de 50. Par la FONCTION, et
       non en réécrivant les parts à la main — c'est désormais le seul chemin,
       et c'est voulu : le contrôle de somme ne regardant que le total, les
       reposer soi-même permettait de passer de 600/400 à un centime contre
       999,99 €. */
    const { error: eConf } = await moi.client.rpc('confirme_la_depense',
      { la_depense: d!.id, reel_cents: 3_800 })
    expect(eConf, `confirmation refusée : ${eConf?.message}`).toBeNull()

    const { data: apres } = await admin().from('depense')
      .select('montant_cents, montant_prevu_cents').eq('id', d!.id).single()
    expect(apres!.montant_cents).toBe(3_800)
    expect(apres!.montant_prevu_cents, 'le prévu a été réécrit').toBe(5_000)
  })

  it('calcule l’excédent sans aucun solde bancaire', async () => {
    const { data, error } = await moi.client.rpc('excedent_du_mois', { le_mois: '2029-01-01' })
    expect(error, `excédent refusé : ${error?.message}`).toBeNull()
    const mien = (data ?? []).find(
      (l: { user_profile_id: string }) => l.user_profile_id === moi.userId)
    // 50 € provisionnés, 38 € payés : 12 € versés en trop.
    expect(Number(mien.excedent_cents), 'l’excédent est faux').toBe(1_200)
  })

  it('ne compte que les lignes confirmées', async () => {
    // Une provision non confirmée n'est pas un excédent : on ne sait pas encore.
    await poseCharge({ libelle: 'Pas confirmée', cents: 9_000,
                       periodicite: 'mensuel', variable: true, participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-01-01' })

    const { data } = await moi.client.rpc('excedent_du_mois', { le_mois: '2029-01-01' })
    const mien = (data ?? []).find(
      (l: { user_profile_id: string }) => l.user_profile_id === moi.userId)
    expect(Number(mien.excedent_cents),
      'une ligne non confirmée est comptée dans l’excédent').toBe(1_200)
  })

  it('le prévu ne se réécrit pas', async () => {
    const { data: d } = await admin().from('depense').select('id')
      .eq('household_id', moi.householdId).eq('source', 'modele').limit(1).single()
    const { error } = await moi.client.from('depense')
      .update({ montant_prevu_cents: 1 }).eq('id', d!.id)
    expect(error, 'ce qui avait été prévu a été réécrit').not.toBeNull()
  })

  it('une charge portée par une enveloppe est une prévision', async () => {
    // Le restaurant à 400 € n'est pas un montant connu : c'est un plafond
    // qu'on confirmera. Sans ça, il n'apparaîtrait jamais dans le relevé.
    const { data: env } = await admin().from('enveloppe').insert({
      household_id: moi.householdId, libelle: 'Sorties', plafond_cents: 10_000,
    }).select().single()
    const { data: ch } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Sorties', montant_cents: 10_000,
      periodicite: 'mensuel', debut: '2029-01-01', enveloppe_id: env!.id,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: ch!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-02-01' })

    const { data: d } = await admin().from('depense').select('nature')
      .eq('charge_id', ch!.id).eq('mois', '2029-02-01').single()
    expect(d!.nature, 'une charge d’enveloppe est donnée pour connue').toBe('estimee')
  })
})

describe('la régularisation ne se déclenche qu’une fois', () => {

  it('le voisin ne lit pas les provisions d’un autre foyer', async () => {
    // `provisions_de` est `security definer` et accordée à `authenticated` :
    // sans le filtre de foyer, une fuite passerait la CI sans bruit.
    const { data: sienne } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Privée', montant_cents: 1_000,
      periodicite: 'annuel', debut: '2030-01-01',
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: sienne!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2030-03-01' })

    const { data } = await voisin.client.rpc('provisions_de',
      { la_charge: sienne!.id, annee: 2030 })
    expect(data ?? [], 'le voisin lit les provisions du foyer d’à côté').toHaveLength(0)
  })

  it('un nom d’enveloppe se réutilise une fois archivée', async () => {
    const { data: e } = await admin().from('enveloppe').insert({
      household_id: moi.householdId, libelle: 'Vacances', plafond_cents: 10_000,
    }).select().single()
    await admin().from('enveloppe')
      .update({ archive_le: new Date().toISOString() }).eq('id', e!.id)
    const { error } = await admin().from('enveloppe').insert({
      household_id: moi.householdId, libelle: 'Vacances', plafond_cents: 20_000,
    })
    expect(error, 'une enveloppe archivée confisque son nom').toBeNull()
  })
})

describe('la clé se fige quand le mois est VÉCU, pas quand il est engendré', () => {
  it('un revenu saisi après coup rattrape un mois qui n’a rien coûté', async () => {
    /* Le piège qu'on supprime : quelqu'un arrive, on ouvre le budget avant
       qu'il ait saisi son revenu, `parts_du_foyer` partage à parts égales faute
       de mieux — et le mois restait à 50/50 pour toujours. Il aurait fallu se
       souvenir de saisir les revenus AVANT de regarder l'écran : une règle
       qu'on n'apprend qu'en la ratant. */
    const { data: u } = await admin().auth.admin.createUser({
      email: `sansrevenu-${Date.now()}@fumee.test`, password: 'x'.repeat(12),
      email_confirm: true,
    })
    const nouveau = u.user!.id
    await admin().from('user_profile').insert({
      id: nouveau, household_id: moi.householdId, display_name: 'Nouveau',
      entre_le: '2028-01-01',
    })

    const id = await poseCharge({ libelle: 'Avant revenu', cents: 10_000,
                                  periodicite: 'mensuel',
                                  participants: [moi.userId, nouveau] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2028-06-01' })

    const partsDe = async () => {
      const { data: d } = await admin().from('depense').select('id')
        .eq('charge_id', id).eq('mois', '2028-06-01').single()
      const { data: p } = await admin().from('depense_part')
        .select('user_profile_id, part_cents').eq('depense_id', d!.id)
      return Object.fromEntries(p!.map(x => [x.user_profile_id, x.part_cents]))
    }

    /* Sans son revenu, tout le monde pèse pareil — à un centime près : le
       reliquat de la division va au plus gros contributeur, et à poids égaux
       c'est l'identifiant qui départage. */
    const avant = await partsDe()
    expect(Math.abs(avant[nouveau] - 5_000),
      'le partage n’est pas à parts égales').toBeLessThanOrEqual(2)

    // Il saisit son revenu : le mois n'a encore rien coûté, il se recalcule.
    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: nouveau,
      net_mensuel_cents: 100_000, valid_from: '2028-01-01',
    })

    const apres = await partsDe()
    expect(apres[nouveau], 'le mois est resté figé à parts égales')
      .toBeLessThan(4_500)
    expect(Object.values(apres).reduce((s, n) => s + n, 0),
      'les parts ne recomposent plus le montant').toBe(10_000)

    await admin().from('revenu').delete().eq('user_profile_id', nouveau)
    await admin().from('user_profile').delete().eq('id', nouveau)
  })

  it('mais un mois DÉJÀ VÉCU ne bouge plus', async () => {
    const id = await poseCharge({ libelle: 'Déjà vécu', cents: 10_000,
                                  periodicite: 'mensuel',
                                  participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2028-07-01' })

    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2028-07-01').single()
    /* Ce qui clôt un mois n'est PAS `nature = 'connue'` — une charge fixe naît
       déjà connue, son montant ne fait aucun doute. C'est qu'on l'ait vécu :
       une ligne réglée. Quelqu'un a payé selon un partage qu'on ne peut plus
       lui changer. */
    await admin().from('depense')
      .update({ regle_le: '2028-07-15', paye_par: moi.userId }).eq('id', d!.id)

    const { data: avant } = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)

    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: elle,
      net_mensuel_cents: 900_000, valid_from: '2028-06-01',
    })

    const { data: apres } = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)
    expect(apres, 'un mois déjà vécu a été repartagé').toEqual(avant)

    await admin().from('revenu').delete()
      .eq('user_profile_id', elle).eq('valid_from', '2028-06-01')
  })
})

describe('ce qu’une revue globale a trouvé', () => {
  it('une charge commune accueille le membre qui arrive après', async () => {
    /* Le défaut sournois : une charge posée pendant qu'on est SEUL dans le
       foyer n'a qu'un participant, et rien ne gardait l'intention. Le second
       membre arrivait, le mois se refigeait… et ne changeait rien, puisque
       `charge_participant` ne contenait toujours qu'une personne. Il fallait
       rouvrir les quinze charges une à une. */
    const { data: c } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Commune d’avance',
      montant_cents: 10_000, periodicite: 'mensuel', debut: '2026-01-01',
      commun: true,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })

    const { data: u } = await admin().auth.admin.createUser({
      email: `arrive-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const arrivant = u.user!.id
    await admin().from('user_profile').insert({
      id: arrivant, household_id: moi.householdId, display_name: 'Arrivant',
    })

    const { data: qui } = await admin().from('charge_participant')
      .select('user_profile_id').eq('charge_id', c!.id)
    expect(qui!.map(x => x.user_profile_id),
      'le membre qui arrive n’entre pas dans les charges communes').toContain(arrivant)

    await admin().from('user_profile').delete().eq('id', arrivant)
  })

  it('une charge PERSO n’accueille personne', async () => {
    const { data: c } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Bien à moi',
      montant_cents: 58_000, periodicite: 'mensuel', debut: '2026-01-01',
      commun: false,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })

    const { data: u } = await admin().auth.admin.createUser({
      email: `intrus-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const autre = u.user!.id
    await admin().from('user_profile').insert({
      id: autre, household_id: moi.householdId, display_name: 'Autre',
    })

    const { data: qui } = await admin().from('charge_participant')
      .select('user_profile_id').eq('charge_id', c!.id)
    expect(qui!.map(x => x.user_profile_id),
      'un arrivant s’est invité dans une charge perso').not.toContain(autre)

    await admin().from('user_profile').delete().eq('id', autre)
  })

  it('un relevé ÉGAL à la provision clôt quand même le mois', async () => {
    /* 0060 devinait qu'un mois avait été vécu en comparant le montant au prévu.
       Confirmer une ligne au montant exactement prévu — le cas le plus
       fréquent — ne cochait rien : un changement de revenu repartageait alors
       une ligne déjà réglée. D60 défait dans un cas parfaitement atteignable. */
    const id = await poseCharge({ libelle: 'Égal au prévu', cents: 3_700,
                                  periodicite: 'mensuel',
                                  participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-05-01' })

    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-05-01').single()

    // On confirme le MÊME montant que celui prévu.
    const { error } = await moi.client.rpc('confirme_la_depense',
      { la_depense: d!.id, reel_cents: 3_700 })
    expect(error, `confirmation refusée : ${error?.message}`).toBeNull()

    const { data: apres } = await admin().from('depense')
      .select('confirme_le, nature').eq('id', d!.id).single()
    expect(apres!.confirme_le, 'la confirmation ne laisse aucune trace').not.toBeNull()

    const avant = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)

    // Un revenu qui change ne doit PLUS toucher à ce mois.
    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: elle,
      net_mensuel_cents: 800_000, valid_from: '2029-05-01',
    })

    const apresParts = await admin().from('depense_part')
      .select('user_profile_id, part_cents').eq('depense_id', d!.id)
    expect(apresParts.data, 'un mois confirmé a été repartagé').toEqual(avant.data)

    await admin().from('revenu').delete()
      .eq('user_profile_id', elle).eq('valid_from', '2029-05-01')
  })

  it('la confirmation ne laisse jamais une dépense sans part', async () => {
    const id = await poseCharge({ libelle: 'Sans trou', cents: 5_000,
                                  periodicite: 'mensuel', variable: true,
                                  participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-06-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-06-01').single()

    await moi.client.rpc('confirme_la_depense', { la_depense: d!.id, reel_cents: 7_350 })

    const { data: parts } = await admin().from('depense_part')
      .select('part_cents').eq('depense_id', d!.id)
    expect(parts ?? [], 'la dépense a perdu ses parts').not.toHaveLength(0)
    expect(parts!.reduce((s, p) => s + p.part_cents, 0),
      'les parts ne recomposent pas le réel').toBe(7_350)
  })
})

describe('l’arrivée du second membre, éprouvée', () => {
  it('ne rend PAS communes les charges perso d’un foyer solo', async () => {
    /* Le rétro-remplissage de 0061 disait « commune si plus d'un participant OU
       si le foyer ne compte qu'une personne ». Or le foyer solo est précisément
       le cas de départ : les charges perso — mensualité de prêt, forfait mobile
       — devenaient communes, et le second membre y serait entré. */
    const { data: perso } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Bien à moi seul',
      montant_cents: 58_000, periodicite: 'mensuel', debut: '2026-01-01',
      commun: false,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: perso!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    const { data: relu } = await admin().from('charge')
      .select('commun').eq('id', perso!.id).single()
    expect(relu!.commun, 'une charge perso a été rendue commune').toBe(false)
  })

  it('corriger sa date d’entrée la sort des mois qu’elle n’habitait pas', async () => {
    /* D71 promet que cette date « se confirme, elle ne se devine pas ». Elle se
       devinait — `entre_le` vaut le jour de l'inscription — et la corriger ne
       refigeait rien : il n'existait de trigger qu'à l'insertion. */
    const { data: u } = await admin().auth.admin.createUser({
      email: `tardive-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const tardive = u.user!.id
    // Elle s'inscrit « aujourd'hui » : elle entre donc dans le mois en cours.
    await admin().from('user_profile').insert({
      id: tardive, household_id: moi.householdId, display_name: 'Tardive',
      entre_le: '2027-07-01',
    })

    const id = await poseCharge({ libelle: 'Loyer de juillet', cents: 60_000,
                                  periodicite: 'mensuel',
                                  participants: [moi.userId, tardive] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-07-01' })

    const partsDe = async () => {
      const { data: d } = await admin().from('depense').select('id')
        .eq('charge_id', id).eq('mois', '2027-07-01').single()
      const { data: p } = await admin().from('depense_part')
        .select('user_profile_id, part_cents').eq('depense_id', d!.id)
      return Object.fromEntries(p!.map(x => [x.user_profile_id, x.part_cents]))
    }
    expect((await partsDe())[tardive], 'elle ne porte rien alors qu’elle est là')
      .toBeGreaterThan(0)

    // Elle corrige : elle n'emménage qu'en août.
    await admin().from('user_profile').update({ entre_le: '2027-08-01' }).eq('id', tardive)

    const apres = await partsDe()
    expect(apres[tardive], 'elle paie encore un mois qu’elle n’habitait pas').toBeUndefined()
    expect(apres[moi.userId], 'il ne porte pas tout seul ce mois-là').toBe(60_000)

    await admin().from('user_profile').delete().eq('id', tardive)
  })

  it('refuse de confirmer une dépense que personne ne doit', async () => {
    /* Le marqueur était posé quand même, et `refige_pour` refusait alors le mois
       entier pour toujours : une ligne que personne ne doit, gelée. */
    /* Une ligne `modele` fixe, sans la moindre part, posée par `admin()`. Une
       ligne `manuel` n'est de toute façon pas confirmable : le test passait à
       vide, refusé pour une autre raison que celle qu'il nomme. */
    const id = await poseCharge({ libelle: 'Sans personne', cents: 5_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    const { data: d, error: eLigne } = await admin().from('depense').insert({
      household_id: moi.householdId, charge_id: id, mois: '2027-09-01',
      libelle: 'Sans personne', montant_cents: 5_000, montant_prevu_cents: 5_000,
      source: 'modele', nature: 'connue', facon: 'fixe',
    }).select().single()
    expect(eLigne, `ligne refusée : ${eLigne?.message}`).toBeNull()

    const { error } = await moi.client.rpc('confirme_la_depense',
      { la_depense: d!.id, reel_cents: 4_000 })
    expect(error?.message, 'une dépense sans part a été confirmée')
      .toMatch(/partagée avec personne/)

    const { data: apres } = await admin().from('depense')
      .select('confirme_le').eq('id', d!.id).single()
    expect(apres!.confirme_le, 'le marqueur a été posé quand même').toBeNull()
  })

  it('refige_pour ne touche qu’aux lignes qu’elle saura repeupler', async () => {
    /* ⚠️ Ce test manquait, et son absence se voyait : ramener `refige_pour` à sa
       version d'avant — qui supprimait les parts de TOUTES les lignes engendrées
       mais n'en reposait que pour celles ayant encore une charge — laissait les
       quarante tests verts. Une dépense dénouée perdait ses parts à jamais. */
    const id = await poseCharge({ libelle: 'Bientôt dénouée', cents: 8_000,
                                  periodicite: 'mensuel', participants: [moi.userId] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-11-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2027-11-01').single()

    // On dénoue le lien, comme le fait une régularisation manuelle.
    await admin().from('depense').update({ charge_id: null }).eq('id', d!.id)

    // Puis un revenu change, ce qui déclenche le refige du mois.
    await admin().from('revenu').insert({
      household_id: moi.householdId, user_profile_id: moi.userId,
      net_mensuel_cents: 410_000, valid_from: '2027-11-01',
    })

    const { data: parts } = await admin().from('depense_part')
      .select('part_cents').eq('depense_id', d!.id)
    expect(parts ?? [], 'la dépense dénouée a perdu ses parts').not.toHaveLength(0)
    expect(parts!.reduce((s, p) => s + p.part_cents, 0),
      'ses parts ne recomposent plus le montant').toBe(8_000)

    await admin().from('revenu').delete()
      .eq('user_profile_id', moi.userId).eq('valid_from', '2027-11-01')
  })
})

describe('l’arrondi ne penche d’aucun côté', () => {
  it('le centime alterne au lieu de tomber toujours sur le même', async () => {
    /* Un audit a simulé douze mois avec les vrais revenus du foyer : le
       reliquat allait « au plus gros contributeur » à chaque ligne, donc
       104,52 centimes par an contre la même personne, sur 157 lignes, sans une
       seule exception. Aux plus forts restes, il va à celui dont la part exacte
       a la plus grande partie fractionnaire — et cela dépend du montant, donc
       change d'une ligne à l'autre. */
    const montants = [1_025, 999, 3_701, 15_999, 4_444, 7_777, 1_111, 6_665]
    const recu: Record<string, number> = { [moi.userId]: 0, [elle]: 0 }

    for (const [i, cents] of montants.entries()) {
      const id = await poseCharge({ libelle: `Arrondi ${i}`, cents,
                                    periodicite: 'mensuel',
                                    participants: [moi.userId, elle] })
      await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-04-01' })
      const { data: d } = await admin().from('depense').select('id, montant_cents')
        .eq('charge_id', id).eq('mois', '2027-04-01').single()
      const { data: parts } = await admin().from('depense_part')
        .select('user_profile_id, part_cents, part_bps').eq('depense_id', d!.id)

      // L'invariant d'abord : rien ne se perd ni ne se crée.
      expect(parts!.reduce((s, p) => s + p.part_cents, 0),
        `les parts de ${cents} ne recomposent pas le montant`).toBe(cents)

      /* Puis qui a reçu le centime. On le lit sur la ligne elle-même — sa part
         dépasse-t-elle sa base tronquée ? — plutôt que de recalculer la clé
         ici : refaire le calcul dans le test reviendrait à tester ma propre
         arithmétique contre elle-même. */
      for (const p of parts!) {
        const base = Math.floor(cents * p.part_bps / 10_000)
        if (p.part_cents > base) recu[p.user_profile_id]++
      }
    }

    /* Le point n'est pas que ce soit exactement moitié-moitié — la méthode est
       déterministe, pas aléatoire — mais que les DEUX en reçoivent. L'ancienne
       version donnait 0 à l'un et 8 à l'autre. */
    expect(recu[moi.userId], 'le centime ne tombe jamais sur lui').toBeGreaterThan(0)
    expect(recu[elle], 'le centime ne tombe jamais sur elle').toBeGreaterThan(0)
  })

  it('l’excédent ne déborde pas, et ne perd aucun centime', async () => {
    /* `sum(ecart * part_cents / …)` multipliait deux entiers : un loyer de
       1 250 € confirmé à 1 550 € dépassait la capacité d'un `integer` et tout
       l'écran du mois mourait. Le seuil était de 283 € d'écart. */
    const id = await poseCharge({ libelle: 'Gros loyer', cents: 125_000,
                                  periodicite: 'mensuel', variable: true,
                                  participants: [moi.userId, elle] })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-06-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2027-06-01').single()

    const { error } = await moi.client.rpc('confirme_la_depense',
      { la_depense: d!.id, reel_cents: 155_000 })
    expect(error, `confirmation refusée : ${error?.message}`).toBeNull()

    const { data: exc, error: eExc } = await moi.client.rpc('excedent_du_mois',
      { le_mois: '2027-06-01' })
    expect(eExc, `l’excédent déborde : ${eExc?.message}`).toBeNull()

    const somme = (exc ?? []).reduce(
      (s: number, l: { excedent_cents: number }) => s + Number(l.excedent_cents), 0)
    expect(somme, 'l’excédent ne recompose pas l’écart du foyer').toBe(125_000 - 155_000)
  })
})

describe('les quatre rouges de l’argent (0069)', () => {
  /* Aucun des quatre n'était retenu par un test : trois revues les ont trouvés
     à la main, et la suite restait verte en les remettant. */

  it('l’excédent ne favorise pas toujours le même identifiant', async () => {
    /* `excedent_du_mois` est la CINQUIÈME fonction à départager une égalité, et
       la seule que 0064 n'a jamais migrée : `order by … , uid` donnait le
       centime au plus petit uuid, 60 fois sur 60.

       ⚠️ SON PROPRE FOYER, sans un seul revenu. Deux versions de ce test ont
       passé en présence du défaut : dans le foyer partagé, les revenus changent
       d'un mois à l'autre, les parts avec, et il n'y a donc AUCUNE égalité à
       départager — le test mesurait la variation des parts, pas le tirage.
       Sans revenu, `parts_du_foyer` retombe sur moitié-moitié, et l'égalité est
       garantie tous les mois. */
    const seul = await makeActor('excedent')
    const autre = (await admin().auth.admin.createUser({
      email: `excedent-2-${Date.now()}@fumee.test`, password: 'x'.repeat(12),
      email_confirm: true,
    })).data.user!.id
    await admin().from('user_profile').insert({
      id: autre, household_id: seul.householdId, display_name: 'Autre',
    })

    const gagnants = new Set<string>()
    for (let n = 0; n < 12; n++) {
      const { data: c } = await admin().from('charge').insert({
        household_id: seul.householdId, libelle: `Égalité ${n}`,
        montant_cents: 9_999, periodicite: 'mensuel', debut: '2027-01-01',
      }).select().single()
      await admin().from('charge_participant').insert(
        [seul.userId, autre].map(u => ({
          charge_id: c!.id, user_profile_id: u, household_id: seul.householdId,
        })))

      const mois = `2027-${String(n + 1).padStart(2, '0')}-01`
      await seul.client.rpc('ouvre_le_mois', { le_mois: mois })
      const { data: d } = await admin().from('depense').select('id')
        .eq('charge_id', c!.id).eq('mois', mois).single()
      /* ⚠️ Le PRÉVU est impair et le RÉEL pair, pas l'inverse.
         `excedent_du_mois` lit les parts APRÈS confirmation : confirmer un
         montant impair les rend inégales (5000/4999), l'égalité est déjà
         tranchée en amont, et son propre départage n'est jamais sollicité —
         une version de ce test passait ainsi en présence du défaut. Un réel
         PAIR laisse 5000/5000, et l'écart d'un centime doit alors être
         attribué par elle. */
      await seul.client.rpc('confirme_la_depense', { la_depense: d!.id, reel_cents: 10_000 })

      const { data: parts } = await admin().from('depense_part')
        .select('part_cents').eq('depense_id', d!.id)
      expect(new Set((parts ?? []).map(p => p.part_cents)).size,
        'les parts ne sont pas égales : il n’y a rien à départager').toBe(1)

      const { data: ex } = await seul.client.rpc('excedent_du_mois', { le_mois: mois })
      const impair = (ex ?? []).filter(
        (l: { excedent_cents: number }) => Math.abs(Number(l.excedent_cents)) === 1)
      expect(impair, 'personne ne prend le centime').toHaveLength(1)
      gagnants.add(impair[0].user_profile_id)
    }
    expect(gagnants.size,
      'le centime va toujours au même : le départage ne varie pas').toBeGreaterThan(1)
  })

  it('une dépense confirmée ne se supprime pas à la main', async () => {
    /* 0065 a fermé `depense_part` ; la grande porte restait ouverte. Supprimer
       la DÉPENSE emporte ses parts en cascade, `ouvre_le_mois` la recrée, et
       le partage figé est réécrit. */
    const id = await poseCharge({
      libelle: 'Déjà payée', cents: 7_000, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-09-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2027-09-01').single()
    await moi.client.rpc('confirme_la_depense', { la_depense: d!.id, reel_cents: 7_500 })

    const { data: reste } = await moi.client.from('depense')
      .delete().eq('id', d!.id).select()
    expect(reste ?? [], 'une dépense confirmée a été supprimée').toHaveLength(0)

    const { data: parts } = await admin().from('depense_part')
      .select('part_cents').eq('depense_id', d!.id)
    expect(parts ?? [], 'les parts figées ont disparu').toHaveLength(2)
  })

  it('ni une dépense simplement RÉGLÉE', async () => {
    /* La policy porte sur DEUX colonnes, et un seul des deux cas était éprouvé.
       `useRegleLeMois` marque tout un mois d'un clic : supprimer une de ces
       lignes la ferait recréer par `ouvre_le_mois` avec un partage neuf — le
       scénario même que 0069 existe pour fermer. */
    const id = await poseCharge({
      libelle: 'Déjà virée', cents: 6_000, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-11-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2027-11-01').single()
    await moi.client.from('depense')
      .update({ regle_le: new Date().toISOString() }).eq('id', d!.id)

    const { data: reste } = await moi.client.from('depense')
      .delete().eq('id', d!.id).select()
    expect(reste ?? [], 'une dépense réglée a été supprimée').toHaveLength(0)
  })

  it('le client ne supprime plus aucune ligne, même ouverte et non confirmée', async () => {
    /* Avant 0101, une ligne ni confirmée ni réglée se supprimait : `corrige_la_charge`
       et le ménage ordinaire en avaient besoin. Ils passent désormais par des
       fonctions `security definer`, et le client n'a plus de policy de suppression :
       la ligne ouverte reste, comme les autres. Sans cela, un client supprimait
       la ligne d'un mois à volonté, et les parts avec. */
    const id = await poseCharge({
      libelle: 'Encore ouverte', cents: 4_000, periodicite: 'mensuel',
      participants: [moi.userId],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2027-10-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2027-10-01').single()
    const { data: parti } = await moi.client.from('depense')
      .delete().eq('id', d!.id).select()
    expect(parti ?? [], 'le client a supprimé une ligne de charge').toHaveLength(0)
    const { data: reste } = await admin().from('depense').select('id').eq('id', d!.id)
    expect(reste, 'la ligne a disparu malgré le refus').toHaveLength(1)
  })
})

describe('corriger une charge', () => {
  /* La faute de frappe du premier soir : 11 200 € au lieu de 1 120 €. Avant
     `corrige_la_charge`, elle était DÉFINITIVE — « Retirer » échoue sur la clé
     étrangère dès qu'un mois est ouvert, retombe sur l'archivage, la dépense
     fausse reste, et reposer la charge juste l'ajoute par-dessus. */
  async function montantDuMois(chargeId: string, mois: string) {
    const { data } = await admin().from('depense')
      .select('montant_cents, montant_prevu_cents')
      .eq('charge_id', chargeId).eq('mois', mois).maybeSingle()
    return data
  }

  it('refait le mois ouvert, prévision comprise', async () => {
    const id = await poseCharge({
      libelle: 'Loyer', cents: 1_120_000, periodicite: 'mensuel',
      participants: [moi.userId],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-02-01' })
    expect((await montantDuMois(id, '2026-02-01'))?.montant_cents).toBe(1_120_000)

    const { data: refaits, error } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Loyer', nouveau_montant: 112_000,
      nouvelle_periodicite: 'mensuel',
    })
    expect(error, `correction refusée : ${error?.message}`).toBeNull()
    /* ⚠️ TOUS les mois depuis le départ, pas seulement ceux qui avaient déjà
       une ligne. Corriger une charge ouvre désormais ce qu'elle couvre jusqu'à
       aujourd'hui, comme le fait déjà le fait de la POSER — sinon le passé
       dépend de ce qu'on a feuilleté, et le relevé annuel se calcule sur un
       trou. */
    expect(refaits, 'aucun mois refait').toBeGreaterThanOrEqual(1)

    const d = await montantDuMois(id, '2026-02-01')
    expect(d?.montant_cents, 'le mois garde le montant faux').toBe(112_000)
    /* `montant_prevu_cents` est gelé par `tg_prevu_gele` : s'il restait à
       1 120 000, `excedent_du_mois` annoncerait 10 080 € d'excédent fantôme.
       C'est pour lui que la ligne est supprimée puis refaite. */
    expect(d?.montant_prevu_cents, 'la prévision fausse a survécu').toBe(112_000)

    const { data: parts } = await admin().from('depense_part')
      .select('part_cents').eq('household_id', moi.householdId)
      .in('depense_id', [(await admin().from('depense').select('id')
        .eq('charge_id', id).eq('mois', '2026-02-01').single()).data!.id])
    expect((parts ?? []).reduce((s, p) => s + p.part_cents, 0),
      'les parts ne recomposent pas le nouveau montant').toBe(112_000)
  })

  it('ne réécrit pas un mois confirmé', async () => {
    const id = await poseCharge({
      libelle: 'Électricité', cents: 5_000, periodicite: 'mensuel',
      participants: [moi.userId],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-03-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2026-03-01').single()
    await moi.client.rpc('confirme_la_depense', {
      la_depense: d!.id, reel_cents: 5_500,
    })

    const { data: refaits } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Électricité', nouveau_montant: 9_000,
      nouvelle_periodicite: 'mensuel',
    })
    /* Le mois CONFIRMÉ n'est pas refait — c'est ce qui compte — mais les mois
       que la charge couvre et qui n'avaient pas de ligne s'ouvrent. */
    expect(refaits, 'rien n’a été ouvert').toBeGreaterThan(0)
    expect((await montantDuMois(id, '2026-03-01'))?.montant_cents,
      'ce qu’on a réellement payé a été réécrit').toBe(5_500)
  })

  it('refuse la charge d’un autre foyer, et les montants absurdes', async () => {
    const id = await poseCharge({
      libelle: 'Internet', cents: 3_700, periodicite: 'mensuel',
      participants: [moi.userId],
    })
    const { error: eVoisin } = await voisin.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Volé', nouveau_montant: 1,
      nouvelle_periodicite: 'mensuel',
    })
    expect(eVoisin, 'le voisin a réécrit notre charge').not.toBeNull()

    for (const [montant, periode] of [[0, 'mensuel'], [-1, 'mensuel'],
                                      [100_000_001, 'mensuel'], [1000, 'hebdo']] as const) {
      const { error } = await moi.client.rpc('corrige_la_charge', {
        la_charge: id, nouveau_libelle: 'Internet',
        nouveau_montant: montant, nouvelle_periodicite: periode,
      })
      expect(error, `${montant} / ${periode} est passé`).not.toBeNull()
    }
    const { error: eVide } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: '   ', nouveau_montant: 3_700,
      nouvelle_periodicite: 'mensuel',
    })
    expect(eVide, 'une charge sans nom est passée').not.toBeNull()
  })
})

describe('ranger un compte, une enveloppe, et corriger la date', () => {
  it('la date de départ se corrige, et les mois hors période s’en vont', async () => {
    /* C'était le seul champ que l'écran signale comme dangereux — « remonte la
       date, sinon le relevé annuel tombera d'un coup » — et le seul qu'on ne
       pouvait plus toucher : « Retirer » échoue sur la clé étrangère dès qu'un
       mois est ouvert et retombe sur l'archivage. */
    const { data: c } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Foncier décalé',
      montant_cents: 120_000, periodicite: 'annuel', debut: '2030-01-01',
      compte_id: compteCommun,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    for (const m of ['2030-01-01', '2030-02-01', '2030-03-01']) {
      await moi.client.rpc('ouvre_le_mois', { le_mois: m })
    }

    const { error } = await moi.client.rpc('corrige_la_charge', {
      la_charge: c!.id, nouveau_libelle: 'Foncier décalé',
      nouveau_montant: 120_000, nouvelle_periodicite: 'annuel',
      nouveau_debut: '2030-03-01',
    })
    expect(error, `correction refusée : ${error?.message}`).toBeNull()

    const { data: apres } = await admin().from('depense')
      .select('mois').eq('charge_id', c!.id).order('mois')
    expect((apres ?? []).map(d => d.mois),
      'les mois d’avant la nouvelle date facturent encore').toEqual(['2030-03-01'])

    const { data: ch } = await admin().from('charge')
      .select('debut, modifie_par').eq('id', c!.id).single()
    expect(ch!.debut, 'la date n’a pas bougé').toBe('2030-03-01')
    expect(ch!.modifie_par, 'on ne sait pas qui a touché la ligne').toBe(moi.userId)
  })

  it('un compte qui porte encore des charges ne se range pas', async () => {
    const { data: cpt } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'À ranger', genre: 'commun',
    }).select().single()
    const { data: ch } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Sur ce compte', montant_cents: 1_000,
      periodicite: 'mensuel', debut: '2031-01-01', compte_id: cpt!.id,
    }).select().single()

    const { error: eOccupe } = await moi.client.rpc('range_le_compte',
      { le_compte: cpt!.id, ranger: true })
    expect(eOccupe, 'un compte encore utilisé a été rangé').not.toBeNull()
    expect(eOccupe!.message).toMatch(/charge/i)

    /* Détaché, il se range — et il disparaît des comptes proposés. */
    await admin().from('charge').update({ compte_id: null }).eq('id', ch!.id)
    const { error } = await moi.client.rpc('range_le_compte',
      { le_compte: cpt!.id, ranger: true })
    expect(error, `rangement refusé : ${error?.message}`).toBeNull()

    const { data: vivants } = await moi.client.from('compte')
      .select('id').is('archive_le', null)
    expect((vivants ?? []).map(x => x.id),
      'un compte rangé se propose encore').not.toContain(cpt!.id)
  })

  it('un compte qui porte une poche d’épargne ne se range pas', async () => {
    /* La garde ne regardait que `charge.compte_id` — exactement contre son
       propre argument. Mesuré : elle archivait un Livret A portant 2 500 € de
       versements, et la poche continuait de pointer vers un compte filtré hors
       de tous les écrans. */
    const { data: cpt } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Livret à ranger', genre: 'epargne',
    }).select().single()
    const { data: poche } = await admin().from('poche_epargne').insert({
      household_id: moi.householdId, libelle: 'Urgence rangée', genre: 'urgence',
      compte_id: cpt!.id,
    }).select().single()

    const { error } = await moi.client.rpc('range_le_compte',
      { le_compte: cpt!.id, ranger: true })
    expect(error, 'un compte portant une poche a été rangé').not.toBeNull()
    expect(error!.message).toMatch(/épargne/i)

    await admin().from('poche_epargne').delete().eq('id', poche!.id)
    const { error: apres } = await moi.client.rpc('range_le_compte',
      { le_compte: cpt!.id, ranger: true })
    expect(apres, `rangement refusé : ${apres?.message}`).toBeNull()
  })

  it('une enveloppe qui porte les dépenses du mois ne se range pas', async () => {
    /* Rangée au milieu du mois, elle emportait sa jauge alors que les dépenses
       continuaient d'y tomber. Et elle n'avait aucun test, nulle part. */
    const { data: env } = await admin().from('enveloppe').insert({
      household_id: moi.householdId, libelle: 'Courses à ranger', plafond_cents: 50_000,
    }).select().single()
    /* ⚠️ L'enveloppe est attachée AVANT d'ouvrir le mois. `ouvre_le_mois` pose
       l'enveloppe à la création de la dépense et ne repasse pas dessus
       (`on conflict do nothing`) : l'attacher après laissait la dépense sans
       enveloppe, et la garde n'avait rien à voir. */
    const { data: ch } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Dans l’enveloppe',
      montant_cents: 4_000, periodicite: 'mensuel', debut: moisCourant(),
      compte_id: compteCommun, enveloppe_id: env!.id,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: ch!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: moisCourant() })

    const { data: dans } = await admin().from('depense').select('id')
      .eq('enveloppe_id', env!.id).eq('mois', moisCourant())
    expect(dans ?? [], 'aucune dépense dans l’enveloppe : la garde ne verra rien')
      .toHaveLength(1)

    /* ⚠️ On ARCHIVE la charge d'abord. Sinon c'est la garde des charges qui
       lève, et celle des dépenses du mois n'est jamais atteinte — la retirer
       ne changeait rien au test. */
    await admin().from('charge')
      .update({ archive_le: new Date().toISOString() }).eq('id', ch!.id)

    const { error } = await moi.client.rpc('range_l_enveloppe',
      { l_enveloppe: env!.id, ranger: true })
    expect(error, 'une enveloppe portant les dépenses du mois a été rangée')
      .not.toBeNull()
    expect(error!.message).toMatch(/dépense/i)
  })

  it('corriger une charge n’ouvre PAS les mois des autres charges', async () => {
    /*
     * 0078 faisait ouvrir à `corrige_la_charge` tous les mois de `debut` à
     * aujourd'hui — avec `ouvre_le_mois`, qui les ouvre pour TOUTES les charges
     * du foyer. Mesuré : on saisit le relevé de la taxe foncière, puis on
     * corrige le LOYER, une charge sans aucun rapport. Neuf mois de taxe
     * naissent, le provisionné bouge, l'écart posé ne bouge pas, et la garde
     * interdit de ressaisir : 2 416,64 € portés pour une facture de 1 450 €.
     */
    const taxe = await poseCharge({ libelle: 'Taxe intouchable', cents: 145_000,
                                    periodicite: 'annuel', participants: [moi.userId] })
    const loyer = await poseCharge({ libelle: 'Loyer à corriger', cents: 58_000,
                                     periodicite: 'mensuel', participants: [moi.userId] })
    /* ⚠️ Un mois de l'ANNÉE EN COURS, et un seul, ouvert pour les deux.
       `poseCharge` fait courir les charges depuis janvier ; corriger le loyer
       doit donc ouvrir janvier→aujourd'hui pour LUI, et rien pour la taxe. Une
       première version déplaçait la date vers 2031 : `generate_series` partait
       du futur vers le passé et n'ouvrait rien du tout. */
    const moisCi = moisCourant()
    await moi.client.rpc('ouvre_le_mois', { le_mois: moisCi })
    const combien = async (c: string) => {
      const { data } = await admin().from('depense').select('id')
        .eq('charge_id', c).eq('source', 'modele')
      return (data ?? []).length
    }
    const avant = await combien(taxe)

    /* On corrige le LOYER, en reculant sa date : ses mois à lui s'ouvrent. */
    await moi.client.rpc('corrige_la_charge', {
      la_charge: loyer, nouveau_libelle: 'Loyer à corriger',
      nouveau_montant: 58_000, nouvelle_periodicite: 'mensuel',
    })

    expect(await combien(taxe),
      'corriger une charge a fait naître les mois d’une autre').toBe(avant)
    expect(await combien(loyer),
      'corriger une charge n’a pas ouvert ses propres mois').toBeGreaterThan(1)
  })

  it('une année dont le relevé est saisi ne gagne plus de mois', async () => {
    /*
     * LA garde, et elle manquait depuis quatre tours. À chaque tour on
     * déplaçait l'appelant — `corrige_la_charge`, puis les triggers d'arrivée —
     * et le suivant rouvrait la porte. Faire naître un mois dans une année
     * déjà régularisée ajoute sa provision par-dessus un écart qui ne bouge
     * plus, et la garde « une seule fois » interdit de ressaisir.
     *
     * Le geste est celui que le code PRÉVOIT : `accept-invite` pose la date
     * d'arrivée au 1er du mois prochain exprès, et renvoie la personne vers son
     * profil « qui lui demande la vraie date ». Reculer cette date est normal.
     */
    const seul = await makeActor('garde-releve')
    const juin = `${new Date().getFullYear()}-06-01`
    const janvier = `${new Date().getFullYear()}-01-01`
    await admin().from('user_profile').update({ entre_le: juin }).eq('id', seul.userId)

    const { data: c } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Taxe verrouillée',
      montant_cents: 145_000, periodicite: 'annuel', debut: janvier,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
    })
    /* Les mois d'abord : une fois l'année soldée, plus aucun n'y naît. Depuis
       sa date d'arrivée, juin : ceux d'avant n'ont personne pour les porter. */
    await ouvreLAnnee(c!.id, new Date().getFullYear(), seul)

    /* ⚠️ L'ARGENT RÉELLEMENT POSÉ, sans y ajouter `provisions_a_venir`.
       La première version de ce test additionnait la promesse à la somme : il
       mesurait donc une intention, pas de l'argent, et restait vert sur un
       scénario qui en perdait 362,49 € — puisque la garde venait justement de
       rendre cette promesse intenable. */
    const pose = async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', c!.id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    }

    const avantReleve = await pose()
    expect(avantReleve, 'la préparation n’a ouvert aucun mois').toBeGreaterThan(0)
    await soldeAdmin(c!.id, new Date().getFullYear(), 145_000, seul)
    const apresReleve = await pose()
    expect(apresReleve, 'le relevé a posé une ligne : le solde ne vit plus ici')
      .toBe(avantReleve)

    /* Le geste qui rouvrait la porte : « en fait, je suis là depuis janvier ».
       Il ne doit RIEN ajouter : les mois révolus de l'année sont clos. */
    await seul.client.from('user_profile')
      .update({ entre_le: janvier }).eq('id', seul.userId)
    expect(await pose(),
      'une année dont le relevé est saisi a gagné des mois révolus')
      .toBe(apresReleve)

    /* ⚠️ LA GARDE TOTALE, éprouvée par le seul geste qui la sollicite.
       La version d'avant se contentait de rouvrir un mois à venir déjà
       présent : `on conflict do nothing` rendait l'appel inopérant avec ou
       sans la garde, donc elle ne mesurait RIEN — c'est le titre même de cette
       migration qui n'était couvert par aucun test. Il faut creuser un trou
       dans l'avenir, puis tenter de le combler. */
    const an = new Date().getFullYear()
    const prochain = new Date().getMonth() + 2
    if (prochain <= 12) {
      const futur = `${an}-${String(prochain).padStart(2, '0')}-01`
      const { data: efface } = await admin().from('depense')
        .delete().eq('charge_id', c!.id).eq('mois', futur).select()
      expect(efface ?? [], 'le relevé n’a pas matérialisé le mois à venir')
        .toHaveLength(1)
      const creuse = await pose()
      expect(creuse, 'le trou n’a pas été creusé').toBeLessThan(apresReleve)

      for (const rouvre of [
        () => seul.client.rpc('ouvre_le_mois', { le_mois: futur }),
        () => seul.client.rpc('ouvre_la_charge',
          { la_charge: c!.id, foyer: seul.householdId, le_mois: futur }),
        () => seul.client.rpc('rattrape_les_mois'),
      ]) {
        await rouvre()
        expect(await pose(),
          'un mois À VENIR est né dans une année dont le relevé est saisi')
          .toBe(creuse)
      }
    }
  })

  it('reculer sa date d’entrée FAIT NAÎTRE les mois, sans feuilleter', async () => {
    /*
     * `tg_entre_le_refige` et `tg_membre_rejoint_les_communes` ne faisaient que
     * REFIGER : ils bouclaient sur les mois qui avaient déjà une dépense, et
     * `refige_pour` n'en crée jamais. Reculer sa date d'entrée rendait donc
     * éligibles des mois sans ligne, qui ne naissaient qu'à la première visite
     * du budget. Le même geste donnait 604,19 € ou 0,04 € d'écart selon qu'on
     * avait feuilleté entre-temps.
     *
     * C'est le geste que le code PRÉVOIT : `accept-invite` pose la date au 1er
     * du mois prochain, et renvoie la personne vers son profil pour la vraie.
     */
    const seul = await makeActor('naissance')
    const an = new Date().getFullYear()
    await admin().from('user_profile')
      .update({ entre_le: `${an}-08-01` }).eq('id', seul.userId)

    const { data: c } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Depuis janvier',
      montant_cents: 12_000, periodicite: 'mensuel', debut: `${an}-01-01`,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
    })
    await seul.client.rpc('ouvre_le_mois', { le_mois: `${an}-08-01` })

    const combien = async () => {
      const { data } = await admin().from('depense').select('id').eq('charge_id', c!.id)
      return (data ?? []).length
    }
    const avant = await combien()

    /* Le geste, et RIEN d'autre : on ne feuillette aucun mois. */
    await seul.client.from('user_profile')
      .update({ entre_le: `${an}-01-01` }).eq('id', seul.userId)

    expect(await combien(),
      'reculer sa date d’entrée n’a fait naître aucun mois').toBeGreaterThan(avant)
  })

  it('`ouvre_la_charge` pose la même chose qu’`ouvre_le_mois`', async () => {
    /*
     * Les deux doivent être indiscernables : même prédicat de participant,
     * même nature. Trois clauses d'`ouvre_la_charge` survivaient à leur
     * suppression sans qu'un test ne bronche — dont celle du participant, qui
     * avait coûté 724,98 € quand elle manquait ailleurs.
     */
    const seul = await makeActor('jumelles')
    const janvier = `${new Date().getFullYear()}-01-01`
    await admin().from('user_profile').update({ entre_le: janvier }).eq('id', seul.userId)

    /* Un membre qui n'arrive que PLUS TARD : aucun mois ne doit naître pour sa
       charge à lui, ni par un chemin ni par l'autre. */
    const tard = (await admin().auth.admin.createUser({
      email: `jum-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })).data.user!.id
    await admin().from('user_profile').insert({
      id: tard, household_id: seul.householdId, display_name: 'Plus tard',
      entre_le: `${new Date().getFullYear() + 1}-01-01`,
    })
    const { data: sienne } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Pour lui seul',
      montant_cents: 3_000, periodicite: 'mensuel', debut: janvier,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: sienne!.id, user_profile_id: tard, household_id: seul.householdId,
    })

    await seul.client.rpc('corrige_la_charge', {
      la_charge: sienne!.id, nouveau_libelle: 'Pour lui seul',
      nouveau_montant: 3_000, nouvelle_periodicite: 'mensuel',
    })
    const { data: rien } = await admin().from('depense').select('id')
      .eq('charge_id', sienne!.id)
    expect(rien ?? [],
      'un mois est né pour quelqu’un qui n’est pas encore arrivé').toHaveLength(0)

    /* Et la NATURE : une charge mensuelle simple est « connue », une variable
       est « estimee ». C'est elle qui décide de ce qu'on fait confirmer. */
    const { data: fixe } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Fixe', montant_cents: 4_000,
      periodicite: 'mensuel', debut: janvier,
    }).select().single()
    const { data: molle } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Molle', montant_cents: 4_000,
      periodicite: 'mensuel', debut: janvier, variable: true,
    }).select().single()
    for (const c of [fixe, molle]) {
      await admin().from('charge_participant').insert({
        charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
      })
      await seul.client.rpc('corrige_la_charge', {
        la_charge: c!.id, nouveau_libelle: c!.libelle, nouveau_montant: 4_000,
        nouvelle_periodicite: 'mensuel',
      })
    }
    const nature = async (c: string) => {
      const { data } = await admin().from('depense').select('nature')
        .eq('charge_id', c).limit(1).maybeSingle()
      return data?.nature
    }
    expect(await nature(fixe!.id), 'une charge fixe est rendue estimée').toBe('connue')
    expect(await nature(molle!.id), 'une charge variable est rendue connue').toBe('estimee')

    await admin().from('user_profile').delete().eq('id', tard)
  })

  it('corriger une charge n’efface pas les mois d’une année close', async () => {
    /*
     * Le pire des défauts de la boucle, et il est né de sa correction :
     * `corrige_la_charge` effaçait les mois sans regarder si la TRACE de
     * l'année survivait. Or la trace ne part que si aucune régularisation de
     * l'année n'est réglée ni confirmée. Quand elle reste, la garde est armée
     * et les mois effacés ne peuvent PLUS renaître.
     *
     * Le geste est entièrement dans l'app : on saisit le relevé, on marque le
     * mois réglé — `useRegleLeMois` pose `regle_le` sur TOUTES les lignes du
     * mois, régularisation comprise — puis on corrige une faute de frappe.
     * Mesuré : 960 € évaporés, année verrouillée à 18 000 centimes pour
     * toujours.
     */
    const an = new Date().getFullYear()
    const id = await poseCharge({ libelle: 'Année close', cents: 144_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    /* Les douze mois, puis l'année soldée : une fois soldée, plus aucun n'y naît. */
    await ouvreLAnnee(id, an)
    await soldeAdmin(id, an, 150_000)

    const pose = async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    }
    const avant = await pose()

    await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Année close, renommée',
      nouveau_montant: 144_000, nouvelle_periodicite: 'annuel',
    })

    expect(await pose(),
      'corriger a effacé les mois d’une année que la garde empêche de renaître')
      .toBe(avant)
  })

  it('changer la DATE d’une charge n’efface pas une année close', async () => {
    /* La garde n'avait été posée que sur UNE des deux suppressions. Celle-ci —
       « la charge ne court plus sur ces mois-là » — est déclenchée par le champ
       « elle court depuis », affiché pour toute charge non mensuelle, donc pour
       toute taxe foncière. Mesuré : 720 € perdus et l'année figée. */
    const an = new Date().getFullYear()
    const id = await poseCharge({ libelle: 'Date et année close', cents: 144_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    /* Les douze mois, puis l'année soldée : une fois soldée, plus aucun n'y naît. */
    await ouvreLAnnee(id, an)
    await soldeAdmin(id, an, 150_000)

    const pose = async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    }
    const avant = await pose()

    /* ⚠️ Le geste est désormais PERMIS, et c'est la garde qui protège l'année.
       Le refus qui vivait ici était un cul-de-sac permanent — une charge dont
       une année ancienne était réglée n'acceptait plus aucune correction, même
       pour les années suivantes — et il n'a plus lieu d'être : une année saisie
       est complète et figée, donc changer la date ne peut plus lui retirer ses
       mois. */
    const { error } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Date et année close',
      nouveau_montant: 144_000, nouvelle_periodicite: 'annuel',
      nouveau_debut: `${an}-07-01`,
    })
    expect(error, `correction refusée : ${error?.message}`).toBeNull()
    expect(await pose(),
      'changer la date a effacé les mois d’une année close').toBe(avant)
  })

  it('changer le MONTANT d’une année close est permis, et ne touche pas l’année close', async () => {
    /* Les mois passés garderaient l'ancien douzième, ceux à venir naîtraient
       au nouveau — 1 590 € pour une facture de 1 500 € —, mais une année
       soldée a ses douze mois, et la garde les fige : la correction passe sans
       rien lui prendre. Avant 0113, le refus d'alors rendait la charge
       incorrigible ; il n'a plus lieu d'être. */
    const an = new Date().getFullYear()
    const id = await poseCharge({ libelle: 'Montant verrouillé', cents: 144_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    /* Les douze mois, puis l'année soldée : une fois soldée, plus aucun n'y naît. */
    await ouvreLAnnee(id, an)
    await soldeAdmin(id, an, 150_000)

    const avantM = await (async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    })()

    /* Permis, et sans effet sur l'année close : ses douze mois existent et la
       garde les fige. C'est ça qui rend le refus inutile. */
    const { error } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Montant verrouillé',
      nouveau_montant: 180_000, nouvelle_periodicite: 'annuel',
    })
    expect(error, `correction refusée : ${error?.message}`).toBeNull()

    const { data: apresM } = await admin().from('depense').select('montant_cents')
      .eq('charge_id', id)
    expect((apresM ?? []).reduce((s, d) => s + d.montant_cents, 0),
      'changer le montant a bougé une année close').toBe(avantM)

    /* Mais RENOMMER reste permis : le nom ne change aucun chiffre. */
    const { error: eNom } = await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Renommée quand même',
      nouveau_montant: 144_000, nouvelle_periodicite: 'annuel',
    })
    expect(eNom, `renommer a été refusé : ${eNom?.message}`).toBeNull()
  })

  it('avancer sa date d’entrée ne vide pas une année close', async () => {
    /* La troisième porte : `refige_pour` supprime les mois sans participant
       arrivé, et la garde des ouvreurs les empêche ensuite de renaître.
       Mesuré : 1 140 € tombaient à 420 €, et reculer la date ne restaurait
       rien. */
    /* ⚠️ TROIS membres. Une première version n'en avait qu'UN : le partage
       était alors de 100 % quoi qu'il arrive, donc aucun déplacement de
       porteur n'était observable, et la garde des parts n'était mesurée par
       rien. C'est la somme qui reste juste pendant que les porteurs changent. */
    const seul = await makeActor('entree-close')
    const an = new Date().getFullYear()
    await admin().from('user_profile')
      .update({ entre_le: `${an}-01-01` }).eq('id', seul.userId)

    const autres: string[] = []
    for (const n of [1, 2]) {
      const u = (await admin().auth.admin.createUser({
        email: `ec-${n}-${Date.now()}@fumee.test`, password: 'x'.repeat(12),
        email_confirm: true,
      })).data.user!.id
      await admin().from('user_profile').insert({
        id: u, household_id: seul.householdId, display_name: `Autre ${n}`,
        entre_le: `${an}-01-01`,
      })
      autres.push(u)
    }

    const { data: c } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Close et vidée',
      montant_cents: 144_000, periodicite: 'annuel', debut: `${an}-01-01`,
    }).select().single()
    await admin().from('charge_participant').insert(
      [seul.userId, ...autres].map(u => ({
        charge_id: c!.id, user_profile_id: u, household_id: seul.householdId,
      })))
    await ouvreLAnnee(c!.id, an, seul)
    await soldeAdmin(c!.id, an, 150_000, seul)

    const pose = async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', c!.id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    }
    const avant = await pose()
    const porteursAvant = await (async () => {
      const { data } = await admin().from('depense_part')
        .select('user_profile_id, part_cents')
        .in('depense_id', ((await admin().from('depense').select('id')
          .eq('charge_id', c!.id)).data ?? []).map(d => d.id))
      const m = new Map<string, number>()
      for (const p of data ?? []) {
        m.set(p.user_profile_id, (m.get(p.user_profile_id) ?? 0) + p.part_cents)
      }
      return [...m.entries()].sort().map(([, v]) => v)
    })()

    /* « En fait je suis arrivé en juillet », dit l'un des deux autres.
       ⚠️ Par `admin()` : la RLS n'autorise chacun qu'à écrire SON profil, et
       une mise à jour refusée en silence rendait ce test vert dans les deux
       sens — il ne déclenchait même pas le trigger qu'il prétend éprouver. */
    const { data: bouge } = await admin().from('user_profile')
      .update({ entre_le: `${an}-07-01` }).eq('id', autres[1]).select()
    expect(bouge ?? [], 'la date d’entrée n’a pas bougé').toHaveLength(1)

    expect(await pose(),
      'avancer sa date d’entrée a vidé une année close').toBe(avant)

    /* ⚠️ Et QUI porte quoi, pas seulement combien.
       La garde n'était posée que sur la suppression des dépenses ; celle des
       PARTS ne l'avait pas. L'année gardait ses mois et changeait de porteur —
       242,72 € déplacés d'un membre à l'autre pendant que la somme, seule
       chose que ce test regardait, restait identique. */
    const parPersonne = async () => {
      const { data } = await admin().from('depense_part')
        .select('user_profile_id, part_cents')
        .in('depense_id', ((await admin().from('depense').select('id')
          .eq('charge_id', c!.id)).data ?? []).map(d => d.id))
      const m = new Map<string, number>()
      for (const p of data ?? []) {
        m.set(p.user_profile_id, (m.get(p.user_profile_id) ?? 0) + p.part_cents)
      }
      return [...m.entries()].sort().map(([, v]) => v)
    }
    expect(await parPersonne(),
      'une année close a changé de porteur').toEqual(porteursAvant)
  })

  it('et `ouvre_la_charge` respecte la garde, elle aussi', async () => {
    /* La garde vit dans les DEUX ouvreurs. Celle d'`ouvre_la_charge` n'est
       atteinte que si un mois d'une année close a disparu autrement — par
       `refige_pour`, qui efface les orphelines — et qu'on tente de le
       recréer. Rare, mais la fonction est accordée à `authenticated` : sa
       garde doit tenir seule. */
    const an = new Date().getFullYear()
    const id = await poseCharge({ libelle: 'Close et trouée', cents: 120_000,
                                  periodicite: 'annuel', participants: [moi.userId] })
    await ouvreLAnnee(id, an)
    await soldeAdmin(id, an, 130_000)

    /* On creuse un trou dans l'année close. */
    await admin().from('depense').delete()
      .eq('charge_id', id).eq('mois', `${an}-01-01`)
    const combien = async () => {
      const { data } = await admin().from('depense').select('id')
        .eq('charge_id', id).eq('mois', `${an}-01-01`)
      return (data ?? []).length
    }
    expect(await combien(), 'le trou n’a pas été creusé').toBe(0)

    await moi.client.rpc('ouvre_la_charge',
      { la_charge: id, foyer: moi.householdId, le_mois: `${an}-01-01` })
    expect(await combien(),
      'un mois est né dans une année dont le relevé est saisi').toBe(0)
  })

  it('et `ouvre_la_charge` n’écrit pas chez le voisin', async () => {
    /* Elle est accordée à `authenticated` et faisait CONFIANCE à son argument
       de foyer : mesuré, on créait une dépense de 999 € chez le voisin, avec
       zéro part — l'invariant de somme cassé dans un foyer auquel l'appelant
       n'a aucun accès. */
    const { data: sienne } = await admin().from('charge').insert({
      household_id: voisin.householdId, libelle: 'Chez eux', montant_cents: 99_900,
      periodicite: 'mensuel', debut: moisCourant(),
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: sienne!.id, user_profile_id: voisin.userId,
      household_id: voisin.householdId,
    })

    await moi.client.rpc('ouvre_la_charge', {
      la_charge: sienne!.id, foyer: voisin.householdId, le_mois: moisCourant(),
    })

    const { data: chez_eux } = await admin().from('depense').select('id')
      .eq('charge_id', sienne!.id)
    expect(chez_eux ?? [], 'on a écrit une dépense chez le voisin').toHaveLength(0)
  })

  it('le voisin ne range pas nos comptes', async () => {
    const { data: cpt } = await admin().from('compte').insert({
      household_id: moi.householdId, nom: 'Le nôtre', genre: 'commun',
    }).select().single()
    const { error } = await voisin.client.rpc('range_le_compte',
      { le_compte: cpt!.id, ranger: true })
    expect(error, 'le voisin a rangé notre compte').not.toBeNull()
  })
})

describe('ce que 0072 corrigeait, et que rien ne retenait', () => {
  /* Une contre-revue a montré que les TROIS corrections annoncées par 0072
     survivaient à la suite entière : on pouvait remettre chaque défaut sans
     qu'un seul test ne rougisse. */

  it('corriger une charge ÉPARGNE les mois déjà réglés hors période', async () => {
    /* 0074 l'énonce en toutes lettres — « un mois réglé ou confirmé garde la
       sienne » — et rien ne le mesurait. */
    const id = await poseCharge({
      libelle: 'Décalée réglée', cents: 6_000, periodicite: 'mensuel',
      participants: [moi.userId],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2031-01-01' })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2031-02-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2031-01-01').single()
    await moi.client.from('depense')
      .update({ regle_le: new Date().toISOString() }).eq('id', d!.id)

    await moi.client.rpc('corrige_la_charge', {
      la_charge: id, nouveau_libelle: 'Décalée réglée', nouveau_montant: 6_000,
      nouvelle_periodicite: 'mensuel', nouveau_debut: '2031-02-01',
    })

    const { data: restants } = await admin().from('depense')
      .select('mois').eq('charge_id', id).order('mois')
    expect((restants ?? []).map(x => x.mois),
      'un mois déjà réglé a été effacé par la correction')
      .toContain('2031-01-01')
  })
})

describe('rattraper les mois manquants', () => {
  /* La fonction la plus risquée du lot — appelée à chaque lecture du budget —
     et elle n'était éprouvée nulle part. */

  it('rattrape PAR CHARGE, pas par foyer', async () => {
    /* Son critère était « aucune dépense du foyer ce mois-là », donc un mois où
       une charge sur quinze avait une ligne était déclaré fait. Et le fabricant
       de ces mois partiels, c'est `corrige_la_charge`, qui n'ouvre que SA
       charge : les deux moitiés se contredisaient. Mesuré : 845,81 € jamais
       provisionnés selon l'ORDRE des gestes. */
    const seul = await makeActor('rattrape')
    const an = new Date().getFullYear()
    await admin().from('user_profile')
      .update({ entre_le: `${an}-01-01` }).eq('id', seul.userId)

    const ids: string[] = []
    for (const nom of ['Loyer', 'Internet']) {
      const { data: c } = await admin().from('charge').insert({
        household_id: seul.householdId, libelle: nom, montant_cents: 6_000,
        periodicite: 'mensuel', debut: `${an}-01-01`,
      }).select().single()
      await admin().from('charge_participant').insert({
        charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
      })
      ids.push(c!.id)
    }

    /* On ouvre les mois pour UNE seule charge — ce que fait `corrige_la_charge`. */
    for (let m = 1; m <= new Date().getMonth() + 1; m++) {
      await seul.client.rpc('ouvre_la_charge', {
        la_charge: ids[0], foyer: seul.householdId,
        le_mois: `${an}-${String(m).padStart(2, '0')}-01`,
      })
    }
    const combien = async (id: string) => {
      const { data } = await admin().from('depense').select('id').eq('charge_id', id)
      return (data ?? []).length
    }
    expect(await combien(ids[1]), 'la seconde charge a des mois avant rattrapage').toBe(0)

    await seul.client.rpc('rattrape_les_mois')

    expect(await combien(ids[1]),
      'le rattrapage a déclaré faits des mois où une seule charge avait une ligne')
      .toBe(await combien(ids[0]))
  })

  it('ne rouvre pas une année dont le relevé est saisi', async () => {
    const seul = await makeActor('rattrape-close')
    const an = new Date().getFullYear()
    await admin().from('user_profile')
      .update({ entre_le: `${an}-01-01` }).eq('id', seul.userId)
    const { data: c } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Close au rattrapage',
      montant_cents: 120_000, periodicite: 'annuel', debut: `${an}-01-01`,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
    })
    await ouvreLAnnee(c!.id, an, seul)
    await soldeAdmin(c!.id, an, 130_000, seul)

    const pose = async () => {
      const { data } = await admin().from('depense').select('montant_cents')
        .eq('charge_id', c!.id)
      return (data ?? []).reduce((s, d) => s + d.montant_cents, 0)
    }
    const avant = await pose()
    /* On creuse un trou, puis on rattrape : rien ne doit renaître. */
    await admin().from('depense').delete()
      .eq('charge_id', c!.id).eq('mois', `${an}-03-01`)
    await seul.client.rpc('rattrape_les_mois')

    /* ⚠️ Une ÉGALITÉ. `toBeLessThan` était vert pour n'importe quelle valeur
       inférieure, y compris un mois reconstruit au mauvais montant. */
    expect(await pose(), 'le rattrapage a rouvert une année close')
      .toBe(avant - 10_000)
  })
})

describe('le prédicat de participant, le même partout', () => {
  it('saisir son revenu n’efface pas le mois qu’on vient d’ouvrir', async () => {
    /*
     * `ouvre_le_mois`, `provisions_a_venir` et `parts_du_foyer` écrivent tous
     * `entre_le <= fin_mois`. `refige_pour` écrivait `<= debut_mois` — le
     * PREMIER du mois — et supprimait donc comme orphelines les lignes que les
     * trois autres comptent.
     *
     * Le cas le plus ordinaire : quelqu'un dont la date d'entrée vaut
     * aujourd'hui — le défaut de la colonne, et ce que l'écran de profil
     * propose — pose une charge, puis saisit son revenu. Le trigger du revenu
     * appelle `refige_pour`, qui ne le voit pas encore arrivé au 1er du mois,
     * et EFFACE la dépense. Le membre invité était protégé, le fondateur non.
     */
    const seul = await makeActor('predicat-milieu')
    const aujourdhui = new Date().toISOString().slice(0, 10)
    await admin().from('user_profile')
      .update({ entre_le: aujourdhui }).eq('id', seul.userId)

    const { data: c } = await admin().from('charge').insert({
      household_id: seul.householdId, libelle: 'Milieu de mois',
      montant_cents: 12_000, periodicite: 'mensuel', debut: aujourdhui.slice(0, 8) + '01',
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: c!.id, user_profile_id: seul.userId, household_id: seul.householdId,
    })

    const mois = aujourdhui.slice(0, 8) + '01'
    await seul.client.rpc('ouvre_le_mois', { le_mois: mois })
    const { data: avant } = await admin().from('depense').select('id')
      .eq('charge_id', c!.id).eq('mois', mois)
    expect(avant ?? [], 'le mois ne s’est pas ouvert').toHaveLength(1)

    /* Le geste qui déclenchait la perte. */
    await seul.client.from('revenu').insert({
      household_id: seul.householdId, user_profile_id: seul.userId,
      net_mensuel_cents: 250_000, valid_from: mois,
    })

    const { data: apres } = await admin().from('depense').select('id')
      .eq('charge_id', c!.id).eq('mois', mois)
    expect(apres ?? [],
      'saisir son revenu a effacé la dépense du mois en cours').toHaveLength(1)
  })
})

describe('l’excédent et les avoirs', () => {
  it('un avoir entier compte, il ne disparaît pas', async () => {
    /*
     * 0072 écarte du calcul les lignes dont les parts changent de SIGNE : une
     * proportion n'existe pas entre 8 100 et −7 100. Juste. Mais le filtre
     * écrit `min(part) >= 0`, qui attrape aussi les lignes ENTIÈREMENT
     * négatives — un avoir, dont la proportion est parfaitement définie.
     *
     * Mesuré par une revue : excédent annoncé 5,00 € pour 65,00 € réels. La
     * ligne disparaissait en silence, et c'est ce nombre qui pilote « le verser
     * à l'épargne » et « baisser le prochain virement ».
     */
    const id = await poseCharge({
      libelle: 'Énergie avoir', cents: 5_000, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    /* Un avoir : on nous rend 10 €, donc la dépense réelle est négative. La
       ligne se fabrique par `admin()`, comme celle des signes mêlés plus bas :
       `confirme_la_ligne` refuse un montant négatif (0104), et ouvrir 2030-10
       d'abord ferait doublon sur l'unicité des lignes `modele`. */
    const { data: d, error } = await admin().from('depense').insert({
      household_id: moi.householdId, charge_id: id, mois: '2030-10-01',
      libelle: 'Énergie avoir', montant_cents: -1_000, montant_prevu_cents: 5_000,
      nature: 'connue', source: 'modele', facon: 'fixe',
      confirme_le: '2030-10-31T20:00:00Z',
    }).select().single()
    expect(error, `avoir refusé : ${error?.message}`).toBeNull()
    await admin().from('depense_part').insert([
      { depense_id: d!.id, user_profile_id: moi.userId, household_id: moi.householdId,
        part_cents: -600, part_bps: 6_000 },
      { depense_id: d!.id, user_profile_id: elle, household_id: moi.householdId,
        part_cents: -400, part_bps: 4_000 },
    ])

    const { data: ex } = await moi.client.rpc('excedent_du_mois', { le_mois: '2030-10-01' })
    const total = (ex ?? []).reduce(
      (s: number, l: { excedent_cents: number }) => s + Number(l.excedent_cents), 0)
    /* Prévu 50 €, réel −10 € : le foyer a 60 € de trop. */
    expect(total, 'un avoir entier est écarté en silence').toBe(6_000)
  })

  it('mais des parts de signes MÊLÉS restent écartées', async () => {
    /* Là, la proportion n'existe vraiment pas : on préfère ne rien dire que
       d'annoncer un chiffre absurde. */
    const id = await poseCharge({
      libelle: 'Mêlée', cents: 1_000, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    const { data: d } = await admin().from('depense').insert({
      household_id: moi.householdId, charge_id: id, mois: '2030-11-01',
      libelle: 'Mêlée', montant_cents: 1_000, montant_prevu_cents: 1_001,
      nature: 'connue', source: 'modele', facon: 'fixe',
      confirme_le: '2030-11-30T20:00:00Z',
    }).select().single()
    await admin().from('depense_part').insert([
      { depense_id: d!.id, user_profile_id: moi.userId, household_id: moi.householdId,
        part_cents: 8_100, part_bps: 8_100 },
      { depense_id: d!.id, user_profile_id: elle, household_id: moi.householdId,
        part_cents: -7_100, part_bps: 1_900 },
    ])

    const { data: ex } = await moi.client.rpc('excedent_du_mois', { le_mois: '2030-11-01' })
    expect(ex ?? [], 'une ligne de signes mêlés a produit un chiffre').toHaveLength(0)
  })
})

describe('retirer le dernier participant', () => {
  /* Mesuré : on décoche tout le monde, la ligne affiche « personne n'y
     participe », et elle continue de facturer. `refige_pour` ne supprimait les
     parts que des lignes qu'il saurait repeupler — donc jamais celles d'une
     charge que plus personne ne porte. */
  it('la dépense du mois s’en va, au lieu de facturer un absent', async () => {
    const id = await poseCharge({
      libelle: 'Netflix orphelin', cents: 1_500, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-06-01' })
    const { data: avant } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-06-01')
    expect(avant ?? [], 'le mois ne s’est pas ouvert').toHaveLength(1)

    await moi.client.from('charge_participant').delete().eq('charge_id', id)
    await moi.client.rpc('refige_le_mois', { le_mois: '2029-06-01' })

    const { data: apres } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-06-01')
    expect(apres ?? [], 'une charge que personne ne porte facture encore')
      .toHaveLength(0)
  })

  it('mais un mois CONFIRMÉ garde ce qu’on a réellement payé', async () => {
    const id = await poseCharge({
      libelle: 'Netflix payé', cents: 1_500, periodicite: 'mensuel',
      participants: [moi.userId, elle],
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2029-07-01' })
    const { data: d } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-07-01').single()
    await moi.client.rpc('confirme_la_depense', { la_depense: d!.id, reel_cents: 1_500 })

    await moi.client.from('charge_participant').delete().eq('charge_id', id)
    await moi.client.rpc('refige_le_mois', { le_mois: '2029-07-01' })

    const { data: apres } = await admin().from('depense').select('id')
      .eq('charge_id', id).eq('mois', '2029-07-01')
    expect(apres ?? [], 'un mois confirmé a été effacé').toHaveLength(1)
  })
})

describe('se retirer d’une charge commune', () => {
  /* 0065 l'interdisait par trigger, et cette interdiction a tué les DEUX seuls
     chemins qui suppriment une ligne de `charge_participant` : le bouton
     « Changer qui participe » et la cascade de `delete_my_account()`. Aucun
     test ne l'a vu — celui de suppression de compte a un foyer sans charge
     commune, et le bouton n'est appelé par aucun test d'intégration.

     Ces deux-là mordent : reposer le trigger les fait rougir. */
  async function chargeCommune(libelle: string): Promise<string> {
    const { data: c, error } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle, montant_cents: 100_000,
      periodicite: 'mensuel', compte_id: compteCommun, debut: '2026-01-01',
      commun: true,
    }).select().single()
    expect(error, `charge refusée : ${error?.message}`).toBeNull()
    const { error: eP } = await admin().from('charge_participant').insert(
      [moi.userId, elle].map(u => ({
        charge_id: c!.id, user_profile_id: u, household_id: moi.householdId,
      })))
    expect(eP, `participants refusés : ${eP?.message}`).toBeNull()
    return c!.id
  }

  it('un membre retire SA ligne d’une charge commune', async () => {
    const id = await chargeCommune('Loyer à quitter')
    const { data, error } = await moi.client.from('charge_participant')
      .delete().eq('charge_id', id).eq('user_profile_id', moi.userId).select()
    expect(error, `retrait refusé : ${error?.message}`).toBeNull()
    expect(data ?? [], 'la ligne est restée').toHaveLength(1)
  })

  it('et n’emporte pas celle de l’autre au passage', async () => {
    /* L'écran supprimait TOUS les participants pour en reposer deux. Une
       suppression de masse touche des lignes que personne n'a demandé à
       changer — et c'est elle qui a fait mourir le bouton en silence. */
    const id = await chargeCommune('Loyer partagé')
    await moi.client.from('charge_participant')
      .delete().eq('charge_id', id).eq('user_profile_id', moi.userId)
    const { data } = await admin().from('charge_participant')
      .select('user_profile_id').eq('charge_id', id)
    expect((data ?? []).map(r => r.user_profile_id))
      .toEqual([elle])
  })

  it('mais pas celle de quelqu’un d’un autre foyer', async () => {
    const id = await chargeCommune('Loyer d’à côté')
    const { data } = await voisin.client.from('charge_participant')
      .delete().eq('charge_id', id).select()
    expect(data ?? [], 'le voisin a défait notre charge').toHaveLength(0)
  })
})

describe('les gardes que l’audit a trouvées absentes', () => {
  it('une part ne s’attribue pas à quelqu’un d’un autre foyer', async () => {
    /* `depense_part.user_profile_id` n'a plus de clé étrangère — à raison, une
       part figée doit survivre au départ de son titulaire. Mais la garde de
       rattachement avait été retirée dans la foulée, au motif qu'elle en
       dépendait : elle n'en a jamais dépendu, elle lit `user_profile`. */
    const { data: d } = await admin().from('depense').select('id')
      .eq('household_id', moi.householdId).limit(1).single()
    const { error } = await admin().from('depense_part').insert({
      depense_id: d!.id, user_profile_id: voisin.userId,
      household_id: moi.householdId, part_cents: 1, part_bps: 1,
    })
    expect(error, 'une part a été attribuée au voisin').not.toBeNull()
  })

  it('les parts ne se réécrivent pas à la main', async () => {
    /* Le contrôle différé ne regarde que la SOMME : supprimer puis reposer
       permettait de passer de 600/400 à un centime contre 999,99 €. */
    const { data: p } = await admin().from('depense_part')
      .select('depense_id').eq('household_id', moi.householdId).limit(1).single()
    const { data: pose } = await moi.client.from('depense_part').insert({
      depense_id: p!.depense_id, user_profile_id: moi.userId,
      household_id: moi.householdId, part_cents: 1, part_bps: 1,
    }).select()
    expect(pose ?? [], 'on peut encore poser une part à la main').toHaveLength(0)

    const { data: reste } = await moi.client.from('depense_part')
      .delete().eq('depense_id', p!.depense_id).select()
    expect(reste ?? [], 'on peut encore supprimer les parts à la main').toHaveLength(0)
  })

  it('un versement d’épargne ne se pose qu’à son propre nom', async () => {
    const { data: poche } = await admin().from('poche_epargne').insert({
      household_id: moi.householdId, libelle: `Poche ${Date.now()}`, genre: 'urgence',
    }).select().single()

    const { data: pose } = await moi.client.from('versement_epargne').insert({
      household_id: moi.householdId, poche_id: poche!.id,
      user_profile_id: elle, montant_cents: -49_999,
    }).select()
    expect(pose ?? [], 'on a versé — ou retiré — au nom de quelqu’un d’autre')
      .toHaveLength(0)

    const { data: mien } = await moi.client.from('versement_epargne').insert({
      household_id: moi.householdId, poche_id: poche!.id,
      user_profile_id: moi.userId, montant_cents: 5_000,
    }).select()
    expect(mien ?? [], 'on ne peut plus verser à son propre nom').toHaveLength(1)
  })


  it('un compte, une clé de partage : le voisin ne les lit pas', async () => {
    // Deux policies dont l'audit a montré qu'aucun test ne les gardait :
    // les remplacer par `using (true)` laissait la suite entière verte.
    const { data: comptes } = await voisin.client.from('compte')
      .select('id').eq('household_id', moi.householdId)
    expect(comptes ?? [], 'le voisin lit les comptes du foyer d’à côté').toHaveLength(0)

    const { data: parts } = await voisin.client.from('depense_part')
      .select('depense_id').eq('household_id', moi.householdId)
    expect(parts ?? [], 'le voisin lit les parts du foyer d’à côté').toHaveLength(0)

    const { data: vers } = await voisin.client.from('versement_epargne')
      .select('id').eq('household_id', moi.householdId)
    expect(vers ?? [], 'le voisin lit l’épargne du foyer d’à côté').toHaveLength(0)

    // Et la clé de partage ne s'emprunte pas : l'argument n'est honoré que
    // pour le rôle de service.
    const { data: cle } = await voisin.client.rpc('parts_du_foyer',
      { le_mois: '2026-09-01', le_foyer: moi.householdId })
    const chezMoi = (cle ?? []).some(
      (l: { user_profile_id: string }) => l.user_profile_id === moi.userId)
    expect(chezMoi, 'le voisin a obtenu la clé de partage du foyer d’à côté').toBe(false)
  })
})
