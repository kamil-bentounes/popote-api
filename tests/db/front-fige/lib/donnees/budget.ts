/**
 * Le budget du foyer.
 *
 * Tout ce que cet écran montre se calcule en base : les parts sont figées en
 * centimes sur chaque dépense au moment où elle naît (D60), et rien ici ne les
 * recalcule. Ce module ne fait que lire et présenter.
 *
 * ⚠️ Les montants sont des CENTIMES ENTIERS de bout en bout. Ils ne deviennent
 *    des euros qu'à l'affichage, par `euros()`. Un `number` flottant traversant
 *    la couche de données finirait par rendre 10,26 € pour deux parts de 5,125,
 *    et un budget dont les parts ne recomposent pas le total est abandonné au
 *    troisième mois.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ou, supabase } from '../supabase.ts'
import { maintenant, moisCourantDeParis } from '../horloge.ts'
import { dernierJour, moisDeDepart, type Saisie as SaisieDuMois } from '../budget/mois.ts'
import type { Categorie, Mode } from '../budget/categories.ts'
import { cleNonSoldees, oublieNonSoldees, retientNonSoldees } from '../budget/non-soldees.ts'
import type { PartsParCle } from '../budget/mois-type.ts'

export const CLE = {
  mois: (m: string) => ['budget-mois', m] as const,
  charges: ['budget-charges'] as const,
  comptes: ['budget-comptes'] as const,
  poches: ['budget-poches'] as const,
  soldes: (p: string) => ['budget-solde', p] as const,
  revenus: ['budget-revenus'] as const,
}

/** Le premier jour du mois d'une date, en heure de PARIS — celle de la base (`mois_courant()`). */
export function moisDe(d: Date = maintenant()): string {
  return moisCourantDeParis(d)
}

/** Des centimes vers « 1 618,53 € ». Jamais l'inverse ailleurs qu'ici. */
export function euros(cents: number, avecUnite = true): string {
  const s = (cents / 100).toLocaleString('fr-FR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return avecUnite ? `${s} €` : s
}

/**
 * Un montant saisi vers des centimes entiers. `null` si ce n'est pas un montant.
 *
 * Elle existe parce que `Number(x.replace(',', '.'))` échouait sur « 1 234,56 »
 * — l'espace insécable que `toLocaleString('fr-FR')` produit LUI-MÊME, si bien
 * que recopier un montant affiché par l'app était rejeté — sur « 1,2,3 » (une
 * seule virgule remplacée), et acceptait « 1e3 » comme mille euros.
 *
 * Et `Math.round(12.345 * 100)` rend 1234 : le flottant vaut 1234,4999…, donc
 * on ne multiplie jamais, on découpe la chaîne.
 */
export function enCentimes(saisi: string): number | null {
  const net = saisi.replace(/[\s\u00A0\u202F]/g, '').replace(',', '.')
  /* ⚠️ Sept chiffres, pas neuf : les colonnes de montant sont des `integer` (2 147 483 647
     centimes, soit 21 M€). Neuf chiffres laissaient passer « 999 999 999 € », que la base
     refusait en anglais (« out of range for type integer ») après avoir écrit le prénom.
     Moins de dix millions d'euros : plus que n'importe quel foyer, et ça tient. */
  if (!/^\d{1,7}(\.\d{0,2})?$/.test(net)) return null
  const [entier, decimales = ''] = net.split('.')
  return Number(entier) * 100 + Number(decimales.padEnd(2, '0'))
}

/** « 1 619 € » — pour les gros chiffres, où les centimes n'aident personne. */
export function eurosRonds(cents: number): string {
  return `${Math.round(cents / 100).toLocaleString('fr-FR')} €`
}

export type Depense = {
  id: string
  charge_id: string | null
  libelle: string
  mois: string
  montant_cents: number
  montant_prevu_cents: number | null
  nature: 'estimee' | 'connue'
  source: string
  /* La façon de la LIGNE, figée à sa naissance (§ 4.1). Null : un ajustement. */
  facon: Mode | null
  confirme_le: string | null
  regularise_annee: number | null
  /* Quand ça a été réellement payé. Un mois rattrapé — la taxe foncière posée
     en septembre ouvre janvier à août — annonçait « à verser » des mois qu'on
     a déjà vécus et déjà payés, sans aucun moyen de le dire. */
  regle_le: string | null
  enveloppe_id: string | null
  compte_id: string | null
  /* Les points de base survivent à une ligne confirmée à 0 € : c'est sur eux
     que se lit la proportion d'un mois rouvert (`partSur`). */
  parts: { user_profile_id: string; part_cents: number; part_bps: number }[]
}

/**
 * Le mois : ses dépenses et les parts de chacun.
 *
 * L'ouverture du mois est PARESSEUSE — il n'y a pas de tâche planifiée, donc
 * c'est la première lecture qui la déclenche. `ouvre_le_mois` est idempotente :
 * la clé se fige au premier appel, les suivants ne touchent rien.
 */
export async function lisLeMois(mois: string): Promise<Depense[]> {
  /* ⚠️ On n'ouvre JAMAIS un mois futur.
   *
   *    `ouvre_le_mois` est idempotente et fige la clé au premier appel :
   *    feuilleter jusqu'en 2028 y créait donc les dépenses avec le partage
   *    d'aujourd'hui, définitivement. Regarder l'avenir ne doit rien y
   *    écrire — on le lit, on ne le décide pas. */
  if (mois <= moisDe()) {
    /* ⚠️ On RATTRAPE tous les mois manquants, pas seulement celui qu'on
       regarde. Un mois qu'on n'ouvrait pas pendant son propre mois ne
       s'ouvrait plus jamais — 120,83 € par mois d'absence, jamais mis de
       côté, sans un mot. Le passé cesse de dépendre du moment où l'on a
       regardé. */
    const { error: eR } = await supabase.rpc('rattrape_les_mois')
    if (eR) throw new Error(eR.message)
    const { error } = await supabase.rpc('ouvre_le_mois', { le_mois: mois })
    if (error) throw new Error(error.message)
  }
  const lignes = ou(await supabase.from('depense')
    /* ⚠️ Une seule chaîne LITTÉRALE. PostgREST infère le type du résultat
       depuis le texte du `select` ; une concaténation n'est plus un
       littéral pour TypeScript, et tout retombe sur `GenericStringError`. */
    .select('id, charge_id, libelle, mois, montant_cents, montant_prevu_cents, nature, source, facon, confirme_le, regularise_annee, enveloppe_id, compte_id, regle_le, depense_part(user_profile_id, part_cents, part_bps)')
    .eq('mois', mois).order('libelle'))
  return lignes.map(l => ({
    ...l,
    nature: l.nature as Depense['nature'],
    facon: l.facon as Mode | null,
    parts: (l.depense_part ?? []) as Depense['parts'],
  }))
}

export function useMois(mois: string) {
  return useQuery({ queryKey: CLE.mois(mois), queryFn: () => lisLeMois(mois) })
}

export type Virement = { vers: string; compteId: string | null; cents: number; detail: string }

/**
 * Ce que quelqu'un doit verser, et où.
 *
 * On ne rend pas un solde abstrait mais des VIREMENTS À FAIRE : c'est la seule
 * forme sur laquelle on peut agir. L'écart entre ce qu'on doit et ce qu'on a
 * réellement payé est tout le moteur — une charge due à deux mais débitée du
 * compte de l'un crée une dette envers lui, pas envers le compte commun.
 */
export function virements(
  depenses: Depense[], moi: string, comptes: Compte[], prenoms: Map<string, string>,
): Virement[] {
  const parCompte = new Map<string | null, number>()
  for (const d of depenses) {
    /* Une dépense DÉJÀ RÉGLÉE ne se redemande pas. Sans ça, rattraper une
       charge annuelle depuis janvier réclamait huit virements pour des mois
       qu'on a vécus et payés. */
    if (d.regle_le) continue
    const mienne = d.parts.find(p => p.user_profile_id === moi)
    if (!mienne) continue
    parCompte.set(d.compte_id, (parCompte.get(d.compte_id) ?? 0) + mienne.part_cents)
  }

  const sortie: Virement[] = []
  for (const [compteId, cents] of parCompte) {
    if (cents === 0) continue
    const c = comptes.find(x => x.id === compteId)
    /* Mon PROPRE compte perso : je me dois à moi-même, c'est-à-dire rien. La
       première version demandait de se virer de l'argent à soi, et gonflait le
       total d'autant. */
    if (c?.genre === 'perso' && c.titulaire_id === moi) continue
    // Un compte perso qui n'est pas le sien : on doit à son titulaire, pas au
    // compte. C'est ce que la personne comprend, et ce qu'elle fera.
    const versQuelquun = c?.genre === 'perso' && c.titulaire_id && c.titulaire_id !== moi
    sortie.push({
      vers: versQuelquun ? (prenoms.get(c!.titulaire_id!) ?? 'l’autre') : (c?.nom ?? 'à répartir'),
      compteId: compteId,
      cents,
      detail: versQuelquun ? 'avancé par lui' : 'charges et enveloppes',
    })
  }
  return sortie.sort((a, b) => b.cents - a.cents)
}

export type Compte = {
  id: string; nom: string; genre: 'commun' | 'perso' | 'epargne'
  titulaire_id: string | null; matelas_cents: number
}

export function useComptes() {
  return useQuery({
    queryKey: CLE.comptes,
    queryFn: async (): Promise<Compte[]> => ou(await supabase.from('compte')
      .select('id, nom, genre, titulaire_id, matelas_cents, archive_le')
      /* Un compte rangé ne se propose plus — ni dans la liste, ni dans le menu
         « où débiter » de chaque charge. C'est tout l'intérêt de le ranger. */
      .is('archive_le', null).order('nom')) as Compte[],
  })
}

export type Charge = {
  id: string; libelle: string; montant_cents: number; commun: boolean; debut: string
  /* Qui a touché la ligne en dernier. Le foyer partage tout — chacun peut
     corriger la charge de l'autre — mais une correction silencieuse sur la
     ligne de quelqu'un d'autre est une surprise. On ne verrouille pas, on dit. */
  modifie_par: string | null
  periodicite: 'mensuel' | 'trimestriel' | 'annuel'
  /* La façon de la CHARGE : elle ne sert qu'à « Mes charges ». L'écran du mois
     lit celle de chaque ligne. */
  mode: Mode
  categorie: Categorie
  catalogue_id: string | null
  variable: boolean; cle: 'prorata' | 'moitie' | null
  compte_id: string | null; enveloppe_id: string | null
  archive_le: string | null
  participants: string[]
}

export function useCharges(actif = true) {
  return useQuery({
    queryKey: CLE.charges,
    enabled: actif,
    queryFn: async (): Promise<Charge[]> => {
      const l = ou(await supabase.from('charge')
        .select('id, libelle, montant_cents, periodicite, mode, categorie, catalogue_id, variable, cle, compte_id, enveloppe_id, archive_le, commun, debut, modifie_par, charge_participant(user_profile_id)')
        .order('libelle'))
      return l.map(c => ({
        ...c,
        periodicite: c.periodicite as Charge['periodicite'],
        mode: c.mode as Mode, categorie: c.categorie as Categorie,
        cle: c.cle as Charge['cle'],
        /* ⚠️ TRIÉS. Sans ordre, PostgREST rend les participants dans celui de
           la base : on lisait « Thauba et Kamil » sur une ligne et « Kamil et
           Thauba » sur la suivante, du même écran. Deux façons d'écrire la même
           chose se lisent comme deux choses. */
        participants: (c.charge_participant ?? [])
          .map(p => p.user_profile_id).sort(),
      }))
    },
  })
}

/** Le catalogue, groupé par section, dans l'ordre voulu. */
export function useCatalogue() {
  return useQuery({
    queryKey: ['catalogue-charges'],
    queryFn: async () => {
      const l = ou(await supabase.from('catalogue_charge')
        .select('id, section, libelle, periode, portee, precision_txt, ordre, plafond_ordre').order('ordre'))
      const sections = new Map<string, typeof l>()
      for (const x of l) {
        if (!sections.has(x.section)) sections.set(x.section, [])
        sections.get(x.section)!.push(x)
      }
      return [...sections].map(([nom, lignes]) => ({ nom, lignes }))
    },
    staleTime: Infinity,   // un référentiel ne bouge pas pendant une session
  })
}

export type Poche = {
  id: string; libelle: string; genre: 'urgence' | 'projet'
  objectif_cents: number | null; echeance: string | null
  cle: 'prorata' | 'moitie' | null
}

export function usePoches() {
  return useQuery({
    queryKey: CLE.poches,
    queryFn: async (): Promise<Poche[]> => ou(await supabase.from('poche_epargne')
      .select('id, libelle, genre, objectif_cents, echeance, cle')
      .order('genre').order('libelle')) as Poche[],
  })
}

/** Le cumul de chacun sur une poche. Jamais un solde seul (D64). */
export function useSolde(pocheId: string | undefined) {
  return useQuery({
    queryKey: CLE.soldes(pocheId ?? ''),
    enabled: !!pocheId,
    queryFn: async () => {
      const l = ou(await supabase.rpc('solde_epargne', { la_poche: pocheId! }))
      return l.map(x => ({ userId: x.user_profile_id, cents: Number(x.cumul_cents) }))
    },
  })
}

export function useAjouteCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (c: {
      libelle: string; montantCents: number; periodicite: string
      participants: string[]; cle?: string | null; catalogueId?: string | null
      variable?: boolean; compteId?: string | null; enveloppeId?: string | null
      commun?: boolean; debut?: string
      /** L'arrivée de qui pose la charge : rien ne court avant elle (voir `moisDeDepart`). */
      arrivee?: string | null
      mode?: Mode; categorie?: Categorie
      foyerId: string
    }) => {
      /* ⚠️ Une charge ne court pas avant l'arrivée de qui la pose. La dictée envoyait `debut` vide pour
         une charge mensuelle, donc octobre pour quelqu'un qui n'entre qu'en novembre : la charge entrait
         dans le total d'octobre, et si le second membre arrivait avant le 1er novembre, la base ouvrait
         octobre avec 100 % des parts sur lui. Un seul endroit, pour le formulaire comme pour la dictée. */
      const debut = moisDeDepart(c.arrivee, c.debut ?? moisDe())
      const ligne = ou(await supabase.from('charge').insert({
        household_id: c.foyerId, libelle: c.libelle, montant_cents: c.montantCents,
        periodicite: c.periodicite, cle: c.cle ?? null, catalogue_id: c.catalogueId ?? null,
        /* La façon et la catégorie, dites par l'écran (§ 3.7). Sans elles, le
           trigger de `charge` les déduit — c'est le chemin de l'ancien paquet. */
        ...(c.mode ? { mode: c.mode } : {}),
        ...(c.categorie ? { categorie: c.categorie } : {}),
        variable: c.variable ?? false, compte_id: c.compteId ?? null,
        enveloppe_id: c.enveloppeId ?? null,
        /* L'INTENTION, pas l'état : une charge commune posée pendant qu'on est
           seul dans le foyer doit accueillir le second membre à son arrivée.
           Sans cette colonne, il fallait rouvrir les quinze charges une à une. */
        commun: c.commun ?? false,
        /* Et sa date de début se choisit. `moisDe()` en dur voulait dire qu'une
           taxe foncière posée en septembre ne provisionnait que septembre — et
           que sa régularisation facturait l'année entière d'un coup, exactement
           ce que D61 existe pour empêcher. */
        debut,
      }).select().single())
      /* Une charge sans participant n'engendre rien : le générateur l'ignore.
         Les deux écritures vont donc ensemble, toujours. */
      ou(await supabase.from('charge_participant').insert(
        c.participants.map(u => ({
          charge_id: ligne.id, user_profile_id: u, household_id: c.foyerId,
        }))).select())

      /* ⚠️ Et on OUVRE les mois écoulés depuis son début.
       *
       *    `ouvre_le_mois` n'engendre que le mois demandé. Une taxe foncière
       *    qui court depuis janvier, posée en septembre, ne provisionnait donc
       *    que septembre — et sa régularisation annuelle facturait 1 208 € d'un
       *    coup, exactement ce que D61 existe pour empêcher. Le champ « depuis
       *    quand » ne servait à rien sans ça. */
      const depuis = debut.slice(0, 7)
      const jusqua = moisDe().slice(0, 7)
      for (let [a, m] = depuis.split('-').map(Number);
           `${a}-${String(m).padStart(2, '0')}` <= jusqua; m === 12 ? (a++, m = 1) : m++) {
        await supabase.rpc('ouvre_le_mois',
          { le_mois: `${a}-${String(m).padStart(2, '0')}-01` })
      }
      return ligne
    },
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: CLE.charges }),
      qc.invalidateQueries({ queryKey: ['budget-mois'] }),
    ]),
  })
}

/**
 * Corriger le libellé, le montant ou le rythme d'une charge.
 *
 * Il manquait, et une faute de frappe le premier soir était définitive : « Retirer »
 * échoue sur la clé étrangère dès qu'un mois est ouvert, retombe sur l'archivage, et
 * la dépense fausse reste. Reposer la charge corrigée ajoutait la bonne PAR-DESSUS.
 *
 * Le SQL refait les mois ouverts qui ne sont ni réglés ni confirmés, et rend
 * combien — pour pouvoir le dire.
 */
export function useCorrigeCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (m: {
      id: string; libelle: string; montantCents: number
      periodicite: 'mensuel' | 'trimestriel' | 'annuel'
      /* La date de départ : le seul champ que l'écran signale comme dangereux,
         et le seul qu'on ne pouvait plus toucher. */
      debut: string
      /* Absente, la clé ne part pas et la base prend son défaut (`null` : la
         façon ne change pas). Un `null` explicite ne passerait pas le typage :
         les types générés font des paramètres à défaut des `?: string`. */
      mode?: Mode
    }) => {
      const { data, error } = await supabase.rpc('corrige_la_charge', {
        la_charge: m.id, nouveau_libelle: m.libelle,
        nouveau_montant: m.montantCents, nouvelle_periodicite: m.periodicite,
        nouveau_debut: m.debut, nouveau_mode: m.mode,
      })
      if (error) throw new Error(error.message)
      return (data as number) ?? 0
    },
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: CLE.charges }),
      qc.invalidateQueries({ queryKey: ['budget-mois'] }),
    ]),
  })
}

/* ── Ce qui manquait : de quoi POSER les prérequis ─────────────────────────
 *
 * Les écrans du budget lisaient des comptes, des enveloppes et des revenus
 * qu'aucun écran ne permettait d'écrire. Conséquence mesurée : les virements ne
 * rendaient qu'une ligne « à répartir », la section des enveloppes ne
 * s'affichait jamais, et le prorata basculait silencieusement en moitié-moitié
 * faute de revenu — le formulaire proposait « Au prorata » et ne l'honorait pas.
 */

export type Revenu = { id: string; user_profile_id: string; net_mensuel_cents: number; valid_from: string }

export async function lisLesRevenus(): Promise<Revenu[]> {
  return ou(await supabase.from('revenu')
    .select('id, user_profile_id, net_mensuel_cents, valid_from')
    .order('valid_from', { ascending: false })) as Revenu[]
}

/** TOUT l'historique : le revenu en vigueur se lit à la fin du mois affiché
    (`revenuDuMois`). Ne garder que le dernier faisait afficher décembre « sur
    4 500 € » quand le revenu changeait en janvier. */
export function useRevenus() {
  return useQuery({ queryKey: CLE.revenus, queryFn: lisLesRevenus })
}

/**
 * Poser son revenu : UNE instruction, un `upsert` sur (personne, date d'effet).
 * Le `delete` puis `insert` d'avant faisait deux transactions : un revenu posé
 * pendant le départ de son compte tenait sa ligne en attendant le verrou du
 * foyer, que `delete_my_account` tenait en attendant de la supprimer.
 */
export async function poseRevenu(v: { foyerId: string; userId: string; cents: number; entreLe?: string | null }) {
  return ou(await supabase.from('revenu').upsert({
    household_id: v.foyerId, user_profile_id: v.userId,
    /* `entreLe` : qui arrive plus tard n'a pas de revenu avant son arrivée (`moisDeDepart`). */
    net_mensuel_cents: v.cents, valid_from: moisDeDepart(v.entreLe, moisDe()),
  }, { onConflict: 'user_profile_id,valid_from' }).select().single())
}

export function usePoseRevenu() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: poseRevenu, onSuccess: () => relisLeBudget(qc) })
}

export function usePoseCompte() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (c: {
      foyerId: string; nom: string; genre: 'commun' | 'perso' | 'epargne'
      titulaireId: string | null; matelasCents: number
    }) => ou(await supabase.from('compte').insert({
      household_id: c.foyerId, nom: c.nom, genre: c.genre,
      /* La contrainte l'exige : un compte `perso` a un titulaire, les autres
         n'en ont pas. Un compte commun avec titulaire prétendrait le contraire
         de ce qu'il est. */
      titulaire_id: c.genre === 'perso' ? c.titulaireId : null,
      matelas_cents: c.matelasCents,
    }).select().single()),
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: CLE.comptes }),
      qc.invalidateQueries({ queryKey: ['budget-mois'] }),
    ]),
  })
}

/** Rattacher une charge à un compte, après coup. Les enveloppes sont parties de
    l'écran (§ 3.7) ; `virements()` lira le compte au lot 4. */
export function useRattacheCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (r: { id: string; compteId: string | null }) =>
      ou(await supabase.from('charge').update({ compte_id: r.compteId })
        .eq('id', r.id).select().single()),
    onSuccess: () => relisLeBudget(qc),
  })
}

/* ── L'épargne : verser, et savoir à qui c'est ────────────────────────────── */

export function usePosePoche() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: {
      foyerId: string; libelle: string; genre: 'urgence' | 'projet'
      objectifCents: number | null; echeance: string | null; cle: 'prorata' | 'moitie' | null
    }) => ou(await supabase.from('poche_epargne').insert({
      household_id: p.foyerId, libelle: p.libelle, genre: p.genre,
      objectif_cents: p.objectifCents, echeance: p.echeance, cle: p.cle,
    }).select().single()),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE.poches }),
  })
}

/**
 * Verser — ou retirer, le montant étant signé.
 *
 * Une seule colonne signée plutôt qu'un booléen de sens : on n'a pas à se
 * rappeler dans quelle direction lire un drapeau, et la somme se fait toute
 * seule.
 */
export function useVerse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: {
      foyerId: string; pocheId: string; userId: string; cents: number
      motif?: 'mensuel' | 'balayage' | 'retrait' | 'correction'
    }) => ou(await supabase.from('versement_epargne').insert({
      household_id: v.foyerId, poche_id: v.pocheId, user_profile_id: v.userId,
      montant_cents: v.cents, motif: v.motif ?? (v.cents < 0 ? 'retrait' : 'mensuel'),
    }).select().single()),
    /* ⚠️ `onSettled`, pas `onSuccess` : une réponse perdue (le réseau coupe après que la base a
       écrit) finit en erreur côté écran alors que le versement EST là. Sans relecture, le solde
       restait périmé (30 s) et un second retrait passait la garde du front (`refusDuRetrait`)
       sur un solde qui n'existait plus. */
    onSettled: (_d, _e, v) => Promise.all([
      qc.invalidateQueries({ queryKey: CLE.soldes(v.pocheId) }),
      qc.invalidateQueries({ queryKey: CLE.poches }),
    ]),
  })
}

/* ── La régularisation : ce qu'on a VRAIMENT payé ─────────────────────────── */

/** La règle par défaut du foyer. Datée : elle ne réécrit pas les mois passés. */
export function useRegle() {
  return useQuery({
    queryKey: ['regle-partage'],
    queryFn: async () => {
      const l = ou(await supabase.from('regle_partage')
        .select('cle, valid_from').order('valid_from', { ascending: false }).limit(1))
      return (l[0]?.cle ?? 'prorata') as 'prorata' | 'moitie'
    },
  })
}

/**
 * Les parts de chacun pour un mois, telles que la base les calcule (`parts_du_foyer`) : la clé du foyer,
 * et chacune des deux clés qu'une charge peut porter. C'est sur elles que le mois type partage — jamais
 * sur un prorata recompté ici, qui oublierait l'arrivée, le revenu manquant ou l'arrondi de la base.
 */
export function usePartsDuFoyer(mois: string, actif = true) {
  return useQuery({
    queryKey: ['parts-du-foyer', mois],
    enabled: actif,
    queryFn: async (): Promise<PartsParCle> => {
      const lis = async (cle: 'prorata' | 'moitie' | null) => Object.fromEntries(
        ou(await supabase.rpc('parts_du_foyer', { le_mois: mois, ...(cle ? { la_cle: cle } : {}) }))
          .map(p => [p.user_profile_id, p.part_bps]))
      const [foyer, prorata, moitie] = await Promise.all([lis(null), lis('prorata'), lis('moitie')])
      return { foyer, prorata, moitie }
    },
  })
}

/* Comme un revenu : une nouvelle règle est un FAIT DATÉ, pas une correction.
   Deux changements le même mois sont la même intention : un `upsert`, une seule
   transaction. */
export async function poseRegle(r: { foyerId: string; cle: 'prorata' | 'moitie' }) {
  return ou(await supabase.from('regle_partage').upsert({
    household_id: r.foyerId, cle: r.cle, valid_from: moisDe(),
  }, { onConflict: 'household_id,valid_from' }).select().single())
}

export function usePoseRegle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: poseRegle,
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: ['regle-partage'] }),
      qc.invalidateQueries({ queryKey: ['budget-mois'] }),
      /* Le mois type partage avec ces parts : sans elles, il montrait encore l'ancienne règle. */
      qc.invalidateQueries({ queryKey: ['parts-du-foyer'] }),
    ]),
  })
}

/* ── Les projets (D72) ────────────────────────────────────────────────────── */

export type Poste = { id: string; libelle: string; montant_cents: number; ordre: number }

export function usePostes(pocheId: string | undefined) {
  return useQuery({
    queryKey: ['poche-postes', pocheId],
    enabled: !!pocheId,
    queryFn: async (): Promise<Poste[]> => ou(await supabase.from('poche_poste')
      .select('id, libelle, montant_cents, ordre')
      .eq('poche_id', pocheId!).order('ordre')) as Poste[],
  })
}

export function usePosePoste() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: {
      foyerId: string; pocheId: string; libelle: string; cents: number; ordre: number
    }) => ou(await supabase.from('poche_poste').insert({
      household_id: p.foyerId, poche_id: p.pocheId,
      libelle: p.libelle, montant_cents: p.cents, ordre: p.ordre,
    }).select().single()),
    onSuccess: (_d, p) => Promise.all([
      qc.invalidateQueries({ queryKey: ['poche-postes', p.pocheId] }),
      qc.invalidateQueries({ queryKey: CLE.poches }),
    ]),
  })
}

export function useRetirePoste() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: { id: string; pocheId: string }) =>
      ou(await supabase.from('poche_poste').delete().eq('id', p.id).select()),
    onSuccess: (_d, p) => qc.invalidateQueries({ queryKey: ['poche-postes', p.pocheId] }),
  })
}

export function useMajPoche() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (p: {
      id: string; objectifCents?: number | null; echeance?: string | null
      cle?: 'prorata' | 'moitie' | null
    }) => ou(await supabase.from('poche_epargne').update({
      ...(p.objectifCents !== undefined ? { objectif_cents: p.objectifCents } : {}),
      ...(p.echeance !== undefined ? { echeance: p.echeance } : {}),
      ...(p.cle !== undefined ? { cle: p.cle } : {}),
    }).eq('id', p.id).select().single()),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE.poches }),
  })
}

/**
 * L'effort mensuel qu'il reste à fournir pour tenir une échéance.
 *
 * `null` quand il n'y a ni objectif ni date : sans les deux, il n'y a rien à
 * tenir. Zéro mois restant veut dire « c'est maintenant », pas « divise par
 * zéro ».
 */
export function effortMensuel(
  objectifCents: number | null, echeance: string | null, dejaCents: number,
): { parMois: number; mois: number } | null {
  if (!objectifCents || !echeance) return null
  const [a, m] = echeance.split('-').map(Number)
  const n = maintenant()
  const mois = Math.max(0, (a - n.getFullYear()) * 12 + (m - 1 - n.getMonth()))
  const reste = Math.max(0, objectifCents - dejaCents)
  return { parMois: mois === 0 ? reste : Math.ceil(reste / mois), mois }
}

/**
 * Changer qui participe à une charge.
 *
 * Il manquait, et le manque était bloquant : les participants ne se cochaient
 * qu'à la CRÉATION, si bien qu'inviter quelqu'un après avoir posé ses charges
 * obligeait à toutes les refaire.
 *
 * Le mois en cours se repose derrière, quand il n'a encore rien coûté à
 * personne : ajouter quelqu'un à une charge doit changer ce qu'il doit, sinon
 * le bouton ment. Un mois déjà vécu, lui, ne bouge pas — `refige_le_mois` s'en
 * charge et refuse toute seule.
 */
/**
 * Qui retirer, qui ajouter — et personne d'autre.
 *
 * Sortie de la mutation pour être éprouvable : le défaut n'était pas dans le
 * SQL mais ici, dans un `delete` sans discernement.
 */
export function diffParticipants(avant: string[], veut: string[]) {
  const dedans = new Set(veut)
  return {
    retires: avant.filter(u => !dedans.has(u)),
    ajoutes: veut.filter(u => !avant.includes(u)),
  }
}

export function useMajParticipants() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (m: { chargeId: string; foyerId: string; participants: string[] }) => {
      /* ⚠️ On ne supprime QUE ceux qu'on retire.
         Cette fonction effaçait tous les participants pour en reposer deux, sa
         propre ligne comprise. Elle a survécu tant que rien ne surveillait ces
         suppressions ; le jour où un trigger l'a fait, le bouton est mort en
         silence sur toute charge commune. Un écrasement complet est une
         écriture de plus, pas une simplification : il touche des lignes que
         personne n'a demandé à changer, et il les touche à chaque clic. */
      const avant = ou(await supabase.from('charge_participant')
        .select('user_profile_id').eq('charge_id', m.chargeId))
        .map(r => r.user_profile_id as string)
      const { retires, ajoutes } = diffParticipants(avant, m.participants)

      if (retires.length > 0) {
        ou(await supabase.from('charge_participant')
          .delete().eq('charge_id', m.chargeId)
          .in('user_profile_id', retires).select())
      }
      if (ajoutes.length > 0) {
        ou(await supabase.from('charge_participant').insert(
          ajoutes.map(u => ({
            charge_id: m.chargeId, user_profile_id: u, household_id: m.foyerId,
          }))).select())
      }
      const { error } = await supabase.rpc('refige_le_mois', { le_mois: moisDe() })
      if (error) throw new Error(error.message)
    },
    onSuccess: () => Promise.all([
      qc.invalidateQueries({ queryKey: CLE.charges }),
      qc.invalidateQueries({ queryKey: ['budget-mois'] }),
    ]),
  })
}

/** Archiver un compte, ou le remettre. Il a débité des mois qu'on relit : on
    le RANGE, on ne le supprime pas. */
export function useRangeCompte() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (m: { id: string; ranger: boolean }) => {
      const { error } = await supabase.rpc('range_le_compte',
        { le_compte: m.id, ranger: m.ranger })
      if (error) throw new Error(error.message)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE.comptes }),
  })
}

/* ── Le budget refait ─────────────────────────────────────────────────────── */

/* Chaque mutation relit tout ce que l'argent touche. Sans cela, la feuille
   restée ouverte après une facture de 320 € annonçait « Il restera 66,68 € de
   côté » pour 100 €, quand la base posait +100 €.

   ⚠️ Et la mutation ATTEND ces relectures : `onSuccess` rend cette promesse, et
   TanStack ne déclare la mutation finie qu'après elle. Sans le `return`, la feuille de
   déclaration vidait son champ et rallumait « Ajouter » pendant que la jauge montrait
   encore l'ancien chiffre ; sur réseau lent on croyait l'ajout perdu, on le retapait,
   et l'identifiant neuf le comptait deux fois. */
const CE_QUE_L_ARGENT_TOUCHE = ['budget-mois', 'saisies', 'factures', 'cloture',
  'etat-de-l-annee', 'apercu-des-soldes', 'budget-charges', 'budget-poches', 'budget-solde',
  'budget-revenus', 'parts-du-foyer']
export function relisLeBudget(qc: QueryClient) {
  return Promise.all(CE_QUE_L_ARGENT_TOUCHE.map(cle => qc.invalidateQueries({ queryKey: [cle] })))
}

// ── Les dépenses au fil du mois ──────────────────────────────────────────────
export type Saisie = SaisieDuMois & { created_at: string }

export async function lisLesSaisies(mois: string): Promise<Saisie[]> {
  return ou(await supabase.from('saisie')
    .select('id, depense_id, fait_le, montant_cents, saisi_par, created_at')
    .gte('fait_le', mois).lte('fait_le', dernierJour(mois))
    .order('fait_le', { ascending: false }).order('created_at', { ascending: false })) as Saisie[]
}
export function useSaisies(mois: string) {
  return useQuery({ queryKey: ['saisies', mois], queryFn: () => lisLesSaisies(mois) })
}

/**
 * Déclarer une dépense. L'identifiant vient de l'appareil : la feuille le crée
 * à la frappe du montant, le garde pour ses renvois, et en prend un neuf après
 * un succès. Un second envoi du même identifiant — une coupure, un double
 * toucher — rend 23505 : c'est un succès.
 */
export async function ajouteSaisie(s: {
  id: string; foyerId: string; depenseId: string; faitLe: string; cents: number; moi: string
}) {
  const { error } = await supabase.from('saisie').insert({
    id: s.id, household_id: s.foyerId, depense_id: s.depenseId, fait_le: s.faitLe,
    montant_cents: s.cents, saisi_par: s.moi,
  })
  if (error && error.code !== '23505') throw new Error(error.message)
}
export function useAjouteSaisie() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: ajouteSaisie, onSuccess: () => relisLeBudget(qc) })
}

export async function retireSaisie(id: string) {
  ou(await supabase.from('saisie').delete().eq('id', id).select())
}
export function useRetireSaisie() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: retireSaisie, onSuccess: () => relisLeBudget(qc) })
}

// ── Les factures du mois ─────────────────────────────────────────────────────
/** « C'est ça » ou « Valider X € » : la feuille Facture du mois (§ 3.3). */
export async function confirmeFacture(c: { depenseId: string; cents: number }) {
  const { error } = await supabase.rpc('confirme_la_depense',
    { la_depense: c.depenseId, reel_cents: c.cents })
  if (error) throw new Error(error.message)
}
export function useConfirmeFacture() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: confirmeFacture, onSuccess: () => relisLeBudget(qc) })
}

// ── Les factures des charges mises de côté ───────────────────────────────────
export type Facture = {
  id: string; charge_id: string; annee: number; paye_le: string; montant_cents: number
  origine: 'saisie' | 'releve'; saisi_par: string | null
}
export async function lisLesFactures(chargeId: string, annee: number): Promise<Facture[]> {
  return ou(await supabase.from('facture')
    .select('id, charge_id, annee, paye_le, montant_cents, origine, saisi_par')
    .eq('charge_id', chargeId).eq('annee', annee)
    .order('paye_le', { ascending: false })) as Facture[]
}
export function useFactures(chargeId: string, annee: number, actif = true) {
  return useQuery({ queryKey: ['factures', chargeId, annee], enabled: actif,
                    queryFn: () => lisLesFactures(chargeId, annee) })
}

export async function paieFacture(p: { id: string; chargeId: string; cents: number; payeLe: string }) {
  const { error } = await supabase.rpc('paie_une_facture', {
    la_facture: p.id, la_charge: p.chargeId, montant_cents: p.cents, paye_le: p.payeLe })
  if (error) throw new Error(error.message)
}
export function usePaieFacture() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: paieFacture, onSuccess: () => relisLeBudget(qc) })
}

export async function retireFacture(id: string) {
  const { error } = await supabase.rpc('retire_une_facture', { la_facture: id })
  if (error) throw new Error(error.message)
}
export function useRetireFacture() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: retireFacture, onSuccess: () => relisLeBudget(qc) })
}

export async function corrigeLeReleve(c: { id: string; cents: number }) {
  const { error } = await supabase.rpc('corrige_le_releve',
    { la_facture: c.id, montant_cents: c.cents })
  if (error) throw new Error(error.message)
}
export function useCorrigeLeReleve() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: corrigeLeReleve, onSuccess: () => relisLeBudget(qc) })
}

export type EtatAnnee = {
  b: number; pl: number; pose: number; soldee: boolean; premier_mois_suivi: string | null
}
/** Ce que la base calcule pour une année : la feuille applique la formule du § 4.4
    au montant tapé, elle ne recompte rien. */
export async function lisEtatDeLAnnee(chargeId: string, annee: number): Promise<EtatAnnee> {
  return ou(await supabase.rpc('etat_de_l_annee', { la_charge: chargeId, annee })) as EtatAnnee
}
export function useEtatDeLAnnee(chargeId: string, annee: number, actif = true) {
  return useQuery({ queryKey: ['etat-de-l-annee', chargeId, annee], enabled: actif,
                    queryFn: () => lisEtatDeLAnnee(chargeId, annee) })
}

/**
 * Une charge mise de côté a-t-elle une histoire : une facture (les relevés en
 * sont, depuis 0114), ou une ligne mise de côté confirmée ou réglée — un mois
 * clôturé, même rouvert, est tout confirmé ? Elle ne devient alors pas
 * mensuelle (§ 3.7). La base le refuse (0110) ; l'écran le dit AVANT, en
 * grisant les trois autres façons.
 */
export async function aUneHistoire(chargeId: string): Promise<boolean> {
  const f = await supabase.from('facture').select('id', { count: 'exact', head: true })
    .eq('charge_id', chargeId)
  if (f.error) throw new Error(f.error.message)
  const d = await supabase.from('depense').select('id', { count: 'exact', head: true })
    .eq('charge_id', chargeId).eq('source', 'modele').eq('facon', 'mis_de_cote')
    .or('confirme_le.not.is.null,regle_le.not.is.null')
  if (d.error) throw new Error(d.error.message)
  return (f.count ?? 0) + (d.count ?? 0) > 0
}
export function useAUneHistoire(chargeId: string, actif: boolean) {
  /* Sous `factures` : chaque mutation de l'argent la relit (`relisLeBudget`). */
  return useQuery({ queryKey: ['factures', 'histoire', chargeId],
                    enabled: actif && chargeId !== '', queryFn: () => aUneHistoire(chargeId) })
}

// ── La clôture ──────────────────────────────────────────────────────────────
export type Choix = {
  user_profile_id: string; reste_cents: number | null; mis_de_cote_cents: number
  poche_id: string | null; versement_id: string | null
}
export type Cloture = { id: string; mois: string; cloture_le: string; choix: Choix[] }

export async function lisLesClotures(): Promise<Cloture[]> {
  const l = ou(await supabase.from('cloture')
    .select('id, mois, cloture_le, cloture_choix(user_profile_id, reste_cents, mis_de_cote_cents, poche_id, versement_id)')
    .order('mois', { ascending: false }))
  return l.map(k => ({ id: k.id, mois: k.mois, cloture_le: k.cloture_le,
                       choix: (k.cloture_choix ?? []) as Choix[] }))
}
export function useClotures() {
  return useQuery({ queryKey: ['cloture'], queryFn: lisLesClotures })
}

export type NonSoldee = { charge: string; libelle: string; annee: number; raison: string }
export async function clotureLeMois(c: {
  mois: string
  rien: string[]; misDeCote: number | null; poche: string | null
}): Promise<{ cloture: string; non_soldees: NonSoldee[] }> {
  const { data, error } = await supabase.rpc('cloture_le_mois', {
    /* `factures: []` : « C'est ça » et « Modifier » valident tout de suite (choix 17) ; la base
       confirme ce qui reste à son montant. */
    le_mois: c.mois, factures: [], rien: c.rien,
    /* `undefined`, pas `null` : la clé ne part pas, et la base prend son défaut —
       `null`, c'est-à-dire « tout ce qui reste », et aucune poche. Les types
       générés n'acceptent pas `null` pour un paramètre à défaut. */
    mis_de_cote_cents: c.misDeCote ?? undefined, la_poche: c.poche ?? undefined })
  if (error) throw new Error(error.message)
  return data as { cloture: string; non_soldees: NonSoldee[] }
}
export function useClotureLeMois() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: clotureLeMois,
    /* Ce qui n'a pas pu être soldé se dit sous le chiffre du mois (§ 3.5) : la
       page de clôture n'est plus là pour le dire. */
    onSuccess: (r, c) => { retientNonSoldees(qc, c.mois, r.non_soldees) },
    /* ⚠️ `onSettled`, pas `onSuccess` : une réponse perdue après que la base a clos le mois
       finit en erreur ici, et `['cloture']` restait périmé — chaque clic répondait alors
       « déjà clôturé », sans que la page sache jamais que le mois l'est. Réussie ou non, on
       relit ; TanStack attend cette promesse avant de déclarer la mutation finie. */
    onSettled: () => relisLeBudget(qc),
  })
}

/** Les années qu'une clôture n'a pas pu solder, telles qu'elle les a rendues. Rien
    en base ne les garde : la clôture suivante réessaie, et le redit. */
export function useNonSoldees(mois: string) {
  return useQuery({ queryKey: cleNonSoldees(mois), queryFn: () => [] as NonSoldee[],
                    staleTime: Infinity })
}

export async function rouvreLeMois(mois: string) {
  const { error } = await supabase.rpc('rouvre_le_mois', { le_mois: mois })
  if (error) throw new Error(error.message)
}
export function useRouvreLeMois() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: rouvreLeMois,
    onSuccess: (_r, mois) => { oublieNonSoldees(qc, mois) },
    /* `onSettled` : une réouverture dont la réponse se perd a pourtant rouvert le mois (voir
       `useClotureLeMois`). */
    onSettled: () => relisLeBudget(qc),
  })
}

export type Solde = { charge: string; libelle: string; annee: number; cents: number }
export async function lisApercuDesSoldes(mois: string): Promise<Solde[]> {
  return ou(await supabase.rpc('apercu_des_soldes', { le_mois: mois })) as Solde[]
}
export function useApercuDesSoldes(mois: string, actif = true) {
  return useQuery({ queryKey: ['apercu-des-soldes', mois], enabled: actif,
                    queryFn: () => lisApercuDesSoldes(mois) })
}

// ── Retirer une charge ───────────────────────────────────────────────────────
export type Retrait = { sort: 'supprimee' | 'archivee' }
  | { aConfirmer: { cents: number; message: string } }

/**
 * « Retirer » (0111). Une saisie ne part pas sans qu'on l'ait vue : la base
 * refuse d'abord, avec le total (`hint` = `avec_les_saisies`, `details` = les
 * centimes). L'écran demande alors « Retirer Courses et ses 430 € déclarés ? »,
 * puis rappelle avec `avecLesSaisies`.
 */
export async function retireCharge(id: string, avecLesSaisies = false): Promise<Retrait> {
  const { data, error } = await supabase.rpc('retire_charge',
    { p_charge: id, avec_les_saisies: avecLesSaisies })
  if (error) {
    if (error.hint === 'avec_les_saisies') {
      return { aConfirmer: { cents: Number(error.details), message: error.message } }
    }
    throw new Error(error.message)
  }
  return { sort: data as 'supprimee' | 'archivee' }
}
export function useRetireLaCharge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (r: { id: string; avecLesSaisies?: boolean }) => retireCharge(r.id, r.avecLesSaisies),
    onSuccess: () => relisLeBudget(qc),
  })
}

/** Changer de catégorie : un simple `update`, sous la policy `charge_update` (§ 4.1).
    Rien d'autre ne bouge. */
export function useChangeCategorie() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (c: { id: string; categorie: Categorie }) =>
      ou(await supabase.from('charge').update({ categorie: c.categorie }).eq('id', c.id).select().single()),
    onSuccess: () => relisLeBudget(qc),
  })
}
