/**
 * Les calculs de l'écran du mois — purs, sans réseau (§ 6.2).
 *
 * La base porte l'argent ; ce module le lit et le montre. Il ne recompte que ce
 * que l'écran affiche avant elle : le montant d'une ligne au fil du mois tant
 * que le mois est ouvert (le plus grand du prévu et du déclaré), et ce que la
 * clôture laissera. Tout est en CENTIMES ENTIERS.
 */
import { md5 } from '../md5.ts'
import { CATEGORIES, infoCategorie, rangDeCategorie, type Categorie, type Mode } from './categories.ts'

export type Facon = Mode
export type Part = { user_profile_id: string; part_cents: number; part_bps?: number }
/** Une ligne du mois, telle que `useMois` la lit. */
export type Ligne = {
  id: string; charge_id: string | null; libelle: string
  montant_cents: number; montant_prevu_cents: number | null
  /** La façon de la LIGNE, figée à sa naissance (§ 4.1). Null : un ajustement. */
  facon: Facon | null
  confirme_le: string | null
  regularise_annee: number | null
  parts: Part[]
}
export type Saisie = {
  id: string; depense_id: string; fait_le: string; montant_cents: number
  saisi_par: string | null
}
export type ChargeVue = { id: string; categorie: Categorie | string; commun: boolean }
export type Revenu = { user_profile_id: string; net_mensuel_cents: number; valid_from: string }
export type Filtre = 'tout' | 'commun' | 'moi'

/** « 4 325 € », « 426,80 € » : sans « ,00 » quand le montant est rond. */
export function montant(cents: number): string {
  const rond = cents % 100 === 0
  const s = (Math.abs(cents) / 100).toLocaleString('fr-FR', {
    minimumFractionDigits: rond ? 0 : 2, maximumFractionDigits: 2 })
  return `${cents < 0 ? '−' : ''}${s} €`
}

const ORDRE_DU_FILTRE: Filtre[] = ['tout', 'commun', 'moi']

/**
 * La flèche d'un `radiogroup` : → et ↓ vont au suivant, ← et ↑ au précédent, en boucle.
 * Toute autre touche rend `null` : Tab, Entrée et les lettres restent au navigateur.
 */
export function filtreVoisin(filtre: Filtre, touche: string): Filtre | null {
  const pas = touche === 'ArrowRight' || touche === 'ArrowDown' ? 1
    : touche === 'ArrowLeft' || touche === 'ArrowUp' ? -1 : 0
  if (pas === 0) return null
  return ORDRE_DU_FILTRE[(ORDRE_DU_FILTRE.indexOf(filtre) + pas + ORDRE_DU_FILTRE.length) % ORDRE_DU_FILTRE.length]
}

/**
 * Un reste non nul que l'arrondi à l'euro ferait disparaître (−0,30 € devient « 0 € »).
 * Le hub arrondit ses gros chiffres ; sur ceux-là il dit les centimes, parce que « Il te
 * manque 0 € » est faux et que le signe, lui, ne se lit plus.
 */
export function sousLEuro(cents: number): boolean {
  const a = Math.abs(cents)
  return a !== 0 && Math.round(a / 100) === 0
}

/** La façon d'une ligne. Celle de la charge ne sert qu'à « Mes charges ». */
export function facon(l: Ligne): Facon | 'ajustement' {
  return l.facon ?? 'ajustement'
}

export function prevu(l: Ligne): number {
  return l.montant_prevu_cents ?? l.montant_cents
}

/** Ce qui a été déclaré sur une ligne au fil du mois. */
export function declare(l: Ligne, saisies: Saisie[]): number {
  let total = 0
  for (const s of saisies) if (s.depense_id === l.id) total += s.montant_cents
  return total
}

export function aDesSaisies(l: Ligne, saisies: Saisie[]): boolean {
  return saisies.some(s => s.depense_id === l.id)
}

/**
 * Ce que la ligne pèse dans le mois, pour le foyer (§ 3.1.1). Mois ouvert, ligne
 * au fil du mois : max(prévu, déclaré), confirmée ou non — le chiffre ne baisse
 * que si l'on dépasse, et ne remonte qu'à la clôture. Partout ailleurs : la base.
 */
export function montantCompte(l: Ligne, saisies: Saisie[], clos: boolean): number {
  if (clos || l.facon !== 'au_fil') return l.montant_cents
  return Math.max(prevu(l), declare(l, saisies))
}

/**
 * Ma part de `cents`, comme la base la répartirait (`confirme_depense`, 0072) : au poids des
 * POINTS DE BASE des parts ; à défaut (aucun point), au poids de leurs centimes ; à défaut, à parts
 * égales. Chacun reçoit le plancher de sa part et les centimes restants vont aux plus forts restes.
 *
 * Lire la proportion sur les centimes seuls était faux sur une ligne rouverte : ses parts sont
 * celles du réel (47,90 €), arrondies au centime, et recompter le prévu (800 €) multipliait cet
 * arrondi par ×16,7 : le reste dérivait de six centimes. Les points de base, eux, ne s'arrondissent
 * pas avec le montant. L'égalité d'un reste à l'autre se départage COMME la base : par
 * `md5(uid::text || ligne::text)` (`confirme_la_ligne` 0104, `repartit_les_lignes` 0100/0112). En 50/50
 * avec un montant impair l'égalité est systématique, et un départage par identifiant donnait le
 * centime à l'autre : `maPart` d'une ligne dépassée et le récap de clôture différaient de la base.
 */
function prorata(l: Ligne, moi: string, cents: number): number {
  if (!l.parts.some(p => p.user_profile_id === moi)) return 0
  const poidsBps = l.parts.map(p => Math.max(0, p.part_bps ?? 0))
  const poidsCents = l.parts.map(p => Math.abs(p.part_cents))
  const somme = (v: number[]) => v.reduce((t, x) => t + x, 0)
  const poids = somme(poidsBps) > 0 ? poidsBps : somme(poidsCents) > 0 ? poidsCents : l.parts.map(() => 1)
  const total = somme(poids)
  const signe = cents < 0 ? -1 : 1
  const a = Math.abs(cents)
  const lignes = l.parts.map((p, i) => ({
    id: p.user_profile_id,
    base: Math.floor((a * poids[i]) / total),
    reste: (a * poids[i]) % total,
  }))
  let manque = a - lignes.reduce((t, x) => t + x.base, 0)
  /* `md5` en hexadécimal minuscule : chiffres puis a-f, le même ordre que la base. */
  const rang = new Map(lignes.map(x => [x.id, md5(x.id + l.id)]))
  const ordre = [...lignes].sort((x, y) =>
    y.reste - x.reste || (rang.get(x.id)! < rang.get(y.id)! ? -1 : 1))
  const bonus = new Set<string>()
  for (const x of ordre) {
    if (manque <= 0) break
    bonus.add(x.id)
    manque--
  }
  const mienne = lignes.find(x => x.id === moi)!
  return signe * (mienne.base + (bonus.has(moi) ? 1 : 0))
}

/** Ma part d'un montant, dans la proportion de mes parts sur la ligne. */
export function partSur(l: Ligne, moi: string, cents: number): number {
  const mienne = l.parts.find(p => p.user_profile_id === moi)
  if (!mienne) return 0
  if (cents === l.montant_cents) return mienne.part_cents
  return prorata(l, moi, cents)
}

/** Ma part de la ligne, comme « Il te reste » la compte (§ 3.1.1). « Voir une ligne
    ne veut pas dire la payer » (D80) : sans part, elle ne compte pas. */
export function maPart(l: Ligne, moi: string, saisies: Saisie[], clos: boolean): number {
  if (clos || l.facon !== 'au_fil') {
    return l.parts.find(p => p.user_profile_id === moi)?.part_cents ?? 0
  }
  return partSur(l, moi, montantCompte(l, saisies, false))
}

/** « 2026-10-31 » pour « 2026-10-01 ». */
export function dernierJour(mois: string): string {
  const [a, m] = mois.split('-').map(Number)
  return `${mois.slice(0, 7)}-${String(new Date(a, m, 0).getDate()).padStart(2, '0')}`
}

/**
 * Le revenu du mois : celui dont le `valid_from` est le plus récent sans dépasser
 * le dernier jour du mois, comme la base. Ne garder que le dernier posé faisait
 * afficher décembre « sur 4 500 € » quand le revenu changeait en janvier.
 */
export function revenuDuMois(revenus: Revenu[], qui: string, mois: string): number | null {
  const fin = dernierJour(mois)
  let retenu: Revenu | null = null
  for (const r of revenus) {
    if (r.user_profile_id !== qui || r.valid_from > fin) continue
    if (!retenu || r.valid_from > retenu.valid_from) retenu = r
  }
  return retenu ? retenu.net_mensuel_cents : null
}

/**
 * Le membre habite déjà là ce mois-là : son `entre_le` ne dépasse pas le dernier jour du mois.
 * Avant, il ne porte aucune part (la base ne lui en donne pas) et on ne lui demande rien.
 */
export function estLaCeMois(m: { entre_le?: string | null }, mois: string): boolean {
  /* Une arrivée inconnue ne cache personne : on ne dit « pas encore là » que sur une date. */
  return !m.entre_le || m.entre_le <= dernierJour(mois)
}

/**
 * Le mois où un revenu posé AUJOURD'HUI prend effet : le courant, ou le mois d'arrivée quand elle est à
 * venir. Daté du mois courant, le revenu de qui n'arrive qu'en novembre donnait à octobre un reste plein
 * (« Il te reste 2 400 € ») et un « Octobre est à clôturer » sur un mois qui n'est pas le sien.
 */
export function moisDeDepart(entreLe: string | null | undefined, courant: string): string {
  const arrivee = entreLe ? `${entreLe.slice(0, 7)}-01` : null
  return arrivee && arrivee > courant ? arrivee : courant
}

/**
 * Ceux qui sont là ce mois-là et n'ont pas de revenu : le partage bascule alors en
 * moitié-moitié. Seul (ou presque : une seule personne présente), il n'y a rien à partager.
 * Celle qui arrive en octobre ne « manque » pas de revenu en septembre.
 */
export function membresSansRevenu<M extends { id: string; entre_le?: string | null }>(
  membres: M[], revenus: Revenu[], mois: string,
): M[] {
  const presents = membres.filter(m => estLaCeMois(m, mois))
  return presents.length < 2 ? [] : presents.filter(m => revenuDuMois(revenus, m.id, mois) === null)
}

/**
 * Un mois CLOS où la personne n'a ni revenu ni part : la clôture s'est faite sans elle. Elle est arrivée
 * (ou a posé son premier revenu) après, et un mois clos ne se recalcule pas. Sans cette règle, l'écran lui
 * lisait « Il t'est resté — » (un tiret) et, sous le chiffre, qu'elle « n'a pas encore dit son revenu ».
 */
export function clotureSansMoi(o: { clos: boolean; revenu: number | null; charges: number }): boolean {
  return o.clos && o.revenu === null && o.charges === 0
}

export type Reste = { revenu: number | null; charges: number; reste: number | null }

/** « Il te reste » : mon revenu du mois, moins ma part de chaque ligne. */
export function resteDuMois(o: {
  lignes: Ligne[]; saisies: Saisie[]; moi: string; revenus: Revenu[]; mois: string; clos: boolean
}): Reste {
  const charges = o.lignes.reduce((t, l) => t + maPart(l, o.moi, o.saisies, o.clos), 0)
  const revenu = revenuDuMois(o.revenus, o.moi, o.mois)
  return { revenu, charges, reste: revenu === null ? null : revenu - charges }
}

function categorieDe(l: Ligne, charges: Map<string, ChargeVue>): Categorie {
  return infoCategorie((l.charge_id && charges.get(l.charge_id)?.categorie) || 'autre').cle
}

/**
 * Le filtre (§ 3.1, point 8). « Commun » : les lignes dont la charge est
 * commune. « Moi » : mes lignes perso. « Tout » : les deux — y compris les
 * lignes perso de l'autre, parce que c'est un seul foyer (D80).
 */
export function dansLeFiltre(l: Ligne, charges: Map<string, ChargeVue>, filtre: Filtre,
                             moi: string): boolean {
  if (filtre === 'tout') return true
  const commune = (l.charge_id && charges.get(l.charge_id)?.commun) || false
  if (filtre === 'commun') return commune
  return !commune && l.parts.some(p => p.user_profile_id === moi)
}

export function totauxDuFiltre(lignes: Ligne[], charges: Map<string, ChargeVue>,
                               saisies: Saisie[], moi: string, clos: boolean): Record<Filtre, number> {
  const t = { tout: 0, commun: 0, moi: 0 }
  for (const l of lignes) {
    const m = montantCompte(l, saisies, clos)
    for (const f of ['tout', 'commun', 'moi'] as const) {
      if (dansLeFiltre(l, charges, f, moi)) t[f] += m
    }
  }
  return t
}

/**
 * Une ligne « à dire » : au fil du mois, sans aucune saisie, dans un mois
 * ouvert. Une facture du mois n'en est pas : on la valide à la clôture, et elle
 * ne doit pas rester signalée tout le mois.
 */
export function estADire(l: Ligne, saisies: Saisie[], clos: boolean): boolean {
  return !clos && l.facon === 'au_fil' && !aDesSaisies(l, saisies)
}

export function aDire(lignes: Ligne[], saisies: Saisie[], clos: boolean): number {
  return lignes.filter(l => estADire(l, saisies, clos)).length
}

/** Générique : l'écran y range ses `Depense`, et les retrouve telles quelles. */
export type CategorieDuMois<L extends Ligne = Ligne> = {
  cle: Categorie; nom: string; total: number; lignes: L[]; aDire: number
}

/** Les catégories du filtre, par montant décroissant, et dans l'ordre de D74 à montant
    égal. Une catégorie sans ligne ne s'affiche pas. */
export function parCategorie<L extends Ligne>(o: {
  lignes: L[]; charges: Map<string, ChargeVue>; saisies: Saisie[]
  filtre: Filtre; moi: string; clos: boolean
}): CategorieDuMois<L>[] {
  const groupes = new Map<Categorie, L[]>()
  for (const l of o.lignes) {
    if (!dansLeFiltre(l, o.charges, o.filtre, o.moi)) continue
    const c = categorieDe(l, o.charges)
    groupes.set(c, [...(groupes.get(c) ?? []), l])
  }
  const poids = (l: L) => montantCompte(l, o.saisies, o.clos)
  return [...groupes].map(([cle, lignes]) => ({
    cle, nom: infoCategorie(cle).nom,
    total: lignes.reduce((t, l) => t + poids(l), 0),
    lignes: [...lignes].sort((a, b) => poids(b) - poids(a)
                                       || a.libelle.localeCompare(b.libelle, 'fr')),
    aDire: lignes.filter(l => estADire(l, o.saisies, o.clos)).length,
  })).sort((a, b) => b.total - a.total || rangDeCategorie(a.cle) - rangDeCategorie(b.cle))
}

/** Des pourcentages entiers dont la somme fait 100, au plus fort reste. Une valeur
    négative ou nulle vaut 0. Arrondis un à un, 33 + 33 + 33 faisait 99. */
export function pourcentages(valeurs: number[]): number[] {
  const v = valeurs.map(x => Math.max(0, Math.round(x)))
  const total = v.reduce((t, x) => t + x, 0)
  if (total === 0) return v.map(() => 0)
  const bas = v.map(x => Math.floor((x * 100) / total))
  let manque = 100 - bas.reduce((t, x) => t + x, 0)
  const ordre = v.map((x, i) => ({ i, r: (x * 100) % total }))
    .sort((a, b) => b.r - a.r || a.i - b.i)
  for (const { i } of ordre) {
    if (manque <= 0) break
    bas[i]++
    manque--
  }
  return bas
}

export type Segment = { cle: Categorie | 'reste'; nom: string; cents: number; pourcent: number }

/**
 * La barre du récap (§ 3.1, point 4) : mes parts par catégorie, et ce qui reste,
 * en part du revenu. Quand il manque de l'argent, elle se répartit sur le total
 * des charges, sans segment « Reste ».
 */
export function barre(o: {
  lignes: Ligne[]; charges: Map<string, ChargeVue>; saisies: Saisie[]
  moi: string; revenu: number; clos: boolean
}): Segment[] {
  const parCat = new Map<Categorie, number>()
  for (const l of o.lignes) {
    const c = categorieDe(l, o.charges)
    parCat.set(c, (parCat.get(c) ?? 0) + maPart(l, o.moi, o.saisies, o.clos))
  }
  /* Le reste se compte sur TOUTES les parts nettes, y compris celles d'une catégorie à 0 ou
     en négatif (un solde réglé) : seul l'affichage les écarte. Sinon « Reste » ne valait plus
     « Il te reste » (`resteDuMois` les compte). */
  const reste = o.revenu - [...parCat.values()].reduce((t, c) => t + c, 0)
  const cats = [...parCat].filter(([, cents]) => cents > 0)
    .sort((a, b) => b[1] - a[1] || rangDeCategorie(a[0]) - rangDeCategorie(b[0]))
    .map(([cle, cents]) => ({ cle: cle as Categorie | 'reste', nom: infoCategorie(cle).nom, cents }))
  const tous = reste > 0 ? [...cats, { cle: 'reste' as const, nom: 'Reste', cents: reste }] : cats
  const p = pourcentages(tous.map(s => s.cents))
  return tous.map((s, i) => ({ ...s, pourcent: p[i] }))
}

export const NOMS_DES_MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
  'août', 'septembre', 'octobre', 'novembre', 'décembre'] as const

export function nomDuMois(iso: string): string {
  return NOMS_DES_MOIS[Number(iso.slice(5, 7)) - 1]
}

/** « septembre » pour l'année courante, « septembre 2025 » sinon : un mois d'une autre année
    se nomme avec son année, ou l'adresse `/cloture/2025-09` lisait « Clôturer septembre ». */
export function nomDuMoisDate(mois: string, courant: string): string {
  return mois.slice(0, 4) === courant.slice(0, 4) ? nomDuMois(mois) : `${nomDuMois(mois)} ${mois.slice(0, 4)}`
}

/**
 * Le mois que `/budget/AAAA-MM` demande. Jamais au-delà du mois courant : l'ouvrir créerait ses
 * lignes avec la clé du jour, figée. Un mois à venir rend le courant ET `futur` : l'écran quitte
 * alors l'adresse, au lieu d'afficher le mois courant sous une adresse 2030. Une adresse qui ne
 * se lit pas retombe sur le courant, sans rien à rediriger.
 */
export function moisDemande(depart: string | undefined, courant: string): { mois: string; futur: boolean } {
  if (!depart || !/^\d{4}-(0[1-9]|1[0-2])-01$/.test(depart)) return { mois: courant, futur: false }
  return depart <= courant ? { mois: depart, futur: false } : { mois: courant, futur: true }
}

/**
 * `/budget/…` ou `/cloture/…` dont la suite n'est pas un mois (`2026-13`, `abc`, `2026-1`) : l'écran
 * ne sait pas la lire, et affichait le hub sous cette adresse, qui ne se corrigeait pas. Un mois
 * entier (`AAAA-MM`, même à venir) n'est PAS fausse : `moisDemande` s'occupe du futur.
 */
export function adresseDeMoisFausse(chemin: string): boolean {
  const m = chemin.match(/^\/(?:budget|cloture)\/(.*)$/)
  return m !== null && !/^\d{4}-(0[1-9]|1[0-2])$/.test(m[1])
}

export function capitale(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function moisVoisin(iso: string, pas: number): string {
  const [a, m] = iso.split('-').map(Number)
  const d = new Date(a, m - 1 + pas, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/** « Il reste N jours. », sur le mois courant seulement. On compte des JOURS : le dernier
    jour à 14 h, il en reste 0 (« Dernier jour. »). */
export function joursRestants(mois: string, aujourdhui: string): number | null {
  if (aujourdhui.slice(0, 7) !== mois.slice(0, 7)) return null
  return Number(dernierJour(mois).slice(8)) - Number(aujourdhui.slice(8))
}

const JOURS_COURTS = ['Dim.', 'Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.']
const MOIS_COURTS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août',
  'sept.', 'oct.', 'nov.', 'déc.']

/** « Sam. 3 oct. » */
export function dateCourte(iso: string): string {
  const [a, m, j] = iso.split('-').map(Number)
  return `${JOURS_COURTS[new Date(a, m - 1, j).getDay()]} ${j} ${MOIS_COURTS[m - 1]}`
}

/** Ferme une phrase par un point, sans doubler celui d'une abréviation : « …et le Jeu. 15 oct.. » */
export function finDePhrase(s: string): string {
  return s.endsWith('.') ? s : `${s}.`
}

function veille(iso: string): string {
  const [a, m, j] = iso.split('-').map(Number)
  const d = new Date(a, m - 1, j - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${
    String(d.getDate()).padStart(2, '0')}`
}

/**
 * Les jours qu'on propose pour une dépense (§ 3.2) : toujours dans le mois
 * affiché. Mois courant : « Aujourd'hui », « Hier » (pas le 1er), et un autre
 * jour jusqu'à aujourd'hui. Mois passé : son dernier jour, et un autre jour du
 * mois. Une dépense n'est pas dans l'avenir.
 */
export function joursProposes(mois: string, aujourdhui: string): {
  choix: { libelle: string; date: string }[]; min: string; max: string
} {
  if (aujourdhui.slice(0, 7) === mois.slice(0, 7)) {
    const choix = [{ libelle: 'Aujourd’hui', date: aujourdhui }]
    if (aujourdhui.slice(8) !== '01') choix.push({ libelle: 'Hier', date: veille(aujourdhui) })
    return { choix, min: mois, max: aujourdhui }
  }
  const dernier = dernierJour(mois)
  return { choix: [{ libelle: dateCourte(dernier), date: dernier }], min: mois, max: dernier }
}

export const JOUR_DU_RAPPEL = 27

export type Bandeau = { genre: 'rappel' | 'bientot' | 'cloturer'; mois: string } | null

/**
 * Le bandeau du mois (§ 3.1, point 9) : un seul à la fois, et celui du mois
 * précédent non clôturé passe devant les autres. Les bandeaux de clôture ne
 * paraissent que si j'ai un revenu ce mois-là : sans revenu (janvier à août
 * 2026), un mois ne se clôture pas, et rien ne le propose.
 */
export function bandeau(o: {
  mois: string; aujourdhui: string; clos: (m: string) => boolean; aRevenu: (m: string) => boolean
}): Bandeau {
  const courant = `${o.aujourdhui.slice(0, 7)}-01`
  if (o.clos(o.mois)) return null
  if (o.mois === courant) {
    const precedent = moisVoisin(courant, -1)
    if (!o.clos(precedent) && o.aRevenu(precedent)) return { genre: 'cloturer', mois: precedent }
    return { genre: Number(o.aujourdhui.slice(8)) >= JOUR_DU_RAPPEL ? 'bientot' : 'rappel',
             mois: o.mois }
  }
  if (o.mois < courant && o.aRevenu(o.mois)) return { genre: 'cloturer', mois: o.mois }
  return null
}

/**
 * La seconde ligne de la carte Budget du hub (§ 3.6). `noms` : les lignes à dire — « 2 montants à
 * dire » ne disait pas lesquels, et une arrivante ne devinait pas par où commencer. Trois noms au
 * plus, puis « et N autres » ; sans noms (non lus), le compte seul.
 */
export function ligneDuHub(o: { aCloturer: string | null; aDire: number; noms?: string[] }): string {
  if (o.aCloturer) return `${capitale(nomDuMois(o.aCloturer))} est à clôturer`
  if (o.aDire > 0) {
    const compte = `${o.aDire} montant${o.aDire > 1 ? 's' : ''} à dire`
    const noms = (o.noms ?? []).filter(n => n.trim() !== '')
    if (noms.length === 0) return compte
    const vus = noms.slice(0, 3)
    const autres = noms.length - vus.length
    const liste = autres > 0 ? `${vus.join(', ')} et ${autres} autre${autres > 1 ? 's' : ''}`
      : vus.length > 1 ? `${vus.slice(0, -1).join(', ')} et ${vus[vus.length - 1]}` : vus[0]
    return `${compte} : ${liste}`
  }
  return 'Tout est à jour'
}

/**
 * Ma part des soldes d'année que la clôture posera (`apercu_des_soldes`).
 *
 * Seul au foyer, tout le solde est le mien. À deux, elle n'est PAS lisible : l'aperçu ne rend
 * que le total de la charge, et la base répartit l'ajustement selon ce que chacun a porté sur
 * l'année (`recale_l_annee`, `porte_par`) — pas selon les parts de la ligne du mois. Au prorata
 * de décembre, Kamil lisait −83,34 € là où la base lui posait −125 € (Thauba arrivée en
 * novembre : `tests/budget-solde-part.test.ts`). Plutôt qu'un faux chiffre, on n'en donne pas :
 * `incertain` dit que le reste est « avant les soldes ». Foyer pas lu : on ne sait pas si l'on
 * est seul, donc incertain aussi. Sans solde, rien à répartir : sûr.
 */
export function partDesSoldes(apercu: { cents: number }[], membres: number | undefined):
  { cents: number; incertain: boolean } {
  if (apercu.length === 0) return { cents: 0, incertain: false }
  if (membres === 1) return { cents: apercu.reduce((t, s) => t + s.cents, 0), incertain: false }
  return { cents: 0, incertain: true }
}

/** `incertain` : le reste est « avant les soldes d'année » — leur part dans mon chiffre n'est pas
    lisible à deux (`partDesSoldes`). Absent quand le chiffre est sûr. */
export type RecapCloture = { prevus: number; ecart: number; reste: number; incertain?: true }

/**
 * Le récap de la clôture (§ 3.5, étape 3). X (`prevus`) : ce qui resterait si
 * chaque ligne au fil du mois coûtait son prévu, soldes d'année compris. Y
 * (`ecart`) : l'écart net de l'étape 2, prévu moins réel. X + Y fait le chiffre.
 * Le tout en MES parts, comme « Il te reste ».
 *
 * Le réel d'une ligne au fil du mois est ce que la clôture retiendra : la somme
 * des saisies s'il y en a ; 0 si « Rien dépensé » ; sinon le prévu.
 */
export function recapCloture(o: {
  revenu: number; lignes: Ligne[]; saisies: Saisie[]; moi: string
  rien: Set<string>
  /** Ma part des soldes ; `null` quand elle n'est pas lisible (`partDesSoldes`) : le récap est alors « avant les soldes ». */
  soldes: number | null
}): RecapCloture {
  let prevus = o.revenu - (o.soldes ?? 0)
  let ecart = 0
  for (const l of o.lignes) {
    if (l.facon === 'au_fil') {
      const p = prevu(l)
      const reel = aDesSaisies(l, o.saisies) ? declare(l, o.saisies)
        : l.charge_id && o.rien.has(l.charge_id) ? 0 : p
      prevus -= partSur(l, o.moi, p)
      ecart += partSur(l, o.moi, p) - partSur(l, o.moi, reel)
    } else {
      prevus -= l.parts.find(p => p.user_profile_id === o.moi)?.part_cents ?? 0
    }
  }
  return { prevus, ecart, reste: prevus + ecart, ...(o.soldes === null ? { incertain: true as const } : {}) }
}

export { CATEGORIES }
