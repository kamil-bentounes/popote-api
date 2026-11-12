/**
 * Ce qu'une clôture n'a pas pu solder (§ 3.5, choix 20) : rien en base ne le garde, la
 * clôture suivante réessaie et le redit. On le retient donc dans le cache des requêtes,
 * jusqu'au rechargement. Un module à part, sans dépendance : la couche de données
 * (`donnees/budget.ts`) l'importe, et `cloture.ts` importe elle-même cette couche.
 */
import type { QueryClient } from '@tanstack/react-query'
import type { NonSoldee } from '../donnees/budget.ts'

/** La clé de ce qu'une clôture n'a pas pu solder (rien en base ne le garde). */
export const cleNonSoldees = (mois: string) => ['non-soldees', mois] as const

/** Ce que la clôture vient de dire : elle l'a rendu, la page de clôture n'est plus là pour le dire. */
export function retientNonSoldees(qc: QueryClient, mois: string, liste: NonSoldee[]): void {
  qc.setQueryData(cleNonSoldees(mois), liste)
}

/**
 * Le mois rouvert n'a plus de clôture : ce qu'elle n'avait pas pu solder ne se dit plus.
 * On POSE `[]` plutôt que de retirer la requête : l'écran du mois la regarde déjà, et une
 * requête retirée sous un observateur laisse l'ancienne ligne à l'écran jusqu'au rendu suivant.
 */
export function oublieNonSoldees(qc: QueryClient, mois: string): void {
  qc.setQueryData(cleNonSoldees(mois), [])
}
