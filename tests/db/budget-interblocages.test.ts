/**
 * Les interblocages (§ 4.5, § 8).
 *
 * Chaque banc TIENT une transaction ouverte, lance l'autre geste, vérifie qu'il
 * attend, relâche, et exige qu'aucun `deadlock detected` (40P01) ne tombe. Les
 * deux premiers cas ont été reproduits le 01/10 sur une base jetable.
 */
import { randomUUID } from 'node:crypto'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { admin, type Actor } from './helpers/db'
import { ajustements, clore, declare, foyerDOctobre, foyerSolo, ligne, membre, ou, ouvreLAnnee,
         poseCharge, type Foyer } from './helpers/budget'
import { attends, commeLui, connexion, suivie } from './helpers/pg'
import { regleLHeure, remetLHeure } from './helpers/horloge'

const ouvertes: pg.Client[] = []
beforeAll(() => regleLHeure('2026-11-01T10:00:00+01:00'))
afterAll(async () => {
  for (const c of ouvertes) await c.end().catch(() => {})
  await remetLHeure()
})

/** Une transaction ouverte, comme ce membre. */
async function session(qui: Actor) {
  const c = await connexion()
  ouvertes.push(c)
  await commeLui(c, qui.userId)
  return c
}
/** Prendre le verrou comme le client le prend : une écriture sur son propre profil. */
const tient = (c: pg.Client, qui: Actor) =>
  c.query('update public.user_profile set display_name = display_name where id = $1', [qui.userId])

/** Un compte d'authentification sans profil : l'arrivée viendra après. */
async function compte(nom: string) {
  const u = ou(await admin().auth.admin.createUser({
    email: `${nom}-${randomUUID()}@test.local`, password: 'test-password-12345',
    email_confirm: true }))
  return u.user!.id
}
/** L'arrivée d'un membre comme l'invitation la fait : par la clé de service. */
const arrive = (f: Foyer, uid: string) => admin().from('user_profile').insert({
  id: uid, household_id: f.householdId, display_name: 'Thauba', entre_le: '2026-01-01' }).select()

async function avecEntretien(nom: string) {
  const f = await foyerSolo(nom)
  const entretien = await poseCharge(f, { libelle: 'Entretien auto', cents: 50_004,
                                          mode: 'mis_de_cote', commun: true })
  await ouvreLAnnee(f, entretien, 2026)
  return { f, entretien }
}

/**
 * Joue `un_banc` avec l'horloge réglée à 5 s de minuit, puis la remet à
 * l'heure ordinaire du fichier, que le banc réussisse ou non : un banc qui
 * meurt à 23 h 59 fausserait tous les suivants.
 *
 * Les attentes qui y passent minuit durent moins de 8 s : `authenticated` et
 * `authenticator` ont un `statement_timeout` de 8 s, et une requête qui attend
 * le verrou plus longtemps tombe en erreur au lieu de passer minuit.
 */
async function avantMinuit(un_banc: () => Promise<void>) {
  await regleLHeure('2026-10-31T23:59:55+01:00')
  try { await un_banc() } finally { await regleLHeure('2026-11-01T10:00:00+01:00') }
}

describe('l’arrivée d’un membre', () => {
  // Le verrou de tg_entre_le_refige (0103) suffit à ce cas : retirer celui de
  // tg_membre_rejoint_les_communes ne le fait pas rougir, voir le cas du retrait.
  it('par la clé de service, elle attend le verrou de SON foyer', async () => {
    const f = await foyerSolo('ib-arrivee')
    const uid = await compte('ib-arrivee')
    const s1 = await session(f)
    await tient(s1, f)
    const a = suivie(arrive(f, uid))
    await attends(800)
    expect(a.fini, 'l’arrivée n’a pas attendu le verrou').toBe(false)
    await s1.query('commit')
    expect((await a.p).error).toBeNull()
  })

  it('pendant une facture : pas d’interblocage', async () => {
    const { f, entretien } = await avecEntretien('ib-facture')
    const uid = await compte('ib-facture')
    const s1 = await session(f)
    await s1.query(`select public.paie_une_facture($1, $2, 32000, '2026-10-20')`,
      [randomUUID(), entretien])
    const a = suivie(arrive(f, uid))
    await attends(800)
    expect(a.fini).toBe(false)
    await s1.query('commit')
    expect((await a.p).error).toBeNull()
  })

  // Mutation : dans tg_membre_rejoint_les_communes (0103), déplacer le verrou
  // APRÈS l'insertion dans charge_participant. Seul ce cas rougit : sans charge
  // commune, l'insertion ne tient rien, et le premier cas passe encore.
  it('pendant le retrait d’une charge commune : pas d’interblocage', async () => {
    const { f, id } = await foyerDOctobre('ib-retrait')
    const uid = await compte('ib-retrait')
    const s1 = await session(f)
    await tient(s1, f)
    const a = suivie(arrive(f, uid))
    await attends(800)
    expect(a.fini).toBe(false)
    await s1.query('select public.retire_charge($1, true)', [id.restaurants])
    await s1.query('commit')
    expect((await a.p).error).toBeNull()
  })
})

describe('une saisie', () => {
  // Mutation : supprimer le trigger d'instruction `a_verrou_du_foyer` de `saisie` (0097).
  it('supprimée pendant une correction qui cascade sur elle : pas d’interblocage', async () => {
    const { f, id } = await foyerDOctobre('ib-saisie')
    const s = randomUUID()
    ou(await declare(f, (await ligne(id.courses, '2026-10-01'))!.id, '2026-10-05', 2_000, s))
    const s1 = await session(f)
    await tient(s1, f)
    const sup = suivie(f.client.from('saisie').delete().eq('id', s).select())
    await attends(800)
    expect(sup.fini, 'la suppression n’a pas attendu le verrou').toBe(false)
    await s1.query(
      `select public.corrige_la_charge($1, 'Courses', 85000, 'mensuel', null, 'au_fil')`,
      [id.courses])
    await s1.query('commit')
    expect((await sup.p).error).toBeNull()
  })

  it('lancée pendant une clôture du même mois : elle attend, puis elle est refusée', async () => {
    const { f, id } = await foyerDOctobre('ib-cloture')
    const courses = (await ligne(id.courses, '2026-10-01'))!.id
    const s1 = await session(f)
    await s1.query(`select public.cloture_le_mois('2026-10-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
    const d = suivie(declare(f, courses, '2026-10-30', 1_500))
    await attends(800)
    expect(d.fini).toBe(false)
    await s1.query('commit')
    expect((await d.p).error?.message).toMatch(/Octobre est clôturé/)
  })

  it('écrite par le trigger d’une autre table pendant une clôture : elle attend aussi', async () => {
    const { f, id } = await foyerDOctobre('ib-ticket')
    const courses = (await ligne(id.courses, '2026-10-01'))!.id
    /* « Demain les tickets (D67) » : une table dont le trigger, `security
       invoker`, écrit une saisie. Créée sous `authenticated`, dans la session. */
    const s2 = await session(f)
    await s2.query('create temp table ticket_essai (montant integer)')
    await s2.query(`create function pg_temp.tg_ticket() returns trigger language plpgsql as $$
      begin
        insert into public.saisie (id, household_id, depense_id, fait_le, montant_cents, saisi_par)
        values (gen_random_uuid(), '${f.householdId}', '${courses}', '2026-10-30',
                new.montant, '${f.userId}');
        return new;
      end $$`)
    await s2.query(`create trigger tg_ticket after insert on ticket_essai
                    for each row execute function pg_temp.tg_ticket()`)
    await s2.query('commit')

    const s1 = await session(f)
    await s1.query(`select public.cloture_le_mois('2026-10-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
    await commeLui(s2, f.userId)
    const t = suivie(s2.query('insert into ticket_essai values (1500)'))
    await attends(800)
    expect(t.fini, 'la saisie du ticket n’a pas attendu la clôture').toBe(false)
    await s1.query('commit')
    await expect(t.p).rejects.toThrow(/Octobre est clôturé/)
    await s2.query('rollback')
  })
})

describe('un compte supprimé', () => {
  // Mutation : retirer `perform verrou_du_foyer(v_hh)` de delete_my_account (0112).
  it('pendant un « Revenir dessus » : pas d’interblocage', async () => {
    const { f, poche } = await foyerDOctobre('ib-rouvre')
    const thauba = await membre(f, 'Thauba', { revenu: 240_000 })
    ou(await clore(f, { poche }))
    const s1 = await session(f)
    await s1.query(`select public.rouvre_le_mois('2026-10-01')`)
    const dep = suivie(thauba.client.rpc('delete_my_account'))
    await attends(800)
    expect(dep.fini).toBe(false)
    await s1.query('commit')
    expect((await dep.p).error).toBeNull()
  })

  it('pendant une ouverture du mois : pas d’interblocage', async () => {
    const { f } = await foyerDOctobre('ib-ouverture')
    const thauba = await membre(f, 'Thauba', { revenu: 240_000 })
    const s1 = await session(f)
    await s1.query(`select public.ouvre_le_mois('2026-11-01')`)
    const dep = suivie(thauba.client.rpc('delete_my_account'))
    await attends(800)
    expect(dep.fini).toBe(false)
    await s1.query('commit')
    expect((await dep.p).error).toBeNull()
  })
})

describe('« Revenir dessus »', () => {
  // Mutation : retirer `perform public.verrou_du_foyer(foyer)` de rouvre_le_mois (0109).
  // Sans le verrou, la réouverture passerait au travers d'une écriture en cours du foyer :
  // elle ne lit pas l'heure, c'est donc LA seule chose que ce cas peut prouver d'elle.
  it('attend le verrou du foyer, puis rouvre le mois', async () => {
    const { f, poche } = await foyerDOctobre('ib-rouvre-attend')
    ou(await clore(f, { poche }))
    const s1 = await session(f)
    await tient(s1, f)
    const r = suivie(f.client.rpc('rouvre_le_mois', { le_mois: '2026-10-01' }))
    await attends(800)
    expect(r.fini, 'la réouverture n’a pas attendu le verrou').toBe(false)
    await s1.query('commit')
    expect((await r.p).error).toBeNull()
    expect(ou(await admin().from('cloture').select('id').eq('household_id', f.householdId)
      .eq('mois', '2026-10-01'))).toEqual([])
  })
})

describe('une clôture', () => {
  // Mutation : dans cloture_le_mois (0108), lire `courant := public.mois_courant();`
  // AVANT `perform public.verrou_du_foyer(foyer);`.
  // Lancée à 23 h 59 55 le 31/10, la clôture d'octobre est refusée (« une fois fini »).
  // Elle attend le verrou, minuit passe, puis elle lit l'heure : octobre est fini. Lue
  // avant le verrou, l'heure dirait encore octobre, et la clôture serait refusée à tort.
  it('qui obtient le verrou après minuit, le 1er, clôture octobre : l’heure se lit après le verrou',
    async () => {
      const { f, poche } = await foyerDOctobre('ib-cloture-minuit')
      await avantMinuit(async () => {
        const s1 = await session(f)
        const { rows } = await s1.query('select public.mois_courant()::text as m')
        expect(rows[0].m, 'minuit est passé avant le début du banc').toBe('2026-10-01')
        await tient(s1, f)
        const c = suivie(clore(f, { poche }))
        await attends(6_000)   // minuit passe pendant l'attente : sous les 8 s de PostgREST
        expect(c.fini, 'la clôture n’a pas attendu le verrou').toBe(false)
        await s1.query('commit')
        expect((await c.p).error, 'octobre est fini : la clôture devait passer').toBeNull()
        expect(ou(await admin().from('cloture').select('mois').eq('household_id', f.householdId)))
          .toEqual([{ mois: '2026-10-01' }])
      })
    }, 40_000)
})

describe('une facture', () => {
  it('payée pendant la clôture du mois précédent : son ajustement tombe sur le mois en cours',
    async () => {
      const { f, entretien } = await avecEntretien('ib-facture-cloture')
      const s1 = await session(f)
      await s1.query(`select public.cloture_le_mois('2026-10-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
      const p = suivie(f.client.rpc('paie_une_facture', { la_facture: randomUUID(),
        la_charge: entretien, montant_cents: 32_000, paye_le: '2026-10-28' }))
      await attends(800)
      expect(p.fini).toBe(false)
      await s1.query('commit')
      expect((await p.p).error).toBeNull()
      expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents]))
        .toEqual([['2026-11-01', 15_332]])
    })

  // Mutation : dans recale_l_annee (0105), prendre le mois cible sur `now()` au
  // lieu de `public.mois_courant()`. Rougit tant que le mois réel n'est pas novembre 2026 :
  // `now()` ne suit pas l'heure jouée.
  it('qui obtient le verrou après minuit, le 1er, pose son ajustement sur le nouveau mois',
    async () => {
      const { f, entretien } = await avecEntretien('ib-minuit')
      await avantMinuit(async () => {
        const s1 = await session(f)
        const { rows } = await s1.query('select public.mois_courant()::text as m')
        expect(rows[0].m, 'minuit est passé avant le début du banc').toBe('2026-10-01')
        await tient(s1, f)
        const p = suivie(f.client.rpc('paie_une_facture', { la_facture: randomUUID(),
          la_charge: entretien, montant_cents: 32_000, paye_le: '2026-10-31' }))
        await attends(6_000)   // minuit passe pendant l'attente : sous les 8 s de PostgREST
        expect(p.fini).toBe(false)
        await s1.query('commit')
        expect((await p.p).error).toBeNull()
        expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents]))
          .toEqual([['2026-11-01', 15_332]])
      })
    }, 40_000)

  // Mutation : dans recale_l_annee (0105), prendre le mois cible sur
  // `date_trunc('month', public.maintenant())::date` : l'heure UTC, sans le fuseau de Paris.
  // Entre minuit et 2 h le 1er, la base est encore « hier » : l'ajustement tomberait sur
  // octobre. Celle-là rougit même quand le mois réel est novembre 2026, puisqu'elle suit
  // l'heure jouée.
  it('payée à 0 h 30 heure de Paris le 1er, pose son ajustement sur le nouveau mois',
    async () => {
      const { f, entretien } = await avecEntretien('ib-zero-h-trente')
      await regleLHeure('2026-11-01T00:30:00+01:00')
      try {
        expect(ou(await admin().rpc('mois_courant')), 'à 0 h 30 à Paris, on est en novembre')
          .toBe('2026-11-01')
        ou(await f.client.rpc('paie_une_facture', { la_facture: randomUUID(),
          la_charge: entretien, montant_cents: 32_000, paye_le: '2026-11-01' }))
        expect((await ajustements(entretien)).map(l => [l.mois, l.montant_cents]))
          .toEqual([['2026-11-01', 15_332]])
      } finally {
        await regleLHeure('2026-11-01T10:00:00+01:00')
      }
    }, 40_000)
})
