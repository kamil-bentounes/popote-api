/**
 * Les enveloppes, l'épargne et les projets.
 *
 * Trois choses qu'on confond, et qu'il faut séparer :
 *
 *  · une enveloppe est un PLAFOND. Aucun argent ne bouge ;
 *  · une poche d'épargne est de l'argent qui PERSISTE, donc qui appartient à
 *    quelqu'un — et un livret joint est présumé moitié-moitié alors que les
 *    versements, eux, ne le sont pas ;
 *  · un projet est une poche datée.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

let moi: Actor
let elle: string
let urgence: string
let restaurant: string

beforeAll(async () => {
  moi = await makeActor('epargne')
  const { data } = await admin().auth.admin.createUser({
    email: `elle-ep-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
  })
  elle = data.user!.id
  await admin().from('user_profile').insert({
    id: elle, household_id: moi.householdId, display_name: 'Elle', entre_le: '2026-01-01',
  })
  await admin().from('user_profile').update({ entre_le: '2026-01-01' }).eq('id', moi.userId)

  const { data: p } = await admin().from('poche_epargne').insert({
    household_id: moi.householdId, libelle: 'Urgence', genre: 'urgence',
    objectif_cents: 450_000,
  }).select().single()
  urgence = p!.id

  const { data: e } = await admin().from('enveloppe').insert({
    household_id: moi.householdId, libelle: 'Restaurant', plafond_cents: 40_000,
  }).select().single()
  restaurant = e!.id
})

describe('l’épargne appartient à quelqu’un', () => {
  it('suit le cumul VERSÉ PAR PERSONNE, pas seulement le solde', async () => {
    await admin().from('versement_epargne').insert([
      { household_id: moi.householdId, poche_id: urgence,
        user_profile_id: moi.userId, montant_cents: 15_500, fait_le: '2026-02-01' },
      { household_id: moi.householdId, poche_id: urgence,
        user_profile_id: elle, montant_cents: 9_500, fait_le: '2026-02-01' },
      { household_id: moi.householdId, poche_id: urgence,
        user_profile_id: moi.userId, montant_cents: 15_500, fait_le: '2026-03-01' },
    ])

    const { data, error } = await moi.client.rpc('solde_epargne', { la_poche: urgence })
    expect(error, `solde refusé : ${error?.message}`).toBeNull()
    const cumul = Object.fromEntries(
      (data ?? []).map((l: { user_profile_id: string; cumul_cents: number }) =>
        [l.user_profile_id, Number(l.cumul_cents)]))

    expect(cumul[moi.userId], 'son cumul à lui est faux').toBe(31_000)
    expect(cumul[elle], 'son cumul à elle est faux').toBe(9_500)
    // Le solde n'est jamais « 405 € » tout court : c'est 310 + 95.
    expect(Object.values(cumul).reduce((s, n) => s + n, 0)).toBe(40_500)
  })

  it('un retrait se compte, et ne se confond pas avec un versement', async () => {
    await admin().from('versement_epargne').insert({
      household_id: moi.householdId, poche_id: urgence,
      user_profile_id: moi.userId, montant_cents: -5_000, motif: 'retrait',
    })
    const { data } = await moi.client.rpc('solde_epargne', { la_poche: urgence })
    const mien = (data ?? []).find(
      (l: { user_profile_id: string }) => l.user_profile_id === moi.userId)
    expect(Number(mien.cumul_cents), 'le retrait n’a pas été déduit').toBe(26_000)
  })

  it('un versement ne change ni de personne ni de poche', async () => {
    // Déplacer un versement, c'est déplacer de la propriété. On corrige par une
    // ligne de correction, qui laisse une trace.
    const { data: v } = await admin().from('versement_epargne')
      .select('id').eq('household_id', moi.householdId).limit(1).single()

    const { error: e1 } = await moi.client.from('versement_epargne')
      .update({ user_profile_id: elle }).eq('id', v!.id)
    expect(e1, 'un versement a changé de propriétaire').not.toBeNull()

    const { data: autre } = await admin().from('poche_epargne').insert({
      household_id: moi.householdId, libelle: 'Voyages', genre: 'projet',
      objectif_cents: 120_000, echeance: '2027-12-01', cle: 'moitie',
    }).select().single()
    const { error: e2 } = await moi.client.from('versement_epargne')
      .update({ poche_id: autre!.id }).eq('id', v!.id)
    expect(e2, 'un versement a changé de poche').not.toBeNull()
  })

  it('le registre survit au départ de la personne', async () => {
    // Sans clé étrangère, délibérément : le pot doit toujours pouvoir se rendre
    // dans les proportions versées, même si l'un des deux est parti.
    const { data: u } = await admin().auth.admin.createUser({
      email: `part-${Date.now()}@fumee.test`, password: 'x'.repeat(12), email_confirm: true,
    })
    const partant = u.user!.id
    await admin().from('user_profile').insert({
      id: partant, household_id: moi.householdId, display_name: 'Partant',
    })
    await admin().from('versement_epargne').insert({
      household_id: moi.householdId, poche_id: urgence,
      user_profile_id: partant, montant_cents: 7_000,
    })
    await admin().from('user_profile').delete().eq('id', partant)

    const { data } = await moi.client.rpc('solde_epargne', { la_poche: urgence })
    const sien = (data ?? []).find(
      (l: { user_profile_id: string }) => l.user_profile_id === partant)
    expect(sien, 'le versement de la personne partie a disparu').toBeDefined()
    expect(Number(sien.cumul_cents)).toBe(7_000)
  })

  it('le voisin ne lit pas le solde d’une poche qui n’est pas la sienne', async () => {
    const voisin = await makeActor('epargne-voisin')
    const { data } = await voisin.client.rpc('solde_epargne', { la_poche: urgence })
    expect(data ?? [], 'le voisin lit l’épargne du foyer d’à côté').toHaveLength(0)
  })
})

describe('les enveloppes', () => {
  it('disent ce qu’il reste, ce mois-ci, pas en fin de mois', async () => {
    // D66 : un plafond qu'on découvre trop tard est une décoration.
    const { data: ch } = await admin().from('charge').insert({
      household_id: moi.householdId, libelle: 'Restaurant', montant_cents: 26_000,
      periodicite: 'mensuel', debut: '2026-01-01', enveloppe_id: restaurant,
    }).select().single()
    await admin().from('charge_participant').insert({
      charge_id: ch!.id, user_profile_id: moi.userId, household_id: moi.householdId,
    })
    await moi.client.rpc('ouvre_le_mois', { le_mois: '2026-04-01' })

    const { data, error } = await moi.client.rpc('reste_enveloppe', { le_mois: '2026-04-01' })
    expect(error, `reste refusé : ${error?.message}`).toBeNull()
    const resto = (data ?? []).find((l: { libelle: string }) => l.libelle === 'Restaurant')
    expect(resto, 'l’enveloppe n’apparaît pas').toBeDefined()

    /* La provision est le PLAN, pas une sortie. Comptée comme dépensée, elle
       affichait « 400,00 / 400,00 € » et « il reste 0,00 € » le premier du
       mois, avant le moindre achat — alors que l'écran des réglages promet
       « aucun argent ne bouge, c'est une limite ». */
    expect(Number(resto.prevu_cents), 'la provision n’est pas rattachée à l’enveloppe')
      .toBe(26_000)
    expect(Number(resto.depense_cents), 'une provision non confirmée compte comme dépensée')
      .toBe(0)
    expect(Number(resto.reste_cents), 'l’enveloppe se vide toute seule').toBe(40_000)
  })

  it('un mois sans dépense laisse le plafond entier', async () => {
    const { data } = await moi.client.rpc('reste_enveloppe', { le_mois: '2026-09-01' })
    const resto = (data ?? []).find((l: { libelle: string }) => l.libelle === 'Restaurant')
    expect(Number(resto.reste_cents), 'le plafond ne se remet pas à zéro chaque mois')
      .toBe(40_000)
  })

  it('une enveloppe d’un autre foyer n’entre pas dans le calcul', async () => {
    const voisin = await makeActor('env-voisin')
    await admin().from('enveloppe').insert({
      household_id: voisin.householdId, libelle: 'Restaurant', plafond_cents: 99_900,
    })
    const { data } = await moi.client.rpc('reste_enveloppe', { le_mois: '2026-04-01' })
    expect((data ?? []).filter((l: { libelle: string }) => l.libelle === 'Restaurant'),
      'l’enveloppe du voisin est comptée').toHaveLength(1)
  })
})

describe('les projets (D72)', () => {
  it('portent une échéance, des postes, et leur propre clé', async () => {
    const { data: p } = await moi.client.from('poche_epargne').insert({
      household_id: moi.householdId, libelle: 'Lisbonne', genre: 'projet',
      objectif_cents: 120_000, echeance: '2027-12-01', cle: 'moitie',
    }).select().single()
    expect(p!.cle, 'un projet peut être à moitié-moitié même si le foyer est au prorata')
      .toBe('moitie')

    const { error } = await moi.client.from('poche_poste').insert([
      { poche_id: p!.id, household_id: moi.householdId, libelle: 'Hôtel',
        montant_cents: 50_000, ordre: 0 },
      { poche_id: p!.id, household_id: moi.householdId, libelle: 'Transport',
        montant_cents: 40_000, ordre: 1 },
    ])
    expect(error, `postes refusés : ${error?.message}`).toBeNull()

    const { data: postes } = await moi.client.from('poche_poste')
      .select('montant_cents').eq('poche_id', p!.id)
    expect(postes!.reduce((s, x) => s + x.montant_cents, 0)).toBe(90_000)
  })

  it('un poste ne se rattache pas à la poche du voisin', async () => {
    const voisin = await makeActor('projet-voisin')
    const { data: sienne } = await admin().from('poche_epargne').insert({
      household_id: voisin.householdId, libelle: 'Chez lui', genre: 'projet',
    }).select().single()

    const { error } = await moi.client.from('poche_poste').insert({
      poche_id: sienne!.id, household_id: moi.householdId,
      libelle: 'Intrus', montant_cents: 1_000, ordre: 0,
    })
    expect(error, 'un poste a été rattaché à la poche d’un autre foyer').not.toBeNull()
  })

  it('une échéance de fantaisie est refusée', async () => {
    const { error } = await moi.client.from('poche_epargne').insert({
      household_id: moi.householdId, libelle: 'An mille', genre: 'projet',
      echeance: '1000-01-01',
    })
    expect(error, 'une échéance hors bornes est acceptée').not.toBeNull()
  })
})
