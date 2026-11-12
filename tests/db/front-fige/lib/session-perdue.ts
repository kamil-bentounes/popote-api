/**
 * La session a disparu pendant que l'écran croyait encore la personne connectée.
 *
 * Grand test, parcours « nouveau venu » (22/10) : le jeton retiré du stockage, un clic sur
 * « Enregistrer le plafond » répondait « Aucun foyer. » — `current_household` partait avec la
 * clé ANONYME, la base répondait 401, et l'écran traduisait un refus de session en « tu n'as
 * pas de foyer ». Les autres écrans affichaient « permission denied for function … ».
 *
 * Une requête de données qui part avec la clé anonyme comme jeton ET se fait refuser (401) ne
 * peut être que cela : l'application bascule alors sur l'écran de connexion, une phrase à
 * l'appui, au lieu de laisser chaque écran inventer son message.
 */
export const SESSION_PERDUE = 'popote:session-perdue'

export function sessionPerdue(
  statut: number, url: string, autorisation: string | null, cleAnonyme: string,
): boolean {
  return statut === 401
    && (url.includes('/rest/v1/') || url.includes('/functions/v1/'))
    && autorisation === `Bearer ${cleAnonyme}`
}
