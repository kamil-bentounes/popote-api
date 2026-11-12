/**
 * Les calculs qui produisent les chiffres affichés.
 *
 * Aucun de ces trois n'était testé, et ce sont eux qu'on lit : `virements()`
 * rend le seul chiffre sur lequel on peut agir, `enCentimes()` est la ligne
 * exacte où un flottant fabrique un centime faux, et `euros()` est ce qui
 * s'affiche. Une relecture a trouvé trois défauts dedans.
 */
import { describe, expect, it } from 'vitest'
import { virements, euros, eurosRonds, enCentimes, effortMensuel, diffParticipants,
         type Depense, type Compte }
  from './front-fige/lib/donnees/budget.ts'

const MOI = 'moi', ELLE = 'elle'
const prenoms = new Map([[MOI, 'Kamil'], [ELLE, 'Thauba']])

const compte = (o: Partial<Compte> & { id: string }): Compte => ({
  nom: 'Commun', genre: 'commun', titulaire_id: null, matelas_cents: 0, ...o,
})
const depense = (o: Partial<Depense> & { id: string }): Depense => ({
  charge_id: null, libelle: 'X', montant_cents: 1000, montant_prevu_cents: 1000, nature: 'estimee', source: 'modele',
  regle_le: null, enveloppe_id: null, compte_id: null, parts: [], ...o,
})

describe('enCentimes', () => {
  it('laisse passer une virgule en cours de frappe', () => {
    // « 3, » est un état de passage vers « 3,50 » : refuser afficherait une
    // erreur à chaque montant décimal, entre deux touches.
    expect(enCentimes('3,')).toBe(300)
  })

  it('accepte ce que l’application affiche elle-même', () => {
    // `toLocaleString('fr-FR')` produit une espace INSÉCABLE : recopier un
    // montant affiché par l'app était rejeté par la première version.
    expect(enCentimes('1 234,56')).toBe(123_456)
    expect(enCentimes('1 234,56')).toBe(123_456)
    expect(enCentimes('1 234,56')).toBe(123_456)
    expect(enCentimes('10,70')).toBe(1_070)
    expect(enCentimes('37')).toBe(3_700)
    expect(enCentimes('0,05')).toBe(5)
    expect(enCentimes('12.5')).toBe(1_250)
  })

  it('ne fabrique pas de centime faux', () => {
    // `Math.round(12.345 * 100)` rend 1234 : le flottant vaut 1234,4999…
    expect(enCentimes('12,34')).toBe(1_234)
    expect(enCentimes('1,15')).toBe(115)
    expect(enCentimes('8,07')).toBe(807)
    expect(enCentimes('1000000')).toBe(100_000_000)
  })

  it('refuse ce qui n’est pas un montant, au lieu de deviner', () => {
    for (const faux of ['', 'abc', '-20', '1,2,3', '1e3', '12,345', ',5', '1..2']) {
      expect(enCentimes(faux), `« ${faux} » a été accepté`).toBeNull()
    }
  })
})

describe('euros', () => {
  it('rend des centimes exacts, et des euros ronds quand on le demande', () => {
    /* On asserte les CHIFFRES, pas les espaces : `toLocaleString` choisit
       lui-même entre espace fine insécable, espace insécable et espace
       ordinaire, et ce choix a déjà changé d'une version de Node à l'autre. */
    const sansEspaces = (s: string) => s.replace(/[\s\u00A0\u202F]/g, '')
    expect(sansEspaces(euros(161_853))).toBe('1618,53€')
    expect(euros(5)).toContain('0,05')
    expect(euros(0)).toContain('0,00')
    expect(sansEspaces(eurosRonds(161_853))).toBe('1619€')
  })
})

describe('virements', () => {
  it('range ce qu’on doit par compte, et rend le plus gros d’abord', () => {
    const commun = compte({ id: 'c1', nom: 'Commun' })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c1', parts: [{ user_profile_id: MOI, part_cents: 60_000 }] }),
      depense({ id: 'd2', compte_id: 'c1', parts: [{ user_profile_id: MOI, part_cents: 3_123 }] }),
    ], MOI, [commun], prenoms)

    expect(v).toHaveLength(1)
    expect(v[0].vers).toBe('Commun')
    expect(v[0].cents, 'les centimes se perdent en route').toBe(63_123)
  })

  it('doit à la PERSONNE quand elle a avancé, pas à son compte', () => {
    const sien = compte({ id: 'c2', nom: 'Compte de Kamil', genre: 'perso', titulaire_id: MOI })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c2', parts: [{ user_profile_id: ELLE, part_cents: 2_200 }] }),
    ], ELLE, [sien], prenoms)

    expect(v[0].vers, 'on doit à un compte au lieu d’une personne').toBe('Kamil')
    expect(v[0].detail).toContain('avancé')
  })

  it('ne demande PAS de se virer de l’argent à soi-même', () => {
    /* Une charge débitée de mon propre compte perso créait une dette envers
       moi, et gonflait le total du hub d'autant. */
    const mien = compte({ id: 'c3', nom: 'Mon compte', genre: 'perso', titulaire_id: MOI })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c3', parts: [{ user_profile_id: MOI, part_cents: 58_000 }] }),
    ], MOI, [mien], prenoms)

    expect(v, 'on se doit de l’argent à soi-même').toHaveLength(0)
  })

  it('ignore les dépenses où l’on n’a aucune part', () => {
    const commun = compte({ id: 'c1' })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c1', parts: [{ user_profile_id: ELLE, part_cents: 9_000 }] }),
    ], MOI, [commun], prenoms)
    expect(v, 'on paie une charge à laquelle on ne participe pas').toHaveLength(0)
  })

  it('ne rend rien pour une part à zéro', () => {
    const commun = compte({ id: 'c1' })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c1', parts: [{ user_profile_id: MOI, part_cents: 0 }] }),
    ], MOI, [commun], prenoms)
    expect(v, 'un virement de zéro euro est proposé').toHaveLength(0)
  })

  it('regroupe sous « à répartir » ce qui n’a pas de compte', () => {
    const v = virements([
      depense({ id: 'd1', compte_id: null, parts: [{ user_profile_id: MOI, part_cents: 1_000 }] }),
      depense({ id: 'd2', compte_id: null, parts: [{ user_profile_id: MOI, part_cents: 500 }] }),
    ], MOI, [], prenoms)
    expect(v, 'les dépenses sans compte se dispersent').toHaveLength(1)
    expect(v[0].cents).toBe(1_500)
  })
})

describe('effortMensuel', () => {
  it('dit combien verser par mois pour tenir une date', () => {
    const dans = (mois: number) => {
      const d = new Date()
      d.setMonth(d.getMonth() + mois)
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
    }
    // 1 200 € dans 12 mois, 480 déjà versés : il reste 720 sur 12 mois = 60.
    expect(effortMensuel(120_000, dans(12), 48_000)).toEqual({ parMois: 6_000, mois: 12 })
  })

  it('ne divise pas par zéro le mois de l’échéance', () => {
    const ceMois = (() => {
      const d = new Date()
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
    })()
    // Zéro mois restant veut dire « c'est maintenant », pas l'infini.
    expect(effortMensuel(120_000, ceMois, 48_000)).toEqual({ parMois: 72_000, mois: 0 })
  })

  it('ne réclame rien quand l’objectif est déjà atteint', () => {
    const d = new Date(); d.setMonth(d.getMonth() + 6)
    const dans6 = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
    expect(effortMensuel(120_000, dans6, 150_000)?.parMois).toBe(0)
  })

  it('ne dit rien sans objectif ou sans date : il n’y a rien à tenir', () => {
    expect(effortMensuel(null, '2027-12-01', 0)).toBeNull()
    expect(effortMensuel(120_000, null, 0)).toBeNull()
  })
})

describe('diffParticipants', () => {
  /* L'écran supprimait TOUS les participants d'une charge pour en reposer
     deux, sa propre ligne comprise. Tant que rien ne surveillait ces
     suppressions, ça passait ; le jour où un trigger l'a fait, le bouton est
     mort en silence sur toute charge commune — et la suppression de compte
     avec lui, même cascade. */
  it('ne touche que ce qui change', () => {
    expect(diffParticipants(['a', 'b'], ['a']))
      .toEqual({ retires: ['b'], ajoutes: [] })
    expect(diffParticipants(['a'], ['a', 'b']))
      .toEqual({ retires: [], ajoutes: ['b'] })
  })

  it('ne retire rien quand rien ne change', () => {
    // C'est le cas le plus fréquent — et c'était une réécriture complète.
    expect(diffParticipants(['a', 'b'], ['b', 'a']))
      .toEqual({ retires: [], ajoutes: [] })
  })

  it('laisse se retirer soi-même sans emporter l’autre', () => {
    expect(diffParticipants(['moi', 'elle'], ['elle']))
      .toEqual({ retires: ['moi'], ajoutes: [] })
  })

  it('accepte la liste vide : on peut tous se décocher', () => {
    expect(diffParticipants(['moi', 'elle'], []))
      .toEqual({ retires: ['moi', 'elle'], ajoutes: [] })
  })
})

describe('un mois déjà réglé', () => {
  it('ne se redemande pas', () => {
    /* Rattraper une charge annuelle depuis janvier ouvre huit mois d'un coup,
       et chacun réclamait un virement pour un mois déjà vécu et déjà payé. */
    const commun = compte({ id: 'c1' })
    const v = virements([
      depense({ id: 'd1', compte_id: 'c1', regle_le: '2026-02-03T10:00:00Z',
                parts: [{ user_profile_id: MOI, part_cents: 22_083 }] }),
      depense({ id: 'd2', compte_id: 'c1',
                parts: [{ user_profile_id: MOI, part_cents: 5_000 }] }),
    ], MOI, [commun], prenoms)
    expect(v, 'un mois réglé réclame encore un virement').toHaveLength(1)
    expect(v[0].cents).toBe(5_000)
  })
})
