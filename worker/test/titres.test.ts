/**
 * Les dix titres de la maquette sont de VRAIS titres du catalogue de prod : ils
 * disent mieux que des cas inventés ce que le nettoyage doit tenir (R5).
 *
 * Ici et non sous `src/` : le test lit un fichier, et `tsc` compile `src/` sans les
 * types de Node — un `node:fs` y casserait `npm run build`.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { titrePropre } from '../src/partage/texte.ts'

describe('les titres réels', () => {
  it('nettoie les dix titres de la maquette', () => {
    const dix: { title: string }[] = JSON.parse(readFileSync(
      new URL('../../docs/superpowers/maquettes/recettes/dix.json', import.meta.url), 'utf8'))
    const propres = dix.map(d => titrePropre(d.title)!)
    expect(propres.filter(t => /recette|cookeo|&amp;| a l'/i.test(t))).toEqual([])
    expect(propres).toContain('Hachis parmentier')
    expect(propres).toContain('Poulet mariné à l\'indienne')
    expect(propres).toContain('Chili con carne traditionnel')
  })
})
