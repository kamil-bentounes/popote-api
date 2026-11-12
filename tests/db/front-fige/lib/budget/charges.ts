/**
 * Ce que « Mes charges » décide, sans écran : les phrases, les filtres et les
 * comparaisons qui touchent à l'argent. Tenus ici pour qu'un test puisse les
 * figer — l'écran, lui, n'a pas de banc de composants.
 */
import { infoCategorie, NOM_DU_MODE, type Categorie, type Mode } from './categories.ts'
import { montant, moisDeDepart, nomDuMois } from './mois.ts'
import { lisLeMontant } from './feuilles.ts'
import type { Retrait } from '../donnees/budget.ts'

export type Rythme = 'trimestriel' | 'annuel'

/**
 * La charge pèse-t-elle dans ce mois ? Son départ ne dépasse pas le mois : l'écran du mois n'a
 * aucune ligne pour une charge qui démarre plus tard. « Mes charges » la comptait pourtant dans
 * « … par mois pour le foyer » : 3 988,57 € là où le mois en lisait 3 978,57 €, pour une charge
 * qui ne démarre qu'en 2031.
 */
export function enVigueur(c: { debut: string }, mois: string): boolean {
  return c.debut.slice(0, 7) <= mois.slice(0, 7)
}

/** Ce que la liste dit d'une charge qui ne court pas encore : son mois de départ. Null si elle court. */
export function departDeLaCharge(c: { debut: string }, mois: string): string | null {
  if (enVigueur(c, mois)) return null
  return `commence en ${nomDuMois(c.debut)} ${c.debut.slice(0, 4)}`
}

/**
 * Pourquoi une charge ne compte PAS ce mois-là, ou null si elle compte. UN seul prédicat, pour la liste des charges
 * comme pour le mois type et le tableau de toutes les charges :
 * - `debut` : elle commence plus tard ;
 * - `arrivee` : aucun de ses participants n'est encore dans le foyer — la base ne lui crée alors aucune ligne (0098).
 * `presents` : ceux qui sont dans le foyer CE mois-là. Le départ passe avant l'arrivée, comme dans le mois type.
 */
export function pourquoiElleNeComptePas(
  c: { debut: string; participants: string[] }, mois: string, presents: ReadonlySet<string>,
): 'debut' | 'arrivee' | null {
  if (!enVigueur(c, mois)) return 'debut'
  return c.participants.some(q => presents.has(q)) ? null : 'arrivee'
}

/**
 * « 3 978,57 € par mois pour le foyer, une fois tout ramené au mois. » Null tant que les charges ne sont
 * pas lues : un total qu'on n'a pas lu n'est pas zéro. Avant, l'écran affirmait « 0,00 € par mois » le temps
 * du chargement, puis changeait de chiffre sous les yeux de qui venait de le lire.
 * `total` et `avance` sont déjà écrits en euros ; `avance` est null quand rien n'est payé de son propre compte.
 */
export function phraseDuTotal(o: { lu: boolean; total: string; avance: string | null; pourToi: boolean }): string | null {
  if (!o.lu) return null
  const base = `${o.total} par mois ${o.pourToi ? 'pour toi' : 'pour le foyer'}, une fois tout ramené au mois.`
  return o.avance ? `${base} Dont ${o.avance} que tu paies depuis ton propre compte.` : base
}

/**
 * Que faire de la réponse de « Retirer » (0111). Une saisie ne part pas sans
 * qu'on l'ait vue : la base refuse d'abord avec le total, on le demande, puis on
 * rappelle. Un refus de l'utilisateur ne rappelle JAMAIS — sinon les dépenses
 * déclarées partiraient sans son accord.
 */
export function suiteDuRetrait(r: Retrait, libelle: string, confirmer: (question: string) => boolean):
  { dit: string } | { rappeler: true } | { rien: true } {
  if ('aConfirmer' in r) {
    return confirmer(`Retirer ${libelle} et ses ${montant(r.aConfirmer.cents)} déclarés ?`)
      ? { rappeler: true } : { rien: true }
  }
  return { dit: r.sort === 'supprimee'
    ? `« ${libelle} » retirée.`
    : `« ${libelle} » retirée. Les mois que tu as confirmés ou réglés la gardent : c’est de l’argent sorti.` }
}

/** Les mises de côté retirées qui attendent encore une facture : elles gardent leur
    feuille jusqu'au 31 décembre de l'année qui suit leur retrait (§ 3.7). Sans cela,
    la régularisation de copropriété votée en avril n'aurait plus d'endroit où entrer. */
export function retireesEncoreAReg<C extends { archive_le: string | null; mode: Mode }>(
  charges: C[], annee: number): C[] {
  return charges.filter(c => c.archive_le && c.mode === 'mis_de_cote'
    && Number(c.archive_le.slice(0, 4)) + 1 >= annee)
}

/** Sous le nom d'une retirée : l'année de son retrait. `soldee` inconnu (pas encore lu)
    ne prétend pas qu'elle l'est : mieux vaut un « reste à régler » de trop qu'une
    facture oubliée. */
export function texteDeLaRetiree(soldee: boolean | undefined, annee: number): string {
  return soldee ? `Retirée en ${annee}` : `${annee} reste à régler`
}

/** La périodicité qui sort d'une façon : seule la mise de côté n'est pas mensuelle.
    Le rythme resté en mémoire (« annuel ») ne doit pas fuir sur une charge fixe. */
export function periodiciteDeLaFacon(mode: Mode, rythme: Rythme): 'mensuel' | Rythme {
  return mode === 'mis_de_cote' ? rythme : 'mensuel'
}

/** Le bout de sous-titre d'une charge : sa catégorie, et sa façon quand elle n'est
    pas « Fixe » (qui est le cas ordinaire, donc muet). */
export function sousTitreDeLaFacon(c: { categorie: Categorie | string; mode: Mode }): string {
  return ` · ${infoCategorie(c.categorie).nom}`
    + (c.mode !== 'fixe' ? ` · ${NOM_DU_MODE[c.mode].toLowerCase()}` : '')
}

/**
 * Ce qu'une correction change. L'argent passe par `corrige_la_charge`, qui refait
 * les mois ; la catégorie, par un simple `update`. Une catégorie seule n'appelle pas
 * la première : « 0 mois refait » aurait laissé croire qu'on avait corrigé l'argent.
 */
export function ceQuiChange(
  c: { libelle: string; montant_cents: number; mode: Mode; periodicite: string; debut: string
       categorie: string },
  s: { libelle: string; cents: number; mode: Mode; periodicite: string; debut: string
       categorie: string },
): { argent: boolean; categorie: boolean } {
  return {
    argent: s.libelle.trim() !== c.libelle || s.cents !== c.montant_cents || s.mode !== c.mode
      || s.periodicite !== c.periodicite || s.debut !== c.debut,
    categorie: s.categorie !== c.categorie,
  }
}

export function ditLaCorrection(libelle: string, moisRefaits: number): string {
  return moisRefaits === 0
    ? `« ${libelle} » corrigée.`
    : `« ${libelle} » corrigée, ${moisRefaits} mois refait${moisRefaits > 1 ? 's' : ''}.`
}

/**
 * Le champ « Elle court depuis » (`<input type="month">`) rend « 2026-09 » — ou « » quand
 * on l'efface, ou qu'on n'a tapé qu'une partie. L'écran écrivait `${''}-01`, soit « -01 »,
 * et l'envoyait à la base : on ne garde que ce qui est un mois entier.
 */
export function debutDuChamp(valeur: string): string {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(valeur) ? `${valeur}-01` : ''
}

/** Le plus ancien départ que la base accepte (0096) : janvier de l'année précédente. */
export function plancherDuDebut(maintenant: Date): string {
  return `${maintenant.getFullYear() - 1}-01-01`
}

/**
 * Un départ est-il acceptable ? `garde` : celui que la charge a déjà. Il reste accepté même
 * avant le plancher — corriger un libellé ne doit pas obliger à réécrire une date que la
 * base a posée —, mais tout AUTRE départ passe le plancher.
 */
export function lisLeDebut(debut: string, o: { plancher: string; garde?: string; arrivee?: string | null }):
  { valide: boolean; refus: string | null } {
  if (!/^\d{4}-\d{2}-01$/.test(debut)) return { valide: false, refus: 'Choisis le mois où elle commence.' }
  if (debut !== o.garde && debut < o.plancher) {
    return { valide: false,
             refus: `Pas avant ${nomDuMois(o.plancher)} ${o.plancher.slice(0, 4)}.` }
  }
  /* Rien ne court avant l'arrivée de qui agit (`moisDeDepart`, la règle de l'ajout) : une charge qui démarre avant
     elle fait porter toute la part à celui qui est déjà là. Un départ DÉJÀ posé (`garde`) reste accepté. */
  const depart = moisDeDepart(o.arrivee, debut)
  if (debut !== o.garde && depart !== debut) {
    return { valide: false, refus: `Pas avant ton arrivée, en ${nomDuMois(depart)} ${depart.slice(0, 4)}.` }
  }
  return { valide: true, refus: null }
}

/** La borne de `charge_libelle_check` : au-delà, la base répond en anglais (« violates check constraint »). */
export const LIBELLE_MAX = 80

/** Le refus d'un nom trop long (les espaces autour ne comptent pas : la base les retire). */
export function refusDuLibelle(libelle: string): string | null {
  return libelle.trim().length > LIBELLE_MAX ? `Un nom de ${LIBELLE_MAX} caractères au plus.` : null
}

/**
 * Ce que le formulaire d'ajout permet d'envoyer. Le montant passe par `lisLeMontant`, comme
 * les feuilles : 0 € et plus de 1 000 000 € se refusent AVANT l'envoi, avec leur phrase.
 */
export function peutPoser(o: { libelle: string; montant: string; qui: number; debut: string; plancher: string }):
  { pret: boolean; cents: number | null; refusMontant: string | null; refusDebut: string | null
    refusLibelle: string | null } {
  const m = lisLeMontant(o.montant, { zeroOk: false })
  const d = lisLeDebut(o.debut, { plancher: o.plancher })
  const refusLibelle = refusDuLibelle(o.libelle)
  return { pret: o.libelle.trim() !== '' && refusLibelle === null && m.valide && o.qui > 0 && d.valide,
           cents: m.cents, refusMontant: m.refus, refusDebut: d.refus, refusLibelle }
}

/**
 * Ce que le panneau « Corriger » permet d'enregistrer. Le départ ne se lit que pour une mise
 * de côté : c'est la seule façon dont le champ est montré, et les autres envoient celui que
 * la charge a déjà.
 */
export function peutCorriger(o: {
  libelle: string; montant: string; mode: Mode; debut: string; garde: string; plancher: string
  /** L'arrivée de qui corrige : rien ne court avant elle. */
  arrivee?: string | null
}): { pret: boolean; cents: number | null; refusMontant: string | null; refusDebut: string | null
      refusLibelle: string | null } {
  const m = lisLeMontant(o.montant, { zeroOk: false })
  const d = o.mode === 'mis_de_cote'
    ? lisLeDebut(o.debut, { plancher: o.plancher, garde: o.garde, arrivee: o.arrivee })
    : { valide: true, refus: null }
  const refusLibelle = refusDuLibelle(o.libelle)
  return { pret: o.libelle.trim() !== '' && refusLibelle === null && m.valide && d.valide,
           cents: m.cents, refusMontant: m.refus, refusDebut: d.refus, refusLibelle }
}

/**
 * Commune : elle se partage (plusieurs participants), ou — seul dans le foyer seulement — la
 * personne a dit qu'elle devra être partagée avec celle qu'elle invite (l'intention).
 * À deux ou plus, une charge payée par une seule personne est perso : l'intention pré-cochée
 * par le catalogue ne vaut que tant qu'il n'y a personne d'autre à qui la partager.
 */
export function communeDeLaCharge(o: { qui: number; membres: number; intention: boolean }): boolean {
  return o.qui > 1 || (o.membres === 1 && o.intention)
}
