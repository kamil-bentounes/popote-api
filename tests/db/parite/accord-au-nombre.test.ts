import { describe, expect, it } from 'vitest'
import { partsDuPlat as duFrigo } from '../front-fige/lib/frigo.ts'
import { partsDuPlat as desMails } from '../../../supabase/functions/_shared/rappels/texte.ts'

/**
 * Deux copies d'une même règle : celle de l'écran (`src/lib/frigo.ts`) et celle des mails
 * (`supabase/functions/_shared/rappels/texte.ts`, car le bundle d'une fonction ne contient que son dossier).
 * Ce test les fait répondre aux mêmes libellés : qu'elles divergent, il échoue.
 */
const LIBELLES = [
  'Wrap', 'Burger', 'Pizzas', 'Gâteau', 'Tuyau', 'Couscous', 'Chou', 'Riz', 'Lasagnes', 'Œufs', 'Agneau',
  'Petit salé aux lentilles', 'Pâtes au pesto', 'Bœuf bourguignon', 'Agneau aux olives', 'Tajine d’agneau',
  'Pot-au-feu', 'Gâteau de patates douces', 'Burger de feuilles de riz', 'Lasagnes au saumon-poireaux',
  'Pizza vietnamienne protéinée', 'Wraps poulet', 'Ébly jambon', 'Yaourt protéiné', 'Omelette', 'Hachis parmentier',
  'Wrap protéinée', '  Wrap  ', 'Œuf cocotte', 'Yakitori de poulet',
]

describe('l’accord au nombre : l’écran et les mails disent la même chose', () => {
  for (const label of LIBELLES) {
    for (const n of [1, 2, 3, 12]) {
      for (const defini of [false, true]) {
        it(`« ${label.trim()} », ${n}${defini ? ', défini' : ''}`, () => {
          expect(desMails(label, n, defini)).toBe(duFrigo(label, n, defini))
        })
      }
    }
  }
})
