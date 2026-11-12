/**
 * L'urgence d'une barquette (D29).
 *
 * Deux règles, et elles sont toutes les deux des décisions de produit :
 *
 * 1. Des seuils ABSOLUS par lieu, jamais un pourcentage. « 20 % de trois mois »
 *    ne veut rien dire ; « il reste un jour » se comprend sans réfléchir.
 * 2. L'urgence se lit TOUJOURS avec le mot, pas seulement avec la couleur.
 *    Un daltonien — ou n'importe qui dans une cuisine mal éclairée — doit
 *    pouvoir la lire. La couleur ne fait que confirmer.
 *
 * Les deux oranges sont différents à dessein : un mot exige 4,5:1 de contraste,
 * un aplat 3:1. Chacun le sien, mesuré et non estimé.
 */

export type Lieu = 'frigo' | 'congelateur'
export type Niveau = 'perime' | 'urgent' | 'bientot' | 'ok'

export type Urgence = {
  niveau: Niveau
  /** Le texte à afficher. Il porte l'information à lui seul. */
  mot: string
  /** Aplat : pastille, barre. Contraste 3:1. */
  pastille: string
  /** Texte coloré. Contraste 4,5:1 sur le fond ivoire. */
  encre: string
  heuresRestantes: number
}

const HEURE = 3_600_000
const JOUR = 24 * HEURE

/**
 * `jours` jours PLEINS après `d` : `jours × 24 h`, à l'instant près.
 *
 * C'est ce que fait la base (`tg_portion_peremption` : `prepared_at + make_interval(days => 4)`, en UTC) :
 * ni changement d'heure, ni calendrier local. L'ancien calcul de l'écran (`setDate`) ajoutait des jours
 * de calendrier en heure locale et, de part et d'autre du passage à l'heure d'hiver, affichait une date
 * d'un jour de différence avec celle que la base écrit. UN seul calcul : « On range » et la fiche du
 * frigo s'en servent tous deux.
 */
export function plusDeJours(d: Date, jours: number): Date {
  return new Date(d.getTime() + jours * JOUR)
}

/** Frigo : rouge le jour même, orange le lendemain. */
const FRIGO_URGENT_H = 24
const FRIGO_BIENTOT_H = 48

/** Congélateur : orange à sept jours. Rien n'y est jamais « rouge ». */
const CONGELE_BIENTOT_H = 24 * 7

const COULEURS: Record<Niveau, { pastille: string; encre: string }> = {
  perime: { pastille: '#B3402F', encre: '#9A3526' },
  urgent: { pastille: '#B3402F', encre: '#9A3526' },
  bientot: { pastille: '#B8791A', encre: '#8F5A0D' },
  ok: { pastille: '#DCE2D6', encre: '#5D6E62' },
}

function jours(heures: number): number {
  return Math.floor(heures / 24)
}

function motDe(niveau: Niveau, lieu: Lieu, heures: number): string {
  if (niveau === 'perime') return 'périmée'
  if (lieu === 'congelateur') {
    if (niveau === 'bientot') return `à sortir sous ${Math.max(1, jours(heures))} j`
    return `${jours(heures)} j au congélateur`
  }
  if (niveau === 'urgent') return "à manger aujourd'hui"
  if (niveau === 'bientot') return 'demain dernier délai'
  const j = jours(heures)
  return j <= 1 ? 'encore un jour' : `encore ${j} jours`
}

export function urgence(
  expireLe: Date | string, lieu: Lieu, maintenant: Date = new Date(),
): Urgence {
  const fin = typeof expireLe === 'string' ? new Date(expireLe) : expireLe
  const heuresRestantes = (fin.getTime() - maintenant.getTime()) / HEURE

  const niveau: Niveau =
    heuresRestantes <= 0 ? 'perime'
    : lieu === 'congelateur'
      ? (heuresRestantes <= CONGELE_BIENTOT_H ? 'bientot' : 'ok')
      : heuresRestantes <= FRIGO_URGENT_H ? 'urgent'
      : heuresRestantes <= FRIGO_BIENTOT_H ? 'bientot'
      : 'ok'

  return {
    niveau,
    mot: motDe(niveau, lieu, heuresRestantes),
    ...COULEURS[niveau],
    heuresRestantes,
  }
}

/** Le plus pressé d'abord : c'est l'ordre de l'inventaire et de l'accueil. */
export function parUrgence<T extends { expires_at: string; location: Lieu }>(
  items: T[], maintenant: Date = new Date(),
): T[] {
  return [...items].sort((a, b) =>
    urgence(a.expires_at, a.location, maintenant).heuresRestantes -
    urgence(b.expires_at, b.location, maintenant).heuresRestantes)
}
