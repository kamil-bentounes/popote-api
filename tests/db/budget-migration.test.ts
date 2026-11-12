/**
 * La migration des données de prod (§ 5), rejouée sur une copie.
 *
 * Ne tourne QUE derrière `scripts/banc-migration-budget.sh`, qui remet la base à
 * la veille du budget refait, y charge la copie de la prod, puis applique les
 * migrations. Sans lui, la base n'a pas la copie : le banc se tait.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type pg from 'pg'
import { commeLui, connexion } from './helpers/pg'
import { regleLHeure, remetLHeure } from './helpers/horloge'

const ICI = process.env.BANC_MIGRATION === '1'
/* Sans variante : la copie telle quelle. Avec : `scripts/banc-migration-budget.sh
   --variantes` pose BANC_VARIANTE, et seul le bloc de cette variante tourne. */
const VARIANTE = process.env.BANC_VARIANTE ?? ''

const ATTENDU: Record<string, { mode: string; categorie?: string }> = {
  'Courses': { mode: 'au_fil', categorie: 'vie_courante' },
  'Restaurants': { mode: 'au_fil', categorie: 'vie_courante' },
  'Sorties et culture': { mode: 'au_fil', categorie: 'vie_courante' },
  'Électricité': { mode: 'facture', categorie: 'maison' },
  'Essence': { mode: 'au_fil', categorie: 'auto' },
  'Péage': { mode: 'au_fil', categorie: 'auto' },
  'Taxe foncière': { mode: 'mis_de_cote', categorie: 'maison' },
  'Charges de copropriété': { mode: 'mis_de_cote', categorie: 'maison' },
  'Entretien Auto': { mode: 'mis_de_cote', categorie: 'auto' },
  'Crédit auto ou LOA': { mode: 'fixe', categorie: 'auto' },
  'Droguerie et hygiène': { mode: 'au_fil', categorie: 'vie_courante' },
  'Coiffeur et soins': { mode: 'au_fil', categorie: 'vie_courante' },
  'Pharmacie': { mode: 'au_fil', categorie: 'sante' },
}

describe.skipIf(!ICI || VARIANTE !== '')('la migration des données de prod (§ 5)', () => {
  let c: pg.Client
  let foyer: string
  let kamil: string
  beforeAll(async () => {
    c = await connexion()
    foyer = (await c.query(`select household_id from public.charge
      group by 1 order by count(*) desc limit 1`)).rows[0].household_id
    kamil = (await c.query(`select id from public.user_profile where household_id = $1
      order by created_at limit 1`, [foyer])).rows[0].id
  })
  afterAll(async () => { await c.end(); await remetLHeure() })

  const un = async (sql: string, args: unknown[] = []) => (await c.query(sql, args)).rows

  it('chaque charge a sa façon et sa catégorie', async () => {
    const lues = Object.fromEntries((await un(
      `select libelle, mode, categorie from public.charge where household_id = $1
         and archive_le is null`, [foyer])).map(r => [r.libelle, r]))
    for (const [libelle, attendu] of Object.entries(ATTENDU)) {
      expect(lues[libelle], libelle).toMatchObject(attendu)
    }
    expect(lues['Essence ou recharge'], 'l’enveloppe en doublon est devenue une charge')
      .toBeUndefined()
  })

  it('les trois nouvelles : au mois du déploiement, sur le compte des autres, à Kamil', async () => {
    const nouvelles = await un(`select c.libelle, c.montant_cents, c.commun, c.debut::text,
        (select count(*)::int from public.charge_participant p where p.charge_id = c.id) as qui,
        (select nom from public.compte k where k.id = c.compte_id) as compte
      from public.charge c where c.household_id = $1
        and c.libelle in ('Droguerie et hygiène', 'Coiffeur et soins', 'Pharmacie')
      order by c.libelle`, [foyer])
    expect(nouvelles).toEqual([
      { libelle: 'Coiffeur et soins', montant_cents: 3_000, commun: false,
        debut: '2026-10-01', qui: 1, compte: 'Kamil CA' },
      { libelle: 'Droguerie et hygiène', montant_cents: 6_000, commun: true,
        debut: '2026-10-01', qui: 1, compte: 'Kamil CA' },
      { libelle: 'Pharmacie', montant_cents: 2_000, commun: false,
        debut: '2026-10-01', qui: 1, compte: 'Kamil CA' },
    ])
  })

  it('les relevés sont devenus des factures, et marquent l’année soldée avec leur prévu', async () => {
    const r = await un(`select c.libelle, f.montant_cents, f.origine, ra.prevu_cents::int as prevu
      from public.facture f join public.charge c on c.id = f.charge_id
      join public.releve_annuel ra on ra.charge_id = f.charge_id and ra.annee = f.annee
      where f.household_id = $1 order by c.libelle`, [foyer])
    expect(r.map(x => [x.montant_cents, x.origine, x.prevu]).sort())
      .toEqual([[120_000, 'releve', 120_000], [145_000, 'releve', 144_996]].sort())
  })

  it('septembre : inchangé, et ses trois lignes confirmées ont leur saisie d’amorce', async () => {
    const [s] = await un(`select count(*)::int as n, sum(montant_cents)::int as total
      from public.depense where household_id = $1 and mois = '2026-09-01'`, [foyer])
    expect(s).toEqual({ n: 23, total: 389_824 })
    const amorces = await un(`select d.libelle, s.montant_cents, s.fait_le::text, s.saisi_par
      from public.saisie s join public.depense d on d.id = s.depense_id
      where s.household_id = $1 order by d.libelle`, [foyer])
    expect(amorces).toEqual([
      { libelle: 'Courses', montant_cents: 80_000, fait_le: '2026-09-30', saisi_par: null },
      { libelle: 'Restaurants', montant_cents: 40_000, fait_le: '2026-09-30', saisi_par: null },
      { libelle: 'Sorties et culture', montant_cents: 10_000, fait_le: '2026-09-30',
        saisi_par: null },
    ])
  })

  it('clôturer octobre tout de suite : la clôture l’ouvre, 25 lignes, 316,80 € de reste',
    async () => {
      /* Le cas « sans avoir ouvert /budget » : la clôture fait elle-même la
         première ouverture. Elle vaut donc aussi pour « après la première
         ouverture du mois ». */
      await regleLHeure('2026-11-01T10:00:00+01:00')
      /* `alter database … set` ne vaut que pour les connexions ouvertes APRÈS
         lui : la nôtre, ouverte avant, verrait encore octobre comme le mois
         courant et refuserait de le clôturer. */
      await c.end()
      c = await connexion()
      await commeLui(c, kamil)
      await c.query(`select public.cloture_le_mois('2026-10-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
      await c.query('commit')
      const [o] = await un(`select count(*)::int as n, sum(montant_cents)::int as total
        from public.depense where household_id = $1 and mois = '2026-10-01'`, [foyer])
      expect(o).toEqual({ n: 25, total: 400_820 })
      const [k] = await un(`select sum(d.montant_cents) filter (where ch.commun)::int as commun,
          sum(d.montant_cents) filter (where not ch.commun)::int as moi
        from public.depense d join public.charge ch on ch.id = d.charge_id
        where d.household_id = $1 and d.mois = '2026-10-01'`, [foyer])
      expect(k).toEqual({ commun: 167_853, moi: 232_967 })
      const [r] = await un(`select reste_cents from public.cloture_choix
        where household_id = $1`, [foyer])
      expect(r.reste_cents).toBe(31_680)
    })

  it('les contraintes sont posées', async () => {
    const noms = (await un(`select conname from pg_constraint
      where conname in ('charge_mode_periodicite', 'depense_modele_a_une_facon')`))
      .map(r => r.conname).sort()
    expect(noms).toEqual(['charge_mode_periodicite', 'depense_modele_a_une_facon'])
  })
})

/* ── Les variantes qui PASSENT (tests/fixtures/variante-*.sql) ───────────────
   Chacune charge la copie plus un cas que la prod du 01/10 n'a pas. Les arrêts
   (arret-*.sql) ne passent pas par ici : le banc les rejoue lui-même
   (`--arrets`), message attendu et 0114 non enregistrée. */

type Banc = { c: pg.Client; foyer: string; kamil: string; un: (sql: string, args?: unknown[]) => Promise<any[]> }

const OUVERTES: string[] = []

/** La connexion, le foyer, Kamil : ce que chaque bloc de variante ouvre. */
function ouvre(nom: string, corps: (b: () => Banc) => void) {
  OUVERTES.push(nom)
  describe.skipIf(!ICI || VARIANTE !== nom)(`la migration, variante « ${nom} »`, () => {
    const b = {} as Banc
    beforeAll(async () => {
      b.c = await connexion()
      b.foyer = (await b.c.query(`select household_id from public.charge
        group by 1 order by count(*) desc limit 1`)).rows[0].household_id
      b.kamil = (await b.c.query(`select id from public.user_profile where household_id = $1
        order by created_at limit 1`, [b.foyer])).rows[0].id
      b.un = async (sql, args = []) => (await b.c.query(sql, args)).rows
    })
    afterAll(async () => { await b.c.end(); await remetLHeure() })
    corps(() => b)
    it('les contraintes sont posées, et aucune ligne modèle n’est restée sans façon', async () => {
      const noms = (await b.un(`select conname from pg_constraint
        where conname in ('charge_mode_periodicite', 'depense_modele_a_une_facon')`))
        .map(r => r.conname).sort()
      expect(noms).toEqual(['charge_mode_periodicite', 'depense_modele_a_une_facon'])
      const [{ n }] = await b.un(`select count(*)::int as n from public.depense
        where source = 'modele' and facon is null`)
      expect(n).toBe(0)
    })
  })
}

ouvre('variante-releve-sans-auteur', b => {
  it('un relevé positif sans auteur devient une facture sans auteur, les autres gardent le leur', async () => {
    const f = await b().un(`select f.annee, f.montant_cents, f.saisi_par is null as sans_auteur
      from public.facture f where f.household_id = $1 and f.origine = 'releve'
      order by f.annee, f.montant_cents`, [b().foyer])
    expect(f).toEqual([
      { annee: 2025, montant_cents: 145_000, sans_auteur: true },
      { annee: 2026, montant_cents: 120_000, sans_auteur: expect.any(Boolean) },
      { annee: 2026, montant_cents: 145_000, sans_auteur: expect.any(Boolean) },
    ])
  })
})

ouvre('variante-deux-membres', b => {
  it('Thauba est arrivée avant : deux membres, et les charges nées des enveloppes la comptent', async () => {
    const [{ n }] = await b().un(`select count(*)::int as n from public.user_profile
      where household_id = $1`, [b().foyer])
    expect(n).toBe(2)
    const nouvelles = await b().un(`select c.libelle, c.commun,
        array_agg(p.user_profile_id = $2 order by p.user_profile_id) as dont_kamil
      from public.charge c join public.charge_participant p on p.charge_id = c.id
      where c.household_id = $1
        and c.libelle in ('Droguerie et hygiène', 'Coiffeur et soins', 'Pharmacie')
      group by c.libelle, c.commun order by c.libelle`, [b().foyer, b().kamil])
    /* Commune : les deux. Personnelle : Kamil seul, titulaire du seul compte
       personnel actif — pas Thauba, pas tout le foyer. */
    expect(nouvelles.map(r => [r.libelle, r.commun, r.dont_kamil.length])).toEqual([
      ['Coiffeur et soins', false, 1],
      ['Droguerie et hygiène', true, 2],
      ['Pharmacie', false, 1],
    ])
    for (const r of nouvelles.filter(r => !r.commun)) expect(r.dont_kamil, r.libelle).toEqual([true])
  })

  it('les saisies d’amorce de septembre n’ont pas d’auteur, avec deux membres comme avec un', async () => {
    const amorces = await b().un(`select d.libelle, s.montant_cents, s.saisi_par
      from public.saisie s join public.depense d on d.id = s.depense_id
      where s.household_id = $1 order by d.libelle`, [b().foyer])
    expect(amorces).toEqual([
      { libelle: 'Courses', montant_cents: 80_000, saisi_par: null },
      { libelle: 'Restaurants', montant_cents: 40_000, saisi_par: null },
      { libelle: 'Sorties et culture', montant_cents: 10_000, saisi_par: null },
    ])
  })

  it('clôturer octobre à deux : 25 lignes, 4 008,20 € au total, parts qui somment', async () => {
    await regleLHeure('2026-11-01T10:00:00+01:00')
    await b().c.end()
    b().c = await connexion()
    await commeLui(b().c, b().kamil)
    await b().c.query(`select public.cloture_le_mois('2026-10-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
    await b().c.query('commit')
    const [o] = await b().un(`select count(*)::int as n, sum(montant_cents)::int as total
      from public.depense where household_id = $1 and mois = '2026-10-01'`, [b().foyer])
    expect(o).toEqual({ n: 25, total: 400_820 })
    const faux = await b().un(`select d.libelle from public.depense d
      where d.household_id = $1 and d.mois = '2026-10-01'
        and d.montant_cents <> (select coalesce(sum(p.part_cents), 0)
                                from public.depense_part p where p.depense_id = d.id)`, [b().foyer])
    expect(faux, 'une ligne dont les parts ne somment pas à son montant').toEqual([])
  })
})

ouvre('variante-montants-impairs', b => {
  it('les amorces reprennent les centimes, au centime près', async () => {
    const amorces = await b().un(`select d.libelle, s.montant_cents, s.fait_le::text, s.saisi_par
      from public.saisie s join public.depense d on d.id = s.depense_id
      where s.household_id = $1 order by d.libelle`, [b().foyer])
    expect(amorces).toEqual([
      { libelle: 'Courses', montant_cents: 80_001, fait_le: '2026-09-30', saisi_par: null },
      { libelle: 'Restaurants', montant_cents: 40_003, fait_le: '2026-09-30', saisi_par: null },
      { libelle: 'Sorties et culture', montant_cents: 10_007, fait_le: '2026-09-30',
        saisi_par: null },
    ])
    const [s] = await b().un(`select sum(montant_cents)::int as total from public.depense
      where household_id = $1 and mois = '2026-09-01'`, [b().foyer])
    expect(s.total).toBe(389_824 + 1 + 3 + 7)
  })

  it('clôturer septembre ne perd ni n’arrondit un centime : montants et parts inchangés', async () => {
    await commeLui(b().c, b().kamil)
    await b().c.query(`select public.cloture_le_mois('2026-09-01', '[]'::jsonb, '{}'::uuid[], 0, null)`)
    await b().c.query('commit')
    const l = await b().un(`select d.libelle, d.montant_cents,
        (select sum(p.part_cents)::int from public.depense_part p where p.depense_id = d.id) as parts
      from public.depense d
      where d.household_id = $1 and d.mois = '2026-09-01' and d.libelle in
        ('Courses', 'Restaurants', 'Sorties et culture') order by d.libelle`, [b().foyer])
    expect(l).toEqual([
      { libelle: 'Courses', montant_cents: 80_001, parts: 80_001 },
      { libelle: 'Restaurants', montant_cents: 40_003, parts: 40_003 },
      { libelle: 'Sorties et culture', montant_cents: 10_007, parts: 10_007 },
    ])
  })
})

ouvre('variante-charge-archivee-saisie-facture', b => {
  it('l’enveloppe d’une charge archivée ne ressuscite pas : une seule « Courses », archivée', async () => {
    const c = await b().un(`select libelle, mode, archive_le is not null as archivee
      from public.charge where household_id = $1 and libelle like 'Courses%'
      order by libelle`, [b().foyer])
    expect(c).toEqual([{ libelle: 'Courses', mode: 'au_fil', archivee: true }])
  })

  it('une ligne réglée garde sa date, sa façon et son montant', async () => {
    const [n] = await b().un(`select regle_le::text, facon, montant_cents from public.depense
      where household_id = $1 and libelle = 'Netflix' and mois = '2026-09-01'`, [b().foyer])
    expect(n).toMatchObject({ regle_le: '2026-09-05', facon: 'fixe' })
  })

  it('une saisie déjà posée n’est pas doublée d’une amorce ; les autres lignes ont la leur', async () => {
    const s = await b().un(`select d.libelle, s.montant_cents, s.saisi_par is null as amorce
      from public.saisie s join public.depense d on d.id = s.depense_id
      where s.household_id = $1 order by d.libelle`, [b().foyer])
    expect(s).toEqual([
      { libelle: 'Courses', montant_cents: 80_000, amorce: true },
      { libelle: 'Restaurants', montant_cents: 5_001, amorce: false },
      { libelle: 'Sorties et culture', montant_cents: 10_000, amorce: true },
    ])
  })

  it('une facture déjà née du relevé n’est pas doublée', async () => {
    const f = await b().un(`select c.libelle, count(*)::int as n from public.facture f
      join public.charge c on c.id = f.charge_id
      where f.household_id = $1 and f.origine = 'releve' group by c.libelle order by c.libelle`,
      [b().foyer])
    expect(f).toEqual([
      { libelle: 'Charges de copropriété', n: 1 },
      { libelle: 'Taxe foncière', n: 1 },
    ])
  })
})

ouvre('variante-mois-deja-cloture', b => {
  it('septembre est déjà clôturé : aucune amorce, et rien de septembre ne bouge', async () => {
    const [{ n }] = await b().un(`select count(*)::int as n from public.saisie
      where household_id = $1`, [b().foyer])
    expect(n).toBe(0)
    const [s] = await b().un(`select count(*)::int as n, sum(montant_cents)::int as total
      from public.depense where household_id = $1 and mois = '2026-09-01'`, [b().foyer])
    expect(s).toEqual({ n: 23, total: 389_824 })
  })
})

/* Un nom de variante que rien ne connaît ferait tourner zéro test, et vitest
   répondrait « réussi » : le banc croirait une variante vérifiée qui ne l'est pas. */
it.runIf(ICI && VARIANTE !== '')('la variante demandée a son bloc de tests', () => {
  expect(OUVERTES, `aucun bloc « ${VARIANTE} » dans ce fichier`).toContain(VARIANTE)
})
