/**
 * La réconciliation des remises, éprouvée sur le cas RÉEL qui l'a motivée.
 *
 * Mesuré le 18/09/2026 sur huit lectures d'un même ticket : le modèle repère la
 * remise et la pose sur la bonne ligne, mais ne la soustrait du montant qu'une
 * fois sur deux. Le cas se vérifie par l'arithmétique, donc il se corrige — et
 * la correction doit échouer FERMÉE, parce qu'un prix corrigé de travers
 * s'apprend et se propage à toutes les estimations suivantes.
 */
import { describe, expect, it } from 'vitest'
import { reconcilie } from '../../supabase/functions/ticket/lignes.ts'
import type { LigneLue } from '../../supabase/functions/ticket/lignes.ts'

const ligne = (label: string, price_eur: number, remise_eur: number | null = null): LigneLue => ({
  label, price_eur, remise_eur,
  quantity: null, unit: null, unit_price_eur: null, confiance: 1,
})

/** Le vrai ticket du banc d'essai : huit articles, une remise de 0,50 €. */
const TICKET = [
  ligne('FIL PLT 500G', 6.49), ligne('PDT CHARLOTTE', 3.99),
  ligne('YT NAT X8', 2.16), ligne('LAIT DEMI ECR 1L', 2.1),
  ligne('TOMATES GRAPPE', 2.98), ligne('CRM FRAICHE 20CL', 1.35),
  ligne('SACS POUB 30L', 3.2), ligne('COURGETTE VRAC', 1.79, 0.5),
]

describe('les remises annoncées mais non déduites', () => {
  it('se déduisent quand l’arithmétique le prouve', () => {
    const r = reconcilie(TICKET, 23.56)
    expect(r.remisesDeduites, 'la remise n’a pas été rattrapée').toBe(true)
    expect(r.somme).toBe(23.56)
    expect(r.ecart).toBe(0)
    expect(r.lignes.find(l => l.label === 'COURGETTE VRAC')!.price_eur).toBe(1.29)
  })

  it('ne touchent à rien quand elles ont DÉJÀ été déduites', () => {
    // L'autre moitié des lectures : la somme tombe juste du premier coup.
    const deja = TICKET.map(l => (l.remise_eur ? { ...l, price_eur: 1.29 } : l))
    const r = reconcilie(deja, 23.56)
    expect(r.remisesDeduites).toBe(false)
    expect(r.lignes.find(l => l.label === 'COURGETTE VRAC')!.price_eur).toBe(1.29)
    expect(r.ecart).toBe(0)
  })

  it('se taisent quand il manque AUSSI autre chose', () => {
    // Un écart de 2,70 € pour 0,50 € de remises veut dire qu'une ligne a été
    // manquée. Déduire la remise masquerait la moitié du problème.
    const ampute = TICKET.filter(l => l.label !== 'SACS POUB 30L')
    const r = reconcilie(ampute, 23.56)
    expect(r.remisesDeduites, 'une correction a été inventée').toBe(false)
    expect(r.ecart).toBeCloseTo(-2.7, 2)
  })

  it('ne corrigent rien sans total imprimé', () => {
    // Sans le total, l'égalité ne se vérifie pas : il n'y a rien à prouver.
    const r = reconcilie(TICKET, null)
    expect(r.remisesDeduites).toBe(false)
    expect(r.ecart).toBeNull()
    expect(r.somme).toBe(24.06)
  })
})

describe('ce qui n’est pas un achat', () => {
  it('écarte une ligne à prix négatif', () => {
    // Une remise listée comme ligne apprendrait un prix négatif.
    const r = reconcilie([ligne('PAIN', 1.1), ligne('REMISE', -0.5)], null)
    expect(r.lignes).toHaveLength(1)
    expect(r.somme).toBe(1.1)
  })

  it('écarte aussi une ligne à zéro', () => {
    // Un article offert n'enseigne aucun prix : le retenir apprendrait que ce
    // produit est gratuit.
    const r = reconcilie([ligne('PAIN', 1.1), ligne('ECHANTILLON', 0)], null)
    expect(r.lignes).toHaveLength(1)
  })
})

describe('l’écart', () => {
  it('est positif quand on a lu plus cher que le total', () => {
    expect(reconcilie([ligne('PAIN', 2)], 1.5).ecart).toBeCloseTo(0.5, 2)
  })

  it('est négatif quand une ligne manque', () => {
    expect(reconcilie([ligne('PAIN', 2)], 5).ecart).toBeCloseTo(-3, 2)
  })

  it('est nul quand la lecture tombe juste', () => {
    expect(reconcilie([ligne('PAIN', 2)], 2).ecart).toBe(0)
  })

  it('ne traîne pas de flottant', () => {
    const r = reconcilie([ligne('A', 0.1), ligne('B', 0.2)], 0.3)
    expect(r.somme).toBe(0.3)
    expect(r.ecart).toBe(0)
  })
})
