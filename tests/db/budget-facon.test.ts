/**
 * La façon de payer d'une charge, et sa catégorie (§ 4.1).
 *
 * Deux choses à tenir : l'ancien paquet, qui ne connaît ni l'une ni l'autre,
 * écrit encore des charges justes ; et le client ne change plus lui-même
 * l'argent d'une charge — un update direct du montant laissait la ligne
 * d'octobre à 800 € sous une charge à 850 €.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { foyerSolo, ou, type Foyer } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

let f: Foyer
let enveloppe: string
beforeAll(async () => {
  f = await foyerSolo('facon')
  enveloppe = (ou(await admin().from('enveloppe').insert({
    household_id: f.householdId, libelle: 'Restaurants', plafond_cents: 40_000,
  }).select().single()) as { id: string }).id
})
afterAll(remetLHeure)

/** Ce qu'écrit l'ancien « Mes charges » : ni mode, ni catégorie. */
async function ancienPaquet(o: Record<string, unknown>) {
  return f.client.from('charge').insert({
    household_id: f.householdId, montant_cents: 5_000, periodicite: 'mensuel',
    debut: '2026-10-01', ...o,
  }).select('id, mode, categorie').single()
}
const article = async (libelle: string) => (ou(await admin().from('catalogue_charge')
  .select('id').eq('libelle', libelle).single()) as { id: string }).id

describe('la façon déduite pour l’ancien paquet', () => {
  it('« variable » fait une facture du mois', async () => {
    const { data, error } = await ancienPaquet({ libelle: 'Électricité', variable: true })
    expect(error).toBeNull()
    expect(data!.mode).toBe('facture')
  })
  it('une enveloppe fait une ligne au fil du mois', async () => {
    expect((await ancienPaquet({ libelle: 'Restaurants', enveloppe_id: enveloppe })).data!.mode)
      .toBe('au_fil')
  })
  it('une périodicité non mensuelle est toujours mise de côté', async () => {
    expect((await ancienPaquet({ libelle: 'Taxe', periodicite: 'annuel' })).data!.mode)
      .toBe('mis_de_cote')
  })
  it('le reste est fixe', async () => {
    expect((await ancienPaquet({ libelle: 'Internet' })).data!.mode).toBe('fixe')
  })
  it('« mise de côté » sur une charge mensuelle retombe sur ce qu’elle porte', async () => {
    expect((await ancienPaquet({ libelle: 'Gaz', mode: 'mis_de_cote', variable: true }))
      .data!.mode).toBe('facture')
  })
  it('rattacher une enveloppe à une charge fixe la passe au fil du mois', async () => {
    const { data: c } = await ancienPaquet({ libelle: 'Sorties' })
    const { data, error } = await f.client.from('charge').update({ enveloppe_id: enveloppe })
      .eq('id', c!.id).select('mode').single()
    expect(error).toBeNull()
    expect(data!.mode).toBe('au_fil')
  })
  it('le nouveau paquet dit lui-même la façon et la catégorie', async () => {
    const { data } = await f.client.from('charge').insert({
      household_id: f.householdId, libelle: 'Péage', montant_cents: 3_000,
      periodicite: 'mensuel', mode: 'au_fil', categorie: 'auto', debut: '2026-10-01',
    }).select('mode, categorie').single()
    expect(data).toEqual({ mode: 'au_fil', categorie: 'auto' })
  })
})

describe('la catégorie vient de l’article du catalogue', () => {
  it.each([
    ['Pharmacie', 'sante'], ['Taxe foncière', 'maison'], ['Courses', 'vie_courante'],
    ['Crédit immobilier — résidence', 'maison'], ['Crédit immobilier — locatif', 'credits'],
    ['Forfait mobile', 'abonnements'], ['Impôt sur le revenu', 'impots'], ['Péages', 'auto'],
  ])('%s → %s', async (libelle, categorie) => {
    const { data } = await ancienPaquet({ libelle, catalogue_id: await article(libelle) })
    expect(data!.categorie).toBe(categorie)
  })
  it('une catégorie choisie n’est pas écrasée', async () => {
    const { data } = await ancienPaquet({
      libelle: 'Pharmacie', catalogue_id: await article('Pharmacie'), categorie: 'auto' })
    expect(data!.categorie).toBe('auto')
  })
})

describe('le client ne change plus l’argent d’une charge en direct', () => {
  let id: string
  beforeAll(async () => { id = (await ancienPaquet({ libelle: 'Assurance' })).data!.id })

  it.each([
    ['montant_cents', 6_000], ['periodicite', 'annuel'], ['mode', 'facture'],
    ['variable', true], ['cle', 'moitie'], ['debut', '2026-09-01'],
    ['fin', '2027-01-01'], ['commun', true],
  ])('%s passe par « Corriger »', async (colonne, valeur) => {
    const { error } = await f.client.from('charge').update({ [colonne]: valeur })
      .eq('id', id).select()
    expect(error?.message).toMatch(/Corriger/)
  })
  it('archive_le passe par « Retirer »', async () => {
    const { error } = await f.client.from('charge')
      .update({ archive_le: new Date().toISOString() }).eq('id', id).select()
    expect(error?.message).toMatch(/Retirer/)
  })
  it('le libellé, la catégorie, le compte et l’enveloppe restent au client', async () => {
    const { error } = await f.client.from('charge').update({
      libelle: 'Assurance habitation', categorie: 'maison', compte_id: f.compte,
      enveloppe_id: null,
    }).eq('id', id).select()
    expect(error).toBeNull()
  })
  it('sous la clé de service, rien n’est refusé', async () => {
    const { error } = await admin().from('charge').update({ montant_cents: 6_500 })
      .eq('id', id).select()
    expect(error).toBeNull()
  })
})

describe('la date de départ', () => {
  it('ne remonte pas avant le 1er janvier de l’année précédente, pour personne', async () => {
    await regleLHeure('2026-10-15T12:00:00+02:00')
    expect((await ancienPaquet({ libelle: 'Vieille', debut: '2024-12-01' })).error?.message)
      .toMatch(/01\/01\/2025/)
    const { error } = await admin().from('charge').insert({
      household_id: f.householdId, libelle: 'Vieille', montant_cents: 1_000,
      periodicite: 'mensuel', debut: '2024-12-01' }).select()
    expect(error?.message, 'la clé de service passait').toMatch(/01\/01\/2025/)
    expect((await ancienPaquet({ libelle: 'Juste', debut: '2025-01-01' })).error).toBeNull()
  })
  it('une charge plus ancienne qui ne change pas de date reste modifiable', async () => {
    await regleLHeure('2024-06-15T12:00:00+02:00')
    const { data: c } = await admin().from('charge').insert({
      household_id: f.householdId, libelle: 'Ancienne', montant_cents: 1_000,
      periodicite: 'mensuel', debut: '2023-03-01' }).select().single()
    await regleLHeure('2026-10-15T12:00:00+02:00')
    const { error } = await f.client.from('charge').update({ libelle: 'Ancienne, renommée' })
      .eq('id', c!.id).select()
    expect(error).toBeNull()
  })
})
