/**
 * L'heure du front.
 *
 * En production, c'est `new Date()`, et rien d'autre : Vite remplace
 * `import.meta.env.MODE` par sa valeur, et la branche du banc disparaît du
 * paquet.
 *
 * Le banc e2e de la clôture doit jouer un 1er novembre. `page.clock` le ferait,
 * mais il avance aussi l'horloge de supabase-js : le jeton, émis pour une heure,
 * y paraît expiré, et chaque requête relance un rafraîchissement jusqu'à la
 * limite de débit de l'authentification. Le banc pose donc
 * `popote.maintenant` dans le `localStorage`, que SEUL un paquet construit en
 * mode `development` lit (celui de `playwright.config.ts`).
 */
export function maintenant(): Date {
  if (import.meta.env.MODE === 'development') {
    try {
      const reglee = globalThis.localStorage?.getItem('popote.maintenant')
      if (reglee) {
        const d = new Date(reglee)
        /* Une valeur illisible donnerait « Invalid Date », puis « NaN-NaN-NaN » dans
           chaque date de l'écran : mieux vaut l'heure vraie. */
        if (!Number.isNaN(d.getTime())) return d
      }
    } catch { /* stockage bloqué : l'heure vraie */ }
  }
  return new Date()
}

/** « 2026-10-03 », en heure LOCALE : `toISOString` dirait la veille entre minuit et 2 h. */
export function aujourdhui(d: Date = maintenant()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${
    String(d.getDate()).padStart(2, '0')}`
}

const PARIS = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit',
})

/**
 * « 2026-11-01 », en heure de PARIS : c'est celle de la base (`mois_courant()`, `maintenant()`).
 * L'heure locale de l'appareil ne convient pas : entre minuit et 2 h à Paris, un navigateur à un
 * autre fuseau voit encore le mois d'avant, propose « Clôturer » trop tôt et la base le refuse.
 * L'horloge jouée du banc (`maintenant`) est respectée.
 */
export function jourDeParis(d: Date = maintenant()): string {
  const p = Object.fromEntries(PARIS.formatToParts(d).map(x => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}`
}

/** « 2026-11-01 » : le premier jour du mois en cours à Paris. */
export function moisCourantDeParis(d: Date = maintenant()): string {
  return `${jourDeParis(d).slice(0, 7)}-01`
}
