/**
 * Les factures des charges mises de côté (D77).
 *
 * Chaque facture s'ajoute au total payé de l'année, qu'on compare au prévu de
 * l'année entière sur les mois suivis. Au-dessus, le dépassement s'ajoute tout
 * de suite au mois en cours ; en dessous, rien ne bouge avant la clôture de
 * décembre. Les chiffres sont ceux du tableau du § 4.4.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { ajustementEnAdmin, ajustements, foyerSolo, membre, ou, ouvreLAnnee, poseCharge,
         soldeEnAdmin, type Foyer } from './helpers/budget'
import { connexion } from './helpers/pg'
import { regleLHeure, remetLHeure } from './helpers/horloge'

beforeAll(() => regleLHeure('2026-11-10T12:00:00+01:00'))
afterAll(remetLHeure)

/** Le foyer de Kamil : revenu depuis septembre 2026, l'Entretien et ses douze lignes. */
async function avecEntretien(nom: string) {
  const f = await foyerSolo(nom)
  const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                          mode: 'mis_de_cote', categorie: 'auto' })
  await ouvreLAnnee(f, entretien, 2026)
  return { f, entretien }
}

const paie = (f: Foyer, charge: string, cents: number, payeLe: string, id = randomUUID()) =>
  f.client.rpc('paie_une_facture',
    { la_facture: id, la_charge: charge, montant_cents: cents, paye_le: payeLe })

const montants = async (charge: string) =>
  (await ajustements(charge)).map(l => [l.mois, l.montant_cents, l.libelle])

describe('payer une facture', () => {
  it('sous le prévu : aucune ligne', async () => {
    const { f, entretien } = await avecEntretien('fac-sous')
    expect((await paie(f, entretien, 10_000, '2026-11-10')).error).toBeNull()
    expect(await montants(entretien)).toEqual([])
    const etat = ou(await f.client.rpc('etat_de_l_annee', { la_charge: entretien, annee: 2026 }))
    expect(etat).toMatchObject({ b: 10_000, pl: 16_668, pose: 0 })
  })

  it('320 € en novembre : +153,32 € sur novembre, tout de suite', async () => {
    const { f, entretien } = await avecEntretien('fac-320')
    expect((await paie(f, entretien, 32_000, '2026-11-10')).error).toBeNull()
    expect(await montants(entretien))
      .toEqual([['2026-11-01', 15_332, 'Entretien auto — facture 2026']])
  })

  it('600 € en novembre : +433,32 €', async () => {
    const { f, entretien } = await avecEntretien('fac-600')
    ou(await paie(f, entretien, 60_000, '2026-11-10'))
    expect((await montants(entretien)).map(m => m[1])).toEqual([43_332])
  })

  it('une seconde facture ne pose que le delta ; la retirer pose le contre-ajustement', async () => {
    const { f, entretien } = await avecEntretien('fac-delta')
    ou(await paie(f, entretien, 32_000, '2026-11-10'))
    const seconde = randomUUID()
    ou(await paie(f, entretien, 10_000, '2026-11-09', seconde))
    expect((await montants(entretien)).map(m => m[1])).toEqual([15_332, 10_000])
    ou(await f.client.rpc('retire_une_facture', { la_facture: seconde }))
    expect((await montants(entretien)).map(m => m[1])).toEqual([15_332, 10_000, -10_000])
  })

  it('deux appels parallèles : le bon total, et une ligne par delta', async () => {
    const { f, entretien } = await avecEntretien('fac-paralleles')
    const [a, b] = await Promise.all([
      paie(f, entretien, 20_000, '2026-11-10'), paie(f, entretien, 20_000, '2026-11-10')])
    expect(a.error).toBeNull()
    expect(b.error).toBeNull()
    const poses = (await montants(entretien)).map(m => m[1] as number)
    expect(poses).toHaveLength(2)
    expect(poses.reduce((s, x) => s + x, 0)).toBe(40_000 - 16_668)
  })

  it('le même identifiant deux fois ne crée rien', async () => {
    const { f, entretien } = await avecEntretien('fac-meme-id')
    const id = randomUUID()
    expect(ou(await paie(f, entretien, 32_000, '2026-11-10', id))).toBe(id)
    expect(ou(await paie(f, entretien, 32_000, '2026-11-10', id))).toBe(id)
    const { data } = await admin().from('facture').select('id').eq('charge_id', entretien)
    expect(data).toHaveLength(1)
    expect(await montants(entretien)).toHaveLength(1)
  })

  it('une charge au nom très long se solde quand même : le libellé de l’ajustement tient en 80', async () => {
    /* `depense_libelle_check` s'arrête à 80 caractères (0084). Le suffixe « — facture
       2026 » en fait 15 : le nom est coupé à 55, sans quoi la facture d'une charge
       nommée sur 70 caractères échouerait sur une erreur brute. */
    const nom = 'Entretien de la voiture familiale, '.padEnd(70, 'pneus et freins, ')
    expect(nom).toHaveLength(70)
    const f = await foyerSolo('fac-nom-long')
    const entretien = await poseCharge(f, { libelle: nom, cents: 50_004, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, entretien, 2026)
    ou(await paie(f, entretien, 32_000, '2026-11-10'))
    const [aj] = await ajustements(entretien)
    expect(aj.montant_cents).toBe(15_332)
    expect(aj.libelle).toHaveLength(70)
    expect(aj.libelle).toBe(`${nom.slice(0, 55)} — facture 2026`)
  })

  it('une charge qui n’est pas mise de côté ne prend pas de facture', async () => {
    const f = await foyerSolo('fac-fixe')
    const internet = await poseCharge(f, { libelle: 'Internet', cents: 3_700 })
    expect((await paie(f, internet, 3_700, '2026-11-10')).error?.message)
      .toMatch(/facture par facture/)
  })
})

describe('les dates et les mois suivis', () => {
  it('refuse un mois que Popote ne suivait pas, et le mois en cours sans revenu', async () => {
    const { f, entretien } = await avecEntretien('fac-non-suivi')
    expect((await paie(f, entretien, 5_000, '2026-03-10')).error?.message)
      .toMatch(/Popote ne suivait pas encore mars 2026/)
    const sans = await foyerSolo('fac-sans-revenu', { revenu: null })
    const c = await poseCharge(sans, { libelle: 'Entretien', cents: 50_004, mode: 'mis_de_cote' })
    expect((await paie(sans, c, 32_000, '2026-11-10')).error?.message)
      .toMatch(/Ajoute ton revenu d'abord/)
  })

  it('refuse avant le 1er janvier de l’année précédente, et demain', async () => {
    const { f, entretien } = await avecEntretien('fac-bornes')
    expect((await paie(f, entretien, 5_000, '2024-12-31')).error?.message).toMatch(/01\/01\/2025/)
    expect((await paie(f, entretien, 5_000, '2026-11-11')).error?.message).toMatch(/01\/01\/2025/)
  })

  it('à 0 h 30, heure de Paris, « aujourd’hui » passe', async () => {
    const { f, entretien } = await avecEntretien('fac-minuit')
    await regleLHeure('2026-11-30T23:30:00Z')
    expect((await paie(f, entretien, 5_000, '2026-12-01')).error).toBeNull()
    await regleLHeure('2026-11-10T12:00:00+01:00')
  })

  it('changer un revenu ne pose rien', async () => {
    const { f, entretien } = await avecEntretien('fac-revenu')
    ou(await paie(f, entretien, 32_000, '2026-11-10'))
    ou(await f.client.from('revenu').insert({ household_id: f.householdId,
      user_profile_id: f.userId, net_mensuel_cents: 450_000, valid_from: '2026-11-01' }).select())
    expect(await montants(entretien)).toHaveLength(1)
  })
})

describe('une année soldée', () => {
  it('un relevé se corrige, il ne se retire pas ; son prévu figé ne bouge pas', async () => {
    const f = await foyerSolo('fac-releve')
    const taxe = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000,
                                       mode: 'mis_de_cote', commun: true })
    await ouvreLAnnee(f, taxe, 2026)
    await soldeEnAdmin(f, taxe, 2026, { reel: 145_000, prevu: 144_996 })
    await ajustementEnAdmin(f, taxe, '2026-09-01', 2026, 4)
    const releve = (ou(await admin().from('facture').select('id').eq('charge_id', taxe)
      .eq('origine', 'releve').single()) as { id: string }).id

    expect((await f.client.rpc('retire_une_facture', { la_facture: releve })).error?.message)
      .toMatch(/Un relevé se corrige, il ne se retire pas/)
    ou(await f.client.rpc('corrige_le_releve', { la_facture: releve, montant_cents: 146_000 }))
    expect((await montants(taxe)).map(m => [m[1], m[2]]))
      .toEqual([[4, 'Ajustement'], [1_000, 'Taxe foncière — solde 2026']])
    const { data } = await admin().from('releve_annuel')
      .select('reel_cents, prevu_cents, ecart_cents').eq('charge_id', taxe).single()
    expect(data).toEqual({ reel_cents: 146_000, prevu_cents: 144_996, ecart_cents: 1_004 })
  })

  it('l’appel d’un trimestre saisi après le relevé de la copro s’ajoute en entier', async () => {
    const f = await foyerSolo('fac-copro')
    const copro = await poseCharge(f, { libelle: 'Charges de copropriété', cents: 30_000,
                                        mode: 'mis_de_cote', periodicite: 'trimestriel' })
    await ouvreLAnnee(f, copro, 2026)
    await soldeEnAdmin(f, copro, 2026, { reel: 120_000, prevu: 120_000 })
    ou(await paie(f, copro, 30_000, '2026-11-05'))
    expect((await montants(copro)).map(m => m[1])).toEqual([30_000])
  })

  it('soldée à 0, elle ne rend rien de plus : seule la facture nouvelle compte', async () => {
    await regleLHeure('2027-01-15T12:00:00+01:00')
    const { f, entretien } = await avecEntretien('fac-soldee-zero')
    await soldeEnAdmin(f, entretien, 2026, { reel: 0, prevu: 16_668 })
    ou(await admin().from('facture').delete().eq('charge_id', entretien).select())
    await ajustementEnAdmin(f, entretien, '2026-12-01', 2026, -16_668, 'Entretien auto — solde 2026')
    ou(await paie(f, entretien, 5_000, '2026-12-20'))
    expect((await montants(entretien)).map(m => [m[0], m[1]]))
      .toEqual([['2026-12-01', -16_668], ['2027-01-01', 5_000]])
    await regleLHeure('2026-11-10T12:00:00+01:00')
  })
})

/**
 * Les parts d'un ajustement : `recale_l_annee` et `pose_les_parts` (0105). Un foyer
 * à deux, où chacun a porté une provision différente : l'écart se partage selon ce
 * que chacun a porté, au plus fort reste, et la somme des parts vaut le montant
 * au centime. Un test à un seul membre ne voit rien : sa part est toujours le tout.
 */
describe('les parts d’un ajustement, à deux', () => {
  type Part = { user_profile_id: string; part_cents: number; part_bps: number }
  const partsDe = async (ligneId: string) =>
    ou(await admin().from('depense_part').select('user_profile_id, part_cents, part_bps')
      .eq('depense_id', ligneId)) as Part[]
  const portes = async (charge: string) => {
    const lignes = ou(await admin().from('depense')
      .select('mois, depense_part(user_profile_id, part_cents)')
      .eq('charge_id', charge).eq('source', 'modele')) as
      { mois: string; depense_part: { user_profile_id: string; part_cents: number }[] }[]
    const m = new Map<string, number>()
    // Les mois suivis seuls : les revenus datent de septembre.
    for (const l of lignes.filter(l => l.mois >= '2026-09-01'))
      for (const p of l.depense_part) m.set(p.user_profile_id, (m.get(p.user_profile_id) ?? 0) + p.part_cents)
    return m
  }

  async function aDeux(nom: string) {
    const f = await foyerSolo(nom, { revenu: 300_000 })
    const g = await membre(f, `${nom}-g`, { revenu: 150_000, arrivee: '2026-09-01' })
    const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
      mode: 'mis_de_cote', commun: true, participants: [f.userId, g.userId] })
    await ouvreLAnnee(f, entretien, 2026)
    return { f, g, entretien }
  }

  it('600 € : 433,32 € partagés selon ce que chacun a porté, la somme au centime', async () => {
    const { f, g, entretien } = await aDeux('fac-duo')
    const porte = await portes(entretien)
    expect(porte.size).toBe(2)
    expect(new Set(porte.values()).size, 'deux portées différentes, sinon le test ne prouve rien').toBe(2)
    expect([...porte.values()].reduce((s, x) => s + x, 0), 'L de septembre à décembre').toBe(16_668)

    ou(await paie(f, entretien, 60_000, '2026-11-10'))
    const [aj] = await ajustements(entretien)
    expect(aj.montant_cents).toBe(43_332)
    const parts = await partsDe(aj.id)
    expect(parts).toHaveLength(2)
    expect(parts.reduce((s, p) => s + p.part_cents, 0)).toBe(43_332)
    expect(parts.reduce((s, p) => s + p.part_bps, 0)).toBe(10_000)
    for (const p of parts) {
      const attendu = 43_332 * porte.get(p.user_profile_id)! / 16_668
      expect(Math.abs(p.part_cents - attendu), `part de ${p.user_profile_id}`).toBeLessThan(1)
    }
    expect(new Set(parts.map(p => p.user_profile_id))).toEqual(new Set([f.userId, g.userId]))
  })

  it('retirer la facture : le contre-ajustement se partage de même, en négatif', async () => {
    const { f, entretien } = await aDeux('fac-duo-retrait')
    const id = randomUUID()
    ou(await paie(f, entretien, 60_000, '2026-11-10', id))
    ou(await f.client.rpc('retire_une_facture', { la_facture: id }))
    const lignes = await ajustements(entretien)
    expect(lignes.map(l => l.montant_cents)).toEqual([43_332, -43_332])
    const [pose, contre] = await Promise.all(lignes.map(l => partsDe(l.id)))
    const parUser = (ps: Part[]) => new Map(ps.map(p => [p.user_profile_id, p.part_cents]))
    // Mêmes poids, mêmes départages : le contre-ajustement annule chaque part.
    for (const [u, c] of parUser(pose)) expect(parUser(contre).get(u)).toBe(-c)
  })

  it('à deux, le dépassement se répartit selon ce que chacun a porté sur l’année', async () => {
    const f = await foyerSolo('fac-porte', { revenu: 370_000 })
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-11-01', revenu: 240_000,
                                               depuis: '2026-11-01' })
    const e = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004, mode: 'mis_de_cote',
      commun: true, participants: [f.userId, thauba.userId] })
    await ouvreLAnnee(f, e, 2026)
    const porte = await portes(e)
    const total = [...porte.values()].reduce((s, x) => s + x, 0)
    ou(await paie(f, e, 32_000, '2026-11-10'))
    const [aj] = await ajustements(e)
    expect(aj.montant_cents).toBe(15_332)
    const parts = await partsDe(aj.id)
    expect(parts.reduce((s, p) => s + p.part_cents, 0)).toBe(15_332)
    const sienne = parts.find(p => p.user_profile_id === thauba.userId)!.part_cents
    // Elle n'a porté que novembre et décembre, au prorata : bien moins d'un quart.
    expect(sienne).toBeGreaterThan(0)
    expect(sienne).toBeLessThan(15_332 / 4)
    // Et au centime près ce qu'elle a porté sur l'année, pas une clé fraîche du jour.
    expect(Math.abs(sienne - 15_332 * porte.get(thauba.userId)! / total)).toBeLessThan(1)
  })

  it('l’état de l’année suit : ce qui est posé vaut le dépassement', async () => {
    const { f, entretien } = await aDeux('fac-duo-etat')
    ou(await paie(f, entretien, 60_000, '2026-11-10'))
    const etat = ou(await f.client.rpc('etat_de_l_annee', { la_charge: entretien, annee: 2026 }))
    expect(etat).toMatchObject({ b: 60_000, pl: 16_668, pose: 43_332 })
  })
})

describe('recaler une charge (interne)', () => {
  it('pose ce qui manque sur chaque année ouverte, et laisse l’année soldée', async () => {
    const f = await foyerSolo('fac-recale-la-charge')
    const ouverte = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, ouverte, 2026)
    const soldee = await poseCharge(f, { libelle: 'Taxe foncière', cents: 145_000, mode: 'mis_de_cote' })
    await ouvreLAnnee(f, soldee, 2026)
    await soldeEnAdmin(f, soldee, 2026, { reel: 145_000, prevu: 144_996 })
    // Une facture écrite sans recalage : c'est l'état où `retire_charge` appelle la fonction.
    ou(await admin().from('facture').insert({ id: randomUUID(), household_id: f.householdId,
      charge_id: ouverte, annee: 2026, paye_le: '2026-11-05', montant_cents: 32_000,
      origine: 'saisie', saisi_par: f.userId }).select())
    expect(await montants(ouverte)).toEqual([])

    const c = await connexion()
    try {
      await c.query('select public.recale_la_charge($1)', [ouverte])
      await c.query('select public.recale_la_charge($1)', [soldee])
      await c.query('select public.recale_la_charge($1)', [ouverte])   // idempotente
    } finally { await c.end() }
    expect(await montants(ouverte))
      .toEqual([['2026-11-01', 15_332, 'Entretien auto — facture 2026']])
    expect(await montants(soldee)).toEqual([])
  })

  it('reste fermée au client', async () => {
    const { f, entretien } = await avecEntretien('fac-recale-ferme')
    expect((await f.client.rpc('recale_la_charge', { la_charge: entretien })).error).not.toBeNull()
  })
})
