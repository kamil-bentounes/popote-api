/**
 * Du groupe CIQUAL au rayon du magasin.
 *
 * CIQUAL classe par nature d'aliment, un magasin par circulation. Les deux ne
 * coïncident pas : le lait est un « produit laitier » chez l'ANSES, il est au
 * frais chez Lidl, et les yaourts aussi mais trois mètres plus loin.
 *
 * Cette table n'est qu'un POINT DE DÉPART. L'ordre réel des rayons s'apprend du
 * geste (D58, trigger `shopping_check`) : dès la deuxième sortie, c'est
 * l'observation qui commande, pas cette liste.
 */

export const RAYONS = [
  'Fruits et légumes',
  'Boucherie, poissonnerie',
  'Frais',
  'Surgelés',
  'Épicerie salée',
  'Épicerie sucrée',
  'Boissons',
  'Entretien',
  'Hygiène',
  'Autre',
] as const

export type Rayon = (typeof RAYONS)[number]

/** Groupe CIQUAL → rayon. Les clés sont celles de la base, en toutes lettres. */
const PAR_GROUPE: Record<string, Rayon> = {
  'fruits, légumes, légumineuses et oléagineux': 'Fruits et légumes',
  'viandes, œufs, poissons et assimilés': 'Boucherie, poissonnerie',
  'produits laitiers et assimilés': 'Frais',
  'glaces et sorbets': 'Surgelés',
  'produits céréaliers': 'Épicerie salée',
  'aides culinaires et ingrédients divers': 'Épicerie salée',
  'matières grasses': 'Épicerie salée',
  'entrées et plats composés': 'Épicerie salée',
  'produits sucrés': 'Épicerie sucrée',
  'eaux et autres boissons': 'Boissons',
  'aliments infantiles': 'Autre',
}

/** Catégorie du catalogue « Compléter ma liste » (D43) → rayon. */
const PAR_CATEGORIE: Record<string, Rayon> = {
  Entretien: 'Entretien',
  'Hygiène': 'Hygiène',
  Papeterie: 'Autre',
  Animaux: 'Autre',
  Cuisine: 'Autre',
  'Épicerie de fond': 'Épicerie salée',
}

/**
 * Quelques aliments trahissent leur groupe : les surgelés en sont le cas type.
 * On ne cherche pas l'exhaustivité, seulement à ne pas envoyer quelqu'un
 * chercher des petits pois surgelés au rayon fruits et légumes.
 */
const INDICES: [RegExp, Rayon][] = [
  [/\bsurgel|congel/i, 'Surgelés'],
  [/\bglace\b|sorbet/i, 'Surgelés'],
  [/\bconserve|\bboîte\b|bocal/i, 'Épicerie salée'],
  // « sèche » porte un accent : `\bsec(s|he|hes)?\b` ne la reconnaissait pas (les lentilles allaient
  // au rayon fruits et légumes).
  [/\bs[eè]ches?\b|\bsecs?\b|\bséché/i, 'Épicerie salée'],
]

/**
 * Sous-catégorie CIQUAL → rayon, quand le groupe est trop gros pour trancher : « viandes, œufs,
 * poissons » met les œufs à la boucherie, « fruits, légumes, légumineuses » les lentilles au
 * rayon frais. Les INDICES du libellé (surgelé, conserve, sec) passent avant.
 */
const PAR_SOUS_GROUPE: Record<string, Rayon> = {
  'œufs': 'Frais',
  'légumineuses': 'Épicerie salée',
  'fruits à coque et graines oléagineuses': 'Épicerie salée',
  'charcuteries et assimilés': 'Frais',
  'pommes de terre et autres tubercules': 'Fruits et légumes',
}

export function rayonDe(
  { groupe, sousGroupe, categorie, libelle }:
  { groupe?: string | null; sousGroupe?: string | null; categorie?: string | null; libelle?: string | null },
): Rayon {
  if (categorie && PAR_CATEGORIE[categorie]) return PAR_CATEGORIE[categorie]
  if (libelle) for (const [motif, rayon] of INDICES) if (motif.test(libelle)) return rayon
  if (sousGroupe) {
    if (sousGroupe === 'herbes') return /\bfrais\b|\bfraîche/i.test(libelle ?? '') ? 'Fruits et légumes' : 'Épicerie salée'
    if (PAR_SOUS_GROUPE[sousGroupe]) return PAR_SOUS_GROUPE[sousGroupe]
  }
  if (groupe && PAR_GROUPE[groupe]) return PAR_GROUPE[groupe]
  return 'Autre'
}

/** Rang par défaut d'un rayon, tant que le magasin n'a rien appris de vous. */
export function rangParDefaut(rayon: string): number {
  const i = (RAYONS as readonly string[]).indexOf(rayon)
  return i < 0 ? RAYONS.length : i
}
