-- ═══════════════════════════════════════════════════════════════════════════
-- 0071 · L'invitation tient trente jours, et n'invente plus de prénom
--
-- Mesuré sur le parcours : le lien expire au bout de SEPT jours. Léa
-- emménage dans dix. Elle clique, obtient « Invitation expirée », se retrouve
-- authentifiée sans foyer — et jusqu'à 0070 on lui proposait de créer le sien.
--
-- Sept jours est la durée d'un lien de RÉINITIALISATION, où la brièveté protège.
-- Une invitation à emménager n'a pas le même usage : on l'envoie quand on y
-- pense, on la lit quand on s'installe, et entre les deux il y a un
-- déménagement. Trente jours, et elle reste révocable à tout moment puisqu'un
-- seul jeton vaut à la fois.
-- ═══════════════════════════════════════════════════════════════════════════

alter table public.invitation
  alter column expires_at set default now() + interval '30 days';

-- Les invitations en cours en profitent : ré-envoyer un lien parce que la
-- durée a changé sous les pieds de quelqu'un serait absurde.
update public.invitation
   set expires_at = created_at + interval '30 days'
 where accepted_at is null
   and expires_at > now() - interval '30 days';
