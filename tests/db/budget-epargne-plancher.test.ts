/**
 * On ne retire pas de l'épargne plus que ce qu'on y a versé.
 *
 * Trouvé au grand test : « Je retire 100 000 € » sur 380 € versés laissait la poche à
 * −99 620 €. L'écran le refuse ; la base, elle, ne l'empêchait pas : un appel REST direct
 * passait.
 */
import { afterAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { regleLHeure, remetLHeure } from './helpers/horloge'
import { clore, foyerDOctobre, foyerSolo, membre, ou } from './helpers/budget'

async function unePoche(foyerId: string) {
  return (ou(await admin().from('poche_epargne').insert({
    household_id: foyerId, libelle: 'Urgence', genre: 'urgence' }).select().single()) as { id: string }).id
}
const ecrit = (f: { client: ReturnType<typeof admin>; householdId: string }, uid: string,
               poche: string, cents: number, motif: string) =>
  f.client.from('versement_epargne').insert({
    household_id: f.householdId, poche_id: poche, user_profile_id: uid, montant_cents: cents, motif })
const solde = async (poche: string, uid: string) =>
  ((ou(await admin().from('versement_epargne').select('montant_cents')
    .eq('poche_id', poche).eq('user_profile_id', uid)) as { montant_cents: number }[])
    .reduce((s, v) => s + v.montant_cents, 0))

afterAll(remetLHeure)

describe('le plancher de l’épargne', () => {
  it('un retrait va jusqu’au dernier centime versé, jamais au-delà', async () => {
    const f = await foyerSolo('plancher-solo')
    const poche = await unePoche(f.householdId)
    ou(await ecrit(f, f.userId, poche, 38_000, 'mensuel').select())
    ou(await ecrit(f, f.userId, poche, -3_000, 'retrait').select())
    const { error } = await ecrit(f, f.userId, poche, -35_001, 'retrait')
    expect(error?.message, 'un retrait de trop est passé').toBe(
      'Tu n’as versé que 350 € ici : tu ne peux pas en retirer plus.')
    expect(await solde(poche, f.userId), 'le refus a laissé une trace').toBe(35_000)
    ou(await ecrit(f, f.userId, poche, -35_000, 'retrait').select())
    expect(await solde(poche, f.userId)).toBe(0)
    expect((await ecrit(f, f.userId, poche, -1, 'retrait')).error, 'un centime sous zéro').not.toBeNull()
  })

  it('l’argent d’un autre n’est pas le sien, et la clé de service n’y échappe pas', async () => {
    const f = await foyerSolo('plancher-duo')
    const thauba = await membre(f, 'Thauba', { revenu: 200_000 })
    const poche = await unePoche(f.householdId)
    ou(await ecrit(f, f.userId, poche, 38_000, 'mensuel').select())
    // Kamil a versé 380 € : Thauba, qui n'a rien versé, ne retire rien.
    const sienne = await ecrit({ client: thauba.client, householdId: f.householdId },
                               thauba.userId, poche, -100, 'retrait')
    expect(sienne.error, 'Thauba a retiré l’argent de Kamil').not.toBeNull()
    const service = await admin().from('versement_epargne').insert({
      household_id: f.householdId, poche_id: poche, user_profile_id: f.userId,
      montant_cents: -10_000_000, motif: 'retrait' })
    expect(service.error, 'la clé de service a creusé la poche').not.toBeNull()
    expect(await solde(poche, f.userId)).toBe(38_000)
  })

  it('un versement positif passe toujours, même sur un solde hérité négatif', async () => {
    const f = await foyerSolo('plancher-herite')
    const poche = await unePoche(f.householdId)
    // Un solde négatif d'avant le plancher : posé en désactivant le déclencheur le temps d'une écriture.
    const c = await (await import('./helpers/pg')).connexion()
    try {
      await c.query('alter table public.versement_epargne disable trigger tg_versement_plancher')
      await c.query(`insert into public.versement_epargne
        (household_id, poche_id, user_profile_id, montant_cents, motif) values ($1,$2,$3,-500,'retrait')`,
        [f.householdId, poche, f.userId])
    } finally {
      await c.query('alter table public.versement_epargne enable trigger tg_versement_plancher')
      await c.end()
    }
    ou(await ecrit(f, f.userId, poche, 1_000, 'mensuel').select())
    expect(await solde(poche, f.userId)).toBe(500)
  })

  it('un versement ne se réécrit pas, et ne se supprime pas quand des retraits l’ont entamé', async () => {
    const f = await foyerSolo('plancher-update-delete')
    const poche = await unePoche(f.householdId)
    const v1 = ou(await ecrit(f, f.userId, poche, 38_000, 'mensuel').select().single()) as { id: string }
    const v2 = ou(await ecrit(f, f.userId, poche, 10_000, 'mensuel').select().single()) as { id: string }
    ou(await ecrit(f, f.userId, poche, -30_000, 'retrait').select())
    // Réécrire le montant : refusé (c'était le contournement par PATCH).
    const patch = await f.client.from('versement_epargne').update({ montant_cents: -9_999_999 })
      .eq('id', v1.id).select()
    expect(patch.error?.message, 'un PATCH a creusé la poche').toContain('ne se modifie pas')
    // Une date, elle, se corrige.
    ou(await f.client.from('versement_epargne').update({ fait_le: '2026-10-01' }).eq('id', v2.id).select())
    // 380 + 100 − 300 = 180 : supprimer les 100 laisse 80, supprimer les 380 laisserait −200.
    const sans380 = await f.client.from('versement_epargne').delete().eq('id', v1.id).select()
    expect(sans380.error?.message, 'un versement entamé s’est effacé').toContain('ne peut plus s’annuler')
    ou(await f.client.from('versement_epargne').delete().eq('id', v2.id).select())
    expect(await solde(poche, f.userId)).toBe(8_000)
  })

  it('« Revenir dessus » est refusé quand on a retiré de la poche depuis la clôture', async () => {
    await regleLHeure('2026-11-10T12:00:00+01:00')
    const { f, poche } = await foyerDOctobre('plancher-rouvre')
    ou(await clore(f, { poche }))
    ou(await ecrit(f, f.userId, poche, -10_000, 'retrait').select())
    const { error } = await f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' })
    expect(error?.message, 'la réouverture a laissé la poche en négatif')
      .toBe('Tu as retiré 100 € de cette poche depuis : ce versement ne peut plus s’annuler.')
    expect((await admin().from('cloture').select('id').eq('household_id', f.householdId)).data)
      .toHaveLength(1)
  })

  it('supprimer une poche emporte ses versements, retraits compris', async () => {
    const f = await foyerSolo('plancher-cascade')
    const poche = await unePoche(f.householdId)
    ou(await ecrit(f, f.userId, poche, 38_000, 'mensuel').select())
    ou(await ecrit(f, f.userId, poche, -30_000, 'retrait').select())
    ou(await admin().from('poche_epargne').delete().eq('id', poche).select())
    expect((await admin().from('versement_epargne').select('id').eq('poche_id', poche)).data).toEqual([])
  })

  it('un foyer étranger ne lit pas un solde dans le message d’erreur', async () => {
    const a = await foyerSolo('plancher-etranger-a')
    const b = await foyerSolo('plancher-etranger-b')
    const pocheDeB = await unePoche(b.householdId)
    ou(await ecrit(b, b.userId, pocheDeB, 38_000, 'mensuel').select())
    const { error } = await a.client.from('versement_epargne').insert({
      household_id: b.householdId, poche_id: pocheDeB, user_profile_id: b.userId,
      montant_cents: -10_000_000, motif: 'retrait' })
    expect(error, 'un client a écrit dans un autre foyer').not.toBeNull()
    expect(error!.message, 'le solde d’un autre foyer a fuité').not.toMatch(/versé/)
  })
})
