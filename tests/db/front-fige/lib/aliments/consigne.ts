/**
 * La consigne de la personne (« Dis-moi ce que c'est »), bornée avant de partir avec les photos vers la fonction
 * `etiquette`. COPIE de `supabase/functions/_shared/consigne.ts` (le front ne peut pas importer une fonction) : la fonction
 * borne encore de son côté, et `consigne.test.ts` les fait répondre aux mêmes textes.
 */

/** Au-delà, ce n'est plus un indice : c'est un texte à lire. */
export const CONSIGNE_MAX = 300

function estInvisible(c: number): boolean {
  return c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0x200b && c <= 0x200f) || (c >= 0x2028 && c <= 0x202e)
    || (c >= 0x2060 && c <= 0x206f) || c === 0xfeff
}

/** Sans caractère de contrôle ni invisible, sans chevrons, les blancs réduits à un seul, coupée à 300 caractères. */
export function nettoieLaConsigne(brut: unknown): string {
  if (typeof brut !== 'string') return ''
  let sortie = ''
  for (const c of brut.normalize('NFC')) {
    const code = c.codePointAt(0)!
    sortie += estInvisible(code) || c === '<' || c === '>' || c === '`' ? ' ' : c
  }
  const net = sortie.replace(/\s+/g, ' ').trim()
  const lettres = [...net]
  return lettres.length > CONSIGNE_MAX ? lettres.slice(0, CONSIGNE_MAX).join('').trim() : net
}

/** Ce qui part à la fonction : le corps de l'appel, avec la consigne quand il y en a une. */
export function corpsDeLaLecture(images: string[], consigne: string): { images: string[]; consigne?: string } {
  const c = nettoieLaConsigne(consigne)
  return c === '' ? { images } : { images, consigne: c }
}
