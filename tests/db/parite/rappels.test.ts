import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  MAXIMUM_SORTIES, RAPPELS, TYPES_DE_RAPPEL, DELAI_ESSAI_CLIENT_MS, detailDeSortie, estUnType, lisLesSorties,
  phraseDApresSortie, questionDeSortie, sortablesDuLien,
} from '../front-fige/lib/rappels.ts'
import type { Part } from '../front-fige/lib/frigo.ts'

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`

function part(n: number, o: Partial<Part> = {}): Part {
  return {
    id: ID(n), recipe_id: null, label: 'Wraps poulet', location: 'congelateur', state: 'au_frais', grams: 400, kcal: 600,
    protein_g: 40, prepared_at: '2026-10-01T10:00:00Z', frozen_at: '2026-10-01T10:00:00Z', expires_at: '2027-01-01T10:00:00Z',
    ...o,
  }
}

describe('le catalogue', () => {
  it('sept rappels, un par type, avec leur moment et leur phrase', () => {
    expect(RAPPELS.map(r => r.type)).toEqual([...TYPES_DE_RAPPEL])
    expect(new Set(RAPPELS.map(r => r.type)).size).toBe(7)
    for (const r of RAPPELS) {
      expect(r.nom.length, r.type).toBeGreaterThan(5)
      expect(r.moment, r.type).toMatch(/\d ?h/)
      expect(r.quand.startsWith('Part '), r.type).toBe(true)
    }
    expect(RAPPELS.find(r => r.type === 'sortir_du_congelateur')?.moment).toBe('La veille à 19 h')
  })

  it('trois en cuisine, quatre au budget ; une couleur par famille', () => {
    expect(RAPPELS.filter(r => r.groupe === 'Cuisine')).toHaveLength(3)
    expect(RAPPELS.filter(r => r.groupe === 'Budget')).toHaveLength(4)
    expect(RAPPELS.filter(r => r.groupe === 'Budget').every(r => r.famille === 'sable')).toBe(true)
    expect(RAPPELS.find(r => r.type === 'sortir_du_congelateur')?.famille).toBe('bleu')
    expect(RAPPELS.find(r => r.type === 'barquette_perime')?.famille).toBe('encre')
    expect(RAPPELS.find(r => r.type === 'choisir_les_repas')?.famille).toBe('herbe')
  })

  it('les types sont ceux de la migration', () => {
    const sql = readFileSync(new URL('../../../supabase/migrations/0126_rappels.sql', import.meta.url), 'utf8')
    const bloc = sql.slice(sql.indexOf('check (type in ('), sql.indexOf('actif      boolean'))
    expect([...bloc.matchAll(/'([a-z_]+)'/g)].map(m => m[1]).sort()).toEqual([...TYPES_DE_RAPPEL].sort())
  })

  it('estUnType', () => {
    expect(estUnType('barquette_perime')).toBe(true)
    expect(estUnType('spam')).toBe(false)
    expect(estUnType(null)).toBe(false)
  })
})

describe('lisLesSorties : le lien « C’est fait »', () => {
  it('pas de paramètre : rien à demander', () => {
    expect(lisLesSorties('')).toBeNull()
    expect(lisLesSorties('?jour=2026-10-29')).toBeNull()
  })

  it('une liste d’identifiants séparés par des virgules', () => {
    expect(lisLesSorties(`?sortir=${ID(1)},${ID(2)},${ID(3)}`)).toEqual([ID(1), ID(2), ID(3)])
    expect(lisLesSorties(`?sortir=${ID(1)}`)).toEqual([ID(1)])
  })

  it('écarte ce qui n’est pas un identifiant, les doublons, la casse', () => {
    expect(lisLesSorties(`?sortir=${ID(1)},x,${ID(1)},,${ID(2).toUpperCase()},../..,1;drop table`)).toEqual([ID(1), ID(2)])
    expect(lisLesSorties('?sortir=')).toEqual([])
    expect(lisLesSorties('?sortir=nimporte')).toEqual([])
  })

  it('un lien démesuré est tronqué', () => {
    const tous = Array.from({ length: MAXIMUM_SORTIES + 25 }, (_, i) => ID(i + 1))
    expect(lisLesSorties(`?sortir=${tous.join(',')}`)).toHaveLength(MAXIMUM_SORTIES)
  })
})

describe('sortablesDuLien : ce qu’on peut vraiment sortir', () => {
  const barquettes = [
    part(1), part(2), part(3, { location: 'frigo', state: 'decongelee' }), part(4, { state: 'mangee' }),
    part(5, { state: 'jetee' }),
  ]

  it('les barquettes du congélateur, encore là', () => {
    const r = sortablesDuLien([ID(1), ID(2)], barquettes)
    expect(r.asortir.map(p => p.id)).toEqual([ID(1), ID(2)])
    expect(r.ignores).toBe(0)
  })

  it('ignore, sans erreur : l’inconnu, l’autre foyer (absent de la liste), le déjà sorti, le mangé, le jeté', () => {
    const r = sortablesDuLien([ID(1), ID(3), ID(4), ID(5), ID(99)], barquettes)
    expect(r.asortir.map(p => p.id)).toEqual([ID(1)])
    expect(r.ignores).toBe(4)
  })

  it('aucune sortable : rien', () => {
    const r = sortablesDuLien([ID(3), ID(99)], barquettes)
    expect(r.asortir).toEqual([])
    expect(r.ignores).toBe(2)
    expect(sortablesDuLien([], barquettes).asortir).toEqual([])
  })
})

describe('les phrases de la confirmation', () => {
  const wrap = (n: number, o: Partial<Part> = {}) => part(n, { label: 'Wrap', ...o })

  it('« Sortir 4 wraps du congélateur ? » : un libellé d’un seul mot prend le pluriel simple', () => {
    expect(questionDeSortie([wrap(1), wrap(2), wrap(3), wrap(4)])).toBe('Sortir 4 wraps du congélateur\u00a0?')
    expect(questionDeSortie([wrap(1)])).toBe('Sortir 1 wrap du congélateur\u00a0?')
  })

  it('plusieurs mots : « 2 barquettes de … », jamais un « s » collé au premier mot', () => {
    expect(questionDeSortie([part(1, { label: 'Petit salé aux lentilles' }), part(2, { label: 'Petit salé aux lentilles' })]))
      .toBe('Sortir 2 barquettes de petit salé aux lentilles du congélateur\u00a0?')
    expect(questionDeSortie([part(1, { label: 'Burger de feuilles de riz' })]))
      .toBe('Sortir 1 barquette de burger de feuilles de riz du congélateur\u00a0?')
    expect(questionDeSortie([part(1)])).toBe('Sortir 1 barquette de wraps poulet du congélateur\u00a0?')
  })

  it('plusieurs plats : on compte les barquettes, et le détail dit lesquelles', () => {
    const lot = [wrap(1), wrap(2), part(3, { label: 'Lasagnes au saumon' })]
    expect(questionDeSortie(lot)).toBe('Sortir 3 barquettes du congélateur\u00a0?')
    expect(detailDeSortie(lot)).toBe('1 barquette de lasagnes au saumon, 2 wraps')
  })

  it('après : « 4 wraps sont au frigo, à manger dans les 24 heures. »', () => {
    expect(phraseDApresSortie([wrap(1), wrap(2), wrap(3), wrap(4)])).toBe('4 wraps sont au frigo, à manger dans les 24 heures.')
    expect(phraseDApresSortie([wrap(1)])).toBe('1 wrap est au frigo, à manger dans les 24 heures.')
    expect(phraseDApresSortie([wrap(1), part(2, { label: 'Pizza' })])).toBe('2 barquettes sont au frigo, à manger dans les 24 heures.')
  })
})

describe('le délai de l’essai', () => {
  it('l’écran attend plus que la fonction ne s’accorde', () => {
    expect(DELAI_ESSAI_CLIENT_MS).toBeGreaterThanOrEqual(20_000)
  })
})
