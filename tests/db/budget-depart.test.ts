/**
 * Le départ d'un membre : le détail part, le total reste.
 *
 * Sans cela, après le départ de Thauba, Kamil lisait encore chacun de ses achats
 * « Pharmacie », datés et chiffrés.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { admin } from './helpers/db'
import { connexion, enProprietaire } from './helpers/pg'
import { ajustements, clore, clos, declare, foyerDOctobre, foyerSolo, ligne, membre, ou, ouvre,
         ouvreLAnnee, poseCharge } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-10T12:00:00+01:00'))
afterAll(remetLHeure)

describe('un membre part, le foyer reste', () => {
  it('ses saisies perso partent, mois clôturés compris ; les montants et ses versements restent',
    async () => {
      const f = await foyerSolo('dep-thauba', { revenu: 300_000 })
      const thauba = await membre(f, 'Thauba', { revenu: 300_000 })
      const pharmacie = await poseCharge(f, { libelle: 'Pharmacie', cents: 2_000, mode: 'au_fil',
                                              participants: [thauba.userId] })
      const courses = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil',
        commun: true, participants: [f.userId, thauba.userId] })
      await ouvre(f, '2026-09-01')
      await ouvre(f, '2026-10-01')
      ou(await declare(thauba, (await ligne(pharmacie, '2026-09-01'))!.id, '2026-09-12', 1_200))
      ou(await declare(thauba, (await ligne(pharmacie, '2026-10-01'))!.id, '2026-10-03', 800))
      ou(await declare(thauba, (await ligne(courses, '2026-10-01'))!.id, '2026-10-05', 5_000))
      await clos(f, '2026-09-01')
      // Ses deux comptes perso, l'un archivé : c'est l'état de Kamil en prod.
      ou(await admin().from('compte').insert([
        { household_id: f.householdId, nom: 'CA de Thauba', genre: 'perso', titulaire_id: thauba.userId },
        { household_id: f.householdId, nom: 'Ancien CA', genre: 'perso', titulaire_id: thauba.userId,
          archive_le: '2026-06-01T00:00:00Z' },
      ]).select())
      // Son choix de clôture de septembre, et son versement.
      const poche = ou(await admin().from('poche_epargne').insert({
        household_id: f.householdId, libelle: 'Urgence', genre: 'urgence' }).select().single()) as { id: string }
      const v = ou(await admin().from('versement_epargne').insert({
        household_id: f.householdId, poche_id: poche.id, user_profile_id: thauba.userId,
        montant_cents: 10_000, motif: 'balayage' }).select().single()) as { id: string }
      const k = ou(await admin().from('cloture').select('id').eq('household_id', f.householdId)
        .eq('mois', '2026-09-01').single()) as { id: string }
      ou(await admin().from('cloture_choix').insert({
        cloture_id: k.id, household_id: f.householdId, user_profile_id: thauba.userId,
        reste_cents: 50_000, mis_de_cote_cents: 10_000, poche_id: poche.id, versement_id: v.id,
      }).select())

      const total = async () => (ou(await admin().from('depense').select('montant_cents')
        .eq('household_id', f.householdId)) as { montant_cents: number }[])
        .reduce((s, l) => s + l.montant_cents, 0)
      const avant = await total()
      const pharmacieDOctobre = (await ligne(pharmacie, '2026-10-01'))!.montant_cents

      const { error } = await thauba.client.rpc('delete_my_account')
      expect(error, `départ refusé : ${error?.message}`).toBeNull()
      /* Sa pharmacie, charge à elle seule, s'en va avec elle : sa ligne d'octobre,
         encore ouverte, disparaît. Rien d'autre ne bouge : un centime de plus ou de
         moins serait une ligne de Kamil touchée. */
      expect(await total(), 'un centime perdu ou créé par le départ')
        .toBe(avant - pharmacieDOctobre)
      expect(await ligne(pharmacie, '2026-10-01'), 'sa ligne d’octobre est restée').toBeFalsy()

      // Septembre est clôturé : la ligne reste (l'historique), mais ses achats partent.
      const septembre = (await ligne(pharmacie, '2026-09-01'))!
      expect((await admin().from('saisie').select('id').eq('depense_id', septembre.id)).data,
        'ses achats de septembre se lisent encore').toEqual([])
      expect((await ligne(pharmacie, '2026-09-01'))!.montant_cents).toBe(2_000)
      const { data: partagee } = await admin().from('saisie').select('saisi_par, montant_cents')
        .eq('depense_id', (await ligne(courses, '2026-10-01'))!.id)
      expect(partagee).toEqual([{ saisi_par: null, montant_cents: 5_000 }])
      /* Les parts de la ligne gelée restent (`depense_part` n'a aucune clé vers
         le profil) : elles font encore 10 000 pb, donc la part de Kamil ne grossit
         pas du départ de Thauba et aucun centime de Courses n'est créé ni perdu. */
      const { data: parts } = await admin().from('depense_part').select('part_bps')
        .eq('depense_id', (await ligne(courses, '2026-10-01'))!.id)
      expect(parts!.reduce((s, p) => s + p.part_bps, 0), 'les parts ne font plus 100 %')
        .toBe(10_000)
      const { data: choix } = await admin().from('cloture_choix')
        .select('reste_cents, versement_id').eq('user_profile_id', thauba.userId)
      expect(choix).toEqual([{ reste_cents: null, versement_id: v.id }])
      expect((await admin().from('compte').select('id').eq('titulaire_id', thauba.userId)).data)
        .toEqual([])
    })

  it('sa charge perso s’archive si elle a une histoire, se supprime sinon ; celles de Kamil restent',
    async () => {
      const f = await foyerSolo('dep-charge-perso', { revenu: 300_000 })
      const thauba = await membre(f, 'Thauba', { revenu: 300_000 })
      const pharmacie = await poseCharge(f, { libelle: 'Pharmacie', cents: 3_000, mode: 'au_fil',
                                              participants: [thauba.userId] })
      const sport = await poseCharge(f, { libelle: 'Sport de Kamil', cents: 2_500, mode: 'fixe',
                                          participants: [f.userId] })
      const courses = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil',
        commun: true, participants: [f.userId, thauba.userId] })
      await ouvre(f, '2026-09-01')
      await ouvre(f, '2026-10-01')
      ou(await declare(thauba, (await ligne(pharmacie, '2026-09-01'))!.id, '2026-09-12', 1_200))
      await clos(f, '2026-09-01')
      // Posée après la clôture de septembre : aucune ligne clôturée, donc aucune histoire.
      const neuve = await poseCharge(f, { libelle: 'Abonnement neuf', cents: 1_500, mode: 'fixe',
                                          participants: [thauba.userId] })
      const restantes = async () => ((ou(await admin().from('depense').select('id, charge_id')
        .in('charge_id', [sport, courses])) as { id: string }[]).map(l => l.id).sort())
      const avant = await restantes()

      ou(await thauba.client.rpc('delete_my_account'))

      const { data: p } = await admin().from('charge').select('archive_le').eq('id', pharmacie)
      expect(p, 'la pharmacie a une histoire : elle s’arrête, elle ne disparaît pas').toHaveLength(1)
      expect(p![0].archive_le, 'la pharmacie est restée active').not.toBeNull()
      expect((await admin().from('charge').select('id').eq('id', neuve)).data,
        'une charge sans histoire part tout à fait').toEqual([])
      const { data: k } = await admin().from('charge').select('archive_le').in('id', [sport, courses])
      expect(k!.map(c => c.archive_le), 'une charge de Kamil a été archivée').toEqual([null, null])
      expect(await restantes(), 'une ligne de Kamil a bougé').toEqual(avant)
    })

  it('les mois ouverts se repartagent entre ceux qui restent ; le mois clôturé garde ses parts',
    async () => {
      const f = await foyerSolo('dep-repartage', { revenu: 300_000 })
      const thauba = await membre(f, 'Thauba', { arrivee: '2026-09-01', revenu: 200_000 })
      const courses = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil',
        commun: true, participants: [f.userId, thauba.userId] })
      await ouvre(f, '2026-09-01')
      await ouvre(f, '2026-10-01')
      await clos(f, '2026-09-01')
      const parts = async (mois: string) => ou(await admin().from('depense_part')
        .select('user_profile_id, part_bps, part_cents')
        .eq('depense_id', (await ligne(courses, mois))!.id)) as
        { user_profile_id: string; part_bps: number; part_cents: number }[]
      const septembre = await parts('2026-09-01')
      // À deux, octobre se partage 60/40 : le test n'a de sens que s'il part de là.
      expect((await parts('2026-10-01')).map(p => p.part_bps).sort((a, b) => a - b))
        .toEqual([4_000, 6_000])

      ou(await thauba.client.rpc('delete_my_account'))

      /* Octobre est ouvert : sa part de Courses revient à Kamil, qui doit TOUT.
         Avant, 40 % restaient rattachés à un profil disparu : Kamil lisait « Il te
         reste 1 275 € après 2 425 € de charges » alors qu'il en devait 3 959 €. */
      expect(await parts('2026-10-01'), 'octobre n’a pas été repartagé').toEqual([
        { user_profile_id: f.userId, part_bps: 10_000, part_cents: 80_000 }])
      // Septembre est clôturé : il vaut son reste, ses parts ne bougent pas.
      expect(await parts('2026-09-01'), 'un mois clôturé a été repartagé').toEqual(septembre)
    })

  it('à trois, le départ de l’un repartage entre les deux qui restent, au prorata de leurs revenus',
    async () => {
      const f = await foyerSolo('dep-trois', { revenu: 300_000 })
      const thauba = await membre(f, 'Thauba', { arrivee: '2026-09-01', revenu: 200_000 })
      const camille = await membre(f, 'Camille', { arrivee: '2026-09-01', revenu: 100_000 })
      const courses = await poseCharge(f, { libelle: 'Courses', cents: 80_000, mode: 'au_fil',
        commun: true, participants: [f.userId, thauba.userId, camille.userId] })
      await ouvre(f, '2026-10-01')
      const ligneDOctobre = (await ligne(courses, '2026-10-01'))!
      ou(await thauba.client.rpc('delete_my_account'))
      const parts = ou(await admin().from('depense_part').select('user_profile_id, part_cents')
        .eq('depense_id', ligneDOctobre.id)) as { user_profile_id: string; part_cents: number }[]
      // 300 000 et 100 000 : 75 % et 25 % de 80 000 €.
      expect(Object.fromEntries(parts.map(p => [p.user_profile_id, p.part_cents])),
        'les parts des deux qui restent ne suivent pas leurs revenus').toEqual({
          [f.userId]: 60_000, [camille.userId]: 20_000 })
    })

  it('l’ajustement posé sur la charge perso archivée de la partante part avec elle', async () => {
    await regleLHeure('2026-11-10T12:00:00+01:00')
    const f = await foyerSolo('dep-ajustement', { revenu: 300_000 })
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-09-01', revenu: 300_000 })
    const entretien = await poseCharge(f, { libelle: 'Entretien perso', cents: 50_004,
      mode: 'mis_de_cote', participants: [thauba.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    ou(await thauba.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                    montant_cents: 32_000, paye_le: '2026-11-10' }))
    expect((await ajustements(entretien)).length, 'le test doit partir d’un ajustement').toBeGreaterThan(0)

    ou(await thauba.client.rpc('delete_my_account'))

    // La charge a une facture : elle s'arrête. Son ajustement du mois ouvert n'est à personne.
    expect((await admin().from('charge').select('archive_le').eq('id', entretien)).data![0].archive_le)
      .not.toBeNull()
    expect(await ajustements(entretien), 'un ajustement sans propriétaire compte encore dans le mois')
      .toEqual([])
  })

  it('le départ du seul membre qui avait un revenu recale les années ouvertes', async () => {
    const f = await foyerSolo('dep-recale', { revenu: null })
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-09-01', revenu: 240_000 })
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
      mode: 'mis_de_cote', commun: true, participants: [f.userId, thauba.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: entretien,
                                                montant_cents: 32_000, paye_le: '2026-11-10' }))
    expect((await ajustements(entretien)).map(l => l.montant_cents)).toEqual([15_332])
    ou(await thauba.client.rpc('delete_my_account'))
    // Plus aucun revenu : plus aucun mois suivi, Pl = 0, toute la facture compte.
    expect((await ajustements(entretien)).map(l => l.montant_cents)).toEqual([15_332, 16_668])
  })
})

/**
 * Une charge perso annuelle de Thauba, dont elle a porté septembre et octobre
 * (2 × 41,67 € = 83,34 €), dont plus aucun participant n'est présent. Ce qu'elle
 * avait mis de côté est parti avec elle : `recale_l_annee` ne le rend pas à Kamil.
 * Mais ce que Kamil a posé LUI-MÊME ensuite lui revient, retirer sa facture comprise.
 *
 * `delete_my_account` retire désormais ces charges avec le partant : l'état n'est
 * plus produit par un départ. On retire donc le compte SANS passer par elle, pour
 * garder éprouvée la garde de `recale_l_annee` (une base peut encore le contenir).
 */
describe('une charge perso de la membre partie', () => {
  let c: pg.Client
  beforeAll(async () => { c = await connexion() })
  afterAll(async () => { await c.end() })

  async function sansThauba(nom: string) {
    const f = await foyerSolo(nom, { revenu: 300_000 })
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-09-01', revenu: 300_000 })
    const entretien = await poseCharge(f, { libelle: 'Entretien perso', cents: 50_004,
      mode: 'mis_de_cote', participants: [thauba.userId] })
    for (const m of ['2026-09-01', '2026-10-01']) {
      ou(await f.client.rpc('ouvre_la_charge', { la_charge: entretien, foyer: f.householdId,
                                                 le_mois: m }))
    }
    ou(await admin().auth.admin.deleteUser(thauba.userId))
    return { f, entretien }
  }
  const somme = async (charge: string) =>
    (await ajustements(charge)).reduce((s, l) => s + l.montant_cents, 0)

  it('la facture de Kamil se pose sur lui, et la retirer la rend : rien ne reste sur novembre',
    async () => {
      const { f, entretien } = await sansThauba('dep-facture-retiree')
      const la = randomUUID()
      ou(await f.client.rpc('paie_une_facture', { la_facture: la, la_charge: entretien,
                                                  montant_cents: 20_001, paye_le: '2026-11-10' }))
      // 200,01 € moins les 83,34 € que Thauba avait mis de côté, sur Kamil seul.
      expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents]))
        .toEqual([['2026-11-01', 11_667]])
      ou(await f.client.rpc('retire_une_facture', { la_facture: la }))
      expect(await somme(entretien), 'les 116,67 € de Kamil sont restés sur novembre').toBe(0)
    })

  it('corriger le relevé à la baisse, après le départ, ne laisse rien non plus', async () => {
    const { f, entretien } = await sansThauba('dep-releve-corrige')
    const la = randomUUID()
    ou(await admin().from('releve_annuel').insert({
      household_id: f.householdId, charge_id: entretien, annee: 2026, reel_cents: 20_000,
      prevu_cents: 8_334, ecart_cents: 11_666, saisi_par: f.userId }).select())
    ou(await admin().from('facture').insert({
      id: la, household_id: f.householdId, charge_id: entretien, annee: 2026,
      paye_le: '2026-11-10', montant_cents: 20_000, origine: 'releve', saisi_par: f.userId }).select())
    ou(await f.client.rpc('corrige_le_releve', { la_facture: la, montant_cents: 20_000 }))
    expect(await somme(entretien)).toBe(11_666)
    ou(await f.client.rpc('corrige_le_releve', { la_facture: la, montant_cents: 8_334 }))
    expect(await somme(entretien), 'la correction n’a pas rendu l’écart à Kamil').toBe(0)
  })

  it('le solde de décembre ne rend pas à Kamil ce que Thauba avait mis de côté', async () => {
    const { f, entretien } = await sansThauba('dep-solde-sans-rendre')
    await enProprietaire(c, f.userId)
    try {
      await c.query('select public.solde_l_annee($1, $2, $3)', [entretien, 2026, '2026-12-01'])
      await c.query('commit')
    } catch (e) { await c.query('rollback'); throw e }
    expect(await ajustements(entretien), 'Kamil a reçu 83,34 € qu’il n’avait pas mis de côté')
      .toEqual([])
    const { data: r } = await admin().from('releve_annuel').select('reel_cents, prevu_cents')
      .eq('charge_id', entretien).eq('annee', 2026)
    expect(r).toEqual([{ reel_cents: 0, prevu_cents: 8_334 }])
  })
})

describe('le dernier membre part', () => {
  it('passe avec des saisies dans un mois clôturé, une facture et ses comptes perso', async () => {
    const { f, id, poche } = await foyerDOctobre('dep-dernier')
    ou(await declare(f, (await ligne(id.courses, '2026-10-01'))!.id, '2026-10-04', 6_000))
    ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(), la_charge: id.entretien,
                                                montant_cents: 32_000, paye_le: '2026-11-10' }))
    ou(await clore(f, { poche }))
    ou(await admin().from('compte').insert([
      { household_id: f.householdId, nom: 'Mon CA', genre: 'perso', titulaire_id: f.userId },
      { household_id: f.householdId, nom: 'Vieux CA', genre: 'perso', titulaire_id: f.userId,
        archive_le: '2026-06-01T00:00:00Z' },
    ]).select())
    const { error } = await f.client.rpc('delete_my_account')
    expect(error, `départ refusé : ${error?.message}`).toBeNull()
    expect((await admin().from('household').select('id').eq('id', f.householdId)).data).toEqual([])
  })
})
