-- ═══════════════════════════════════════════════════════════════════════════
-- 0150 · `verifie_mot_de_passe(text, text)` : PLUS AUCUN RÔLE APPLICATIF (0.4bis S7c)
--
-- La connexion par mot de passe est sortie en S7b : la variante par adresse n'a plus d'appelant. Relevé : le code de cette API
-- (`security/connexion.py` n'appelle que `verifie_mot_de_passe_de`), l'ancienne appli (aucune occurrence), les migrations (0137 la
-- crée seule). Seul `popote_api` l'exécutait. Un appel coûte un `crypt()` et rend l'identifiant d'une personne : mieux vaut qu'il soit
-- impossible. EXPANSION : un `revoke` seulement, la fonction reste (elle part en S15) ; `verifie_mot_de_passe_de`, qui sert la
-- réauthentification, garde son droit.
-- ORDRE DE DÉPLOIEMENT : seulement quand l'API déployée est celle de #147 (cbfe9e0) ou plus récente ; une API plus ancienne
-- appelle encore cette fonction à la connexion par mot de passe (elle répondrait 500).
--
-- Retour arrière (sans perte) :
--   grant execute on function public.verifie_mot_de_passe(text, text) to popote_api;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

revoke execute on function public.verifie_mot_de_passe(text, text) from popote_api;
