/**
 * Les arrivées : le premier revenu, la date d'entrée.
 *
 * Thauba arrive le 15/11 et pose son revenu le 02/12. Sans la règle du premier
 * revenu, novembre n'aurait jamais de revenu pour elle, et la garde de la
 * clôture l'attendrait pour toujours.
 */
import { afterAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
import { connexion } from './helpers/pg'
import { clos, foyerSolo, ligne, membre, ou, ouvre, poseCharge } from './helpers/budget'
import { regleLHeure, remetLHeure } from './helpers/horloge'

afterAll(remetLHeure)

const revenus = async (qui: string) => (ou(await admin().from('revenu')
  .select('valid_from').eq('user_profile_id', qui).order('valid_from')) as
  { valid_from: string }[]).map(r => r.valid_from)

describe('le premier revenu d’un membre compte dès son arrivée', () => {
  it('Thauba arrivée le 15/11, revenu posé le 02/12 : il vaut dès novembre', async () => {
    await regleLHeure('2026-12-02T10:00:00+01:00')
    const f = await foyerSolo('premier-revenu')
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-11-15' })
    ou(await thauba.client.from('revenu').insert({
      household_id: f.householdId, user_profile_id: thauba.userId,
      net_mensuel_cents: 240_000, valid_from: '2026-12-01' }).select())
    expect(await revenus(thauba.userId)).toEqual(['2026-11-01'])

    // Le suivant prend effet au mois de sa saisie.
    ou(await thauba.client.from('revenu').insert({
      household_id: f.householdId, user_profile_id: thauba.userId,
      net_mensuel_cents: 250_000, valid_from: '2027-01-01' }).select())
    expect(await revenus(thauba.userId)).toEqual(['2026-11-01', '2027-01-01'])
  })

  it('sans passer avant le mois qui suit la dernière clôture du foyer', async () => {
    await regleLHeure('2027-01-05T10:00:00+01:00')
    const f = await foyerSolo('premier-revenu-clos')
    await clos(f, '2026-11-01')
    const elle = await membre(f, 'Elle', { arrivee: '2026-10-10' })
    ou(await elle.client.from('revenu').insert({
      household_id: f.householdId, user_profile_id: elle.userId,
      net_mensuel_cents: 200_000, valid_from: '2027-01-01' }).select())
    expect(await revenus(elle.userId)).toEqual(['2026-12-01'])
  })
})

describe('changer sa date d’arrivée', () => {
  it('ne refige que les mois entre les deux dates', async () => {
    await regleLHeure('2026-11-05T10:00:00+01:00')
    const f = await foyerSolo('entre-le', { revenu: 370_000, depuis: '2026-01-01' })
    const thauba = await membre(f, 'Thauba', { revenu: 240_000, depuis: '2026-01-01' })
    const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 167_853, commun: true,
                                        participants: [f.userId, thauba.userId] })
    await ouvre(f, '2026-10-01')
    // Thauba part le 03/11 : ses parts d'octobre sont un fait, elles restent.
    ou(await admin().from('user_profile').delete().eq('id', thauba.userId).select())
    const avant = (await ligne(loyer, '2026-10-01'))!.depense_part.map(p => p.part_cents).sort()
    expect(avant).toHaveLength(2)

    ou(await f.client.from('user_profile').update({ entre_le: '2026-01-15' })
      .eq('id', f.userId).select())
    const apres = (await ligne(loyer, '2026-10-01'))!.depense_part.map(p => p.part_cents).sort()
    expect(apres, 'octobre a été repartagé sur Kamil seul').toEqual(avant)
  })

  it('reculer sa date d’arrivée après avoir posé son premier revenu : le revenu recule avec elle',
    async () => {
      await regleLHeure('2026-11-05T10:00:00+01:00')
      const f = await foyerSolo('entre-le-recule', { revenu: 370_000, depuis: '2026-01-01' })
      const thauba = await membre(f, 'Thauba', { arrivee: '2026-10-01', revenu: 200_000,
                                                 depuis: '2026-10-01' })
      const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 167_853, commun: true,
                                          participants: [f.userId, thauba.userId] })
      await ouvre(f, '2026-09-01')
      await ouvre(f, '2026-10-01')
      expect((await ligne(loyer, '2026-09-01'))!.depense_part, 'septembre : Kamil seul').toHaveLength(1)

      // Elle corrige son arrivée : elle était là dès septembre.
      ou(await thauba.client.from('user_profile').update({ entre_le: '2026-09-01' })
        .eq('id', thauba.userId).select())

      /* Sans cela son premier revenu restait à octobre : septembre se partageait
         50/50 faute de revenu, et la clôture refusait (« Thauba n'a pas encore posé
         son revenu : septembre attend »), sans que rien, à l'écran, permette de le poser. */
      expect(await revenus(thauba.userId)).toEqual(['2026-09-01', '2026-10-01'])
      const parts = (await ligne(loyer, '2026-09-01'))!.depense_part.map(p => p.part_cents)
      expect(parts, 'septembre se partage à parts égales : le revenu n’a pas suivi')
        .not.toEqual([83_926, 83_927])
      expect(parts.reduce((a, b) => a + b, 0)).toBe(167_853)
      await clos(f, '2026-09-01')
    })

  it('un revenu posé bien après l’arrivée reste où il est : celui de Kamil, depuis septembre',
    async () => {
      await regleLHeure('2026-11-05T10:00:00+01:00')
      // Arrivée en janvier, revenu depuis septembre : la base réelle de Kamil.
      const f = await foyerSolo('entre-le-kamil', { revenu: 432_500, depuis: '2026-09-01',
                                                    arrivee: '2026-01-01' })
      ou(await f.client.from('user_profile').update({ entre_le: '2025-06-01' })
        .eq('id', f.userId).select())
      expect(await revenus(f.userId), 'corriger son arrivée a rendu suivis des mois d’avant septembre')
        .toEqual(['2026-09-01'])
    })

  it('sans jeton de personne (réparation en SQL), l’histoire des revenus ne se réécrit pas',
    async () => {
      await regleLHeure('2026-11-05T10:00:00+01:00')
      const f = await foyerSolo('entre-le-sql', { revenu: 370_000, depuis: '2026-01-01' })
      const thauba = await membre(f, 'Thauba', { arrivee: '2026-10-01', revenu: 200_000,
                                                 depuis: '2026-10-01' })
      const c = await connexion()
      try {
        // Le propriétaire, sans claims : `security definer` ne dit rien de l'appelant.
        await c.query('update public.user_profile set entre_le = $2 where id = $1',
                      [thauba.userId, '2026-09-01'])
      } finally { await c.end() }
      expect(await revenus(thauba.userId)).toEqual(['2026-10-01'])
    })

  it('traverse plusieurs mois : refige juillet à septembre, et pas octobre', async () => {
    await regleLHeure('2026-11-05T10:00:00+01:00')
    const f = await foyerSolo('entre-le-mois', { revenu: 370_000, depuis: '2026-01-01' })
    const thauba = await membre(f, 'Thauba', { arrivee: '2026-07-10', revenu: 240_000,
                                               depuis: '2026-01-01' })
    const loyer = await poseCharge(f, { libelle: 'Loyer', cents: 167_853, commun: true,
                                        participants: [f.userId, thauba.userId] })
    for (const m of ['2026-07-01', '2026-08-01', '2026-09-01', '2026-10-01']) {
      await ouvre(f, m)
    }
    // Juillet à octobre : eux deux.
    expect((await ligne(loyer, '2026-08-01'))!.depense_part).toHaveLength(2)
    /* Un centime d'écart posé à la main sur octobre, hors de l'intervalle : un
       refige le remettrait à la valeur calculée, et on le verrait. */
    const marque = async (mois: string) => {
      const l = (await ligne(loyer, mois))!
      const [premier, second] = l.depense_part
      const c = await connexion()
      try {
        // Une part ne se retouche pas : on la supprime et on la repose, dans la même transaction.
        await c.query('begin')
        await c.query('delete from public.depense_part where depense_id = $1', [l.id])
        for (const [p, delta] of [[premier, 1], [second, -1]] as const) {
          await c.query(`insert into public.depense_part
              (depense_id, user_profile_id, household_id, part_cents, part_bps)
            values ($1, $2, $3, $4, 5000)`,
            [l.id, p.user_profile_id, f.householdId, p.part_cents + delta])
        }
        await c.query('commit')
      } finally { await c.end() }
    }
    const lues = async (mois: string) =>
      (await ligne(loyer, mois))!.depense_part.map(p => `${p.user_profile_id}:${p.part_cents}`).sort()
    await marque('2026-10-01')
    const octobre = await lues('2026-10-01')

    // Thauba n'est arrivée que le 15/09 : juillet et août la perdent, septembre la garde.
    ou(await admin().from('user_profile').update({ entre_le: '2026-09-15' })
      .eq('id', thauba.userId).select())
    expect((await ligne(loyer, '2026-07-01'))!.depense_part, 'juillet n’a pas été refigé')
      .toHaveLength(1)
    expect((await ligne(loyer, '2026-08-01'))!.depense_part, 'août n’a pas été refigé')
      .toHaveLength(1)
    expect((await ligne(loyer, '2026-09-01'))!.depense_part).toHaveLength(2)
    expect(await lues('2026-10-01'), 'octobre, après l’intervalle, a été refigé').toEqual(octobre)
  })
})
