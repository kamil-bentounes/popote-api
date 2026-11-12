/**
 * Ce que les trois feuilles — « Déclarer », « Facture du mois », « Facture mise de
 * côté » — décident quand l'argent est en jeu (§ 3.2 à 3.4). Pur, sans réseau :
 * l'écran n'a pas de banc de composants, c'est ici que le test fige les règles.
 *
 * Tout est en CENTIMES ENTIERS. La base reste le juge : ce module dit d'avance ce
 * qu'elle acceptera, pour que le refus se lise AVANT l'envoi.
 */
import { enCentimes, type Charge, type EtatAnnee } from '../donnees/budget.ts'
import { dateCourte, montant, nomDuMois, prevu, type Ligne } from './mois.ts'

/** 1 000 000 € : la borne des fonctions de la base (`confirme_la_ligne`, `paie_une_facture`). */
export const PLAFOND_CENTS = 100_000_000

export type MontantTape =
  | { valide: true; cents: number; refus: null }
  | { valide: false; cents: null; refus: string | null }

/**
 * Un montant tapé vers des centimes, ou la phrase qui dit pourquoi pas.
 *
 * Un champ vide ne refuse rien (`refus: null`) : on n'a pas fini de taper, et un
 * message rouge avant la première touche serait un reproche. `zeroOk` : 0 € ne
 * se déclare pas, mais se confirme — c'est ainsi qu'un avoir se saisit (§ 10) ;
 * sans cela, l'électricité prévue à 50 € et remboursée de 50 € compterait ses 50 €.
 */
export function lisLeMontant(saisi: string, o: { zeroOk: boolean }): MontantTape {
  if (saisi.trim() === '') return { valide: false, cents: null, refus: null }
  const cents = enCentimes(saisi)
  if (cents === null || cents > PLAFOND_CENTS) {
    return { valide: false, cents: null,
             refus: o.zeroOk ? 'Un montant, de 0 € à 1 000 000 € : 47 ou 47,90.'
                             : 'Un montant, au plus 1 000 000 € : 47 ou 47,90.' }
  }
  if (cents === 0 && !o.zeroOk) {
    return { valide: false, cents: null, refus: 'Un montant au-dessus de 0 € : 47 ou 47,90.' }
  }
  return { valide: true, cents, refus: null }
}

/**
 * Des centimes vers ce qu'on remet dans un champ à corriger : « 50 », « 47,90 ».
 * Jamais `cents / 100` converti en chaîne : « 0.05 » y perdrait sa virgule
 * française, et le champ se relirait mal.
 */
export function saisiDe(cents: number): string {
  /* Le signe se pose À PART : `Math.trunc(-5 / 100)` vaut -0, que `String` écrit « 0 » —
     « -0,05 » perdait son signe et se relisait « 0,05 ». */
  const signe = cents < 0 ? '-' : ''
  const a = Math.abs(cents)
  const entier = Math.trunc(a / 100)
  const reste = a % 100
  return reste === 0 ? `${signe}${entier}` : `${signe}${entier},${String(reste).padStart(2, '0')}`
}

/**
 * Le montant que la feuille « Facture du mois » montre, et donc celui que « C'est ça »
 * confirme : avant la confirmation, le prévu ; après, le retenu (0 € compris).
 * Sans cela, le bouton pouvait valider un chiffre que la feuille n'affichait pas.
 */
export function montantPropose(l: Ligne): number {
  return l.confirme_le !== null ? l.montant_cents : prevu(l)
}

/** Un envoi : son identifiant, et ce qu'il porte (la clé). */
export type Envoi = { id: string; cle: string }

/**
 * L'identifiant d'un envoi. Un renvoi — une coupure, un double toucher — garde
 * le sien : la base répond 23505, que `ajouteSaisie` prend pour un succès. Mais
 * un envoi qui PORTE autre chose en reçoit un neuf : 50 € perdus par le réseau,
 * puis 30 € tapés, partaient avec l'identifiant des 50 € ; si la base les avait
 * reçus, elle répondait 23505, et les 30 € étaient perdus sans un mot.
 * (Un envoi réussi se remet à `null` : le suivant est toujours neuf.)
 */
export function envoiPour(precedent: Envoi | null, cle: string, neuf: () => string): Envoi {
  return precedent && precedent.cle === cle ? precedent : { id: neuf(), cle }
}

/** Le bouton d'envoi : jamais deux envois en vol, jamais un montant ou un jour refusés. */
export function envoiPermis(o: { valide: boolean; enCours: boolean; jourOk?: boolean }): boolean {
  return o.valide && !o.enCours && o.jourOk !== false
}

/**
 * Un jour tapé à la main est-il dans la fenêtre du champ ? `min` et `max` d'un
 * `<input type="date">` n'empêchent pas la frappe : `onChange` rend quand même
 * la date, et la base refuserait avec un message qu'on aurait pu éviter.
 */
export function jourAccepte(jour: string, min: string, max: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(jour)
  if (!m) return false
  const [a, mo, j] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const d = new Date(a, mo - 1, j)
  // « 2026-02-31 » devient mars : une date qui n'existe pas ne passe pas.
  if (d.getFullYear() !== a || d.getMonth() !== mo - 1) return false
  return jour >= min && jour <= max
}

/**
 * L'année tapée dans « Autre jour » vaut-elle une lecture ? Un `<input type="date">` rend
 * « 0002-10-21 » dès que l'année en est à son deuxième chiffre : chaque frappe changeait
 * l'année de la feuille et lançait `etat_de_l_annee` et `factures` pour rien. On ne lit que
 * pour quatre chiffres, à cinq ans au plus de l'année du jour (la base n'a rien au-delà).
 */
export function anneePlausible(jour: string, aujourdhui: string): boolean {
  const m = /^(\d{4})-\d{2}-\d{2}$/.exec(jour)
  if (!m) return false
  return Math.abs(Number(m[1]) - Number(aujourdhui.slice(0, 4))) <= 5
}

/** Ce qu'une charge mise de côté met de côté chaque mois : l'arrondi de `provision_mensuelle`. */
export function provisionParMois(c: Pick<Charge, 'montant_cents' | 'periodicite'>): number {
  const diviseur = c.periodicite === 'annuel' ? 12 : c.periodicite === 'trimestriel' ? 3 : 1
  return Math.round(c.montant_cents / diviseur)
}

/**
 * « , depuis septembre » : Popote n'a pas suivi toute l'année (D77). Vide quand
 * le premier mois suivi est janvier, ou n'est pas dans l'année affichée.
 */
export function depuisLe(premier: string | null, annee: number): string {
  if (!premier || premier.slice(0, 4) !== String(annee) || premier.slice(5, 7) === '01') return ''
  return `, depuis ${nomDuMois(premier)}`
}

/**
 * Le plus ancien jour que « Autre jour » propose : ni avant le 1er janvier de
 * l'année précédente, ni avant le premier mois suivi — la base refuserait l'un
 * et l'autre.
 */
export function plancherDuJour(jour: string, premier: string | null): string {
  const janvier = `${Number(jour.slice(0, 4)) - 1}-01-01`
  return premier && premier > janvier ? premier : janvier
}

/**
 * Ce que la base posera pour cette facture, dit en français : la formule du § 4.4
 * appliquée au montant tapé, sur ce que `etat_de_l_annee` rend. `mois` est le nom
 * du mois en cours (« octobre »), qui n'est jamais clôturé (D78).
 *
 *   cible = soldée ? B' − Pl : max(0, B' − Pl)      B' = B + la facture
 *   delta = cible − posé
 */
export function apercuFacture(e: EtatAnnee, annee: number, ajout: number, mois: string): string {
  const nouveauB = e.b + ajout
  if (e.soldee) return `${annee} est soldée : les ${montant(ajout)} s’ajoutent à ${mois}.`
  const cible = Math.max(0, nouveauB - e.pl)
  const delta = cible - e.pose
  if (delta > 0 && e.pose === 0) {
    return `${montant(delta)} de plus que les ${montant(e.pl)} prévus pour ${annee} : ils s’ajoutent à ${mois}.`
  }
  /* Une partie de l'écart est déjà posée : « X de plus que le prévu » mentirait
     (le total dépasse de plus que X). On dit ce qui s'ajoute, et que c'est déjà dépassé. */
  if (delta > 0) {
    return `${montant(delta)} de plus s’ajoutent à ${mois} : ${annee} dépasse déjà les ${montant(e.pl)} prévus.`
  }
  if (delta < 0) return `${montant(-delta)} reviennent à ${mois}.`
  return `Il restera ${montant(Math.max(0, e.pl - nouveauB))} de côté pour ${annee}.`
}

/** La question avant de retirer une facture : son montant et son jour, pas « Êtes-vous sûr ? ». */
export function questionDeRetrait(cents: number, payeLe: string, mois: string): string {
  return `Retirer la facture de ${montant(cents)} du ${dateCourte(payeLe)} ? L’écart se recalcule sur ${mois}.`
}

/** L'effet de la correction du total d'un relevé (§ 3.4) : la différence, sur le mois en cours. */
export function apercuReleve(ancien: number, corrige: number, mois: string): string {
  const d = corrige - ancien
  if (d === 0) return 'Rien ne change.'
  return d > 0 ? `${montant(d)} de plus que le relevé : ils s’ajoutent à ${mois}.`
               : `${montant(-d)} de moins que le relevé : ils reviennent à ${mois}.`
}

/**
 * Retirer de l'épargne : jamais plus que ce que CETTE personne y a versé (« ce qui est versé
 * appartient à qui l'a versé »). Grand test, parcours budget : « Je retire 100 000 € » sur une
 * poche d'urgence de 380 € était accepté, et la poche affichait −99 620 € (la table n'a aucun
 * plancher : la garde est ici). `null` : le retrait passe.
 */
export function refusDuRetrait(cents: number, monSolde: number): string | null {
  if (cents <= monSolde) return null
  return monSolde <= 0
    ? 'Tu n’as rien versé ici : il n’y a rien à retirer.'
    : `Tu n’as versé que ${montant(monSolde)} ici : tu ne peux pas en retirer plus.`
}
