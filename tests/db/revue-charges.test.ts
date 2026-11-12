/**
 * Ce qu'on AFFICHE d'une revue, pas ce que le modèle en dit.
 *
 * Le banc (`npm run banc-revue`) mesure le modèle : est-ce qu'il voit l'erreur
 * d'unité, le doublon, l'oubli. Il coûte des appels réseau, il varie d'une
 * passe à l'autre, et il ne peut donc rien garantir.
 *
 * Ce banc-ci mesure le FILTRE, qui, lui, est déterministe — et c'est lui qui
 * tient les promesses de l'écran. Un modèle qui dérape est un incident ; un
 * filtre qui laisse passer est un défaut permanent.
 */
import { describe, it, expect } from 'vitest'
import { filtre, sansObjet } from '../../supabase/functions/revue-charges/prompt.ts'

const FOYER = {
  postes: ['Internet', 'Box', 'Charges de copropriété', 'Mensualité de prêt'],
  exclus: ['Eau', 'Loyer', 'Assurance emprunteur'],
}

describe('ce qui survit au filtre', () => {
  it('jette une incohérence sur une charge que le foyer n’a pas', () => {
    /* Le cas qui tue la confiance : on lit « ta mutuelle est trop chère », on
       cherche sa mutuelle, elle n'existe pas. Une seule fois suffit pour ne
       plus jamais relancer la revue. */
    const r = filtre({
      incoherences: [
        { libelle: 'Mutuelle', quoi: 'trop chère', question: 'c’est bien ça ?' },
        { libelle: 'Internet', quoi: '37 € deux fois', question: 'tu en as deux ?' },
      ],
    }, FOYER)
    expect(r.incoherences.map(i => i.libelle)).toEqual(['Internet'])
  })

  it('jette un doublon dont il ne reste qu’une ligne', () => {
    /* Un doublon amputé de son jumeau ne désigne plus rien : « Internet fait
       double emploi avec » — avec quoi ? */
    const r = filtre({
      doublons: [
        { libelles: ['Internet', 'Freebox'], pourquoi: 'la même' },
        { libelles: ['Internet', 'Box'], pourquoi: 'la même' },
      ],
    }, FOYER)
    expect(r.doublons).toHaveLength(1)
    expect(r.doublons[0].libelles).toEqual(['Internet', 'Box'])
  })

  it('jette un oubli qui est déjà posé', () => {
    const r = filtre({ oublis: ['Internet', 'Mutuelle'] }, FOYER)
    expect(r.oublis).toEqual(['Mutuelle'])
  })

  it('jette un oubli que ce qui est posé rend sans objet', () => {
    /* 0087. « Loyer » à quelqu'un qui rembourse un prêt, « Eau » à un foyer
       qui paie des charges de copropriété : on l'envoie chercher une facture
       qui n'existe pas. Le prompt l'interdit, le banc a mesuré qu'il ne s'y
       tient pas — c'est donc ici que ça se ferme. */
    const r = filtre({ oublis: ['Eau', 'Loyer', 'Forfait mobile'] }, FOYER)
    expect(r.oublis).toEqual(['Forfait mobile'])
  })

  it('rend des listes vides plutôt que des trous', () => {
    /* L'écran boucle dessus sans se demander si elles existent : `undefined`
       y casserait le rendu au moment précis où tout va bien. */
    const r = filtre({}, FOYER)
    expect(r).toEqual({ doublons: [], incoherences: [], oublis: [], verdict: '' })
  })
})

describe('ce que le foyer rend sans objet', () => {
  const CATALOGUE = [
    { libelle: 'Loyer', exclu_par: ['Mensualité de prêt'] },
    { libelle: 'Eau', exclu_par: ['Charges de copropriété'] },
    { libelle: 'Forfait mobile', exclu_par: [] },
    { libelle: 'Gaz', exclu_par: null },
  ]

  it('exclut ce qu’un poste posé contredit ou comprend déjà', () => {
    expect(sansObjet(CATALOGUE, ['Mensualité de prêt', 'Charges de copropriété']))
      .toEqual(['Loyer', 'Eau'])
  })

  it('n’exclut rien quand le foyer n’a rien qui exclue', () => {
    expect(sansObjet(CATALOGUE, ['Internet'])).toEqual([])
  })

  it('supporte une colonne nulle comme une colonne vide', () => {
    /* `exclu_par` est `not null default '{}'` en base, mais la même fonction
       sert au banc, qui lit du JSON. Un null y vaut « rien n'exclut ». */
    expect(sansObjet([{ libelle: 'Gaz', exclu_par: null }], ['Gaz'])).toEqual([])
  })
})
