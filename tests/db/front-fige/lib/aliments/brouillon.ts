/**
 * Un aliment à moitié rempli : ce que les champs de l'écran contiennent (des TEXTES), et ce qu'on en tire pour la base.
 *
 * Les bornes sont celles de la migration 0124 : si le client les laissait passer, la base répondrait par un nom de
 * contrainte (`aliment_kcal_100g_check`) ; ici, une phrase française par champ, sous le champ.
 */
import { codeBarresValide } from './openfoodfacts.ts'
import { ecrit } from './calcul.ts'
import { enFrancais } from '../reseau.ts'

export type Source = 'main' | 'etiquette' | 'code_barres'

/** D'où viennent les chiffres, dit comme l'écran le dit. */
export const MOT_DE_LA_SOURCE: Record<Source, string> = {
  main: 'à la main', etiquette: 'étiquette', code_barres: 'code-barres',
}

export type Brouillon = {
  label: string
  kcal: string
  proteines: string
  glucides: string
  lipides: string
  fibres: string
  unite: string
  poids: string
  codeBarres: string
  /** Le repère de `reperes.ts` que cet aliment remplace (`''` : aucun). Un choix de la personne, proposé d'après le nom. */
  remplaceRepere: string
  source: Source
}

export type Champ = keyof Brouillon

export const brouillonVide = (): Brouillon => ({
  label: '', kcal: '', proteines: '', glucides: '', lipides: '', fibres: '',
  unite: 'pot', poids: '', codeBarres: '', remplaceRepere: '', source: 'main',
})

/** Un nombre tapé « 5,6 », « 5.6 » ou « 1 250 ». `null` : vide ; `NaN` : illisible. */
export function lisLeNombre(saisie: string): number | null {
  const t = saisie.trim().replace(/\s/g, '').replace(',', '.')
  if (t === '') return null
  return /^-?\d*\.?\d+$/.test(t) ? Number(t) : NaN
}

/** Ce que la base reçoit d'un aliment (sans `household_id`, que l'écriture ajoute). */
export type Valeurs = {
  label: string
  kcal_100g: number
  protein_100g: number
  carb_100g: number
  fat_100g: number
  fiber_100g: number
  unite: string
  unite_g: number
  code_barres: string | null
  remplace_repere: string | null
  source: Source
}

/** `energie` : des calories qui ne cadrent pas avec les macros (des kJ pris pour des kcal ?) — à confirmer, pas à corriger. */
export type Erreurs = Partial<Record<Champ | 'macros' | 'energie', string>>

/** Le texte d'un nombre pour un champ : 12.5 → « 12,5 ». */
const texte = (n: number | string) => String(n).replace('.', ',')

/** Un aliment déjà rangé → les champs de l'écran. */
export function depuisLaBase(a: {
  label: string; kcal_100g: number | string; protein_100g: number | string; carb_100g: number | string
  fat_100g: number | string; fiber_100g: number | string; unite: string; unite_g: number | string
  code_barres: string | null; source: string; remplace_repere?: string | null
}): Brouillon {
  /* Zéro est une vraie valeur pour les glucides, les lipides, les fibres : on l'écrit, on ne le laisse pas vide. */
  return {
    label: a.label, kcal: texte(Number(a.kcal_100g)), proteines: texte(Number(a.protein_100g)),
    glucides: texte(Number(a.carb_100g)), lipides: texte(Number(a.fat_100g)), fibres: texte(Number(a.fiber_100g)),
    unite: a.unite, poids: texte(Number(a.unite_g)), codeBarres: a.code_barres ?? '',
    remplaceRepere: a.remplace_repere ?? '',
    source: a.source === 'etiquette' || a.source === 'code_barres' ? a.source : 'main',
  }
}

const KJ_PAR_KCAL = 4.184

/** Ce que les macros « devraient » faire en kcal : 4 par g de protéines et de glucides, 9 de lipides, 2 de fibres. */
export const energieAttendue = (p: number, g: number, l: number, f: number) => 4 * p + 4 * g + 9 * l + 2 * f

/** Des calories qui ne cadrent pas avec les macros. `enKcal` : ce que vaudraient ces chiffres s'ils étaient des kJ. */
export type DouteSurLEnergie = { kcal: number; attendue: number; trop: boolean; enKcal: number | null }

/**
 * Les calories saisies tiennent-elles avec les macros ? Un tableau lu en kJ passe sous 900 (318 kJ pour 100 g, ce
 * sont 76 kcal) : la borne de la base ne l'arrête pas, ce contrôle-ci oui.
 *
 * Hors de [0,6 ; 1,5] fois l'énergie attendue, et quand elle dépasse 20 kcal (l'eau, le café : rien à comparer).
 * Glucides ou lipides absents : l'énergie attendue n'est qu'un MINIMUM, un excès de calories ne prouve rien ; seul
 * « trop peu » parle. Ne lève jamais : un champ illisible n'a pas de doute à porter (il a déjà son erreur).
 */
export function douteSurLEnergie(b: Brouillon): DouteSurLEnergie | null {
  const [kcal, p, g, l, f] = [b.kcal, b.proteines, b.glucides, b.lipides, b.fibres].map(lisLeNombre)
  if (kcal === null || p === null) return null
  if ([kcal, p, g, l, f].some(n => n !== null && (Number.isNaN(n) || n < 0))) return null
  const attendue = energieAttendue(p, g ?? 0, l ?? 0, f ?? 0)
  if (attendue <= 20) return null
  const trop = kcal > 1.5 * attendue
  const peu = kcal < 0.6 * attendue
  if (!trop && !peu) return null
  if (trop && (g === null || l === null)) return null
  const converti = trop ? Math.round(kcal / KJ_PAR_KCAL) : null
  const tient = converti !== null && converti >= 0.6 * attendue && converti <= 1.5 * attendue
  return { kcal, attendue, trop, enKcal: tient ? converti : null }
}

/** La phrase du doute. « 318 kcal pour 100 g, c’est beaucoup pour ces macros : ce serait des kJ ? 318 kJ = 76 kcal. » */
export function phraseDuDoute(d: DouteSurLEnergie): string {
  const dit = `${ecrit(d.kcal)} kcal pour 100 g`
  if (!d.trop) return `${dit}, c’est peu pour ces macros (elles font environ ${ecrit(Math.round(d.attendue))} kcal) : un chiffre est-il faux ?`
  if (d.enKcal !== null) return `${dit}, c’est beaucoup pour ces macros : ce serait des kJ ? ${ecrit(d.kcal)} kJ = ${ecrit(d.enKcal)} kcal.`
  return `${dit}, c’est beaucoup pour ces macros (elles font environ ${ecrit(Math.round(d.attendue))} kcal) : un chiffre est-il faux ?`
}

/** Les chiffres que « Les valeurs sont justes » couvre : changer l'un d'eux demande de confirmer à nouveau. */
export const empreinteDesValeurs = (b: Brouillon) => [b.kcal, b.proteines, b.glucides, b.lipides, b.fibres].map(x => x.trim()).join('|')

/** L'écriture à la française d'un code-barres refusé. */
const CODE_FAUX = 'Ce code ne ressemble pas à un code-barres : un chiffre doit être faux.'

/**
 * Lire les champs : les valeurs à écrire, ou une phrase par champ refusé.
 *
 * Les calories et les protéines sont EXIGÉES : ce sont elles que le bilan lit, et un zéro n'est pas « inconnu », c'est
 * « ce repas ne t'a rien apporté ». Glucides, lipides et fibres vides valent zéro.
 */
export function lis(
  b: Brouillon,
  /**
   * `energieJuste` : la personne a coché « Les valeurs sont justes » pour ces chiffres.
   * `codeDejaRange` : le code-barres que l'aliment porte déjà en base — on ne lui redemande pas sa clé à chaque
   * modification (il a pu entrer avant ce contrôle).
   */
  { energieJuste = false, codeDejaRange = null }: { energieJuste?: boolean; codeDejaRange?: string | null } = {},
): { ok: true; valeurs: Valeurs } | { ok: false; erreurs: Erreurs } {
  const erreurs: Erreurs = {}

  /* Les blancs de trop (deux espaces, une tabulation) n'entrent pas dans le nom : la base les ignore pour l'unicité. */
  const label = b.label.replace(/\s+/g, ' ').trim()
  if (label === '') erreurs.label = 'Donne-lui un nom.'
  else if (label.length > 80) erreurs.label = '80 caractères au plus.'

  const nombre = (c: 'kcal' | 'proteines' | 'glucides' | 'lipides' | 'fibres', max: number, exige: boolean, manque: string): number => {
    const n = lisLeNombre(b[c])
    if (n === null) { if (exige) erreurs[c] = manque; return 0 }
    if (Number.isNaN(n)) { erreurs[c] = 'Je ne lis pas ce nombre.'; return 0 }
    if (n < 0) { erreurs[c] = 'Pas de valeur négative.'; return 0 }
    if (n > max) {
      erreurs[c] = c === 'kcal'
        ? 'Plus de 900 kcal pour 100 g, c’est de l’huile pure : vérifie que ce ne sont pas des kJ.'
        : 'Pas plus de 100 g pour 100 g.'
      return 0
    }
    return n
  }
  const kcal = nombre('kcal', 900, true, 'Il manque les calories.')
  const proteines = nombre('proteines', 100, true, 'Il manque les protéines.')
  const glucides = nombre('glucides', 100, false, '')
  const lipides = nombre('lipides', 100, false, '')
  const fibres = nombre('fibres', 100, false, '')
  if (!erreurs.proteines && !erreurs.glucides && !erreurs.lipides && proteines + glucides + lipides > 105) {
    erreurs.macros = 'Protéines, glucides et lipides font plus de 100 g pour 100 g : un chiffre est faux.'
  }
  /* Les calories qui ne cadrent pas : bloquant tant qu'on n'a pas corrigé, ou confirmé que les chiffres sont justes. */
  if (!erreurs.kcal && !erreurs.proteines && !erreurs.glucides && !erreurs.lipides && !erreurs.fibres && !erreurs.macros && !energieJuste) {
    const doute = douteSurLEnergie(b)
    if (doute) erreurs.energie = phraseDuDoute(doute)
  }

  const unite = b.unite.trim()
  if (unite === '') erreurs.unite = 'Donne un nom à l’unité : pot, part, portion…'
  else if (unite.length > 20) erreurs.unite = '20 caractères au plus.'

  const poids = lisLeNombre(b.poids)
  if (poids === null) erreurs.poids = `Dis combien pèse ${unite === '' ? '1 unité' : `1 ${unite}`}.`
  else if (Number.isNaN(poids)) erreurs.poids = 'Je ne lis pas ce nombre.'
  else if (poids < 1) erreurs.poids = 'Au moins 1 g.'
  else if (poids > 5000) erreurs.poids = 'Pas plus de 5 000 g.'

  const code = b.codeBarres.replace(/\s/g, '')
  if (code !== '') {
    if (!/^\d+$/.test(code) || ![8, 12, 13, 14].includes(code.length)) erreurs.codeBarres = 'Un code-barres a 8, 12, 13 ou 14 chiffres.'
    else if (code !== codeDejaRange && !codeBarresValide(code)) erreurs.codeBarres = CODE_FAUX
  }

  if (Object.keys(erreurs).length > 0) return { ok: false, erreurs }
  return {
    ok: true,
    valeurs: {
      label, kcal_100g: kcal, protein_100g: proteines, carb_100g: glucides, fat_100g: lipides, fiber_100g: fibres,
      unite, unite_g: poids as number, code_barres: code === '' ? null : code,
      remplace_repere: b.remplaceRepere.trim() === '' ? null : b.remplaceRepere.trim(), source: b.source,
    },
  }
}

/** Le code-barres est-il de ceux qu'on cherche ? (dit « faux » avant de déranger Open Food Facts) */
export const codeAChercher = (saisie: string): { code: string; valide: boolean } => {
  const code = saisie.replace(/\s/g, '')
  return { code, valide: codeBarresValide(code) }
}

const ECRITURE_ECHOUEE = 'L’enregistrement a échoué : réessaie dans un instant.'

/** Chaque contrainte de la table `aliment` (0124) a sa phrase : la base ne parle que par le nom de l'index. */
const CONTRAINTES: [RegExp, string][] = [
  [/aliment_label_unique/, 'Un aliment porte déjà ce nom dans le foyer. Change-le, ou modifie l’autre.'],
  [/aliment_code_barres_unique/, 'Ce code-barres est déjà dans nos aliments : modifie l’aliment qui le porte.'],
  [/aliment_label_check/, 'Le nom doit faire de 1 à 80 caractères, et pas seulement des espaces.'],
  [/aliment_kcal_100g_check/, 'Les calories pour 100 g doivent être entre 0 et 900.'],
  [/aliment_protein_100g_check/, 'Les protéines pour 100 g doivent être entre 0 et 100 g.'],
  [/aliment_carb_100g_check/, 'Les glucides pour 100 g doivent être entre 0 et 100 g.'],
  [/aliment_fat_100g_check/, 'Les lipides pour 100 g doivent être entre 0 et 100 g.'],
  [/aliment_fiber_100g_check/, 'Les fibres pour 100 g doivent être entre 0 et 100 g.'],
  [/aliment_macros_plausibles/, 'Protéines, glucides et lipides font plus de 100 g pour 100 g : un chiffre est faux.'],
  [/aliment_unite_g_check/, 'L’unité doit peser entre 1 g et 5 000 g.'],
  [/aliment_unite_check/, 'Le nom de l’unité doit faire de 1 à 20 caractères.'],
  [/aliment_code_barres_check/, 'Un code-barres a 8, 12, 13 ou 14 chiffres.'],
  [/aliment_remplace_repere_check/, 'Le repère remplacé doit avoir un nom de 1 à 80 caractères, ou rester vide.'],
  [/aliment_source_check/, 'D’où viennent les chiffres : à la main, étiquette ou code-barres.'],
  /* `.single()` sur une ligne qui n'existe plus (retirée depuis l'autre téléphone) : PostgREST répond en anglais. */
  [/cannot coerce|json object requested|PGRST116/i, 'Cet aliment a été retiré entre-temps.'],
  [/row-level security/i, 'Je ne peux pas écrire cet aliment pour ce foyer : reconnecte-toi, puis réessaie.'],
]

/** La phrase d'une panne d'écriture, d'après la contrainte que la base a nommée. Toujours du français. */
export function phraseDeLEcriture(message: string): string {
  for (const [motif, phrase] of CONTRAINTES) if (motif.test(message)) return phrase
  /* Une panne de réseau a déjà sa phrase ; tout le reste (du texte de la base, en anglais) devient une phrase neutre. */
  const f = enFrancais(message)
  return f !== message ? f : ECRITURE_ECHOUEE
}
