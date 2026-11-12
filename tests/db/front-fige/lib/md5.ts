/**
 * MD5 d'une chaîne, en hexadécimal minuscule — comme `md5(text)` de Postgres.
 *
 * Pourquoi cette fonction existe : la base départage les restes égaux d'une répartition au
 * centime par `md5(uid::text || ligne::text)` (`confirme_la_ligne` 0104, `repartit_les_lignes`
 * 0100/0112). L'écran qui recalcule une part (`prorata`, `mois.ts`) doit trancher de la MÊME
 * façon : en 50/50 avec un montant impair, l'égalité est systématique, et un départage par
 * identifiant donnait un centime de moins à l'un, de plus à l'autre — l'écran contre la base.
 * Ni `crypto.subtle` (pas de MD5) ni `node:crypto` (ni navigateur) : on l'écrit.
 *
 * Éprouvée contre les vecteurs de la RFC 1321 (`md5.test.ts`) ET contre `select md5(…)`
 * (`tests/md5-base.test.ts`).
 */

// Décalages de chaque tour, et constantes K[i] = floor(2^32 × |sin(i + 1)|).
const DECALAGES = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
  5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
  6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
]
const K = Array.from({ length: 64 }, (_, i) => Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32) >>> 0)

const tourne = (x: number, n: number) => ((x << n) | (x >>> (32 - n))) >>> 0

export function md5(texte: string): string {
  const octets = new TextEncoder().encode(texte)
  // Remplissage : un 1, des 0, puis la longueur en BITS sur 64 bits (petit-boutiste).
  const total = ((octets.length + 8) >> 6) + 1
  const mots = new Uint32Array(total * 16)
  for (let i = 0; i < octets.length; i++) mots[i >> 2] |= octets[i] << ((i % 4) * 8)
  mots[octets.length >> 2] |= 0x80 << ((octets.length % 4) * 8)
  mots[total * 16 - 2] = (octets.length * 8) >>> 0
  mots[total * 16 - 1] = Math.floor((octets.length * 8) / 2 ** 32)

  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476
  for (let bloc = 0; bloc < total; bloc++) {
    const m = mots.subarray(bloc * 16, bloc * 16 + 16)
    let a = a0, b = b0, c = c0, d = d0
    for (let i = 0; i < 64; i++) {
      let f: number, g: number
      if (i < 16) { f = (b & c) | (~b & d); g = i }
      else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16 }
      else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16 }
      else { f = c ^ (b | ~d); g = (7 * i) % 16 }
      f = (f + a + K[i] + m[g]) >>> 0
      a = d; d = c; c = b
      b = (b + tourne(f, DECALAGES[i])) >>> 0
    }
    a0 = (a0 + a) >>> 0; b0 = (b0 + b) >>> 0; c0 = (c0 + c) >>> 0; d0 = (d0 + d) >>> 0
  }
  // Chaque mot sort octet de poids faible d'abord.
  return [a0, b0, c0, d0].map(w =>
    [0, 8, 16, 24].map(s => ((w >>> s) & 0xff).toString(16).padStart(2, '0')).join('')).join('')
}
